from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .loader import loader
from .registry import DEFAULT_MODEL_KEY, list_models


class ModelListView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request):
        return Response(
            {
                "models": list_models(),
                "default": DEFAULT_MODEL_KEY,
                "current": loader.current_key,
            }
        )
