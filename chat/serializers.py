from rest_framework import serializers

from llm.registry import MODEL_REGISTRY

from .models import Conversation, Message


class MessageSerializer(serializers.ModelSerializer):
    feedback_rating = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ("id", "role", "content", "model_key", "created_at", "feedback_rating")
        read_only_fields = fields

    def get_feedback_rating(self, obj: Message) -> str | None:
        fb = getattr(obj, "feedback", None)
        return fb.rating if fb else None


class ConversationSerializer(serializers.ModelSerializer):
    # External API id: 16-char public token used in /c/<id> URLs.
    id = serializers.CharField(source="public_id", read_only=True)

    class Meta:
        model = Conversation
        fields = ("id", "title", "model_key", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_model_key(self, value: str) -> str:
        if value not in MODEL_REGISTRY:
            raise serializers.ValidationError(
                f"Unknown model_key. Allowed: {sorted(MODEL_REGISTRY)}"
            )
        return value


class ConversationDetailSerializer(ConversationSerializer):
    messages = MessageSerializer(many=True, read_only=True)

    class Meta(ConversationSerializer.Meta):
        fields = ConversationSerializer.Meta.fields + ("messages",)
