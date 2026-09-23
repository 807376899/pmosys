from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Iterable

from backend.app.core.errors import ValidationError


def parse_money(value: object, label: str, *, required: bool = True) -> str | None:
    """Validate non-negative decimal input and return normalized text."""
    if value is None or value == "":
        if required:
            raise ValidationError(f"{label}不能为空")
        return None
    raw = str(value).strip()
    if not raw or "e" in raw.lower():
        raise ValidationError(f"{label}必须为普通十进制数字")
    try:
        amount = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"{label}必须为数字") from exc
    if not amount.is_finite() or amount < 0:
        raise ValidationError(f"{label}不能小于 0")
    return format(amount.normalize(), "f") if amount else "0"


def decimal_of(value: object | None) -> Decimal:
    return Decimal("0") if value is None or value == "" else Decimal(str(value))


def total(values: Iterable[object | None]) -> str:
    result = sum((decimal_of(value) for value in values), Decimal("0"))
    return format(result.normalize(), "f") if result else "0"


def difference(left: object | None, right: object | None) -> str:
    result = decimal_of(left) - decimal_of(right)
    return format(result.normalize(), "f") if result else "0"


def preferred(row: dict, field: str) -> str | None:
    value = row.get(f"{field}_decimal")
    if value not in (None, ""):
        return str(value)
    legacy = row.get(field)
    return format(Decimal(str(legacy)).normalize(), "f") if legacy is not None else None


def legacy_number(value: str | None) -> float | None:
    """Keep legacy REAL columns writable without making them authoritative."""
    return float(value) if value is not None else None
