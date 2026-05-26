from __future__ import annotations

import json
import logging
from collections.abc import Iterator

from django.db.models import Count, Q
from django.http import StreamingHttpResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import GuestVisitor
from accounts.permissions import RequiresUserOrVisitor
from accounts.visitors import actor_owner_kwargs, conversation_owner_q
from bd_backend.api_schema import ConversationRegenerateRequestSerializer, VISITOR_ID_HEADER
from llm.generator import user_facing_generation_error

from arena.models import ArenaBattle
from chat.models import Conversation, Message
from llm.generator import stream_completion
from llm.loader import loader
from llm.registry import MODEL_REGISTRY

from .exporters import (
    arena_pair_iter,
    dpo_pair_iter,
    feedback_csv_bytes,
    feedback_jsonl_iter,
    iter_jsonl,
    regen_pair_iter,
    sft_jsonl_iter,
)
from .models import MessageFeedback, RegenerationPair
from .permissions import IsStaff
from .serializers import (
    AdminConversationSerializer,
    AdminVisitorDetailSerializer,
    AdminVisitorSerializer,
    ArenaPairSerializer,
    FeedbackInputSerializer,
    FeedbackSerializer,
    RegenerationPairSerializer,
)

logger = logging.getLogger("rlhf")


class _SSERenderer(BaseRenderer):
    media_type = "text/event-stream"
    format = "sse"
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if data is None:
            return b""
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
        return str(data).encode(self.charset)


def _sse(data: dict, event: str | None = None) -> bytes:
    parts: list[str] = []
    if event:
        parts.append(f"event: {event}")
    parts.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    parts.append("")
    parts.append("")
    return "\n".join(parts).encode("utf-8")


# ---------- per-user feedback -----------------------------------------------


class MessageFeedbackView(APIView):
    """POST a thumbs up/down (with optional comment) on a single message."""

    permission_classes = (RequiresUserOrVisitor,)

    @extend_schema(
        summary="Submit message feedback",
        parameters=[VISITOR_ID_HEADER],
        request=FeedbackInputSerializer,
        responses={200: FeedbackSerializer},
    )
    def post(self, request, message_id: int):
        owner = conversation_owner_q(request.actor)
        msg = get_object_or_404(
            Message,
            pk=message_id,
            role="assistant",
            **{f"conversation__{k}": v for k, v in owner.items()},
        )
        serializer = FeedbackInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fb, _ = MessageFeedback.objects.update_or_create(
            message=msg,
            defaults={
                **actor_owner_kwargs(request.actor),
                "rating": serializer.validated_data["rating"],
                "comment": serializer.validated_data.get("comment", "") or "",
            },
        )
        return Response(FeedbackSerializer(fb).data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Delete message feedback",
        parameters=[VISITOR_ID_HEADER],
        responses={204: None},
    )
    def delete(self, request, message_id: int):
        owner = conversation_owner_q(request.actor)
        MessageFeedback.objects.filter(
            message_id=message_id,
            **{f"message__conversation__{k}": v for k, v in owner.items()},
        ).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------- regenerate (DPO pair capture) ----------------------------------


class ConversationRegenerateView(APIView):
    """Regenerate the most recent assistant message for a conversation.

    Streams tokens via SSE and, on success, stores a ``RegenerationPair``
    capturing (rejected = old assistant message, chosen = new one).
    """

    permission_classes = (RequiresUserOrVisitor,)
    renderer_classes = (_SSERenderer, JSONRenderer)

    @extend_schema(
        summary="Regenerate latest assistant reply",
        description=(
            "Regenerate the latest assistant reply and receive a Server-Sent "
            "Events stream. Useful for retry UX and RLHF data collection."
        ),
        parameters=[VISITOR_ID_HEADER],
        request=ConversationRegenerateRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=OpenApiTypes.STR,
                description="SSE stream with regenerated response tokens.",
                examples=[
                    OpenApiExample(
                        "Regenerate SSE sample",
                        value=(
                            "event: start\n"
                            'data: {"conversation_id":"abc123","rejected_message_id":9,"model_key":"gemma4-e4b"}\n\n'
                            "event: token\n"
                            'data: {"delta":"Updated"}\n\n'
                            "event: done\n"
                            'data: {"assistant_message_id":10,"rejected_message_id":9,"content":"Updated reply"}\n\n'
                        ),
                    )
                ],
            )
        },
    )
    def post(self, request, public_id: str):
        convo = get_object_or_404(
            Conversation, public_id=public_id, **conversation_owner_q(request.actor)
        )

        last_assistant = (
            convo.messages.filter(role="assistant").order_by("-created_at", "-id").first()
        )
        if last_assistant is None:
            return Response(
                {"detail": "No assistant message to regenerate."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # The prompt that produced it is the most recent user message that came
        # before the assistant message we are regenerating.
        last_user = (
            convo.messages.filter(role="user", created_at__lte=last_assistant.created_at)
            .order_by("-created_at", "-id")
            .first()
        )
        if last_user is None:
            return Response(
                {"detail": "Could not find the user prompt to regenerate from."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        previous_model = convo.model_key
        requested_model = request.data.get("model_key") or last_assistant.model_key or convo.model_key
        if requested_model not in MODEL_REGISTRY:
            return Response(
                {"detail": f"Unknown model_key: {requested_model}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        model_switched = requested_model != previous_model

        # History to feed the model: everything strictly before the assistant
        # message we are about to replace.
        history_qs = convo.messages.filter(created_at__lt=last_assistant.created_at).order_by(
            "created_at", "id"
        )
        history = [{"role": m.role, "content": m.content} for m in history_qs]

        rejected_text = last_assistant.content
        rejected_model_key = last_assistant.model_key

        def event_stream() -> Iterator[bytes]:
            yield _sse(
                {
                    "conversation_id": convo.public_id,
                    "rejected_message_id": last_assistant.id,
                    "model_key": requested_model,
                },
                event="start",
            )
            collected: list[str] = []
            try:
                with loader.session(
                    requested_model,
                    unload_if_idle=model_switched,
                ) as loaded:
                    yield _sse({"model_key": requested_model}, event="model_ready")
                    for chunk in stream_completion(loaded, history):
                        collected.append(chunk)
                        yield _sse({"delta": chunk}, event="token")
            except BaseException as exc:
                logger.exception("Regeneration failed")
                yield _sse({"error": user_facing_generation_error(exc)}, event="error")
                return

            full_text = "".join(collected).strip()
            if not full_text:
                yield _sse({"error": "Empty regeneration"}, event="error")
                return

            # Replace the old assistant message and record the DPO pair.
            old_id = last_assistant.id
            last_assistant.delete()
            new_msg = Message.objects.create(
                conversation=convo,
                role="assistant",
                content=full_text,
                model_key=requested_model,
            )
            convo.model_key = requested_model
            convo.save(update_fields=["model_key", "updated_at"])

            RegenerationPair.objects.create(
                conversation=convo,
                **actor_owner_kwargs(request.actor),
                user_message=last_user,
                prompt=last_user.content,
                history=history,
                rejected_text=rejected_text,
                rejected_model_key=rejected_model_key,
                chosen_text=full_text,
                chosen_model_key=requested_model,
            )

            yield _sse(
                {
                    "assistant_message_id": new_msg.id,
                    "rejected_message_id": old_id,
                    "content": full_text,
                },
                event="done",
            )

        response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


# ---------- admin browse ----------------------------------------------------


class _AdminPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500


class AdminStatsView(APIView):
    permission_classes = (IsStaff,)

    @extend_schema(
        operation_id="admin_rlhf_stats",
        summary="Get RLHF admin stats",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        arena_qs = ArenaBattle.objects.exclude(vote="")
        feedback_counts = MessageFeedback.objects.values("rating").annotate(
            n=Count("id")
        )
        rating_breakdown = {row["rating"]: row["n"] for row in feedback_counts}
        return Response(
            {
                "users": {
                    "total": _user_count(),
                    "staff": _user_count(is_staff=True),
                },
                "visitors": {
                    "total": GuestVisitor.objects.count(),
                    "with_conversations": GuestVisitor.objects.filter(
                        conversations__isnull=False
                    )
                    .distinct()
                    .count(),
                    "countries": GuestVisitor.objects.exclude(country="")
                    .values("country")
                    .distinct()
                    .count(),
                },
                "conversations": Conversation.objects.count(),
                "messages": Message.objects.count(),
                "feedback": {
                    "total": MessageFeedback.objects.count(),
                    "up": rating_breakdown.get("up", 0),
                    "down": rating_breakdown.get("down", 0),
                },
                "arena": {
                    "total_battles": ArenaBattle.objects.count(),
                    "voted_battles": arena_qs.count(),
                    "decisive_battles": arena_qs.exclude(
                        vote__in=("tie", "both_bad")
                    ).count(),
                },
                "regenerations": RegenerationPair.objects.count(),
                "dpo_pairs_available": _dpo_count(),
                "as_of": timezone.now(),
            }
        )


def _user_count(**kwargs) -> int:
    from accounts.models import User

    return User.objects.filter(**kwargs).count()


def _dpo_count() -> int:
    arena = (
        ArenaBattle.objects.exclude(vote="")
        .exclude(vote__in=("tie", "both_bad"))
        .count()
    )
    return arena + RegenerationPair.objects.count()


class AdminFeedbackListView(APIView):
    permission_classes = (IsStaff,)

    @extend_schema(
        operation_id="admin_rlhf_feedback_list",
        summary="List feedback records",
        parameters=[
            OpenApiParameter("page", int, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("page_size", int, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("rating", str, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("q", str, OpenApiParameter.QUERY, required=False),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        qs = MessageFeedback.objects.select_related(
            "user", "guest", "message", "message__conversation"
        )
        rating = request.query_params.get("rating")
        if rating in ("up", "down"):
            qs = qs.filter(rating=rating)
        q = request.query_params.get("q")
        if q:
            qs = qs.filter(
                Q(comment__icontains=q)
                | Q(message__content__icontains=q)
                | Q(user__email__icontains=q)
                | Q(guest__visitor_key__icontains=q)
            )
        paginator = _AdminPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(FeedbackSerializer(page, many=True).data)


class AdminRegenListView(APIView):
    permission_classes = (IsStaff,)

    @extend_schema(
        operation_id="admin_rlhf_regeneration_list",
        summary="List regeneration pairs",
        parameters=[
            OpenApiParameter("page", int, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("page_size", int, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("q", str, OpenApiParameter.QUERY, required=False),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        qs = RegenerationPair.objects.select_related("user", "guest")
        q = request.query_params.get("q")
        if q:
            qs = qs.filter(
                Q(prompt__icontains=q)
                | Q(rejected_text__icontains=q)
                | Q(chosen_text__icontains=q)
                | Q(user__email__icontains=q)
                | Q(guest__visitor_key__icontains=q)
            )
        paginator = _AdminPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(
            RegenerationPairSerializer(page, many=True).data
        )


class AdminArenaListView(APIView):
    permission_classes = (IsStaff,)

    @extend_schema(
        operation_id="admin_rlhf_arena_list",
        summary="List arena preference pairs",
        parameters=[
            OpenApiParameter("page", int, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("page_size", int, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("q", str, OpenApiParameter.QUERY, required=False),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        qs = (
            ArenaBattle.objects.select_related("user", "guest")
            .exclude(vote="")
            .exclude(vote__in=("tie", "both_bad"))
        )
        q = request.query_params.get("q")
        if q:
            qs = qs.filter(
                Q(prompt__icontains=q)
                | Q(response_a__icontains=q)
                | Q(response_b__icontains=q)
                | Q(user__email__icontains=q)
                | Q(guest__visitor_key__icontains=q)
            )
        paginator = _AdminPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        pairs = [_arena_to_pair(b) for b in page]
        return paginator.get_paginated_response(
            ArenaPairSerializer(pairs, many=True).data
        )


def _arena_to_pair(b: ArenaBattle) -> dict:
    if b.vote == "a":
        chosen, chosen_key = b.response_a, b.model_a_key
        rejected, rejected_key = b.response_b, b.model_b_key
    else:
        chosen, chosen_key = b.response_b, b.model_b_key
        rejected, rejected_key = b.response_a, b.model_a_key
    actor = (
        b.user.email
        if b.user_id
        else f"visitor:{b.guest.visitor_key[:8]}" if b.guest_id else "unknown"
    )
    return {
        "id": b.id,
        "user_email": actor,
        "prompt": b.prompt,
        "chosen_text": chosen,
        "chosen_model_key": chosen_key,
        "rejected_text": rejected,
        "rejected_model_key": rejected_key,
        "vote": b.vote,
        "created_at": b.created_at,
        "voted_at": b.voted_at,
    }


# ---------- admin exports ---------------------------------------------------


class AdminExportDPOView(APIView):
    """JSONL export of all DPO pairs (arena + regeneration)."""

    permission_classes = (IsStaff,)

    @extend_schema(
        operation_id="admin_rlhf_export_dpo",
        summary="Export DPO pairs",
        parameters=[
            OpenApiParameter("source", str, OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: OpenApiResponse(
                response=OpenApiTypes.BINARY,
                description="NDJSON download.",
            )
        },
    )
    def get(self, request):
        source = request.query_params.get("source")
        arena_qs = None
        regen_qs = None
        if source == "arena":
            regen_qs = RegenerationPair.objects.none()
        elif source == "regeneration":
            arena_qs = ArenaBattle.objects.none()
        rows = dpo_pair_iter(arena_qs=arena_qs, regen_qs=regen_qs)
        response = StreamingHttpResponse(iter_jsonl(rows), content_type="application/x-ndjson")
        response["Content-Disposition"] = 'attachment; filename="maisha_dpo_pairs.jsonl"'
        return response


class AdminExportFeedbackView(APIView):
    permission_classes = (IsStaff,)

    @extend_schema(
        operation_id="admin_rlhf_export_feedback",
        summary="Export message feedback",
        responses={
            200: OpenApiResponse(
                response=OpenApiTypes.BINARY,
                description="CSV or NDJSON download.",
            )
        },
    )
    def get(self, request, fmt: str):
        qs = MessageFeedback.objects.all()
        if fmt == "csv":
            data = feedback_csv_bytes(qs)
            response = HttpResponse(data, content_type="text/csv")
            response["Content-Disposition"] = 'attachment; filename="maisha_feedback.csv"'
            return response
        if fmt == "jsonl":
            response = StreamingHttpResponse(
                iter_jsonl(feedback_jsonl_iter(qs)),
                content_type="application/x-ndjson",
            )
            response["Content-Disposition"] = 'attachment; filename="maisha_feedback.jsonl"'
            return response
        return Response({"detail": "fmt must be csv or jsonl"}, status=400)


class AdminExportSFTView(APIView):
    """JSONL of every thumbs-up assistant message, formatted as SFT samples."""

    permission_classes = (IsStaff,)

    @extend_schema(
        operation_id="admin_rlhf_export_sft",
        summary="Export SFT dataset",
        responses={
            200: OpenApiResponse(
                response=OpenApiTypes.BINARY,
                description="NDJSON download.",
            )
        },
    )
    def get(self, request):
        msg_ids = MessageFeedback.objects.filter(rating="up").values_list(
            "message_id", flat=True
        )
        qs = Message.objects.filter(id__in=list(msg_ids)).order_by("conversation_id", "created_at")
        response = StreamingHttpResponse(
            iter_jsonl(sft_jsonl_iter(qs)),
            content_type="application/x-ndjson",
        )
        response["Content-Disposition"] = 'attachment; filename="maisha_sft.jsonl"'
        return response


class AdminExportRawView(APIView):
    """JSONL dump of arena rows or regeneration pairs as-is (for inspection)."""

    permission_classes = (IsStaff,)

    @extend_schema(
        operation_id="admin_rlhf_export_raw",
        summary="Export raw RLHF rows",
        responses={
            200: OpenApiResponse(
                response=OpenApiTypes.BINARY,
                description="NDJSON download.",
            )
        },
    )
    def get(self, request, source: str):
        if source == "arena":
            rows = arena_pair_iter(
                ArenaBattle.objects.exclude(vote="")
                .exclude(vote__in=("tie", "both_bad"))
            )
            name = "arena_pairs.jsonl"
        elif source == "regeneration":
            rows = regen_pair_iter(RegenerationPair.objects.all())
            name = "regeneration_pairs.jsonl"
        else:
            return Response({"detail": "source must be arena or regeneration"}, status=400)
        response = StreamingHttpResponse(iter_jsonl(rows), content_type="application/x-ndjson")
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        return response


class AdminVisitorsListView(APIView):
    permission_classes = (IsStaff,)

    @extend_schema(
        operation_id="admin_rlhf_visitor_list",
        summary="List tracked visitors",
        parameters=[
            OpenApiParameter("page", int, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("page_size", int, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("country", str, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("q", str, OpenApiParameter.QUERY, required=False),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        qs = GuestVisitor.objects.annotate(
            conversation_count=Count("conversations", distinct=True),
            message_count=Count("conversations__messages", distinct=True),
        )
        country = request.query_params.get("country")
        if country:
            qs = qs.filter(country__iexact=country)
        q = request.query_params.get("q")
        if q:
            qs = qs.filter(
                Q(visitor_key__icontains=q)
                | Q(city__icontains=q)
                | Q(region__icontains=q)
                | Q(country__icontains=q)
                | Q(last_ip__icontains=q)
                | Q(linked_user__email__icontains=q)
            )
        paginator = _AdminPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(
            AdminVisitorSerializer(page, many=True).data
        )


class AdminVisitorDetailView(APIView):
    permission_classes = (IsStaff,)

    @extend_schema(
        operation_id="admin_rlhf_visitor_detail",
        summary="Get visitor detail",
        responses={200: AdminVisitorDetailSerializer},
    )
    def get(self, request, visitor_key: str):
        visitor = get_object_or_404(
            GuestVisitor.objects.annotate(
                conversation_count=Count("conversations", distinct=True),
                message_count=Count("conversations__messages", distinct=True),
            ),
            visitor_key=visitor_key,
        )
        return Response(AdminVisitorDetailSerializer(visitor).data)


class AdminConversationsListView(APIView):
    permission_classes = (IsStaff,)

    @extend_schema(
        operation_id="admin_rlhf_conversation_list",
        summary="List conversations for admin review",
        parameters=[
            OpenApiParameter("page", int, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("page_size", int, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("owner", str, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("visitor_key", str, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("user_email", str, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("q", str, OpenApiParameter.QUERY, required=False),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        qs = Conversation.objects.select_related("user", "guest").annotate(
            message_count=Count("messages")
        )
        owner = request.query_params.get("owner")
        if owner == "registered":
            qs = qs.filter(user__isnull=False)
        elif owner == "guest":
            qs = qs.filter(guest__isnull=False)
        visitor_key = request.query_params.get("visitor_key")
        if visitor_key:
            qs = qs.filter(guest__visitor_key=visitor_key)
        user_email = request.query_params.get("user_email")
        if user_email:
            qs = qs.filter(user__email__icontains=user_email)
        q = request.query_params.get("q")
        if q:
            qs = qs.filter(
                Q(title__icontains=q)
                | Q(public_id__icontains=q)
                | Q(user__email__icontains=q)
                | Q(guest__visitor_key__icontains=q)
            )
        paginator = _AdminPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(
            AdminConversationSerializer(page, many=True).data
        )


class AdminConversationDetailView(APIView):
    permission_classes = (IsStaff,)

    @extend_schema(
        operation_id="admin_rlhf_conversation_detail",
        summary="Get conversation detail for admin review",
        responses={200: AdminConversationSerializer},
    )
    def get(self, request, public_id: str):
        convo = get_object_or_404(
            Conversation.objects.select_related("user", "guest").prefetch_related(
                "messages"
            ),
            public_id=public_id,
        )
        return Response(AdminConversationSerializer(convo).data)
