from __future__ import annotations

from rest_framework import status
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenRefreshView

from accounts.permissions import AllowAnyWithVisitor
from accounts.visitors import merge_guest_into_user, resolve_actor
from bd_backend.api_schema import (
    AuthResponseSerializer,
    TokenRefreshRequestSerializer,
    TokenRefreshResponseSerializer,
    VISITOR_ID_HEADER,
)

from .serializers import (
    LoginSerializer,
    RegisterSerializer,
    UserSerializer,
    tokens_for_user,
)


class RegisterView(APIView):
    permission_classes = (AllowAnyWithVisitor,)

    @extend_schema(
        summary="Register account",
        description=(
            "Create an account with email/password. If `X-Visitor-Id` is present, "
            "existing guest conversations are linked to the new account."
        ),
        parameters=[VISITOR_ID_HEADER],
        request=RegisterSerializer,
        responses={201: AuthResponseSerializer},
    )
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        actor = resolve_actor(request)
        if actor.guest:
            merge_guest_into_user(actor.guest, user)
        return Response(
            {"user": UserSerializer(user).data, **tokens_for_user(user)},
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = (AllowAnyWithVisitor,)

    @extend_schema(
        summary="Login",
        description=(
            "Authenticate with email/password and receive JWT tokens. If "
            "`X-Visitor-Id` is present, guest activity is merged into the account."
        ),
        parameters=[VISITOR_ID_HEADER],
        request=LoginSerializer,
        responses={200: AuthResponseSerializer},
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        actor = resolve_actor(request)
        if actor.guest:
            merge_guest_into_user(actor.guest, user)
        return Response({"user": UserSerializer(user).data, **tokens_for_user(user)})


class MeView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(summary="Get current user", responses={200: UserSerializer})
    def get(self, request):
        return Response(UserSerializer(request.user).data)

    @extend_schema(
        summary="Update current user",
        request=UserSerializer,
        responses={200: UserSerializer},
    )
    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


@extend_schema(
    summary="Refresh access token",
    request=TokenRefreshRequestSerializer,
    responses={200: TokenRefreshResponseSerializer},
)
class DocumentedTokenRefreshView(TokenRefreshView):
    permission_classes = (AllowAny,)
