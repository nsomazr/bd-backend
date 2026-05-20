"""Models that capture preference data for RLHF / DPO training.

Two main sources feed DPO pairs:

1. ``arena.ArenaBattle`` (already exists) -- explicit pairwise votes between
   two anonymous models.
2. ``RegenerationPair`` (this module) -- every time a user clicks
   "Regenerate response" in the chat, we record the previous assistant
   answer as ``rejected`` and the next one as ``chosen``.

In addition, ``MessageFeedback`` collects per-message thumbs up/down with
optional free-text comments. That is useful for reward modeling, SFT
filtering, and quality dashboards even though it is not strictly DPO-shaped.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from chat.models import Conversation, Message


class MessageFeedback(models.Model):
    RATING_CHOICES = (
        ("up", "Thumbs up"),
        ("down", "Thumbs down"),
    )

    message = models.OneToOneField(
        Message,
        on_delete=models.CASCADE,
        related_name="feedback",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="message_feedback",
    )
    rating = models.CharField(max_length=8, choices=RATING_CHOICES)
    comment = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["rating"]),
        ]

    def __str__(self) -> str:
        return f"{self.rating} on msg#{self.message_id}"


class RegenerationPair(models.Model):
    """A DPO-shaped preference pair captured at the moment of regeneration.

    ``prompt`` is what the user actually typed. The full ``history`` (system +
    prior turns) is stored separately as JSON so we can reconstruct exact
    training samples later.
    """

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="regeneration_pairs",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="regeneration_pairs",
    )
    user_message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="regenerations",
    )

    prompt = models.TextField(help_text="The user prompt at this turn.")
    history = models.JSONField(
        default=list,
        blank=True,
        help_text="Conversation history up to (but not including) the rejected response.",
    )

    rejected_text = models.TextField()
    rejected_model_key = models.CharField(max_length=64, blank=True, default="")

    chosen_text = models.TextField()
    chosen_model_key = models.CharField(max_length=64, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["conversation", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"RegenPair#{self.pk} conv={self.conversation_id}"
