"""Streaming text generation helpers."""
from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from typing import Any

from django.conf import settings

from .loader import LoadedModel

logger = logging.getLogger("llm")

SYSTEM_PROMPT = (
    "You are Maisha, a friendly and trustworthy blood-donation assistant for "
    "Tanzania. Answer clearly, accurately, and empathetically. When in doubt "
    "about a medical detail, encourage the user to consult a healthcare "
    "professional or the nearest blood bank."
)


def _effective_max_tokens(requested: int | None) -> int:
    """Use shorter generations on CPU to keep shared-host chat responsive."""
    import torch

    default = settings.LLM_MAX_NEW_TOKENS
    if requested is not None:
        default = requested
    if not torch.cuda.is_available():
        cpu_cap = int(getattr(settings, "LLM_MAX_NEW_TOKENS_CPU", 256))
        return min(default, cpu_cap)
    return default


def _build_prompt(loaded: LoadedModel, messages: list[dict]) -> str:
    """Return a model-ready prompt string for the given chat history.

    ``messages`` is a list of ``{"role": "user"|"assistant"|"system", "content": str}``.
    A system prompt is prepended if the caller didn't supply one.
    """
    if not any(m.get("role") == "system" for m in messages):
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *messages]

    tokenizer = loaded.tokenizer
    try:
        return tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
    except Exception:
        # Fallback: simple "Role: content" formatting
        rendered = "\n".join(f"{m['role'].title()}: {m['content']}" for m in messages)
        return rendered + "\nAssistant:"


def stream_completion(
    loaded: LoadedModel,
    messages: list[dict],
    max_new_tokens: int | None = None,
    temperature: float = 0.7,
    top_p: float = 0.9,
) -> Iterator[str]:
    """Yield decoded token strings as the model generates."""
    import torch
    from transformers import TextIteratorStreamer

    tokenizer = loaded.tokenizer
    model = loaded.model

    prompt = _build_prompt(loaded, messages)
    inputs = tokenizer(prompt, return_tensors="pt")
    try:
        inputs = {k: v.to(model.device) for k, v in inputs.items()}
    except Exception:
        pass

    streamer = TextIteratorStreamer(
        tokenizer,
        skip_prompt=True,
        skip_special_tokens=True,
    )

    gen_kwargs: dict[str, Any] = {
        **inputs,
        "streamer": streamer,
        "max_new_tokens": _effective_max_tokens(max_new_tokens),
        "do_sample": temperature > 0,
        "temperature": max(temperature, 1e-5),
        "top_p": top_p,
        "pad_token_id": tokenizer.pad_token_id or tokenizer.eos_token_id,
        "eos_token_id": tokenizer.eos_token_id,
    }

    error_box: dict[str, BaseException] = {}

    def _run() -> None:
        try:
            with torch.inference_mode():
                model.generate(**gen_kwargs)
        except BaseException as exc:  # pragma: no cover - surfaced to caller
            logger.exception("Generation error: %s", exc)
            error_box["error"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    try:
        for token in streamer:
            if token:
                yield token
    finally:
        thread.join(timeout=1.0)

    if "error" in error_box:
        raise error_box["error"]
