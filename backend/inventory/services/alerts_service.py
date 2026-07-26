"""
Compute inventory alerts and reorder recommendations from stock, safety stock,
and stored 7-day Prophet predictions.
"""

from __future__ import annotations

import math
from typing import Any

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from ..models import Alert, Prediction, Product


def _sum_predicted_7d(product_id: int) -> float:
    total = (
        Prediction.objects.filter(product_id=product_id).aggregate(s=Sum("predicted_demand"))["s"] or 0.0
    )
    return float(total)


def _reorder_qty(total_predicted: float, safety: int, stock: int) -> int:
    raw = total_predicted + float(safety) - float(stock)
    return max(0, int(math.ceil(raw)))


def build_recommendations() -> list[dict[str, Any]]:
    """Reorder = predicted_7d + safety_stock - current_stock (non-negative, integer)."""
    out: list[dict[str, Any]] = []
    for p in Product.objects.order_by("name"):
        total = _sum_predicted_7d(p.id)
        qty = _reorder_qty(total, int(p.safety_stock), int(p.current_stock))
        if qty <= 0:
            continue
        name = p.name or "Product"
        out.append(
            {
                "product_id": p.id,
                "product_name": name,
                "reorder_quantity": qty,
                "message": f"Reorder {qty} units of {name}",
                "predicted_7d_total": round(total, 4),
                "current_stock": p.current_stock,
                "safety_stock": p.safety_stock,
            }
        )
    return out


def regenerate_alerts() -> dict[str, Any]:
    """
    Replace all Alert rows using current Product + Prediction rows.

    Rules:
    - LOW_STOCK: current_stock < safety_stock
    - STOCKOUT: sum(7d predicted_demand) > current_stock
    - OVERSTOCK: current_stock is much higher than forecast demand (slow mover risk)
    """
    created: list[Alert] = []
    now = timezone.now()

    with transaction.atomic():
        Alert.objects.all().delete()

        for p in Product.objects.order_by("id"):
            stock = int(p.current_stock)
            safety = int(p.safety_stock)
            total_pred = _sum_predicted_7d(p.id)

            # LOW_STOCK
            if safety > 0 and stock < safety:
                gap = safety - stock
                if stock == 0:
                    sev = Alert.Severity.HIGH
                elif gap >= max(1, safety // 2):
                    sev = Alert.Severity.MEDIUM
                else:
                    sev = Alert.Severity.LOW
                msg = (
                    f"{p.name}: on-hand {stock} is below safety stock {safety} "
                    f"(shortfall {gap} units)."
                )
                created.append(
                    Alert(
                        product=p,
                        alert_type=Alert.AlertType.LOW_STOCK,
                        severity=sev,
                        message=msg,
                    )
                )

            # STOCKOUT risk (forecasted demand exceeds on-hand)
            if total_pred > stock:
                over = total_pred - float(stock)
                if stock == 0 and total_pred > 0:
                    sev = Alert.Severity.HIGH
                elif stock > 0 and total_pred >= stock * 2:
                    sev = Alert.Severity.HIGH
                elif stock > 0 and total_pred > stock * 1.25:
                    sev = Alert.Severity.MEDIUM
                else:
                    sev = Alert.Severity.LOW
                msg = (
                    f"{p.name}: next 7-day forecast ({total_pred:.1f} units) exceeds "
                    f"current stock ({stock}). Risk of stockout."
                )
                created.append(
                    Alert(
                        product=p,
                        alert_type=Alert.AlertType.STOCKOUT,
                        severity=sev,
                        message=msg,
                    )
                )

            # OVERSTOCK (holding far more than near-term demand suggests)
            if total_pred > 0.5:
                ratio = stock / max(total_pred, 0.01)
                if ratio >= 10:
                    sev = Alert.Severity.HIGH
                    msg = (
                        f"{p.name}: stock {stock} is very high vs 7-day forecast "
                        f"({total_pred:.1f} units, ratio {ratio:.1f}x)."
                    )
                elif ratio >= 6:
                    sev = Alert.Severity.MEDIUM
                    msg = (
                        f"{p.name}: stock {stock} appears elevated vs forecast demand "
                        f"({total_pred:.1f} units, ratio {ratio:.1f}x)."
                    )
                elif ratio >= 4:
                    sev = Alert.Severity.LOW
                    msg = (
                        f"{p.name}: stock {stock} exceeds typical near-term demand "
                        f"({total_pred:.1f} units, ratio {ratio:.1f}x)."
                    )
                else:
                    sev = None
                    msg = ""
                if sev:
                    created.append(
                        Alert(
                            product=p,
                            alert_type=Alert.AlertType.OVERSTOCK,
                            severity=sev,
                            message=msg,
                        )
                    )

        if created:
            Alert.objects.bulk_create(created)

    return {
        "generated_at": now.isoformat(),
        "count": len(created),
    }


def alerts_payload() -> dict[str, Any]:
    severity_rank = {Alert.Severity.HIGH: 0, Alert.Severity.MEDIUM: 1, Alert.Severity.LOW: 2}
    qs = list(Alert.objects.select_related("product").all())
    qs.sort(key=lambda a: (severity_rank.get(a.severity, 9), a.product.name if a.product else "", a.alert_type))

    alerts = [
        {
            "id": a.id,
            "product_id": a.product_id,
            "product_name": a.product.name if a.product else None,
            "type": a.alert_type,
            "severity": a.severity,
            "message": a.message,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in qs
    ]
    return {
        "alerts": alerts,
        "recommendations": build_recommendations(),
        "summary": {
            "total_alerts": len(alerts),
            "high": sum(1 for x in alerts if x["severity"] == Alert.Severity.HIGH),
            "medium": sum(1 for x in alerts if x["severity"] == Alert.Severity.MEDIUM),
            "low": sum(1 for x in alerts if x["severity"] == Alert.Severity.LOW),
        },
    }
