from __future__ import annotations

from django.contrib.auth import authenticate
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User


def tokens_for_user(user: User) -> dict[str, str]:
    refresh = RefreshToken.for_user(user)
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


def _derive_name_from_email(email: str) -> str:
    """Turn 'bobsmith@x.com' into a friendly display name like 'Bobsmith'."""
    local = (email or "").split("@", 1)[0]
    cleaned = local.replace(".", " ").replace("_", " ").replace("-", " ").strip()
    if not cleaned:
        return ""
    return " ".join(part.capitalize() for part in cleaned.split() if part)


class UserSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ("id", "email", "name", "display_name", "date_joined", "is_staff")
        read_only_fields = ("id", "date_joined", "display_name", "is_staff")


class RegisterSerializer(serializers.Serializer):
    """Minimal signup: just email + password. Name is optional and auto-derived
    from the email local-part when not supplied."""

    email = serializers.EmailField()
    name = serializers.CharField(max_length=120, allow_blank=True, required=False)
    password = serializers.CharField(
        write_only=True,
        min_length=6,
        error_messages={"min_length": "Use at least 6 characters."},
    )

    def validate_email(self, value: str) -> str:
        normalized = (value or "").strip().lower()
        if User.objects.filter(email__iexact=normalized).exists():
            raise serializers.ValidationError("That email is already in use.")
        return normalized

    def create(self, validated_data: dict) -> User:
        name = validated_data.get("name", "").strip()
        if not name:
            name = _derive_name_from_email(validated_data["email"])
        return User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            name=name,
        )


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs: dict) -> dict:
        user = authenticate(
            request=self.context.get("request"),
            username=attrs["email"].strip().lower(),
            password=attrs["password"],
        )
        if not user or not user.is_active:
            raise serializers.ValidationError("That email and password did not match.")
        attrs["user"] = user
        return attrs
