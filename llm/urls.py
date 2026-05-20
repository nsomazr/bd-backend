from django.urls import path

from .views import ModelListView

urlpatterns = [
    path("models/", ModelListView.as_view(), name="model-list"),
]
