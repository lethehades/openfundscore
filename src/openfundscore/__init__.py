"""OpenFundScore public Python package."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .category_metrics import (
        ApplicabilityContext,
        CaptureDenominatorAudit,
        CaptureDenominatorStatus,
        CategoryMetricError,
        CategoryScoreResult,
        DimensionScore,
        HistoryStage,
        ManagerScoreAudit,
        MetricDirection,
        MetricObservation,
        MetricScore,
        MetricState,
        NormalizedMetric,
        PeerAuditRecord,
        PeerObservation,
        PeerSetAudit,
        normalize_metric,
        score_category_metrics,
    )
    from .evidence_usage import canonicalize_score_evidence_ledger_for_digest
    from .manager_research import (
        MANAGER_COMPONENT_SOURCE_MANIFEST,
        ManagerEvidenceSource,
        ManagerResearchHandoff,
        ManagerResearchValidationError,
        build_manager_evidence_sources,
        derive_manager_evidence_sources,
        recompute_manager_handoff,
        score_manager_research,
    )
    from .metric_catalog import (
        MetricCatalogValidationError,
        load_metric_catalog,
        validate_metric_catalog,
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
    "MANAGER_COMPONENT_SOURCE_MANIFEST",
    "ApplicabilityContext",
    "CaptureDenominatorAudit",
    "CaptureDenominatorStatus",
    "CategoryMetricError",
    "CategoryScoreResult",
    "DimensionScore",
    "HistoryStage",
    "ManagerEvidenceSource",
    "ManagerResearchHandoff",
    "ManagerResearchValidationError",
    "ManagerScoreAudit",
    "MappingDecision",
    "MetricCatalogValidationError",
    "MetricDirection",
    "MetricObservation",
    "MetricScore",
    "MetricState",
    "NormalizedMetric",
    "PeerAuditRecord",
    "PeerObservation",
    "PeerSetAudit",
    "PublicationDecision",
    "PublicationGateError",
    "PublicationGateResult",
    "RecordType",
    "RecordValidationError",
    "StrategyMappingError",
    "build_manager_evidence_sources",
    "canonicalize_score_evidence_ledger_for_digest",
    "derive_manager_evidence_sources",
    "evaluate_publication_gate",
    "load_metric_catalog",
    "load_packaged_strategy_mapping",
    "load_strategy_mapping",
    "map_strategy_family",
    "normalize_metric",
    "recompute_manager_handoff",
    "score_category_metrics",
    "score_manager_research",
    "validate_metric_catalog",
    "validate_record",
    "validate_strategy_mapping",
)


_CATEGORY_EXPORTS = {
    "ApplicabilityContext",
    "CaptureDenominatorAudit",
    "CaptureDenominatorStatus",
    "CategoryMetricError",
    "CategoryScoreResult",
    "DimensionScore",
    "HistoryStage",
    "ManagerScoreAudit",
    "MetricDirection",
    "MetricObservation",
    "MetricScore",
    "MetricState",
    "NormalizedMetric",
    "PeerAuditRecord",
    "PeerObservation",
    "PeerSetAudit",
    "normalize_metric",
    "score_category_metrics",
}

_METRIC_CATALOG_EXPORTS = {
    "MetricCatalogValidationError",
    "load_metric_catalog",
    "validate_metric_catalog",
}

_EVIDENCE_USAGE_EXPORTS = {"canonicalize_score_evidence_ledger_for_digest"}

_MANAGER_EXPORTS = {
    "MANAGER_COMPONENT_SOURCE_MANIFEST",
    "ManagerEvidenceSource",
    "ManagerResearchHandoff",
    "ManagerResearchValidationError",
    "build_manager_evidence_sources",
    "derive_manager_evidence_sources",
    "recompute_manager_handoff",
    "score_manager_research",
}


def __getattr__(name: str) -> Any:
    if name in _CATEGORY_EXPORTS:
        from . import category_metrics

        return getattr(category_metrics, name)
    if name in _METRIC_CATALOG_EXPORTS:
        from . import metric_catalog

        return getattr(metric_catalog, name)
    if name in _EVIDENCE_USAGE_EXPORTS:
        from . import evidence_usage

        return getattr(evidence_usage, name)
    if name in _MANAGER_EXPORTS:
        from . import manager_research

        return getattr(manager_research, name)
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
