from __future__ import annotations

import json
import logging
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
from llm.registry import DEFAULT_MODEL_KEY, MODEL_REGISTRY

from .models import Conversation, Message
from .serializers import (
    ConversationDetailSerializer,
    ConversationSerializer,
    MessageSerializer,
)

logger = logging.getLogger("chat")


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


def _get_conversation(request, public_id: str) -> Conversation:
    return get_object_or_404(
        Conversation,
        public_id=public_id,
        **conversation_owner_q(request.actor),
    )


class ConversationListCreateView(APIView):
    permission_classes = (RequiresUserOrVisitor,)

    def get(self, request):
        qs = Conversation.objects.filter(**conversation_owner_q(request.actor))
        return Response(ConversationSerializer(qs, many=True).data)

    def post(self, request):
        data = dict(request.data)
        data.setdefault("model_key", DEFAULT_MODEL_KEY)
        serializer = ConversationSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        convo = serializer.save(**actor_owner_kwargs(request.actor))
        return Response(
            ConversationSerializer(convo).data,
            status=status.HTTP_201_CREATED,
        )


class ConversationDetailView(APIView):
    permission_classes = (RequiresUserOrVisitor,)

    def get(self, request, public_id: str):
        convo = _get_conversation(request, public_id)
        return Response(ConversationDetailSerializer(convo).data)

    def patch(self, request, public_id: str):
        convo = _get_conversation(request, public_id)
        serializer = ConversationSerializer(convo, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, public_id: str):
        convo = _get_conversation(request, public_id)
        convo.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ConversationMessagesView(APIView):
    permission_classes = (RequiresUserOrVisitor,)

    def get(self, request, public_id: str):
        convo = _get_conversation(request, public_id)
        return Response(MessageSerializer(convo.messages.all(), many=True).data)


class ConversationCompleteView(APIView):
    """POST a user message and receive an SSE stream of assistant tokens."""

    permission_classes = (RequiresUserOrVisitor,)
    renderer_classes = (ServerSentEventsRenderer, JSONRenderer)

    def post(self, request, public_id: str):
        convo = _get_conversation(request, public_id)
        content = (request.data.get("content") or "").strip()
        if not content:
            return Response(
                {"detail": "content is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        requested_model = request.data.get("model_key") or convo.model_key
        if requested_model not in MODEL_REGISTRY:
            return Response(
                {"detail": f"Unknown model_key: {requested_model}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if requested_model != convo.model_key:
            convo.model_key = requested_model

        user_msg = Message.objects.create(
            conversation=convo,
            role="user",
            content=content,
            model_key=requested_model,
        )

        if not convo.title or convo.title == "New chat":
            convo.title = content[:40] + ("..." if len(content) > 40 else "")
        convo.save(update_fields=["title", "model_key", "updated_at"])

        history = [
            {"role": m.role, "content": m.content}
            for m in convo.messages.all()
        ]

        def event_stream() -> Iterator[bytes]:
            yield _sse(
                {
                    "conversation_id": convo.public_id,
                    "user_message_id": user_msg.id,
                    "model_key": requested_model,
                },
                event="start",
            )
            collected: list[str] = []
            try:
                loaded = loader.get(requested_model)
                yield _sse({"model_key": requested_model}, event="model_ready")
                for chunk in stream_completion(loaded, history):
                    collected.append(chunk)
                    yield _sse({"delta": chunk}, event="token")
            except BaseException as exc:
                logger.exception("Streaming failed")
                yield _sse({"error": str(exc)}, event="error")
                return
            full_text = "".join(collected).strip()
            assistant_msg = Message.objects.create(
                conversation=convo,
                role="assistant",
                content=full_text,
                model_key=requested_model,
            )
            convo.save(update_fields=["updated_at"])
            yield _sse(
                {
                    "assistant_message_id": assistant_msg.id,
                    "content": full_text,
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
