"""
Train Prophet per product on daily sales totals and produce 7-day demand forecasts.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone

from ..models import Prediction, Product, SalesRecord

logger = logging.getLogger(__name__)

for _name in ("prophet", "cmdstanpy", "stan"):
    logging.getLogger(_name).setLevel(logging.WARNING)


def _tomorrow() -> date:
    return timezone.localdate() + timedelta(days=1)


def _forecast_dates() -> list[date]:
    start = _tomorrow()
    return [start + timedelta(days=i) for i in range(7)]


def _daily_sales_rows(product_id: int) -> list[dict[str, Any]]:
    return list(
        SalesRecord.objects.filter(product_id=product_id)
        .values("date")
        .annotate(y=Sum("quantity"))
        .order_by("date")
    )


def _prophet_predict(rows: list[dict[str, Any]], future_dates: list[date]) -> list[float]:
    """Return non-negative demand forecasts aligned with future_dates."""
    if not rows:
        return [0.0] * len(future_dates)

    import pandas as pd

    df = pd.DataFrame(rows)
    df = df.rename(columns={"date": "ds"})
    df["ds"] = pd.to_datetime(df["ds"])
    df["y"] = df["y"].astype(float)

    future = pd.DataFrame({"ds": pd.to_datetime(pd.Series(future_dates))})

    if len(df) < 2:
        y0 = float(df["y"].iloc[-1])
        return [max(0.0, y0)] * len(future_dates)

    try:
        from prophet import Prophet  # type: ignore import-not-found

        weekly = len(df) >= 14
        m = Prophet(
            yearly_seasonality=False,
            weekly_seasonality=weekly,
            daily_seasonality=False,
            interval_width=0.85,
        )
        m.fit(df)
        fcst = m.predict(future)
        yhat = fcst["yhat"].clip(lower=0).astype(float).tolist()
        return [float(max(0.0, v)) for v in yhat]
    except ImportError as exc:
        logger.error("Prophet or pandas missing: %s", exc)
        mean_y = max(0.0, float(df["y"].mean())) if len(df) else 0.0
        return [mean_y] * len(future_dates)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Prophet forecast failed; using historical mean. error=%s", exc)
        mean_y = max(0.0, float(df["y"].mean())) if len(df) else 0.0
        return [mean_y] * len(future_dates)


def regenerate_predictions_for_product(product: Product) -> dict[str, Any]:
    dates = _forecast_dates()
    rows = _daily_sales_rows(product.id)
    values = _prophet_predict(rows, dates) if rows else [0.0] * len(dates)

    with transaction.atomic():
        Prediction.objects.filter(product=product).delete()
        Prediction.objects.bulk_create(
            [
                Prediction(product=product, date=d, predicted_demand=v)
                for d, v in zip(dates, values, strict=True)
            ]
        )

    return {
        "product_id": product.id,
        "product_name": product.name,
        "points": len(rows),
        "forecast_days": len(dates),
    }


def regenerate_all_predictions() -> dict[str, Any]:
    """Rebuild 7-day forecasts for every product."""
    products = list(Product.objects.order_by("id"))
    details: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for product in products:
        try:
            details.append(regenerate_predictions_for_product(product))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Forecast failed for product %s", product.id)
            errors.append({"product_id": product.id, "product_name": product.name, "error": str(exc)})

    return {
        "ok": len(errors) == 0,
        "products": len(products),
        "updated": len(details),
        "details": details,
        "errors": errors,
    }


def predictions_grouped_payload() -> dict[str, Any]:
    """Shape stored predictions for the API consumer."""
    qs = Prediction.objects.select_related("product").order_by("product_id", "date")
    by_product: dict[int, list[Prediction]] = defaultdict(list)
    for row in qs:
        by_product[row.product_id].append(row)

    products_out: list[dict[str, Any]] = []
    for product_id, rows in sorted(by_product.items(), key=lambda x: x[0]):
        product = rows[0].product
        days = [
            {
                "date": r.date.isoformat(),
                "predicted_demand": round(float(r.predicted_demand), 4),
            }
            for r in rows
        ]
        trend = _trend_label(days)
        total = sum(float(d["predicted_demand"]) for d in days)
        products_out.append(
            {
                "product_id": product.id,
                "product_name": product.name,
                "trend": trend,
                "total_7d": round(total, 4),
                "days": days,
            }
        )

    latest = Prediction.objects.aggregate(m=Max("created_at"))["m"]

    return {
        "as_of": latest.isoformat() if latest else None,
        "forecast_start": _forecast_dates()[0].isoformat(),
        "forecast_end": _forecast_dates()[-1].isoformat(),
        "products": products_out,
    }


def _trend_label(days: list[dict[str, Any]]) -> str:
    if not days:
        return "flat"
    ys = [float(d.get("predicted_demand") or 0) for d in days]
    if len(ys) < 2:
        return "flat"
    mid = max(1, len(ys) // 2)
    first = sum(ys[:mid]) / mid
    second = sum(ys[mid:]) / max(1, len(ys) - mid)
    denom = max(first, 1e-6)
    delta = (second - first) / denom
    if delta > 0.05:
        return "up"
    if delta < -0.05:
        return "down"
    return "flat"
