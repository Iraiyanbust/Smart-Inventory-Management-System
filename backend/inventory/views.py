from rest_framework import generics, status
from rest_framework.response import Response

from .models import Product, SalesRecord
from .serializers import (
    ProductCreateSerializer,
    ProductSerializer,
    SalesRecordCreateSerializer,
    SalesRecordSerializer,
)
from .services.alerts_service import regenerate_alerts
from .services.forecasting_service import regenerate_all_predictions


class ProductCreateView(generics.CreateAPIView):
    serializer_class = ProductCreateSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = serializer.save()
        return Response(ProductSerializer(product).data, status=status.HTTP_201_CREATED)


class ProductListView(generics.ListAPIView):
    serializer_class = ProductSerializer
    queryset = Product.objects.all()


class SalesListCreateView(generics.ListCreateAPIView):
    serializer_class = SalesRecordSerializer

    def get_queryset(self):
        qs = SalesRecord.objects.select_related("product").all()
        product_id = self.request.query_params.get("product")
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        if product_id:
            qs = qs.filter(product_id=product_id)
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        return qs

    def get_serializer_class(self):
        if self.request.method == "POST":
            return SalesRecordCreateSerializer
        return SalesRecordSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        regenerate_all_predictions()
        regenerate_alerts()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
