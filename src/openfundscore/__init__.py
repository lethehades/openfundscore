"""OpenFundScore public Python package."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .manager_research import score_manager_research
    from .official_providers import (
        OFFICIAL_PROVIDER_SCHEMA_VERSION,
        FixedHostHttpClient,
        ProviderHttpError,
        SecEdgarSubmissionsAdapter,
        WorldBankIndicatorsAdapter,
    )
    from .publication_gate import (
        PublicationDecision,
        PublicationGateError,
        PublicationGateResult,
        evaluate_publication_gate,
    )
    from .strategy_mapping import (
        MappingDecision,
        StrategyMappingError,
        load_packaged_strategy_mapping,
        load_strategy_mapping,
        map_strategy_family,
        validate_strategy_mapping,
    )
    from .validation import RecordType, RecordValidationError, validate_record


__version__ = "0.2.0.dev0"

__all__ = (
    "OFFICIAL_PROVIDER_SCHEMA_VERSION",
    "FixedHostHttpClient",
    "MappingDecision",
    "ProviderHttpError",
    "PublicationDecision",
    "PublicationGateError",
    "PublicationGateResult",
    "RecordType",
    "RecordValidationError",
    "SecEdgarSubmissionsAdapter",
    "StrategyMappingError",
    "WorldBankIndicatorsAdapter",
    "evaluate_publication_gate",
    "load_packaged_strategy_mapping",
    "load_strategy_mapping",
    "map_strategy_family",
    "score_manager_research",
    "validate_record",
    "validate_strategy_mapping",
)


def __getattr__(name: str) -> Any:
    if name in {
        "FixedHostHttpClient",
        "OFFICIAL_PROVIDER_SCHEMA_VERSION",
        "ProviderHttpError",
        "SecEdgarSubmissionsAdapter",
        "WorldBankIndicatorsAdapter",
    }:
        from . import official_providers

        return getattr(official_providers, name)
    if name == "score_manager_research":
        from .manager_research import score_manager_research

        return score_manager_research
    if name in {
        "MappingDecision",
        "StrategyMappingError",
        "load_packaged_strategy_mapping",
        "load_strategy_mapping",
        "map_strategy_family",
        "validate_strategy_mapping",
    }:
        from . import strategy_mapping

        return getattr(strategy_mapping, name)
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
