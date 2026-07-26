from django.urls import path

from .alerts_views import AlertsListView, AlertsRegenerateView

urlpatterns = [
    path("", AlertsListView.as_view(), name="alerts-list"),
    path("run/", AlertsRegenerateView.as_view(), name="alerts-run"),
]
