from django.http import JsonResponse
from django.urls import include, path


def health(_request):
    return JsonResponse({"status": "ok", "service": "leticia-agent"})


urlpatterns = [
    path("health/", health),
    path("webhook/", include("bot.urls")),
]
