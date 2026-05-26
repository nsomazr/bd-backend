from __future__ import annotations

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from chat.models import Conversation
from chat.serializers import MessageSerializer

from .models import MessageFeedback, RegenerationPair


def _actor_label(obj) -> str:
    if getattr(obj, "user_id", None) and obj.user:
        return obj.user.email
    if getattr(obj, "guest_id", None) and obj.guest:
        return f"visitor:{obj.guest.visitor_key[:8]}"
    return "unknown"


class FeedbackInputSerializer(serializers.Serializer):
    rating = serializers.ChoiceField(choices=MessageFeedback.RATING_CHOICES)
    comment = serializers.CharField(allow_blank=True, required=False, default="")


class FeedbackSerializer(serializers.ModelSerializer):
    user_email = serializers.SerializerMethodField()
    message_role = serializers.CharField(source="message.role", read_only=True)
    message_content = serializers.CharField(source="message.content", read_only=True)
    conversation_id = serializers.CharField(
        source="message.conversation.public_id", read_only=True
    )
    model_key = serializers.CharField(source="message.model_key", read_only=True)

    class Meta:
        model = MessageFeedback
        fields = (
            "id",
            "rating",
            "comment",
            "created_at",
            "updated_at",
            "user_email",
            "message_id",
            "message_role",
            "message_content",
            "conversation_id",
            "model_key",
        )

    def get_user_email(self, obj: MessageFeedback) -> str:
        return _actor_label(obj)


class RegenerationPairSerializer(serializers.ModelSerializer):
    user_email = serializers.SerializerMethodField()

    class Meta:
        model = RegenerationPair
        fields = (
            "id",
            "conversation_id",
            "user_message_id",
            "user_email",
            "prompt",
            "rejected_text",
            "rejected_model_key",
            "chosen_text",
            "chosen_model_key",
            "created_at",
        )

    def get_user_email(self, obj: RegenerationPair) -> str:
        return _actor_label(obj)


class ArenaPairSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    user_email = serializers.CharField()
    prompt = serializers.CharField()
    chosen_text = serializers.CharField()
    chosen_model_key = serializers.CharField()
    rejected_text = serializers.CharField()
    rejected_model_key = serializers.CharField()
    vote = serializers.CharField()
    created_at = serializers.DateTimeField()
    voted_at = serializers.DateTimeField(allow_null=True)


class AdminVisitorSerializer(serializers.Serializer):
    visitor_key = serializers.CharField()
    linked_user_email = serializers.SerializerMethodField()
    first_seen = serializers.DateTimeField()
    last_seen = serializers.DateTimeField()
    visit_count = serializers.IntegerField()
    first_ip = serializers.IPAddressField(allow_null=True)
    last_ip = serializers.IPAddressField(allow_null=True)
    country = serializers.CharField()
    region = serializers.CharField()
    city = serializers.CharField()
    location_label = serializers.CharField()
    user_agent = serializers.CharField()
    conversation_count = serializers.IntegerField()
    message_count = serializers.IntegerField()

    def get_linked_user_email(self, obj) -> str | None:
        return obj.linked_user.email if obj.linked_user_id else None


class AdminConversationSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source="public_id", read_only=True)
    owner_type = serializers.SerializerMethodField()
    owner_label = serializers.SerializerMethodField()
    visitor_key = serializers.SerializerMethodField()
    location_label = serializers.SerializerMethodField()
    message_count = serializers.SerializerMethodField()
    messages = MessageSerializer(many=True, read_only=True)

    class Meta:
        model = Conversation
        fields = (
            "id",
            "title",
            "model_key",
            "created_at",
            "updated_at",
            "owner_type",
            "owner_label",
            "visitor_key",
            "location_label",
            "message_count",
            "messages",
        )

    def get_owner_type(self, obj: Conversation) -> str:
        if obj.user_id:
            return "registered"
        if obj.guest_id:
            return "guest"
        return "unknown"

    def get_owner_label(self, obj: Conversation) -> str:
        if obj.user_id and obj.user:
            return obj.user.email
        if obj.guest_id and obj.guest:
            return f"visitor:{obj.guest.visitor_key[:8]}"
        return "unknown"

    def get_visitor_key(self, obj: Conversation) -> str | None:
        return obj.guest.visitor_key if obj.guest_id and obj.guest else None

    def get_location_label(self, obj: Conversation) -> str | None:
        if obj.guest_id and obj.guest:
            return obj.guest.location_label
        return None

    def get_message_count(self, obj: Conversation) -> int:
        if hasattr(obj, "message_count"):
            return obj.message_count
        return obj.messages.count()


class AdminVisitorDetailSerializer(AdminVisitorSerializer):
    conversations = serializers.SerializerMethodField()

    @extend_schema_field(AdminConversationSerializer(many=True))
    def get_conversations(self, obj):
        qs = obj.conversations.order_by("-updated_at")[:50]
        return AdminConversationSerializer(qs, many=True).data
