"""Root URL conf for bd_backend."""
from django.contrib import admin
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.urls import include, path
from drf_spectacular.utils import extend_schema
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .api_schema import HealthResponseSerializer


@method_decorator(xframe_options_sameorigin, name="dispatch")
class FramedSwaggerView(SpectacularSwaggerView):
    pass


@method_decorator(xframe_options_sameorigin, name="dispatch")
class FramedRedocView(SpectacularRedocView):
    pass


@extend_schema(
    operation_id="health_check",
    summary="Health check",
    description="Backend health, GPU availability, and currently loaded model.",
    responses=HealthResponseSerializer,
)
@api_view(["GET"])
@permission_classes([AllowAny])
def health(_request):
    from llm.loader import get_gpu_status, loader

    gpu = get_gpu_status()
    payload = {
        "status": "ok",
        "service": "maisha-chat-backend",
        "gpu": gpu,
        "loaded_model": loader.current_key,
    }
    if gpu.get("inference_device") == "cpu":
        payload["warning"] = (
            "Maisha is running on CPU. On shared GPU hosts this is normal when "
            "another user's job holds the GPU or CUDA is unavailable to this "
            "process. Set LLM_DEVICE=cpu in env.local to silence auto-detection, "
            "or coordinate GPU time with the machine owner."
        )
    return Response(payload)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path(
        "api/docs/swagger/",
        FramedSwaggerView.as_view(url_name="api-schema"),
        name="api-docs-swagger",
    ),
    path(
        "api/docs/redoc/",
        FramedRedocView.as_view(url_name="api-schema"),
        name="api-docs-redoc",
    ),
    path("api/auth/", include("accounts.urls")),
    path("api/", include("llm.urls")),
    path("api/", include("chat.urls")),
    path("api/", include("arena.urls")),
    path("api/", include("rlhf.urls")),
]
