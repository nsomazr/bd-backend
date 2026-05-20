from django.urls import path

from .views import (
    ArenaBattleCreateView,
    ArenaBattleVoteView,
    LeaderboardStreamView,
    LeaderboardView,
)

urlpatterns = [
    path("arena/battles/", ArenaBattleCreateView.as_view(), name="arena-battle-create"),
    path(
        "arena/battles/<int:pk>/vote/",
        ArenaBattleVoteView.as_view(),
        name="arena-battle-vote",
    ),
    path("arena/leaderboard/", LeaderboardView.as_view(), name="arena-leaderboard"),
    path(
        "arena/leaderboard/stream/",
        LeaderboardStreamView.as_view(),
        name="arena-leaderboard-stream",
    ),
]
