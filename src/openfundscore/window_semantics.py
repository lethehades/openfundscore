"""Shared calendar semantics for public scoring boundaries."""

from __future__ import annotations

from calendar import monthrange
from datetime import date


def subtract_months(value: date, months: int) -> date:
    """Shift back whole calendar months, clamping to the target month end."""
    month_index = value.year * 12 + value.month - 1 - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def complete_months_between(start: date, end: date) -> int:
    """Return complete elapsed months under the OpenFundScore date convention."""
    if start > end:
        raise ValueError("window start must be on or before window end")
    return max(
        0,
        (end.year - start.year) * 12 + end.month - start.month - (end.day < start.day),
    )
