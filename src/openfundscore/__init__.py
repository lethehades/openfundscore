"""OpenFundScore public Python package."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .publication_gate import (
        PublicationDecision,
        PublicationGateError,
        PublicationGateResult,
        evaluate_publication_gate,
    )
    from .validation import RecordType, RecordValidationError, validate_record


__version__ = "0.2.0.dev0"

__all__ = (
    "PublicationDecision",
    "PublicationGateError",
    "PublicationGateResult",
    "RecordType",
    "RecordValidationError",
    "evaluate_publication_gate",
    "validate_record",
)


def __getattr__(name: str) -> Any:
    if name in {"RecordType", "RecordValidationError", "validate_record"}:
        from .validation import RecordType, RecordValidationError, validate_record

        validation_exports = {
            "RecordType": RecordType,
            "RecordValidationError": RecordValidationError,
            "validate_record": validate_record,
        }
        return validation_exports[name]
    if name in {
        "PublicationDecision",
        "PublicationGateError",
        "PublicationGateResult",
        "evaluate_publication_gate",
    }:
        from .publication_gate import (
            PublicationDecision,
            PublicationGateError,
            PublicationGateResult,
            evaluate_publication_gate,
        )

        publication_exports = {
            "PublicationDecision": PublicationDecision,
            "PublicationGateError": PublicationGateError,
            "PublicationGateResult": PublicationGateResult,
            "evaluate_publication_gate": evaluate_publication_gate,
        }
        return publication_exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
