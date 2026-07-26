from django.urls import path

from . import views

urlpatterns = [
    path("", views.SalesListCreateView.as_view(), name="sales-list-create"),
]
