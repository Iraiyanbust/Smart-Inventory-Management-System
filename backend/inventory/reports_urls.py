from django.urls import path

from .reports_views import SalesCsvExportView

urlpatterns = [
    path("sales/export/", SalesCsvExportView.as_view(), name="reports-sales-export"),
]
