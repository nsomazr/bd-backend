from __future__ import annotations

import json
import logging
import random
from collections.abc import Iterator

from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import RequiresUserOrVisitor
from accounts.visitors import actor_owner_kwargs, conversation_owner_q
from bd_backend.api_schema import (
    ArenaBattleCreateRequestSerializer,
    ArenaVoteRequestSerializer,
    ArenaVoteResponseSerializer,
    LeaderboardSnapshotSerializer,
    VISITOR_ID_HEADER,
)

from llm.generator import stream_completion, user_facing_generation_error
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

    @extend_schema(
        summary="Create arena battle",
        description=(
            "Pick two random models and stream both responses over SSE. "
            "Events include `start`, `model_loading`, `model_ready`, `token`, "
            "`response_done`, `done`, and `error`."
        ),
        parameters=[VISITOR_ID_HEADER],
        request=ArenaBattleCreateRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=OpenApiTypes.STR,
                description="SSE stream containing both arena model outputs.",
                examples=[
                    OpenApiExample(
                        "Arena SSE sample",
                        value=(
                            "event: start\n"
                            'data: {"battle_id":1,"prompt":"Who can donate blood?"}\n\n'
                            "event: token\n"
                            'data: {"slot":"a","delta":"Hello"}\n\n'
                            "event: response_done\n"
                            'data: {"slot":"a","content":"Hello"}\n\n'
                            "event: done\n"
                            'data: {"battle_id":1,"response_a":"...","response_b":"..."}\n\n'
                        ),
                    )
                ],
            )
        },
    )
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
                    with loader.session(model_key, unload_if_idle=True) as loaded:
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
                        {"slot": slot, "error": user_facing_generation_error(exc)},
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

    @extend_schema(
        summary="Vote on arena battle",
        parameters=[VISITOR_ID_HEADER],
        request=ArenaVoteRequestSerializer,
        responses={200: ArenaVoteResponseSerializer},
    )
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

    @extend_schema(
        summary="Get leaderboard",
        responses={200: LeaderboardSnapshotSerializer},
    )
    def get(self, request):
        return Response(leaderboard_snapshot())


class LeaderboardStreamView(APIView):
    permission_classes = ()
    renderer_classes = (ServerSentEventsRenderer, JSONRenderer)

    @extend_schema(
        summary="Stream leaderboard updates",
        description="Server-Sent Events stream of leaderboard snapshots.",
        responses={
            200: OpenApiResponse(
                response=OpenApiTypes.STR,
                description="SSE stream with leaderboard snapshots.",
            )
        },
    )
    def get(self, request):
        response = StreamingHttpResponse(
            leaderboard_sse(),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response
