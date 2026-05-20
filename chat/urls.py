from django.urls import path

from .views import (
    ConversationCompleteView,
    ConversationDetailView,
    ConversationListCreateView,
    ConversationMessagesView,
)

urlpatterns = [
    path(
        "conversations/",
        ConversationListCreateView.as_view(),
        name="conversation-list",
    ),
    path(
        "conversations/<str:public_id>/",
        ConversationDetailView.as_view(),
        name="conversation-detail",
    ),
    path(
        "conversations/<str:public_id>/messages/",
        ConversationMessagesView.as_view(),
        name="conversation-messages",
    ),
    path(
        "conversations/<str:public_id>/complete/",
        ConversationCompleteView.as_view(),
        name="conversation-complete",
    ),
]
