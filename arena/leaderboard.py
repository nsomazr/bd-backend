"""Elo ratings, leaderboard snapshots, and a tiny in-memory pub/sub for
real-time leaderboard updates.

The pub/sub is intentionally simple: a process-wide ``threading.Condition``
guards a monotonically increasing version counter. SSE handlers wait on the
condition for the version to change (with a small timeout for keep-alives).
This is sufficient for the gunicorn ``-w 1 --threads N`` deployment used by
this project. If we ever scale to multiple workers, swap this for Redis pub/sub.
"""
from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Any

from django.db import transaction

from llm.registry import MODEL_REGISTRY

from .models import ArenaBattle, ModelRating

K_FACTOR = 32.0
DEFAULT_RATING = 1000.0

_lock = threading.Condition()
_version = 0


def _bump_version() -> int:
    global _version
    with _lock:
        _version += 1
        _lock.notify_all()
        return _version


def current_version() -> int:
    return _version


def wait_for_change(after: int, timeout: float) -> int:
    """Block until ``_version > after`` or ``timeout`` seconds elapse.

    Returns the current version regardless of whether it changed.
    """
    with _lock:
        if _version > after:
            return _version
        _lock.wait(timeout=timeout)
        return _version


def ensure_ratings_exist() -> None:
    """Create a :class:`ModelRating` row for every model in the registry."""
    for key in MODEL_REGISTRY:
        ModelRating.objects.get_or_create(model_key=key)


def leaderboard_snapshot() -> dict[str, Any]:
    """Return the current rankings as a JSON-serialisable dict."""
    ensure_ratings_exist()
    rows: list[dict[str, Any]] = []
    for r in ModelRating.objects.all().order_by("-rating"):
        spec = MODEL_REGISTRY.get(r.model_key)
        rows.append(
            {
                "model_key": r.model_key,
                "label": spec["label"] if spec else r.model_key,
                "rating": round(r.rating, 1),
                "battles": r.battles,
                "wins": r.wins,
                "losses": r.losses,
                "ties": r.ties,
                "win_rate": round(r.win_rate, 4),
            }
        )
    return {
        "version": _version,
        "total_battles": ArenaBattle.objects.exclude(vote="").count(),
        "models": rows,
    }


def _expected(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


@transaction.atomic
def apply_vote(battle: ArenaBattle, vote: str) -> dict[str, Any]:
    """Persist a vote on ``battle`` and update Elo ratings atomically.

    Returns a small dict with the rating deltas for animation on the client.
    """
    ensure_ratings_exist()

    a = ModelRating.objects.select_for_update().get(model_key=battle.model_a_key)
    b = ModelRating.objects.select_for_update().get(model_key=battle.model_b_key)

    score_a = {"a": 1.0, "b": 0.0, "tie": 0.5, "both_bad": 0.5}[vote]
    score_b = 1.0 - score_a

    exp_a = _expected(a.rating, b.rating)
    exp_b = 1.0 - exp_a

    delta_a = K_FACTOR * (score_a - exp_a)
    delta_b = K_FACTOR * (score_b - exp_b)

    before_a, before_b = a.rating, b.rating
    a.rating += delta_a
    b.rating += delta_b
    a.battles += 1
    b.battles += 1
    if vote == "a":
        a.wins += 1
        b.losses += 1
    elif vote == "b":
        b.wins += 1
        a.losses += 1
    else:
        a.ties += 1
        b.ties += 1
    a.save()
    b.save()

    battle.vote = vote
    from django.utils import timezone

    battle.voted_at = timezone.now()
    battle.save(update_fields=["vote", "voted_at"])

    _bump_version()

    return {
        "battle_id": battle.id,
        "vote": vote,
        "model_a": {
            "key": battle.model_a_key,
            "rating_before": round(before_a, 1),
            "rating_after": round(a.rating, 1),
            "delta": round(delta_a, 1),
        },
        "model_b": {
            "key": battle.model_b_key,
            "rating_before": round(before_b, 1),
            "rating_after": round(b.rating, 1),
            "delta": round(delta_b, 1),
        },
    }


def leaderboard_sse(initial_after: int = -1) -> Iterator[bytes]:
    """Yield SSE bytes whenever the leaderboard version changes.

    Sends an immediate snapshot, then long-polls the version counter,
    re-emitting on every change. Sends a comment keep-alive every 25s so
    proxies don't close the connection.
    """
    import json

    last = initial_after if initial_after >= 0 else -1
    snap = leaderboard_snapshot()
    yield (f"event: snapshot\ndata: {json.dumps(snap, ensure_ascii=False)}\n\n").encode("utf-8")
    last = snap["version"]

    while True:
        ver = wait_for_change(after=last, timeout=25.0)
        if ver == last:
            yield b": keep-alive\n\n"
            continue
        snap = leaderboard_snapshot()
        yield (f"event: snapshot\ndata: {json.dumps(snap, ensure_ascii=False)}\n\n").encode("utf-8")
        last = snap["version"]
