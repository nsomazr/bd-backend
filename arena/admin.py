from django.contrib import admin

from .models import ArenaBattle, ModelRating


@admin.register(ArenaBattle)
class ArenaBattleAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "model_a_key", "model_b_key", "vote", "created_at")
    list_filter = ("vote", "model_a_key", "model_b_key")
    search_fields = ("prompt",)
    readonly_fields = (
        "user",
        "prompt",
        "model_a_key",
        "model_b_key",
        "response_a",
        "response_b",
        "vote",
        "voted_at",
        "created_at",
    )


@admin.register(ModelRating)
class ModelRatingAdmin(admin.ModelAdmin):
    list_display = ("model_key", "rating", "battles", "wins", "losses", "ties", "updated_at")
    readonly_fields = ("updated_at",)
