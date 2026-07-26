from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminOrStoreManager

from .services.alerts_service import regenerate_alerts
from .services.forecasting_service import predictions_grouped_payload, regenerate_all_predictions


class PredictionListView(APIView):
    """
    GET stored 7-day Prophet forecasts per product (next 7 calendar days from local today).
    """

    permission_classes = [IsAuthenticated, IsAdminOrStoreManager]

    def get(self, request, *args, **kwargs):
        return Response(predictions_grouped_payload())


class PredictionRunView(APIView):
    """
    POST — rebuild forecasts for all products from SalesRecord history.
    """

    permission_classes = [IsAuthenticated, IsAdminOrStoreManager]

    def post(self, request, *args, **kwargs):
        summary = regenerate_all_predictions()
        regen = regenerate_alerts()
        return Response({**summary, "alerts": regen}, status=status.HTTP_200_OK)
