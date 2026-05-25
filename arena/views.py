from __future__ import annotations

import json
import logging
import random
from collections.abc import Iterator

from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import RequiresUserOrVisitor
from accounts.visitors import actor_owner_kwargs, conversation_owner_q

from llm.generator import stream_completion
from llm.loader import loader
from llm.registry import MODEL_REGISTRY

from .leaderboard import (
    apply_vote,
    ensure_ratings_exist,
    leaderboard_snapshot,
    leaderboard_sse,
)
from .models import ArenaBattle

logger = logging.getLogger("arena")


class ServerSentEventsRenderer(BaseRenderer):
    media_type = "text/event-stream"
    format = "sse"
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
        if data is None:
            return b""
        return str(data).encode(self.charset)


def _sse(data: dict, event: str | None = None) -> bytes:
    parts: list[str] = []
    if event:
        parts.append(f"event: {event}")
    parts.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    parts.append("")
    parts.append("")
    return "\n".join(parts).encode("utf-8")


def _pick_two_models() -> tuple[str, str]:
    keys = list(MODEL_REGISTRY.keys())
    if len(keys) < 2:
        raise RuntimeError("At least two models are required for the arena.")
    a, b = random.sample(keys, 2)
    return a, b


class ArenaBattleCreateView(APIView):
    """POST /api/arena/battles/  -- creates a battle, streams both responses.

    Two distinct models are picked at random. Their identities are returned
    only as ``model_a_key`` / ``model_b_key`` *labels stripped* until the
    user votes (the keys are exposed but the frontend hides them by
    convention -- a future v2 can mask them server-side).
    """

    permission_classes = (RequiresUserOrVisitor,)
    renderer_classes = (ServerSentEventsRenderer, JSONRenderer)

    def post(self, request):
        prompt = (request.data.get("prompt") or "").strip()
        if not prompt:
            return Response(
                {"detail": "prompt is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ensure_ratings_exist()
        model_a, model_b = _pick_two_models()

        battle = ArenaBattle.objects.create(
            prompt=prompt,
            model_a_key=model_a,
            model_b_key=model_b,
            **actor_owner_kwargs(request.actor),
        )

        history = [{"role": "user", "content": prompt}]

        def event_stream() -> Iterator[bytes]:
            yield _sse(
                {"battle_id": battle.id, "prompt": prompt},
                event="start",
            )
            collected: dict[str, list[str]] = {"a": [], "b": []}
            for slot, model_key in (("a", model_a), ("b", model_b)):
                try:
                    yield _sse({"slot": slot}, event="model_loading")
                    loaded = loader.get(model_key)
                    yield _sse({"slot": slot}, event="model_ready")
                    for chunk in stream_completion(loaded, history):
                        collected[slot].append(chunk)
                        yield _sse({"slot": slot, "delta": chunk}, event="token")
                    yield _sse(
                        {"slot": slot, "content": "".join(collected[slot])},
                        event="response_done",
                    )
                except BaseException as exc:
                    logger.exception("Arena generation failed for slot %s", slot)
                    yield _sse(
                        {"slot": slot, "error": str(exc)},
                        event="error",
                    )
                    return

            battle.response_a = "".join(collected["a"]).strip()
            battle.response_b = "".join(collected["b"]).strip()
            battle.save(update_fields=["response_a", "response_b"])

            yield _sse(
                {
                    "battle_id": battle.id,
                    "response_a": battle.response_a,
                    "response_b": battle.response_b,
                },
                event="done",
            )

        response = StreamingHttpResponse(
            event_stream(),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


class ArenaBattleVoteView(APIView):
    """POST /api/arena/battles/<id>/vote/  body: {"vote": "a"|"b"|"tie"|"both_bad"}."""

    permission_classes = (RequiresUserOrVisitor,)

    def post(self, request, pk: int):
        owner = conversation_owner_q(request.actor)
        battle = get_object_or_404(ArenaBattle, pk=pk, **owner)
        if battle.vote:
            return Response(
                {"detail": "Vote already recorded for this battle."},
                status=status.HTTP_409_CONFLICT,
            )
        vote = request.data.get("vote")
        if vote not in {"a", "b", "tie", "both_bad"}:
            return Response(
                {"detail": "vote must be one of: a, b, tie, both_bad"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = apply_vote(battle, vote)
        result["models"] = {
            "a": {
                "key": battle.model_a_key,
                "label": MODEL_REGISTRY.get(battle.model_a_key, {}).get("label", battle.model_a_key),
            },
            "b": {
                "key": battle.model_b_key,
                "label": MODEL_REGISTRY.get(battle.model_b_key, {}).get("label", battle.model_b_key),
            },
        }
        return Response(result)


class LeaderboardView(APIView):
    permission_classes = ()

    def get(self, request):
        return Response(leaderboard_snapshot())


class LeaderboardStreamView(APIView):
    permission_classes = ()
    renderer_classes = (ServerSentEventsRenderer, JSONRenderer)

    def get(self, request):
        response = StreamingHttpResponse(
            leaderboard_sse(),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response
