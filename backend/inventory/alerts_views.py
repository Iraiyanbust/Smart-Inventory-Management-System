from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAuthenticatedRole

from .services.alerts_service import alerts_payload, regenerate_alerts


class AlertsListView(APIView):
    """
    GET — stored alerts + reorder recommendations (no regeneration).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        return Response(alerts_payload())


class AlertsRegenerateView(APIView):
    """
    POST — rebuild alerts from current stock, safety stock, and stored predictions.
    """

    permission_classes = [IsAuthenticatedRole]

    def post(self, request, *args, **kwargs):
        summary = regenerate_alerts()
        return Response({**summary, **alerts_payload()}, status=status.HTTP_200_OK)
