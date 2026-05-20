from __future__ import annotations

from rest_framework import serializers

from .models import MessageFeedback, RegenerationPair


class FeedbackInputSerializer(serializers.Serializer):
    rating = serializers.ChoiceField(choices=MessageFeedback.RATING_CHOICES)
    comment = serializers.CharField(allow_blank=True, required=False, default="")


class FeedbackSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source="user.email", read_only=True)
    message_role = serializers.CharField(source="message.role", read_only=True)
    message_content = serializers.CharField(source="message.content", read_only=True)
    conversation_id = serializers.IntegerField(
        source="message.conversation_id", read_only=True
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


class RegenerationPairSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source="user.email", read_only=True)

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


class ArenaPairSerializer(serializers.Serializer):
    """Read-only projection of an ArenaBattle into DPO-pair shape."""

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
