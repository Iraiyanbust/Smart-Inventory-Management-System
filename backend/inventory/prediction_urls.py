from django.urls import path

from .prediction_views import PredictionListView, PredictionRunView

urlpatterns = [
    path("", PredictionListView.as_view(), name="prediction-list"),
    path("run/", PredictionRunView.as_view(), name="prediction-run"),
]
