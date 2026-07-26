"""
OCR extraction using EasyOCR.

- Preprocesses images (resize, contrast) for clearer text.
- Sorts detections top-to-bottom, left-to-right (ledger order).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_reader = None
_reader_langs: tuple[str, ...] | None = None


def _langs_from_settings() -> list[str]:
    try:
        from django.conf import settings as dj_settings

        if not dj_settings.configured:
            return ["en", "hi"]
        raw = getattr(dj_settings, "SRS_OCR_LANGS", "en,hi")
    except Exception:  # noqa: BLE001
        return ["en", "hi"]
    if isinstance(raw, str):
        langs = [p.strip() for p in raw.split(",") if p.strip()]
        return langs or ["en"]
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()] or ["en"]
    return ["en"]


def _int_setting(name: str, default: int) -> int:
    try:
        from django.conf import settings as dj_settings

        if not dj_settings.configured:
            return default
        v = getattr(dj_settings, name, default)
        return int(v)
    except Exception:  # noqa: BLE001
        return default


def _float_setting(name: str, default: float) -> float:
    try:
        from django.conf import settings as dj_settings

        if not dj_settings.configured:
            return default
        v = getattr(dj_settings, name, default)
        return float(v)
    except Exception:  # noqa: BLE001
        return default


def get_reader():
    """Return a cached easyocr.Reader."""
    global _reader, _reader_langs
    langs = tuple(_langs_from_settings())
    try:
        import easyocr  # type: ignore import-not-found
    except ImportError as exc:
        raise RuntimeError(
            "EasyOCR is not installed. Install backend requirements (includes easyocr and torch)."
        ) from exc

    if _reader is not None and _reader_langs == langs:
        return _reader

    logger.info("Initializing EasyOCR reader for languages: %s", ",".join(langs))
    use_gpu = False
    try:
        from django.conf import settings as dj_settings

        if dj_settings.configured:
            use_gpu = bool(getattr(dj_settings, "SRS_OCR_GPU", False))
    except Exception:  # noqa: BLE001
        use_gpu = False
    _reader = easyocr.Reader(list(langs), gpu=use_gpu, verbose=False)
    _reader_langs = langs
    return _reader


def _bbox_sort_key(item: tuple) -> tuple[float, float]:
    """Top-to-bottom, then left-to-right using box center."""
    bbox = item[0]
    try:
        xs = [float(p[0]) for p in bbox]
        ys = [float(p[1]) for p in bbox]
        return (sum(ys) / max(len(ys), 1), sum(xs) / max(len(xs), 1))
    except Exception:  # noqa: BLE001
        return (0.0, 0.0)


def preprocess_for_ocr(image_rgb):
    """
    PIL RGB in → PIL RGB out.
    Downscale very large images, boost contrast slightly for pencil/faint ink.
    """
    from PIL import Image, ImageEnhance, ImageOps

    img = image_rgb
    max_side = _int_setting("SRS_OCR_MAX_IMAGE_SIDE", 2000)
    w, h = img.size
    longest = max(w, h)
    if longest > max_side:
        scale = max_side / float(longest)
        nw = max(1, int(w * scale))
        nh = max(1, int(h * scale))
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)

    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray, cutoff=_float_setting("SRS_OCR_AUTOCUT", 1.5))
    rgb = Image.merge("RGB", (gray, gray, gray))
    sharp = ImageEnhance.Sharpness(rgb).enhance(_float_setting("SRS_OCR_SHARPEN", 1.15))
    return sharp


def extract_text_from_image(image_rgb) -> dict[str, Any]:
    """
    Run OCR on a PIL Image (RGB).

    Returns:
        {
          "ok": bool,
          "lines": [{"text": str, "confidence": float | null}],
          "combined_text": str,
          "error": str | null,
        }
    """
    try:
        reader = get_reader()
    except RuntimeError as exc:
        return {
            "ok": False,
            "lines": [],
            "combined_text": "",
            "error": str(exc),
        }

    try:
        import numpy as np
    except ImportError as exc:
        return {
            "ok": False,
            "lines": [],
            "combined_text": "",
            "error": f"NumPy is required for OCR: {exc}",
        }

    try:
        processed = preprocess_for_ocr(image_rgb)
        arr = np.array(processed)
        mag_ratio = _float_setting("SRS_OCR_MAG_RATIO", 1.35)
        canvas_size = _int_setting("SRS_OCR_CANVAS_SIZE", 2560)
        text_threshold = _float_setting("SRS_OCR_TEXT_THRESHOLD", 0.55)
        low_text = _float_setting("SRS_OCR_LOW_TEXT", 0.35)
        link_threshold = _float_setting("SRS_OCR_LINK_THRESHOLD", 0.35)
        adjust_contrast = _float_setting("SRS_OCR_ADJUST_CONTRAST", 0.65)

        results = reader.readtext(
            arr,
            detail=1,
            paragraph=False,
            mag_ratio=mag_ratio,
            canvas_size=canvas_size,
            text_threshold=text_threshold,
            low_text=low_text,
            link_threshold=link_threshold,
            adjust_contrast=adjust_contrast,
        )
        results = sorted(results, key=_bbox_sort_key)
    except Exception as exc:  # noqa: BLE001 - surface OCR failures cleanly
        logger.exception("EasyOCR readtext failed")
        return {
            "ok": False,
            "lines": [],
            "combined_text": "",
            "error": f"OCR failed: {exc}",
        }

    lines: list[dict[str, Any]] = []
    parts: list[str] = []
    for item in results:
        if len(item) == 3:
            _bbox, text, conf = item
        else:
            text, conf = item[0], item[1] if len(item) > 1 else None
        text = (text or "").strip()
        if not text:
            continue
        try:
            conf_f = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            conf_f = None
        lines.append({"text": text, "confidence": conf_f})
        parts.append(text)

    combined = "\n".join(parts).strip()
    return {
        "ok": True,
        "lines": lines,
        "combined_text": combined,
        "error": None,
    }
