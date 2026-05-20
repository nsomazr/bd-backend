"""Registry of available blood-donation chat models.

The keys are stable identifiers used in the API. The labels are what end users
see in the model dropdown. ``family`` controls which Transformers loader is
used in :mod:`llm.loader`.
"""
from __future__ import annotations

from typing import TypedDict


class ModelSpec(TypedDict):
    label: str
    hf_id: str
    family: str
    description: str


MODEL_REGISTRY: dict[str, ModelSpec] = {
    "gemma4-e4b": {
        "label": "Gemma 4 E4B",
        "hf_id": "HMkumbo/blood-donation-gemma4-e4b-merged-16bit",
        "family": "gemma4",
        "description": "Google Gemma 4 E4B fine-tuned for blood donation Q&A.",
    },
    "qwen3.5-4b": {
        "label": "Qwen 3.5 4B",
        "hf_id": "HMkumbo/blood-donation-qwen3.5-4b-merged-16bit",
        "family": "qwen",
        "description": "Qwen 3.5 4B fine-tuned on blood-donation conversations.",
    },
    "llama3.2-3b": {
        "label": "Llama 3.2 3B",
        "hf_id": "HMkumbo/blood-donation-llama32-3b-merged-16bit",
        "family": "llama",
        "description": "Meta Llama 3.2 3B fine-tuned for blood donation guidance.",
    },
}

DEFAULT_MODEL_KEY = "gemma4-e4b"


def list_models() -> list[dict]:
    return [
        {
            "key": key,
            "label": spec["label"],
            "description": spec["description"],
            "family": spec["family"],
        }
        for key, spec in MODEL_REGISTRY.items()
    ]


def get_spec(model_key: str) -> ModelSpec:
    if model_key not in MODEL_REGISTRY:
        raise KeyError(f"Unknown model key: {model_key!r}")
    return MODEL_REGISTRY[model_key]
