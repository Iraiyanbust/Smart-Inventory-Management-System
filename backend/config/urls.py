from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/inventory/", include("inventory.urls")),
    path("api/sales/", include("inventory.sales_urls")),
    path("api/processing/", include("processing.urls")),
    path("api/prediction/", include("inventory.prediction_urls")),
    path("api/alerts/", include("inventory.alerts_urls")),
    path("api/reports/", include("inventory.reports_urls")),
]
