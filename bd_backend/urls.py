"""Root URL conf for bd_backend."""
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


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
    return JsonResponse(payload)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/auth/", include("accounts.urls")),
    path("api/", include("llm.urls")),
    path("api/", include("chat.urls")),
    path("api/", include("arena.urls")),
    path("api/", include("rlhf.urls")),
]
