"""OpenFundScore public Python package."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .ant_fortune_boundary import (
        AccessMode,
        BoundaryConclusion,
        BoundaryUse,
        BoundaryValidationError,
        FieldDecision,
        UseDecision,
        decide_ant_fortune_field,
        load_ant_fortune_boundary,
        validate_ant_fortune_boundary,
    )
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
    from .mainland_official import (
        MainlandOfficialSnapshotAdapter,
        SnapshotValidationError,
        load_mainland_entitlements,
    )
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
    from .walk_forward import (
        CandidateFund,
        FoldWindow,
        FutureOutcome,
        LifecycleInterval,
        PrecomputedScore,
        ScoreComponent,
        ScoreResult,
        ScoringView,
        VersionedSnapshot,
        WalkForwardConfig,
        WalkForwardError,
        WalkForwardReport,
        run_walk_forward,
    )


__version__ = "0.2.0.dev0"

__all__ = (
    "MANAGER_COMPONENT_SOURCE_MANIFEST",
    "OFFICIAL_PROVIDER_SCHEMA_VERSION",
    "AccessMode",
    "ApplicabilityContext",
    "BoundaryConclusion",
    "BoundaryUse",
    "BoundaryValidationError",
    "CandidateFund",
    "CaptureDenominatorAudit",
    "CaptureDenominatorStatus",
    "CategoryMetricError",
    "CategoryScoreResult",
    "DimensionScore",
    "FieldDecision",
    "FixedHostHttpClient",
    "FoldWindow",
    "FutureOutcome",
    "HistoryStage",
    "LifecycleInterval",
    "MainlandOfficialSnapshotAdapter",
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
    "PrecomputedScore",
    "ProviderHttpError",
    "PublicationDecision",
    "PublicationGateError",
    "PublicationGateResult",
    "RecordType",
    "RecordValidationError",
    "ScoreComponent",
    "ScoreResult",
    "ScoringView",
    "SecEdgarSubmissionsAdapter",
    "SnapshotValidationError",
    "StrategyMappingError",
    "UseDecision",
    "VersionedSnapshot",
    "WalkForwardConfig",
    "WalkForwardError",
    "WalkForwardReport",
    "WorldBankIndicatorsAdapter",
    "build_manager_evidence_sources",
    "canonicalize_score_evidence_ledger_for_digest",
    "decide_ant_fortune_field",
    "derive_manager_evidence_sources",
    "evaluate_publication_gate",
    "load_ant_fortune_boundary",
    "load_mainland_entitlements",
    "load_metric_catalog",
    "load_packaged_strategy_mapping",
    "load_strategy_mapping",
    "map_strategy_family",
    "normalize_metric",
    "recompute_manager_handoff",
    "run_walk_forward",
    "score_category_metrics",
    "score_manager_research",
    "validate_ant_fortune_boundary",
    "validate_metric_catalog",
    "validate_record",
    "validate_strategy_mapping",
)


_ANT_FORTUNE_EXPORTS = {
    "AccessMode",
    "BoundaryConclusion",
    "BoundaryUse",
    "BoundaryValidationError",
    "FieldDecision",
    "UseDecision",
    "decide_ant_fortune_field",
    "load_ant_fortune_boundary",
    "validate_ant_fortune_boundary",
}

_MAINLAND_EXPORTS = {
    "MainlandOfficialSnapshotAdapter",
    "SnapshotValidationError",
    "load_mainland_entitlements",
}

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

_OFFICIAL_PROVIDER_EXPORTS = {
    "FixedHostHttpClient",
    "OFFICIAL_PROVIDER_SCHEMA_VERSION",
    "ProviderHttpError",
    "SecEdgarSubmissionsAdapter",
    "WorldBankIndicatorsAdapter",
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
    if name in _ANT_FORTUNE_EXPORTS:
        from . import ant_fortune_boundary

        return getattr(ant_fortune_boundary, name)
    if name in _MAINLAND_EXPORTS:
        from . import mainland_official

        return getattr(mainland_official, name)
    if name in _CATEGORY_EXPORTS:
        from . import category_metrics

        return getattr(category_metrics, name)
    if name in _OFFICIAL_PROVIDER_EXPORTS:
        from . import official_providers

        return getattr(official_providers, name)
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
    if name in {
        "CandidateFund",
        "FoldWindow",
        "FutureOutcome",
        "LifecycleInterval",
        "PrecomputedScore",
        "ScoreComponent",
        "ScoreResult",
        "ScoringView",
        "VersionedSnapshot",
        "WalkForwardConfig",
        "WalkForwardError",
        "WalkForwardReport",
        "run_walk_forward",
    }:
        from . import walk_forward

        return getattr(walk_forward, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
