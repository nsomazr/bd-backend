from django.contrib import admin

from .models import MessageFeedback, RegenerationPair


@admin.register(MessageFeedback)
class MessageFeedbackAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "rating", "created_at")
    list_filter = ("rating",)
    search_fields = ("comment", "message__content", "user__email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(RegenerationPair)
class RegenerationPairAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "conversation", "rejected_model_key", "chosen_model_key", "created_at")
    search_fields = ("prompt", "rejected_text", "chosen_text", "user__email")
    readonly_fields = ("created_at",)
