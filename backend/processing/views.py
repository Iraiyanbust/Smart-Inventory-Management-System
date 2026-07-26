import io

from django.conf import settings
from django.db import transaction
from PIL import Image
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from inventory.models import Product
from inventory.serializers import ProductSerializer, SalesRecordCreateSerializer, SalesRecordSerializer
from inventory.services.alerts_service import alerts_payload, regenerate_alerts
from inventory.services.forecasting_service import predictions_grouped_payload, regenerate_all_predictions

from .serializers import VerifySaveSerializer
from .services.nlp_service import structure_sales_lines
from .services.ocr_service import extract_text_from_image


class ProcessingUploadView(APIView):
    """
    POST multipart form with field `image` or `file` (image/*).
    Returns OCR lines + structured rows fuzzy-matched to Product catalog.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs):
        upload = request.FILES.get("image") or request.FILES.get("file")
        if not upload:
            return Response(
                {"detail": "No image file provided. Use form field 'image' or 'file'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        max_bytes = int(getattr(settings, "SRS_MAX_IMAGE_BYTES", 12 * 1024 * 1024))
        size = getattr(upload, "size", None)
        if size is not None and size > max_bytes:
            return Response(
                {"detail": f"File too large. Maximum size is {max_bytes} bytes."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            raw = upload.read()
            image = Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            return Response(
                {"detail": f"Could not read image: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ocr = extract_text_from_image(image)
        products = list(Product.objects.order_by("name").values_list("id", "name"))

        if ocr.get("ok"):
            nlp = structure_sales_lines(
                ocr.get("combined_text") or "",
                products,
                ocr_lines=ocr.get("lines") or [],
            )
        else:
            nlp = {"structured": [], "unmatched": [], "low_confidence": []}

        warnings: list[str] = []
        if not ocr.get("ok") and ocr.get("error"):
            warnings.append(str(ocr["error"]))
        if nlp.get("low_confidence"):
            warnings.append(
                "Some lines have weak catalog matches (score < 85) or no match. "
                "Review them on the Verification page before saving."
            )

        payload = {
            "ok": bool(ocr.get("ok")),
            "filename": getattr(upload, "name", None),
            "ocr": ocr,
            "nlp": nlp,
            "warnings": warnings,
        }
        return Response(payload, status=status.HTTP_200_OK)


class VerifySaveView(APIView):
    """
    POST JSON { "rows": [ { "product_id", "quantity", "date?" }, ... ] }
    Creates sales (deducts stock), then retrains forecasts and regenerates alerts.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request, *args, **kwargs):
        body = VerifySaveSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        rows = body.validated_data["rows"]

        created: list[dict] = []
        with transaction.atomic():
            for idx, row in enumerate(rows):
                payload = {"product": row["product_id"], "quantity": row["quantity"]}
                if row.get("date") is not None:
                    payload["date"] = row["date"]
                ser = SalesRecordCreateSerializer(data=payload, context={"request": request})
                try:
                    ser.is_valid(raise_exception=True)
                    inst = ser.save()
                    created.append(SalesRecordSerializer(inst).data)
                except serializers.ValidationError as exc:
                    raise serializers.ValidationError(
                        {"detail": f"Row {idx + 1} could not be saved.", "rows": {str(idx): exc.detail}}
                    ) from exc

        forecast_job = regenerate_all_predictions()
        alerts_regen = regenerate_alerts()
        products = Product.objects.order_by("id")

        return Response(
            {
                "ok": True,
                "message": f"Saved {len(created)} sales line(s). Forecasts and alerts were refreshed.",
                "sales_created": len(created),
                "sales": created,
                "products": ProductSerializer(products, many=True).data,
                "forecast_job": forecast_job,
                "alerts_regen": alerts_regen,
                "predictions": predictions_grouped_payload(),
                "alerts": alerts_payload(),
            },
            status=status.HTTP_200_OK,
        )
