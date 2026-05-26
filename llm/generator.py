"""Streaming text generation helpers."""
from __future__ import annotations

import logging
import re
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

SWAHILI_HINTS = {
    "asante",
    "habari",
    "tafadhali",
    "naomba",
    "samahani",
    "karibu",
    "ndio",
    "hapana",
    "sawa",
    "nina",
    "niko",
    "nataka",
    "naweza",
    "inawezekana",
    "vipi",
    "lini",
    "wapi",
    "kwanini",
    "damu",
    "uchangiaji",
    "kuchangia",
    "mchango",
    "donori",
    "hospitali",
    "mgonjwa",
    "msaada",
    "afya",
    "kiswahili",
    "kingereza",
}

ENGLISH_HINTS = {
    "hello",
    "hi",
    "please",
    "thanks",
    "thank",
    "blood",
    "donation",
    "donate",
    "donor",
    "hospital",
    "help",
    "health",
    "can",
    "should",
    "would",
    "what",
    "when",
    "where",
    "why",
    "english",
    "swahili",
}

SWAHILI_OVERRIDE_RE = re.compile(
    r"\b(reply|respond|answer|write|speak)\s+in\s+swahili\b"
    r"|\b(jibu|andika|ongea)\s+(kwa\s+)?kiswahili\b",
    re.I,
)
ENGLISH_OVERRIDE_RE = re.compile(
    r"\b(reply|respond|answer|write|speak)\s+in\s+english\b"
    r"|\b(jibu|andika|ongea)\s+(kwa\s+)?kingereza\b",
    re.I,
)
WORD_RE = re.compile(r"[a-zA-Z]+")


def _effective_max_tokens(requested: int | None, *, model_on_cuda: bool) -> int:
    """Use shorter generations on CPU to keep shared-host chat responsive."""
    default = settings.LLM_MAX_NEW_TOKENS
    if requested is not None:
        default = requested
    if not model_on_cuda:
        cpu_cap = int(getattr(settings, "LLM_MAX_NEW_TOKENS_CPU", 256))
        return min(default, cpu_cap)
    return default


def _is_cuda_oom(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "cuda out of memory" in message or "cuda error: out of memory" in message


def user_facing_generation_error(exc: BaseException) -> str:
    if _is_cuda_oom(exc):
        return (
            "Sorry, the selected model is temporarily busy right now. "
            "Please try again in a moment or switch to another model."
        )
    return (
        "Sorry, I ran into a temporary problem while generating the response. "
        "Please try again."
    )


def _detect_language_override(text: str) -> str | None:
    if SWAHILI_OVERRIDE_RE.search(text):
        return "sw"
    if ENGLISH_OVERRIDE_RE.search(text):
        return "en"
    return None


def _language_score(text: str, hints: set[str]) -> int:
    tokens = [token.lower() for token in WORD_RE.findall(text)]
    return sum(1 for token in tokens if token in hints)


def _detect_reply_language(messages: list[dict]) -> str:
    """Infer whether the assistant should answer in English or Swahili."""
    user_texts = [
        (m.get("content") or "").strip()
        for m in messages
        if m.get("role") == "user" and (m.get("content") or "").strip()
    ]
    if not user_texts:
        return "en"

    latest = user_texts[-1]
    override = _detect_language_override(latest)
    if override:
        return override

    recent = user_texts[-3:]
    sw_score = 0
    en_score = 0
    for idx, text in enumerate(reversed(recent), start=1):
        weight = len(recent) - idx + 1
        sw_score += _language_score(text, SWAHILI_HINTS) * weight
        en_score += _language_score(text, ENGLISH_HINTS) * weight

    if sw_score > en_score:
        return "sw"
    return "en"


def _system_prompt(messages: list[dict]) -> str:
    language = _detect_reply_language(messages)
    if language == "sw":
        return (
            f"{SYSTEM_PROMPT} Reply in Swahili unless the user explicitly asks "
            "you to switch languages."
        )
    return (
        f"{SYSTEM_PROMPT} Reply in English unless the user explicitly asks you "
        "to switch languages."
    )


def _build_prompt(loaded: LoadedModel, messages: list[dict]) -> str:
    """Return a model-ready prompt string for the given chat history.

    ``messages`` is a list of ``{"role": "user"|"assistant"|"system", "content": str}``.
    A system prompt is prepended if the caller didn't supply one.
    """
    if not any(m.get("role") == "system" for m in messages):
        messages = [{"role": "system", "content": _system_prompt(messages)}, *messages]

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

    def _stream_once(active_loaded: LoadedModel) -> Iterator[str]:
        tokenizer = active_loaded.tokenizer
        model = active_loaded.model

        prompt = _build_prompt(active_loaded, messages)
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
            "max_new_tokens": _effective_max_tokens(
                max_new_tokens,
                model_on_cuda=active_loaded.device_label == "cuda",
            ),
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

    emitted_any = False
    fallback_attempted = False
    active_loaded = loaded
    while True:
        try:
            for token in _stream_once(active_loaded):
                emitted_any = True
                yield token
            return
        except BaseException as exc:
            if fallback_attempted or emitted_any or not _is_cuda_oom(exc):
                raise
            logger.warning(
                "CUDA OOM for model %s; retrying this response on CPU.",
                active_loaded.key,
            )
            from .loader import loader

            active_loaded = loader.fallback_to_cpu(active_loaded.key)
            fallback_attempted = True
