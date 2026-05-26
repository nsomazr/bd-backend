from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from bd_backend.api_schema import ModelListResponseSerializer

from .loader import loader
from .registry import DEFAULT_MODEL_KEY, list_models


class ModelListView(APIView):
    permission_classes = (AllowAny,)

    @extend_schema(
        summary="List available models",
        description="Return the selectable chat/arena models and the server default.",
        responses={200: ModelListResponseSerializer},
    )
    def get(self, request):
        return Response(
            {
                "models": list_models(),
                "default": DEFAULT_MODEL_KEY,
                "current": loader.current_key,
            }
        )
