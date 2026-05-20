"""Format helpers that turn DB rows into RLHF-ready training samples.

The DPO format we emit is the one accepted by `trl.DPOTrainer` and most
HuggingFace-style training scripts:

    {"prompt": str, "chosen": str, "rejected": str, "metadata": {...}}

`metadata` carries source-of-record info (arena battle id, model keys, vote
type, etc.) so you can filter or audit later.
"""
from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Iterator
from typing import Any

from arena.models import ArenaBattle

from .models import MessageFeedback, RegenerationPair


# --- DPO pair builders ------------------------------------------------------


def arena_pair_iter(qs) -> Iterator[dict[str, Any]]:
    """Yield DPO pairs from voted Arena battles.

    Battles voted as 'tie' or 'both_bad' are skipped because they carry no
    clear preference signal.
    """
    for b in qs.iterator():
        if b.vote == "a":
            chosen_text, chosen_key = b.response_a, b.model_a_key
            rejected_text, rejected_key = b.response_b, b.model_b_key
        elif b.vote == "b":
            chosen_text, chosen_key = b.response_b, b.model_b_key
            rejected_text, rejected_key = b.response_a, b.model_a_key
        else:
            continue
        if not chosen_text.strip() or not rejected_text.strip():
            continue
        yield {
            "prompt": b.prompt,
            "chosen": chosen_text,
            "rejected": rejected_text,
            "metadata": {
                "source": "arena",
                "battle_id": b.id,
                "chosen_model": chosen_key,
                "rejected_model": rejected_key,
                "vote": b.vote,
                "user_id": b.user_id,
                "created_at": b.created_at.isoformat(),
            },
        }


def regen_pair_iter(qs) -> Iterator[dict[str, Any]]:
    for p in qs.iterator():
        if not p.chosen_text.strip() or not p.rejected_text.strip():
            continue
        yield {
            "prompt": p.prompt,
            "chosen": p.chosen_text,
            "rejected": p.rejected_text,
            "metadata": {
                "source": "regeneration",
                "pair_id": p.id,
                "conversation_id": p.conversation_id,
                "user_message_id": p.user_message_id,
                "chosen_model": p.chosen_model_key,
                "rejected_model": p.rejected_model_key,
                "history": p.history,
                "user_id": p.user_id,
                "created_at": p.created_at.isoformat(),
            },
        }


def dpo_pair_iter(
    arena_qs=None,
    regen_qs=None,
) -> Iterator[dict[str, Any]]:
    if arena_qs is None:
        arena_qs = ArenaBattle.objects.exclude(vote="").exclude(vote="tie").exclude(vote="both_bad")
    if regen_qs is None:
        regen_qs = RegenerationPair.objects.all()
    yield from arena_pair_iter(arena_qs)
    yield from regen_pair_iter(regen_qs)


# --- Stream encoders --------------------------------------------------------


def iter_jsonl(rows: Iterable[dict[str, Any]]) -> Iterator[bytes]:
    for row in rows:
        yield (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")


def feedback_jsonl_iter(qs) -> Iterator[dict[str, Any]]:
    """Yield {prompt, response, rating, comment} rows for reward modelling."""
    qs = qs.select_related("message", "message__conversation", "user")
    for fb in qs.iterator():
        msg = fb.message
        prior = list(
            msg.conversation.messages.filter(created_at__lt=msg.created_at)
            .order_by("created_at", "id")
            .values("role", "content")
        )
        prompt = "\n\n".join(
            f"{m['role'].upper()}: {m['content']}" for m in prior
        )
        yield {
            "prompt": prompt,
            "response": msg.content,
            "rating": fb.rating,
            "comment": fb.comment,
            "metadata": {
                "source": "chat_feedback",
                "feedback_id": fb.id,
                "message_id": msg.id,
                "conversation_id": msg.conversation_id,
                "model_key": msg.model_key,
                "user_id": fb.user_id,
                "created_at": fb.created_at.isoformat(),
            },
        }


def feedback_csv_bytes(qs) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "feedback_id",
            "created_at",
            "user_email",
            "conversation_id",
            "message_id",
            "model_key",
            "rating",
            "comment",
            "message_content",
        ]
    )
    qs = qs.select_related("message", "user")
    for fb in qs.iterator():
        writer.writerow(
            [
                fb.id,
                fb.created_at.isoformat(),
                fb.user.email,
                fb.message.conversation_id,
                fb.message.id,
                fb.message.model_key,
                fb.rating,
                (fb.comment or "").replace("\n", " ").strip(),
                fb.message.content[:2000],
            ]
        )
    return buf.getvalue().encode("utf-8")


def sft_jsonl_iter(message_qs) -> Iterator[dict[str, Any]]:
    """Emit instruction-tuning style rows from positively-rated messages.

    Schema: {messages: [{role, content}, ...]} (OpenAI / TRL chat-template
    friendly).
    """
    for msg in message_qs.select_related("conversation").iterator():
        prior = list(
            msg.conversation.messages.filter(created_at__lt=msg.created_at)
            .order_by("created_at", "id")
            .values("role", "content")
        )
        yield {
            "messages": prior + [{"role": msg.role, "content": msg.content}],
            "metadata": {
                "source": "sft_thumbs_up",
                "message_id": msg.id,
                "conversation_id": msg.conversation_id,
                "model_key": msg.model_key,
            },
        }
