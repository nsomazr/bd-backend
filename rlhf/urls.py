from django.urls import path

from .views import (
    AdminArenaListView,
    AdminExportDPOView,
    AdminExportFeedbackView,
    AdminExportRawView,
    AdminExportSFTView,
    AdminFeedbackListView,
    AdminRegenListView,
    AdminStatsView,
    ConversationRegenerateView,
    MessageFeedbackView,
)

urlpatterns = [
    # End-user write endpoints
    path(
        "messages/<int:message_id>/feedback/",
        MessageFeedbackView.as_view(),
        name="message-feedback",
    ),
    path(
        "conversations/<str:public_id>/regenerate/",
        ConversationRegenerateView.as_view(),
        name="conversation-regenerate",
    ),
    # Admin browse
    path("admin/rlhf/stats/", AdminStatsView.as_view(), name="rlhf-admin-stats"),
    path("admin/rlhf/feedback/", AdminFeedbackListView.as_view(), name="rlhf-admin-feedback"),
    path("admin/rlhf/regenerations/", AdminRegenListView.as_view(), name="rlhf-admin-regen"),
    path("admin/rlhf/arena/", AdminArenaListView.as_view(), name="rlhf-admin-arena"),
    # Admin exports
    path("admin/rlhf/exports/dpo.jsonl", AdminExportDPOView.as_view(), name="rlhf-export-dpo"),
    path(
        "admin/rlhf/exports/feedback.<str:fmt>",
        AdminExportFeedbackView.as_view(),
        name="rlhf-export-feedback",
    ),
    path("admin/rlhf/exports/sft.jsonl", AdminExportSFTView.as_view(), name="rlhf-export-sft"),
    path(
        "admin/rlhf/exports/<str:source>.jsonl",
        AdminExportRawView.as_view(),
        name="rlhf-export-raw",
    ),
]
