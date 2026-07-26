"""
Parse OCR text into product/quantity rows and fuzzy-match against catalog names (RapidFuzz).

Parses per OCR line first, merges with a full-text pass, supports commas/semicolons/colons/dashes.
"""

from __future__ import annotations

import re
from typing import Any

from rapidfuzz import fuzz, process

# --- Cash-memo / table receipts (Particulars + "1 ltr" / "1 kg" + rate + amount) ---
_UNIT = r"(?:ltrs?|lt\.?|kgs?|kg|g|gm|grams?|ml|m[lL]|pcs?|pc|nos?|no\.?|pkt|packets?|units?|ltr)"
# Single OCR line: optional S.No, product name, qty digit(s), optional unit, optional rate/amount decimals
RECEIPT_TABLE_ROW = re.compile(
    rf"^\s*(?:\d+\.\s*)?(?P<name>[A-Za-z\u0900-\u097F][A-Za-z0-9\s.'\-]{{0,42}}?)\s+(?P<qty>\d{{1,5}})\s*(?P<unit>{_UNIT})?\s*(?P<tail>(?:\d+\.?\d*\s*){{0,4}})\s*$",
    re.UNICODE | re.IGNORECASE,
)
# Qty-only line after a product-only line (split cells): "1 ltr" or "1 ltr 60.00"
QTY_UNIT_LINE = re.compile(
    rf"^(?P<qty>\d{{1,5}})\s*(?P<unit>{_UNIT})?(\s+[\d.]+\s*){{0,3}}\s*$",
    re.UNICODE | re.IGNORECASE,
)
# Product-only line (no digits) — often the "Particulars" cell alone
PRODUCT_ANCHOR = re.compile(r"^[A-Za-z\u0900-\u097F][A-Za-z\s.'\-]{1,40}$", re.UNICODE)

_NOISE_SUBSTRINGS = frozenset(
    {
        "cash memo",
        "general store",
        "grocery",
        "particular",
        "qty",
        "rate",
        "amount",
        "total",
        "thank",
        "visit again",
        "mobile",
        "main road",
        "customer",
        "date",
        "name",
        "s.no",
        "serial",
        "mob",
        "town",
        "kinds of",
        "all kinds",
    }
)


def _is_noise_line(text: str) -> bool:
    low = (text or "").lower().strip()
    if len(low) < 2:
        return True
    if any(s in low for s in _NOISE_SUBSTRINGS):
        return True
    if re.fullmatch(r"[\d.\s/:-]+", low) and len(low) > 8:
        return True  # long numeric-only (phone, totals row fragments)
    return False


def _receipt_row_match(line: str) -> dict[str, Any] | None:
    line = (line or "").strip()
    if not line or _is_noise_line(line):
        return None
    m = RECEIPT_TABLE_ROW.match(line)
    if not m:
        return None
    name = _clean_name(m.group("name"))
    if not name or _is_noise_line(name):
        return None
    qty = int(m.group("qty"))
    if qty <= 0:
        return None
    return {
        "raw_name": name,
        "quantity": qty,
        "raw_segment": line,
        "pattern": "RECEIPT_TABLE_ROW",
    }


def extract_receipt_and_split_candidates(line_texts: list[str]) -> list[dict[str, Any]]:
    """
    Handle Indian cash-memo style rows:
    - Full line: "Milk 1 ltr 60.00 60.00"
    - Split OCR: "Milk" then "1 ltr 60.00" (merge consecutive lines)
    """
    out: list[dict[str, Any]] = []
    pending_product: str | None = None

    for raw in line_texts:
        line = re.sub(r"\s+", " ", (raw or "").strip())
        if not line:
            continue

        full = _receipt_row_match(line)
        if full:
            pending_product = None
            out.append(full)
            continue

        if _is_noise_line(line):
            pending_product = None
            continue

        qm = QTY_UNIT_LINE.match(line)
        if qm and pending_product:
            qty = int(qm.group("qty"))
            if qty > 0:
                out.append(
                    {
                        "raw_name": pending_product,
                        "quantity": qty,
                        "raw_segment": f"{pending_product} {line}".strip(),
                        "pattern": "SPLIT_PRODUCT_QTY_UNIT",
                    }
                )
            pending_product = None
            continue

        if PRODUCT_ANCHOR.match(line) and not re.search(r"\d", line):
            low = line.lower()
            if not _is_noise_line(line) and 2 <= len(line) <= 44:
                pending_product = _clean_name(line)
            else:
                pending_product = None
            continue

        pending_product = None

    return out


def _ocr_line_texts_in_order(ocr_lines: list[dict[str, Any]] | None) -> list[str]:
    texts: list[str] = []
    for ln in ocr_lines or []:
        if isinstance(ln, dict) and ln.get("text"):
            texts.append(str(ln["text"]))
    return texts


# Names that are almost always OCR fragments from the Qty./unit column, not products.
_UNIT_LIKE_NAMES = frozenset(
    {
        "ltr",
        "lt",
        "kg",
        "kgs",
        "g",
        "gm",
        "ml",
        "pcs",
        "pc",
        "nos",
        "no",
        "pkt",
        "packet",
        "packets",
        "unit",
        "units",
        "grams",
        "gram",
    }
)


def _is_garbage_product_name(raw: str) -> bool:
    n = (raw or "").strip().lower()
    return len(n) <= 1 or n in _UNIT_LIKE_NAMES


def _skip_generic_patterns_for_ocr_line(text: str) -> bool:
    """
    Avoid PAIR_NAME_SPACE_QTY on table cells like '1 ltr 60.00 60.00' → false 'ltr' + 60.
    Receipt logic handles these lines.
    """
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return True
    if QTY_UNIT_LINE.match(t):
        return True
    if re.fullmatch(r"[\d.\s]+", t):
        return True
    if re.match(rf"^\d{{1,5}}\s+{_UNIT}\b", t, re.IGNORECASE):
        return True
    return False


# "Product: 12", "Product, 12", "Product - 12"
PAIR_NAME_SEP_QTY = re.compile(
    r"(?P<name>[^\d,;:\n\r\t|]{1,120}?)\s*[:,\-–]\s*(?P<qty>\d{1,9})\b",
    re.UNICODE,
)
# "12 x Product"
PAIR_QTY_X_NAME = re.compile(
    r"(?<![\d])(?P<qty>\d{1,9})\s*[xX×]\s*(?P<name>[^\d,;:\n\r\t|]{1,120})",
    re.UNICODE,
)
# "Product 12" (space before number)
PAIR_NAME_SPACE_QTY = re.compile(
    r"(?P<name>[^\d,;:\n\r\t|]{1,120}?)\s+(?P<qty>\d{1,9})\b",
    re.UNICODE,
)
# "12 Product …" at start / before another qty
PAIR_QTY_NAME = re.compile(
    r"(?<![\d])(?P<qty>\d{1,9})\s+(?P<name>[^\d,;:\n\r\t|]{1,120}?)(?=(?:\s+\d{1,9}\s+)|\s*$)",
    re.UNICODE,
)


def _clean_name(raw: str) -> str:
    s = (raw or "").strip()
    s = re.sub(r"\s+", " ", s)
    s = s.strip(" ,;:-\t_•·|")
    return s


def _try_patterns_on_segment(segment: str) -> list[dict[str, Any]]:
    """Extract matches from one segment (no cross-segment overlap)."""
    used: list[tuple[int, int]] = []
    out: list[dict[str, Any]] = []

    def overlaps(start: int, end: int) -> bool:
        return any(start < b and end > a for a, b in used)

    def add(name: str, qty: int, start: int, end: int, pattern: str) -> None:
        name = _clean_name(name)
        if len(name) < 1 or qty <= 0 or overlaps(start, end):
            return
        used.append((start, end))
        out.append(
            {
                "raw_name": name,
                "quantity": qty,
                "raw_segment": segment[start:end].strip(),
                "pattern": pattern,
            }
        )

    for m in PAIR_NAME_SEP_QTY.finditer(segment):
        add(m.group("name"), int(m.group("qty")), m.start(), m.end(), "NAME_SEP_QTY")
    for m in PAIR_QTY_X_NAME.finditer(segment):
        add(m.group("name"), int(m.group("qty")), m.start(), m.end(), "QTY_X_NAME")
    for m in PAIR_NAME_SPACE_QTY.finditer(segment):
        add(m.group("name"), int(m.group("qty")), m.start(), m.end(), "NAME_SPACE_QTY")
    for m in PAIR_QTY_NAME.finditer(segment):
        add(m.group("name"), int(m.group("qty")), m.start(), m.end(), "QTY_NAME")
    return out


def extract_candidate_pairs(text: str) -> list[dict[str, Any]]:
    if not text or not text.strip():
        return []
    cleaned = re.sub(r"\s+", " ", text.strip())
    parts: list[str] = []
    for line in re.split(r"[\n\r|]+", cleaned):
        line = line.strip()
        if not line:
            continue
        for piece in re.split(r"\s*,\s*|\s*;\s*", line):
            piece = piece.strip(" |")
            if piece:
                parts.append(piece)
    if not parts:
        parts = [cleaned]

    rows: list[dict[str, Any]] = []
    for part in parts:
        if _skip_generic_patterns_for_ocr_line(part):
            continue
        rows.extend(_try_patterns_on_segment(part))

    if not rows:
        if not _skip_generic_patterns_for_ocr_line(cleaned):
            rows = _try_patterns_on_segment(cleaned)

    seen: set[tuple[Any, ...]] = set()
    deduped: list[dict[str, Any]] = []
    for r in rows:
        key = (r.get("raw_name"), r.get("quantity"), r.get("raw_segment"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


def extract_candidate_pairs_from_ocr_lines(
    lines: list[dict[str, Any]] | None,
    combined_text: str,
) -> list[dict[str, Any]]:
    """Parse each OCR box line, then merge with a full-text parse (handles one-line ledgers)."""
    merged: list[dict[str, Any]] = []
    # Dedupe by (name, qty): receipt parser + generic patterns often emit the same row with different raw_segment.
    seen: set[tuple[Any, ...]] = set()

    def add_rows(items: list[dict[str, Any]]) -> None:
        for row in items:
            raw = (row.get("raw_name") or "").strip()
            if _is_garbage_product_name(raw):
                continue
            qty = row.get("quantity")
            key = (raw.lower(), qty)
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)

    # Cash memos (handwritten particulars + qty/unit, often split across OCR boxes).
    add_rows(extract_receipt_and_split_candidates(_ocr_line_texts_in_order(lines)))
    clines = [
        re.sub(r"\s+", " ", ln).strip()
        for ln in re.split(r"[\n\r]+", combined_text or "")
        if ln.strip()
    ]
    add_rows(extract_receipt_and_split_candidates(clines))

    for line in lines or []:
        if not isinstance(line, dict):
            continue
        t = line.get("text")
        if not t or not str(t).strip():
            continue
        if _skip_generic_patterns_for_ocr_line(str(t)):
            continue
        add_rows(extract_candidate_pairs(str(t)))

    add_rows(extract_candidate_pairs(combined_text or ""))
    return merged


def _confidence_level(score: float | None) -> str:
    if score is None:
        return "none"
    if score >= 90:
        return "high"
    if score >= 75:
        return "medium"
    return "low"


def structure_sales_lines(
    combined_text: str,
    products: list[tuple[int, str]],
    *,
    ocr_lines: list[dict[str, Any]] | None = None,
    match_cutoff: float = 65.0,
) -> dict[str, Any]:
    choices = [p[1] for p in products]
    choice_by_name = {p[1]: p[0] for p in products}

    candidates = extract_candidate_pairs_from_ocr_lines(ocr_lines, combined_text or "")

    structured: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    low_confidence: list[dict[str, Any]] = []

    for cand in candidates:
        raw_name = cand["raw_name"]
        qty = cand["quantity"]
        if not choices:
            row = {
                "raw_segment": cand.get("raw_segment"),
                "raw_name": raw_name,
                "quantity": qty,
                "product": None,
                "product_id": None,
                "match_score": None,
                "confidence_level": "none",
                "note": "No products in catalog to match against.",
            }
            unmatched.append(row)
            structured.append(row)
            continue

        match = process.extractOne(
            raw_name,
            choices,
            scorer=fuzz.WRatio,
            score_cutoff=match_cutoff,
        )
        if not match:
            match = process.extractOne(
                raw_name,
                choices,
                scorer=fuzz.token_set_ratio,
                score_cutoff=max(55.0, match_cutoff - 10),
            )
        if not match:
            row = {
                "raw_segment": cand.get("raw_segment"),
                "raw_name": raw_name,
                "quantity": qty,
                "product": None,
                "product_id": None,
                "match_score": None,
                "confidence_level": "low",
                "note": "No fuzzy match above cutoff.",
            }
            unmatched.append(row)
            low_confidence.append(row)
            structured.append(row)
            continue

        matched_name, score, _idx = match
        product_id = choice_by_name.get(matched_name)
        level = _confidence_level(float(score))
        row = {
            "raw_segment": cand.get("raw_segment"),
            "raw_name": raw_name,
            "quantity": qty,
            "product": matched_name,
            "product_id": product_id,
            "match_score": round(float(score), 2),
            "confidence_level": level,
            "pattern": cand.get("pattern"),
        }
        structured.append(row)
        if row.get("match_score") is None or float(row["match_score"]) < 85:
            low_confidence.append(row)

    return {
        "structured": structured,
        "unmatched": unmatched,
        "low_confidence": low_confidence,
    }
