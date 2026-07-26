import csv

from django.http import HttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from .models import SalesRecord


class SalesCsvExportView(APIView):
    """GET CSV of all sales rows (optional reporting from Step 3 spec)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="sales_export.csv"'
        writer = csv.writer(response)
        writer.writerow(["id", "product_id", "product_name", "quantity", "date"])
        for r in SalesRecord.objects.select_related("product").order_by("-date", "-id"):
            writer.writerow([r.id, r.product_id, r.product.name, r.quantity, r.date.isoformat()])
        return response
