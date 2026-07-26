from django.contrib import admin

from .models import Alert, InventoryLog, Prediction, Product, SalesRecord


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "current_stock", "safety_stock", "created_at")
    search_fields = ("name",)


@admin.register(SalesRecord)
class SalesRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "quantity", "date")
    list_filter = ("date",)
    search_fields = ("product__name",)


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "alert_type", "severity", "created_at")
    list_filter = ("alert_type", "severity", "created_at")
    search_fields = ("product__name", "message")


@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "date", "predicted_demand", "created_at")
    list_filter = ("date",)
    search_fields = ("product__name",)


@admin.register(InventoryLog)
class InventoryLogAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "change", "timestamp")
    list_filter = ("timestamp",)
