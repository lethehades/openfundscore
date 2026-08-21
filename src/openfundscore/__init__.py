"""OpenFundScore public Python package."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .validation import RecordType, RecordValidationError, validate_record


__version__ = "0.2.0.dev0"

__all__ = (
    "RecordType",
    "RecordValidationError",
    "validate_record",
)


def __getattr__(name: str) -> Any:
    if name in __all__:
        from .validation import RecordType, RecordValidationError, validate_record

        exports = {
            "RecordType": RecordType,
            "RecordValidationError": RecordValidationError,
            "validate_record": validate_record,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
