from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from .models import InventoryLog, Product, SalesRecord


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ("id", "name", "current_stock", "safety_stock", "created_at")
        read_only_fields = ("id", "current_stock", "created_at")


class ProductCreateSerializer(serializers.ModelSerializer):
    current_stock = serializers.IntegerField(min_value=0, required=False, default=0)
    safety_stock = serializers.IntegerField(min_value=0, required=False, default=0)

    class Meta:
        model = Product
        fields = ("name", "current_stock", "safety_stock")

    def validate_name(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Product name is required.")
        return value

    def create(self, validated_data):
        return Product.objects.create(**validated_data)


class SalesRecordSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = SalesRecord
        fields = ("id", "product", "product_name", "quantity", "date")
        read_only_fields = ("id", "product_name")


class SalesRecordCreateSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    quantity = serializers.IntegerField(min_value=1)
    date = serializers.DateField(required=False)

    def validate(self, attrs):
        attrs.setdefault("date", timezone.localdate())
        return attrs

    def create(self, validated_data):
        product = validated_data["product"]
        quantity = validated_data["quantity"]
        sale_date = validated_data["date"]

        with transaction.atomic():
            locked = Product.objects.select_for_update().get(pk=product.pk)
            if locked.current_stock < quantity:
                raise serializers.ValidationError(
                    {
                        "quantity": (
                            f"Insufficient stock for “{locked.name}”. "
                            f"Available: {locked.current_stock}, requested: {quantity}."
                        )
                    }
                )
            locked.current_stock -= quantity
            locked.save(update_fields=["current_stock"])

            sale = SalesRecord.objects.create(
                product=locked,
                quantity=quantity,
                date=sale_date,
            )
            InventoryLog.objects.create(
                product=locked,
                change=-quantity,
            )
            return sale

    def to_representation(self, instance):
        return SalesRecordSerializer(instance, context=self.context).data
