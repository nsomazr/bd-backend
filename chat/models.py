from __future__ import annotations

from django.conf import settings
from django.db import models

from .ids import assign_unique_public_id


class Conversation(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversations",
        null=True,
        blank=True,
    )
    guest = models.ForeignKey(
        "accounts.GuestVisitor",
        on_delete=models.CASCADE,
        related_name="conversations",
        null=True,
        blank=True,
    )
    public_id = models.CharField(max_length=16, unique=True, editable=False, db_index=True)
    title = models.CharField(max_length=200, blank=True, default="New chat")
    model_key = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["user", "-updated_at"]),
            models.Index(fields=["guest", "-updated_at"]),
        ]

    def save(self, *args, **kwargs):
        assign_unique_public_id(self)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.public_id}:{self.title or 'New chat'}"


class Message(models.Model):
    ROLE_CHOICES = (
        ("user", "user"),
        ("assistant", "assistant"),
        ("system", "system"),
    )

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(max_length=12, choices=ROLE_CHOICES)
    content = models.TextField()
    model_key = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["conversation", "created_at"])]

    def __str__(self) -> str:
        return f"{self.role}:{self.content[:32]}"
