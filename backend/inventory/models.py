from django.core.validators import MinValueValidator
from django.db import models


class Product(models.Model):
    name = models.CharField(max_length=255, db_index=True)
    current_stock = models.PositiveIntegerField(default=0)
    safety_stock = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self) -> str:
        return self.name


class SalesRecord(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="sales_records")
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    date = models.DateField(db_index=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self) -> str:
        return f"{self.product_id} x{self.quantity} @ {self.date}"


class Prediction(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="predictions")
    date = models.DateField(db_index=True)
    predicted_demand = models.FloatField(help_text="Forecast units sold for that calendar day.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["product_id", "date"]
        constraints = [
            models.UniqueConstraint(fields=["product", "date"], name="uniq_prediction_per_product_date"),
        ]

    def __str__(self) -> str:
        return f"{self.product_id} @ {self.date}: {self.predicted_demand}"


class Alert(models.Model):
    class AlertType(models.TextChoices):
        LOW_STOCK = "LOW_STOCK", "Low stock"
        STOCKOUT = "STOCKOUT", "Stockout risk"
        OVERSTOCK = "OVERSTOCK", "Overstock"

    class Severity(models.TextChoices):
        HIGH = "HIGH", "High"
        MEDIUM = "MEDIUM", "Medium"
        LOW = "LOW", "Low"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="alerts")
    alert_type = models.CharField(max_length=32, choices=AlertType.choices, db_index=True)
    severity = models.CharField(max_length=16, choices=Severity.choices, db_index=True)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "product_id", "alert_type"]

    def __str__(self) -> str:
        return f"{self.product_id} {self.alert_type} ({self.severity})"


class InventoryLog(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="inventory_logs")
    change = models.IntegerField(help_text="Negative for deductions, positive for additions.")
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp", "-id"]

    def __str__(self) -> str:
        return f"{self.product_id} {self.change:+d} @ {self.timestamp}"
