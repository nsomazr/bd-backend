"""Resolve where Maisha should run inference on shared GPU hosts."""
from __future__ import annotations

import logging
import os

from django.conf import settings

from .gpu_probe import probe_gpu

logger = logging.getLogger("llm")


def resolve_inference_target() -> tuple[str | dict, str]:
    """Return (device_map, label) where label is 'cuda' or 'cpu'."""
    mode = getattr(settings, "LLM_DEVICE", "auto").lower()
    probe = probe_gpu()

    def _log_probe_notes(level: int = logging.INFO) -> None:
        for note in probe.notes:
            logger.log(level, note)

    configured_map = getattr(settings, "LLM_DEVICE_MAP", "auto")

    if mode == "cpu":
        logger.info("LLM_DEVICE=cpu: running inference on CPU.")
        return "cpu", "cpu"

    if mode == "cuda":
        if probe.torch_cuda_available:
            device_map = "cuda:0" if configured_map == "auto" else configured_map
            return device_map, "cuda"
        _log_probe_notes(logging.WARNING)
        logger.warning(
            "LLM_DEVICE=cuda was requested but CUDA is unavailable to this "
            "process. Falling back to CPU without touching other users' jobs."
        )
        return "cpu", "cpu"

    # auto: use CUDA only when this process can actually open a context.
    if probe.torch_cuda_available:
        device_map = "cuda:0" if configured_map == "auto" else configured_map
        return device_map, "cuda"

    _log_probe_notes(logging.INFO)
    if probe.foreign_processes:
        logger.info(
            "Shared GPU is busy with other workloads; Maisha will use CPU "
            "until CUDA becomes available to this process."
        )
    else:
        logger.info("CUDA unavailable; Maisha will use CPU inference.")
    return "cpu", "cpu"


def configure_cpu_runtime() -> None:
    """Tune PyTorch thread count for CPU inference."""
    try:
        import torch

        threads = int(getattr(settings, "LLM_CPU_THREADS", 0) or 0)
        if threads <= 0:
            threads = min(8, os.cpu_count() or 4)
        torch.set_num_threads(threads)
        logger.info("CPU inference threads: %d", threads)
    except Exception as exc:
        logger.debug("CPU thread tuning skipped: %s", exc)
