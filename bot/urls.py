from django.urls import path

from . import views

urlpatterns = [
    path("evolution/", views.evolution_webhook, name="evolution-webhook"),
]
