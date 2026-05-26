"""Lazy single-active LLM loader.

Loads at most one Transformers model at a time. When a new model is
requested, the previous one is released and (where possible) GPU memory is
reclaimed before the new model is loaded. All access is guarded by a single
process-wide lock so concurrent requests serialise around the load step.

GPU is used automatically when available. We prefer bfloat16 on Ampere or
newer (compute capability >= 8.0), fall back to float16 on older GPUs, and
float32 on CPU. SDPA attention and TF32 matmuls are enabled for throughput.
"""
from __future__ import annotations

import gc
import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from django.conf import settings

from .gpu_probe import probe_gpu_dict
from .registry import get_spec
from .runtime import configure_cpu_runtime, resolve_inference_target

logger = logging.getLogger("llm")


def _is_cuda_oom(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "cuda out of memory" in message or "cuda error: out of memory" in message


@dataclass
class LoadedModel:
    key: str
    tokenizer: Any
    model: Any
    family: str
    device_label: str


_GPU_INITIALISED = False


from .gpu_probe import probe_gpu_dict
from .runtime import resolve_inference_target


def get_gpu_status() -> dict:
    """Return GPU + inference status for health checks."""
    probe = probe_gpu_dict()
    _, label = resolve_inference_target()
    probe["inference_device"] = label
    return probe


def _init_gpu_runtime() -> None:
    """Configure global PyTorch knobs for throughput. Idempotent."""
    global _GPU_INITIALISED
    if _GPU_INITIALISED:
        return
    try:
        import torch

        if torch.cuda.is_available():
            # TF32 on Ampere+ -> big speed-up for matmul/convs at negligible cost.
            torch.set_float32_matmul_precision("high")
            try:
                torch.backends.cuda.matmul.allow_tf32 = True
                torch.backends.cudnn.allow_tf32 = True
                torch.backends.cudnn.benchmark = True
            except Exception:
                pass
            device_count = torch.cuda.device_count()
            for i in range(device_count):
                name = torch.cuda.get_device_name(i)
                cap = torch.cuda.get_device_capability(i)
                free, total = torch.cuda.mem_get_info(i)
                logger.info(
                    "CUDA device %d: %s (cc %d.%d, %.1f / %.1f GB free)",
                    i,
                    name,
                    cap[0],
                    cap[1],
                    free / 1024 ** 3,
                    total / 1024 ** 3,
                )
        else:
            probe = probe_gpu_dict()
            if probe.get("foreign_processes"):
                owners = ", ".join(
                    f"PID {p['pid']} ({p.get('owner') or 'unknown'})"
                    for p in probe["foreign_processes"]
                )
                logger.info(
                    "CUDA not available to Maisha; other GPU jobs are active (%s). "
                    "Using CPU inference.",
                    owners,
                )
            else:
                logger.warning(
                    "CUDA not available to Maisha; using CPU inference."
                )
        _GPU_INITIALISED = True
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("GPU runtime init skipped: %s", exc)


def _auto_dtype():
    """Pick the best dtype for the current device."""
    import torch

    requested = getattr(settings, "LLM_TORCH_DTYPE", "auto").lower()
    explicit = {
        "float16": torch.float16,
        "fp16": torch.float16,
        "bfloat16": torch.bfloat16,
        "bf16": torch.bfloat16,
        "float32": torch.float32,
        "fp32": torch.float32,
    }
    if requested in explicit:
        return explicit[requested]
    # Auto: bf16 on Ampere+, fp16 on older CUDA, fp32 on CPU.
    if torch.cuda.is_available():
        try:
            major, _ = torch.cuda.get_device_capability(0)
            return torch.bfloat16 if major >= 8 else torch.float16
        except Exception:
            return torch.float16
    return torch.float32


def _best_attn_impl() -> str | None:
    """Use flash-attn-2 if installed, otherwise PyTorch SDPA."""
    try:
        import flash_attn  # noqa: F401

        return "flash_attention_2"
    except Exception:
        return "sdpa"


class _LazySingleActiveLoader:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: LoadedModel | None = None
        self._active_key: str | None = None
        self._active_count = 0

    @property
    def current_key(self) -> str | None:
        return self._current.key if self._current else None

    def get(self, model_key: str) -> LoadedModel:
        with self._lock:
            if self._current and self._current.key == model_key:
                return self._current
            self._unload_locked()
            self._current = self._load_with_cpu_fallback_locked(model_key)
            return self._current

    def acquire(self, model_key: str) -> LoadedModel:
        with self._lock:
            if not self._current or self._current.key != model_key:
                self._unload_locked()
                self._current = self._load_with_cpu_fallback_locked(model_key)
            self._active_key = model_key
            self._active_count += 1
            return self._current

    def release(self, model_key: str, *, unload_if_idle: bool = False) -> None:
        with self._lock:
            if not self._current or self._current.key != model_key:
                return
            if self._active_key == model_key and self._active_count > 0:
                self._active_count -= 1
                if self._active_count == 0:
                    self._active_key = None
            if unload_if_idle and self._active_count == 0:
                self._unload_locked()

    @contextmanager
    def session(self, model_key: str, *, unload_if_idle: bool = False):
        loaded = self.acquire(model_key)
        try:
            yield loaded
        finally:
            self.release(model_key, unload_if_idle=unload_if_idle)

    def unload(self) -> None:
        with self._lock:
            self._unload_locked()

    def fallback_to_cpu(self, model_key: str) -> LoadedModel:
        with self._lock:
            if self._current and self._current.key == model_key:
                if self._current.device_label == "cpu":
                    return self._current
                active_key = self._active_key
                active_count = self._active_count
                self._unload_locked(reset_usage=False)
                self._current = self._load_locked(model_key, force_device="cpu")
                self._active_key = active_key
                self._active_count = active_count
                return self._current
            self._unload_locked()
            self._current = self._load_locked(model_key, force_device="cpu")
            return self._current

    def _cleanup_failed_load_locked(self) -> None:
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # pragma: no cover
            pass

    def _load_with_cpu_fallback_locked(self, model_key: str) -> LoadedModel:
        try:
            return self._load_locked(model_key)
        except BaseException as exc:
            if not _is_cuda_oom(exc):
                raise
            logger.warning(
                "CUDA OOM while loading model %s; retrying load on CPU.",
                model_key,
            )
            self._cleanup_failed_load_locked()
            return self._load_locked(model_key, force_device="cpu")

    def _unload_locked(self, *, reset_usage: bool = True) -> None:
        if not self._current:
            return
        logger.info("Unloading model %s", self._current.key)
        try:
            del self._current.model
            del self._current.tokenizer
        except Exception:  # pragma: no cover - best effort cleanup
            pass
        self._current = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # pragma: no cover
            pass
        if reset_usage:
            self._active_key = None
            self._active_count = 0

    def _load_locked(self, model_key: str, force_device: str | None = None) -> LoadedModel:
        _init_gpu_runtime()
        spec = get_spec(model_key)
        import time

        import torch

        t0 = time.perf_counter()
        logger.info("Loading model %s (%s)", model_key, spec["hf_id"])

        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(spec["hf_id"], trust_remote_code=True)
        if tokenizer.pad_token_id is None and tokenizer.eos_token_id is not None:
            tokenizer.pad_token = tokenizer.eos_token

        dtype = _auto_dtype()
        if force_device == "cpu":
            device_map, device_label = "cpu", "cpu"
            logger.warning("Retrying model %s on CPU after GPU failure.", model_key)
        else:
            device_map, device_label = resolve_inference_target()
        if device_label == "cpu":
            configure_cpu_runtime()
            dtype = torch.float32
        family = spec["family"]
        attn_impl = _best_attn_impl() if device_label == "cuda" else None

        load_kwargs: dict[str, Any] = {
            "torch_dtype": dtype,
            "device_map": device_map,
            "trust_remote_code": True,
            "low_cpu_mem_usage": True,
        }
        if attn_impl:
            load_kwargs["attn_implementation"] = attn_impl

        logger.info(
            "  dtype=%s device_map=%s attn=%s",
            dtype, device_map, attn_impl,
        )

        if family == "gemma4":
            # Gemma 4 checkpoints use the gemma4 architecture; load via Auto*.
            from transformers import AutoModelForCausalLM

            try:
                model = AutoModelForCausalLM.from_pretrained(
                    spec["hf_id"], **load_kwargs
                )
            except (TypeError, ValueError) as exc:
                logger.warning("Retrying Gemma4 load without attn_implementation: %s", exc)
                load_kwargs.pop("attn_implementation", None)
                model = AutoModelForCausalLM.from_pretrained(
                    spec["hf_id"], **load_kwargs
                )
        else:
            from transformers import AutoModelForCausalLM

            try:
                model = AutoModelForCausalLM.from_pretrained(
                    spec["hf_id"], **load_kwargs
                )
            except (TypeError, ValueError) as exc:
                # Older transformers may not accept attn_implementation.
                logger.warning("Retrying load without attn_implementation: %s", exc)
                load_kwargs.pop("attn_implementation", None)
                model = AutoModelForCausalLM.from_pretrained(
                    spec["hf_id"], **load_kwargs
                )

        model.eval()

        # Tiny warmup so the first user request doesn't pay kernel-compile cost.
        try:
            with torch.inference_mode():
                warm = tokenizer("Hello", return_tensors="pt")
                try:
                    warm = {k: v.to(model.device) for k, v in warm.items()}
                except Exception:
                    pass
                model.generate(
                    **warm,
                    max_new_tokens=2,
                    do_sample=False,
                    pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
                )
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("Warmup skipped: %s", exc)

        elapsed = time.perf_counter() - t0
        on_cuda = torch.cuda.is_available() and any(
            p.is_cuda for p in model.parameters()
        )
        if on_cuda:
            alloc = torch.cuda.memory_allocated() / 1024 ** 3
            logger.info(
                "Model %s loaded in %.1fs (CUDA mem %.1f GB)", model_key, elapsed, alloc
            )
        else:
            logger.warning(
                "Model %s loaded in %.1fs on CPU. On shared hosts, coordinate GPU "
                "time with other users or set LLM_DEVICE=cpu in env.local.",
                model_key,
                elapsed,
            )

        return LoadedModel(
            key=model_key,
            tokenizer=tokenizer,
            model=model,
            family=family,
            device_label=device_label,
        )


loader = _LazySingleActiveLoader()
