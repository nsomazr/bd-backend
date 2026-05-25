from __future__ import annotations

from django.conf import settings
from django.db import models


class ArenaBattle(models.Model):
    VOTE_CHOICES = (
        ("a", "A is better"),
        ("b", "B is better"),
        ("tie", "Tie"),
        ("both_bad", "Both bad"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="arena_battles",
        null=True,
        blank=True,
    )
    guest = models.ForeignKey(
        "accounts.GuestVisitor",
        on_delete=models.CASCADE,
        related_name="arena_battles",
        null=True,
        blank=True,
    )
    prompt = models.TextField()
    model_a_key = models.CharField(max_length=64)
    model_b_key = models.CharField(max_length=64)
    response_a = models.TextField(blank=True, default="")
    response_b = models.TextField(blank=True, default="")
    vote = models.CharField(max_length=12, choices=VOTE_CHOICES, blank=True, default="")
    voted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["guest", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"Battle#{self.pk} {self.model_a_key} vs {self.model_b_key}"


class ModelRating(models.Model):
    """Persistent Elo rating + tally for each model in the arena."""

    model_key = models.CharField(max_length=64, unique=True)
    rating = models.FloatField(default=1000.0)
    battles = models.PositiveIntegerField(default=0)
    wins = models.PositiveIntegerField(default=0)
    losses = models.PositiveIntegerField(default=0)
    ties = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-rating"]

    def __str__(self) -> str:
        return f"{self.model_key}: {self.rating:.0f} ({self.battles} battles)"

    @property
    def win_rate(self) -> float:
        decided = self.wins + self.losses
        if decided == 0:
            return 0.0
        return self.wins / decided
