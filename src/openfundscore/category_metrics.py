"""Fail-closed, auditable category-specific metric scoring engine."""

from __future__ import annotations

import hashlib
import json
import math
import re
from calendar import monthrange
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, NoReturn

from .evidence_usage import (
    EvidenceUsageValidationError,
    canonicalize_score_evidence_ledger_for_digest,
    validate_score_evidence_usage,
)
from .formula_cross_fields import (
    FormulaCrossFieldValidationError,
    validate_formula_cross_fields,
)
from .manager_research import (
    ManagerResearchHandoff,
    ManagerResearchValidationError,
    recompute_manager_handoff,
)
from .metric_catalog import MetricCatalogValidationError, load_metric_catalog
from .peer_admission import PeerAdmissionValidationError, load_peer_admission_contract
from .resources import ResourceError, resolve_resource
from .score_config import ConfigValidationError, validate_score_config
from .validation import RecordValidationError, validate_record
from .window_semantics import complete_months_between


class CategoryMetricError(ValueError):
    """Stable fail-closed category metric boundary error."""

    def __init__(self, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        super().__init__(f"{code} at {path}: {message}")


class MetricDirection(StrEnum):
    """Declared monotonic direction for a category metric."""

    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class MetricState(StrEnum):
    """Whether a metric is observed, missing, or not applicable."""

    OBSERVED = "observed"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"


class CaptureDenominatorStatus(StrEnum):
    """Whether a benchmark downside denominator was actually observed."""

    PRESENT = "present"
    ABSENT = "absent"


class HistoryStage(StrEnum):
    """RFC 0001 short-history publication stage."""

    INSUFFICIENT = "insufficient"
    OBSERVATION = "observation"
    PROVISIONAL = "provisional"
    ELIGIBLE = "eligible"


@dataclass(frozen=True, slots=True)
class ApplicabilityContext:
    """Closed prerequisite facts used to execute conditional applicability."""

    declared_benchmark: bool
    cross_border_or_currency_exposure: bool
    derivative_or_commodity_exposure: bool
    income_distributing_assets: bool
    lookthrough_portfolio: bool
    securities_lending_program: bool


@dataclass(frozen=True, slots=True)
class CaptureDenominatorAudit:
    """Closed provenance for the denominator of one capture observation."""

    denominator_status: CaptureDenominatorStatus
    benchmark_downside_sample_count: int
    evidence_id: str
    lineage_id: str
    series_id: str


@dataclass(frozen=True, slots=True)
class MetricObservation:
    """One upstream-computed raw metric with point-in-time audit context."""

    metric_id: str
    state: MetricState
    raw_value: float | None
    fund_id: str
    series_id: str
    evidence_id: str
    lineage_id: str
    as_of: datetime
    published_at: datetime
    evaluation_timestamp: datetime
    sample_size: int
    window_months: int
    uncertainty: str | None = None
    capture_denominator: CaptureDenominatorAudit | None = None


@dataclass(frozen=True, slots=True)
class PeerObservation:
    """One raw metric value from a reproducible PIT peer snapshot."""

    peer_id: str
    metric_id: str
    raw_value: float
    series_id: str
    source_id: str
    lineage_id: str
    as_of: datetime
    published_at: datetime
    evaluation_timestamp: datetime
    peer_bucket: str
    peer_bucket_version: str
    category_profile: str
    admission_contract_version: str
    admission_contract_sha256: str
    snapshot_hash: str
    document_hash: str
    sample_size: int
    window_basis: str
    window_months: int
    window_start: str
    window_end: str
    capture_denominator: CaptureDenominatorAudit | None = None


@dataclass(frozen=True, slots=True)
class ManagerTenureAudit:
    """One fully validated tenure attribution row from manager scoring."""

    tenure_id: str
    mode: str
    factor: float
    co_manager_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ManagerTenureObservationAudit:
    """One manager performance observation consumed by tenure attribution."""

    observation_id: str
    tenure_id: str
    metric_id: str
    window_start: str
    window_end: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ManagerEvidenceAudit:
    """Canonical 0.2 ledger provenance for one consumed manager evidence item."""

    evidence_id: str
    evidence_role: str
    lineage_id: str
    series_id: str
    source_facts_sha256: str
    evidence_family: str
    target_component: str
    source_scope: str
    usage_mode: str
    observation_as_of: str
    window_basis: str
    window_months: int
    window_start: str
    window_end: str


@dataclass(frozen=True, slots=True)
class ManagerScoreAudit:
    """Closed audit of caller assertions and locally recomputed aggregation."""

    manager_id: str
    as_of: str
    model_version: str
    status: str
    score: float
    confidence: str
    manager_input_assertion_status: str
    component_weights: tuple[tuple[str, int], ...]
    component_raw_scores: tuple[tuple[str, float], ...]
    component_contributions: tuple[tuple[str, float], ...]
    component_evidence_ids: tuple[tuple[str, tuple[str, ...]], ...]
    component_evidence: tuple[ManagerEvidenceAudit, ...]
    tenure_aggregate_factor: float
    tenures: tuple[ManagerTenureAudit, ...]
    observations: tuple[ManagerTenureObservationAudit, ...]
    tenure_attribution_sha256: str


@dataclass(frozen=True, slots=True)
class PeerAuditRecord:
    """Immutable canonical peer tuple committed to a peer-set digest."""

    peer_id: str
    metric_id: str
    raw_value: float
    series_id: str
    source_id: str
    lineage_id: str
    as_of: str
    published_at: str
    evaluation_timestamp: str
    peer_bucket: str
    peer_bucket_version: str
    category_profile: str
    admission_contract_version: str
    admission_contract_sha256: str
    snapshot_hash: str
    document_hash: str
    sample_size: int
    window_basis: str
    window_months: int
    window_start: str
    window_end: str
    capture_denominator: CaptureDenominatorAudit | None


@dataclass(frozen=True, slots=True)
class PeerSetAudit:
    """Reproducible identity of one metric's qualified peer snapshot."""

    metric_id: str
    peer_bucket: str
    peer_bucket_version: str
    category_profile: str
    admission_contract_version: str
    admission_contract_sha256: str
    evaluation_timestamp: str
    peer_ids: tuple[str, ...]
    series_ids: tuple[str, ...]
    snapshot_hashes: tuple[str, ...]
    records: tuple[PeerAuditRecord, ...]
    digest: str


@dataclass(frozen=True, slots=True)
class NormalizedMetric:
    """One normalized metric with complete raw-to-score audit detail."""

    metric_id: str
    fund_id: str
    series_id: str
    evidence_id: str
    lineage_id: str
    as_of: str
    published_at: str
    evaluation_timestamp: str
    state: MetricState
    raw_value: float | None
    adjusted_value: float | None
    lower_bound: float | None
    upper_bound: float | None
    peer_sample_size: int
    direction: MetricDirection
    score: float | None
    adjustment_method: str
    formula_version: str
    catalog_version: str
    catalog_sha256: str
    peer_bucket: str
    peer_bucket_version: str
    sample_size: int
    window_months: int
    uncertainty: str | None
    peer_set_digest: str | None
    capture_denominator: CaptureDenominatorAudit | None


@dataclass(frozen=True, slots=True)
class MetricScore:
    """Configured metric identity plus its normalization audit."""

    dimension: str
    weight: int
    core: bool
    evidence_family: str
    formula: str
    formula_owner: str
    domain: str
    unit: str
    value_minimum: float
    value_maximum: float
    observation_window_kind: str
    observation_window_minimum_months: int
    observation_window_maximum_months: int
    applicability: str
    data_source: str
    normalized: NormalizedMetric


@dataclass(frozen=True, slots=True)
class DimensionScore:
    """One unrounded top-level dimension result."""

    dimension: str
    weight: int
    status: str
    score: float | None
    contribution: float | None
    metrics: tuple[MetricScore, ...]


@dataclass(frozen=True, slots=True)
class CategoryScoreResult:
    """Immutable category score and complete resource/normalization audit."""

    profile_id: str
    fund_strategy_id: str
    as_of: str
    model_version: str
    formula_version: str
    config_version: str
    config_sha256: str
    catalog_version: str
    catalog_sha256: str
    peer_bucket: str
    peer_bucket_version: str
    peer_admission_version: str
    peer_admission_sha256: str
    history_months: int
    adequate_regime_coverage: bool
    history_stage: HistoryStage
    status: str
    confidence: str
    open_score: float | None
    manager_score: float
    manager_audit: ManagerScoreAudit
    evidence_ledger_record_id: str
    evidence_ledger_sha256: str
    peer_sets: tuple[PeerSetAudit, ...]
    dimensions: tuple[DimensionScore, ...]
    metrics: tuple[MetricScore, ...]
    insufficient_dimensions: tuple[str, ...]
    missing_metric_ids: tuple[str, ...]
    not_applicable_metric_ids: tuple[str, ...]
    insufficiency_reasons: tuple[str, ...]


_METRIC_ID = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", re.ASCII)
_ENTITY_ID = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", re.ASCII)
_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){2}", re.ASCII)
_MAX_ID_LENGTH = 64
_MAX_TEXT_LENGTH = 256
_MAX_MONTHS = 1200
_IQR_ZERO_TOLERANCE = 1e-12
_SHA256 = re.compile(r"[0-9a-f]{64}", re.ASCII)
_MANAGER_COMPONENTS = (
    "tenure_attributed_performance",
    "downside_control",
    "cross_cycle_consistency",
    "style_discipline",
    "career_track_record",
    "workload_capacity",
    "research_platform_team",
    "compliance_integrity",
)
_CAPTURE_METRIC_SUFFIX = "_capture"
_MANAGER_LEDGER_COMPONENT = {
    component: f"manager_{component}" for component in _MANAGER_COMPONENTS
}
_FUND_LEDGER_COMPONENT = {
    "performance_evidence": "fund_d1_performance_evidence",
    "downside_risk": "fund_d2_downside_risk",
    "consistency": "fund_d3_consistency",
    "portfolio_structure": "fund_d5_portfolio_structure",
    "implementation_efficiency": "fund_d6_implementation_efficiency",
    "governance_operations": "fund_d7_governance_operations",
}
_APPLICABILITY_PREREQUISITE = {
    "requires_declared_benchmark": "declared_benchmark",
    "requires_cross_border_or_currency_exposure": ("cross_border_or_currency_exposure"),
    "requires_derivative_or_commodity_exposure": ("derivative_or_commodity_exposure"),
    "requires_income_distributing_assets": "income_distributing_assets",
    "requires_lookthrough_portfolio": "lookthrough_portfolio",
    "requires_securities_lending_program": "securities_lending_program",
}
_LEGACY_MANAGER_UNSET = object()


def _fail(code: str, path: str, message: str) -> NoReturn:
    raise CategoryMetricError(code, path, message)


def _identifier(value: object, *, path: str, metric: bool = False) -> str:
    pattern = _METRIC_ID if metric else _ENTITY_ID
    if (
        type(value) is not str
        or not value
        or len(value) > _MAX_ID_LENGTH
        or pattern.fullmatch(value) is None
    ):
        _fail(
            "invalid_identifier", path, "identifier must use the bounded ASCII profile"
        )
    return value


def _version(value: object, *, path: str) -> str:
    if type(value) is not str or len(value) > 32 or _VERSION.fullmatch(value) is None:
        _fail("invalid_version", path, "version must be an explicit semantic version")
    return value


def _finite_number(value: object, *, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("invalid_number", path, "value must be a finite number")
    converted = float(value)
    if not math.isfinite(converted):
        _fail("invalid_number", path, "value must be a finite number")
    return converted


def _bounded_integer(value: object, *, path: str, maximum: int) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        _fail("invalid_integer", path, "value must be a bounded non-negative integer")
    return value


def _validate_capture_denominator(
    value: object,
    *,
    metric_id: str,
    observed: bool,
    sample_size: int,
    path: str,
) -> CaptureDenominatorAudit | None:
    """Validate the closed observed/missing denominator state machine."""
    is_capture = metric_id.endswith(_CAPTURE_METRIC_SUFFIX)
    if not is_capture:
        if value is not None:
            _fail(
                "capture_denominator_mismatch",
                path,
                "non-capture metrics cannot carry capture denominator audit",
            )
        return None
    if type(value) is not CaptureDenominatorAudit:
        _fail(
            "capture_denominator_mismatch",
            path,
            "capture metrics require the closed CaptureDenominatorAudit type",
        )
    audit = value
    if type(audit.denominator_status) is not CaptureDenominatorStatus:
        _fail(
            "capture_denominator_mismatch",
            f"{path}.denominator_status",
            "capture denominator status is unsupported",
        )
    count = _bounded_integer(
        audit.benchmark_downside_sample_count,
        path=f"{path}.benchmark_downside_sample_count",
        maximum=10_000_000,
    )
    _identifier(audit.evidence_id, path=f"{path}.evidence_id")
    _identifier(audit.lineage_id, path=f"{path}.lineage_id")
    _identifier(audit.series_id, path=f"{path}.series_id")
    if observed:
        if (
            audit.denominator_status is not CaptureDenominatorStatus.PRESENT
            or count <= 0
            or count > sample_size
        ):
            _fail(
                "capture_denominator_mismatch",
                path,
                "observed capture requires a present positive denominator sample within the metric sample",
            )
    elif audit.denominator_status is not CaptureDenominatorStatus.ABSENT or count != 0:
        _fail(
            "capture_denominator_mismatch",
            path,
            "unobserved capture requires an absent zero-count denominator",
        )
    return audit


def _aware_datetime(value: object, *, path: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        _fail("invalid_timestamp", path, "timestamp must be timezone-aware")
    return value


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp_text(value: object, *, path: str) -> datetime:
    if type(value) is not str or not value or len(value) > 64:
        _fail("invalid_timestamp", path, "timestamp must use bounded RFC3339 text")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        _fail("invalid_timestamp", path, "timestamp must use RFC3339 text")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail("invalid_timestamp", path, "timestamp must include an offset")
    return parsed


def _subtract_months(value: date, months: int) -> date:
    """Shift a date back by whole calendar months with month-end clamping."""
    month_index = value.year * 12 + value.month - 1 - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def _window_month_bounds(window: Mapping[str, Any]) -> tuple[int, int]:
    """Normalize supported catalog window taxonomies to month bounds."""
    if set(window) >= {"minimum_months", "maximum_months"}:
        return window["minimum_months"], window["maximum_months"]
    if set(window) >= {"minimum", "maximum", "unit"}:
        if window["unit"] == "instant":
            return 0, 0
        if window["unit"] == "months":
            return window["minimum"], window["maximum"]
    _fail(
        "resource_mismatch",
        "$resource.observation_window",
        "catalog window cannot be evaluated in months",
    )


def _canonical_json_object(value: object, *, path: str) -> dict[str, Any]:
    active: set[int] = set()
    nodes = 0

    def copy_value(item: object, *, item_path: str, depth: int) -> Any:
        nonlocal nodes
        nodes += 1
        if nodes > 10_000 or depth > 128:
            _fail("input_too_large", path, "audit object exceeds the canonical limit")
        item_type = type(item)
        if item is None or item_type is bool or item_type is str or item_type is int:
            return item
        if item_type is float:
            return _finite_number(item, path=item_path)
        if item_type is dict:
            identity = id(item)
            if identity in active or len(item) > 1000:
                _fail("invalid_audit", item_path, "audit object is cyclic or too wide")
            active.add(identity)
            try:
                copied: dict[str, Any] = {}
                for key, child in dict.items(item):
                    if type(key) is not str or key in copied:
                        _fail(
                            "invalid_audit",
                            item_path,
                            "audit object keys must be unique strings",
                        )
                    copied[key] = copy_value(
                        child,
                        item_path=f"{item_path}.{key}",
                        depth=depth + 1,
                    )
                return copied
            finally:
                active.remove(identity)
        if item_type is list:
            identity = id(item)
            if identity in active or len(item) > 1000:
                _fail("invalid_audit", item_path, "audit array is cyclic or too wide")
            active.add(identity)
            try:
                return [
                    copy_value(
                        child, item_path=f"{item_path}[{index}]", depth=depth + 1
                    )
                    for index, child in enumerate(list.__iter__(item))
                ]
            finally:
                active.remove(identity)
        _fail("invalid_audit", item_path, "audit input must contain only JSON values")

    snapshot = copy_value(value, item_path=path, depth=0)
    if type(snapshot) is not dict:
        _fail("invalid_audit", path, "audit input must be an object")
    return snapshot


def _json_digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _manager_audit(
    value: object,
    *,
    evaluation: datetime,
    model_version: str,
    configured_components: list[dict[str, Any]],
) -> ManagerScoreAudit:
    if type(value) is ManagerScoreAudit:
        value = {
            "manager_id": value.manager_id,
            "as_of": value.as_of,
            "model_version": value.model_version,
            "status": value.status,
            "score": value.score,
            "confidence": value.confidence,
            "manager_input_assertion_status": value.manager_input_assertion_status,
            "component_weights": dict(value.component_weights),
            "component_raw_scores": dict(value.component_raw_scores),
            "component_contributions": dict(value.component_contributions),
            "component_evidence_ids": {
                component: list(evidence_ids)
                for component, evidence_ids in value.component_evidence_ids
            },
            "component_evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "evidence_role": item.evidence_role,
                    "lineage_id": item.lineage_id,
                    "series_id": item.series_id,
                    "source_facts_sha256": item.source_facts_sha256,
                    "evidence_family": item.evidence_family,
                    "target_component": item.target_component,
                    "source_scope": item.source_scope,
                    "usage_mode": item.usage_mode,
                    "observation_as_of": item.observation_as_of,
                    "window_basis": item.window_basis,
                    "window_months": item.window_months,
                    "window_start": item.window_start,
                    "window_end": item.window_end,
                }
                for item in value.component_evidence
            ],
            "tenure_attribution": {
                "aggregate_factor": value.tenure_aggregate_factor,
                "tenures": [
                    {
                        "tenure_id": item.tenure_id,
                        "mode": item.mode,
                        "factor": item.factor,
                        "co_manager_ids": list(item.co_manager_ids),
                    }
                    for item in value.tenures
                ],
                "observations": [
                    {
                        "observation_id": item.observation_id,
                        "tenure_id": item.tenure_id,
                        "metric_id": item.metric_id,
                        "window_start": item.window_start,
                        "window_end": item.window_end,
                        "evidence_ids": list(item.evidence_ids),
                    }
                    for item in value.observations
                ],
            },
            "insufficient_components": [],
        }
    snapshot = _canonical_json_object(value, path="$manager_audit")
    expected_fields = {
        "manager_id",
        "as_of",
        "model_version",
        "status",
        "score",
        "confidence",
        "manager_input_assertion_status",
        "component_weights",
        "component_raw_scores",
        "component_contributions",
        "component_evidence_ids",
        "component_evidence",
        "tenure_attribution",
        "insufficient_components",
    }
    if set(snapshot) != expected_fields:
        _fail(
            "invalid_manager_audit",
            "$manager_audit",
            "manager result fields are closed",
        )
    if snapshot["manager_input_assertion_status"] != "caller_provided":
        _fail(
            "invalid_manager_audit",
            "$manager_audit.manager_input_assertion_status",
            "manager input assertions must remain caller_provided",
        )
    manager_as_of = _parse_timestamp_text(
        snapshot["as_of"], path="$manager_audit.as_of"
    )
    if manager_as_of > evaluation:
        _fail(
            "manager_as_of_mismatch",
            "$manager_audit.as_of",
            "manager as_of must be on or before score evaluation time",
        )
    manager_as_of_date = manager_as_of.astimezone(UTC).date()
    expected_weights = {
        component["id"]: component["weight"] for component in configured_components
    }
    weights = snapshot["component_weights"]
    if (
        type(weights) is not dict
        or set(weights) != set(_MANAGER_COMPONENTS)
        or any(type(weights[component]) is not int for component in _MANAGER_COMPONENTS)
        or weights != expected_weights
    ):
        _fail(
            "invalid_manager_audit",
            "$manager_audit.component_weights",
            "manager weights do not match the model",
        )
    raw_scores = snapshot["component_raw_scores"]
    if type(raw_scores) is not dict or set(raw_scores) != set(_MANAGER_COMPONENTS):
        _fail(
            "invalid_manager_audit",
            "$manager_audit.component_raw_scores",
            "manager raw component scores are incomplete",
        )
    raw_score_pairs: list[tuple[str, float]] = []
    checked_raw_scores: dict[str, float] = {}
    for component in _MANAGER_COMPONENTS:
        raw_score = _finite_number(
            raw_scores[component],
            path=f"$manager_audit.component_raw_scores.{component}",
        )
        if not 0 <= raw_score <= 100:
            _fail(
                "invalid_manager_audit",
                f"$manager_audit.component_raw_scores.{component}",
                "manager raw component score must be from zero through 100",
            )
        checked_raw_scores[component] = raw_score
        raw_score_pairs.append((component, raw_score))
    contributions = snapshot["component_contributions"]
    if type(contributions) is not dict or set(contributions) != set(
        _MANAGER_COMPONENTS
    ):
        _fail(
            "invalid_manager_audit",
            "$manager_audit.component_contributions",
            "manager contributions are incomplete",
        )
    contribution_pairs: list[tuple[str, float]] = []
    contribution_total = 0.0
    for component in _MANAGER_COMPONENTS:
        amount = _finite_number(
            contributions[component],
            path=f"$manager_audit.component_contributions.{component}",
        )
        if not 0 <= amount <= weights[component]:
            _fail(
                "invalid_manager_audit",
                f"$manager_audit.component_contributions.{component}",
                "manager contribution exceeds its configured weight",
            )
        contribution_pairs.append((component, amount))
        contribution_total = _finite_number(
            contribution_total + amount,
            path="$manager_audit.component_contributions",
        )
    score = _finite_number(snapshot["score"], path="$manager_audit.score")
    if not math.isclose(contribution_total, score, rel_tol=0.0, abs_tol=1e-6):
        _fail(
            "invalid_manager_audit",
            "$manager_audit.score",
            "manager contributions do not reconcile",
        )
    if snapshot["insufficient_components"] != []:
        _fail(
            "invalid_manager_audit",
            "$manager_audit.insufficient_components",
            "scored manager cannot be insufficient",
        )
    evidence = snapshot["component_evidence_ids"]
    if type(evidence) is not dict or set(evidence) != set(_MANAGER_COMPONENTS):
        _fail(
            "invalid_manager_audit",
            "$manager_audit.component_evidence_ids",
            "manager evidence map is incomplete",
        )
    evidence_pairs: list[tuple[str, tuple[str, ...]]] = []
    for component in _MANAGER_COMPONENTS:
        identifiers = evidence[component]
        if (
            type(identifiers) is not list
            or not identifiers
            or len(identifiers) != len(set(identifiers))
        ):
            _fail(
                "invalid_manager_audit",
                f"$manager_audit.component_evidence_ids.{component}",
                "scored component requires unique evidence",
            )
        checked = tuple(
            _identifier(
                identifier,
                path=f"$manager_audit.component_evidence_ids.{component}[{index}]",
            )
            for index, identifier in enumerate(identifiers)
        )
        evidence_pairs.append((component, checked))

    provenance = snapshot["component_evidence"]
    if type(provenance) is not list or not provenance or len(provenance) > 1000:
        _fail(
            "invalid_manager_audit",
            "$manager_audit.component_evidence",
            "manager evidence provenance must be a bounded non-empty array",
        )
    provenance_fields = {
        "evidence_id",
        "evidence_role",
        "lineage_id",
        "series_id",
        "source_facts_sha256",
        "evidence_family",
        "target_component",
        "source_scope",
        "usage_mode",
        "observation_as_of",
        "window_basis",
        "window_months",
        "window_start",
        "window_end",
    }
    checked_provenance: list[ManagerEvidenceAudit] = []
    provenance_pairs: list[tuple[str, str]] = []
    for index, item in enumerate(provenance):
        path = f"$manager_audit.component_evidence[{index}]"
        if type(item) is not dict or set(item) != provenance_fields:
            _fail(
                "invalid_manager_audit",
                path,
                "manager evidence provenance fields are closed",
            )
        evidence_id = _identifier(item["evidence_id"], path=f"{path}.evidence_id")
        if item["evidence_role"] != "primary":
            _fail(
                "invalid_manager_audit",
                f"{path}.evidence_role",
                "manager component evidence must explicitly be primary",
            )
        lineage_id = _identifier(item["lineage_id"], path=f"{path}.lineage_id")
        series_id = _identifier(item["series_id"], path=f"{path}.series_id")
        source_facts_sha256 = item["source_facts_sha256"]
        if (
            type(source_facts_sha256) is not str
            or _SHA256.fullmatch(source_facts_sha256) is None
        ):
            _fail(
                "invalid_manager_audit",
                f"{path}.source_facts_sha256",
                "manager source facts digest must be lowercase SHA-256",
            )
        target_component = item["target_component"]
        if target_component not in set(_MANAGER_LEDGER_COMPONENT.values()):
            _fail(
                "invalid_manager_audit",
                f"{path}.target_component",
                "manager evidence target component is unsupported",
            )
        evidence_family = item["evidence_family"]
        if (
            type(evidence_family) is not str
            or not evidence_family
            or len(evidence_family) > _MAX_TEXT_LENGTH
        ):
            _fail(
                "invalid_manager_audit",
                f"{path}.evidence_family",
                "manager evidence family must be bounded text",
            )
        source_scope = item["source_scope"]
        if source_scope not in {"current_fund", "external_career", "team_platform"}:
            _fail(
                "invalid_manager_audit",
                f"{path}.source_scope",
                "manager evidence source scope is unsupported",
            )
        usage_mode = item["usage_mode"]
        if usage_mode not in {"raw", "residualized", "orthogonal", "descriptive"}:
            _fail(
                "invalid_manager_audit",
                f"{path}.usage_mode",
                "manager evidence usage mode is unsupported",
            )
        observation_as_of = _parse_timestamp_text(
            item["observation_as_of"], path=f"{path}.observation_as_of"
        )
        if observation_as_of > manager_as_of:
            _fail(
                "invalid_manager_audit",
                f"{path}.observation_as_of",
                "manager evidence observation cannot be after manager as_of",
            )
        window_months = _bounded_integer(
            item["window_months"], path=f"{path}.window_months", maximum=_MAX_MONTHS
        )
        window_basis = item["window_basis"]
        if window_basis not in {"point_in_time", "calendar_months", "actual_dates"}:
            _fail(
                "invalid_manager_audit",
                f"{path}.window_basis",
                "manager evidence window basis is unsupported",
            )
        try:
            window_start = date.fromisoformat(item["window_start"])
            window_end = date.fromisoformat(item["window_end"])
        except (TypeError, ValueError):
            _fail(
                "invalid_manager_audit",
                path,
                "manager evidence window must use ISO dates",
            )
        if (
            window_start > window_end
            or window_end > manager_as_of_date
            or window_end > observation_as_of.astimezone(UTC).date()
        ):
            _fail(
                "invalid_manager_audit",
                path,
                "manager evidence window must end by observation and manager as_of",
            )
        observation_date = observation_as_of.astimezone(UTC).date()
        if window_basis == "point_in_time" and (
            window_months != 0
            or window_start != observation_date
            or window_end != observation_date
        ):
            _fail(
                "invalid_manager_audit",
                path,
                "point-in-time manager evidence must use its UTC observation date",
            )
        if window_basis == "calendar_months" and (
            window_end != observation_date
            or window_start != _subtract_months(observation_date, window_months)
        ):
            _fail(
                "invalid_manager_audit",
                path,
                "calendar manager evidence must use exact reverse-clamped endpoints",
            )
        actual_months = max(
            0,
            (window_end.year - window_start.year) * 12
            + window_end.month
            - window_start.month
            - (window_end.day < window_start.day),
        )
        if window_basis == "actual_dates" and window_months != actual_months:
            _fail(
                "invalid_manager_audit",
                f"{path}.window_months",
                "actual-date manager evidence months must match its real endpoints",
            )
        checked_provenance.append(
            ManagerEvidenceAudit(
                evidence_id=evidence_id,
                evidence_role="primary",
                lineage_id=lineage_id,
                series_id=series_id,
                source_facts_sha256=source_facts_sha256,
                evidence_family=evidence_family,
                target_component=target_component,
                source_scope=source_scope,
                usage_mode=usage_mode,
                observation_as_of=_iso_z(observation_as_of),
                window_basis=window_basis,
                window_months=window_months,
                window_start=window_start.isoformat(),
                window_end=window_end.isoformat(),
            )
        )
        provenance_pairs.append((target_component, evidence_id))
    expected_provenance_pairs = [
        (_MANAGER_LEDGER_COMPONENT[component], evidence_id)
        for component, evidence_ids in evidence_pairs
        for evidence_id in evidence_ids
    ]
    if Counter(provenance_pairs) != Counter(expected_provenance_pairs):
        _fail(
            "invalid_manager_audit",
            "$manager_audit.component_evidence",
            "manager provenance must bind every scored component evidence ID exactly once",
        )

    tenure = snapshot["tenure_attribution"]
    if (
        type(tenure) is not dict
        or set(tenure) != {"aggregate_factor", "tenures", "observations"}
        or type(tenure["tenures"]) is not list
        or not tenure["tenures"]
        or type(tenure["observations"]) is not list
        or not tenure["observations"]
    ):
        _fail(
            "invalid_manager_audit",
            "$manager_audit.tenure_attribution",
            "scored manager requires a closed tenure attribution summary",
        )
    factor = _finite_number(
        tenure["aggregate_factor"],
        path="$manager_audit.tenure_attribution.aggregate_factor",
    )
    if not 0 < factor <= 1:
        _fail(
            "invalid_manager_audit",
            "$manager_audit.tenure_attribution.aggregate_factor",
            "tenure factor must be positive through one",
        )
    checked_tenures: list[ManagerTenureAudit] = []
    tenure_ids: set[str] = set()
    for index, item in enumerate(tenure["tenures"]):
        path = f"$manager_audit.tenure_attribution.tenures[{index}]"
        if type(item) is not dict or set(item) != {
            "tenure_id",
            "mode",
            "factor",
            "co_manager_ids",
        }:
            _fail(
                "invalid_manager_audit",
                path,
                "tenure attribution row fields are closed",
            )
        tenure_id = _identifier(item["tenure_id"], path=f"{path}.tenure_id")
        if tenure_id in tenure_ids:
            _fail(
                "invalid_manager_audit",
                f"{path}.tenure_id",
                "tenure identifiers must be unique",
            )
        tenure_ids.add(tenure_id)
        mode = item["mode"]
        if mode not in {"individual", "team", "role_weighted"}:
            _fail(
                "invalid_manager_audit",
                f"{path}.mode",
                "scored tenure mode is unsupported",
            )
        item_factor = _finite_number(item["factor"], path=f"{path}.factor")
        co_managers = item["co_manager_ids"]
        if type(co_managers) is not list or len(co_managers) != len(set(co_managers)):
            _fail(
                "invalid_manager_audit",
                f"{path}.co_manager_ids",
                "co-manager identifiers must be a unique array",
            )
        checked_co_managers = tuple(
            _identifier(manager_id, path=f"{path}.co_manager_ids[{manager_index}]")
            for manager_index, manager_id in enumerate(co_managers)
        )
        if mode == "individual" and (checked_co_managers or item_factor != 1.0):
            _fail(
                "invalid_manager_audit",
                path,
                "individual tenure must have full sole attribution",
            )
        if mode == "team" and (
            not checked_co_managers
            or item_factor != round(1 / (1 + len(checked_co_managers)), 6)
        ):
            _fail(
                "invalid_manager_audit",
                path,
                "team tenure factor must match equal attribution",
            )
        if mode == "role_weighted" and (
            not checked_co_managers or not 0 < item_factor < 1
        ):
            _fail(
                "invalid_manager_audit",
                path,
                "role-weighted tenure requires explicit fractional attribution",
            )
        checked_tenures.append(
            ManagerTenureAudit(
                tenure_id=tenure_id,
                mode=mode,
                factor=item_factor,
                co_manager_ids=checked_co_managers,
            )
        )
    expected_factor = round(
        sum(item.factor for item in checked_tenures) / len(checked_tenures),
        6,
    )
    if factor != expected_factor:
        _fail(
            "invalid_manager_audit",
            "$manager_audit.tenure_attribution.aggregate_factor",
            "aggregate tenure factor does not reconcile",
        )
    tolerance = Decimal("0.000001")
    for component, amount in contribution_pairs:
        multiplier = factor if component == "tenure_attributed_performance" else 1.0
        expected_amount = (
            Decimal(str(checked_raw_scores[component]))
            * Decimal(str(multiplier))
            * Decimal(weights[component])
            / Decimal(100)
        )
        if abs(Decimal(str(amount)) - expected_amount) > tolerance:
            _fail(
                "invalid_manager_audit",
                f"$manager_audit.component_contributions.{component}",
                "manager contribution does not reconcile with raw score, weight, and tenure factor",
            )

    tenure_evidence = dict(evidence_pairs)["tenure_attributed_performance"]
    checked_observations: list[ManagerTenureObservationAudit] = []
    observation_ids: set[str] = set()
    referenced_tenures: set[str] = set()
    for index, item in enumerate(tenure["observations"]):
        path = f"$manager_audit.tenure_attribution.observations[{index}]"
        if type(item) is not dict or set(item) != {
            "observation_id",
            "tenure_id",
            "metric_id",
            "window_start",
            "window_end",
            "evidence_ids",
        }:
            _fail("invalid_manager_audit", path, "tenure observation fields are closed")
        observation_id = _identifier(
            item["observation_id"], path=f"{path}.observation_id"
        )
        if observation_id in observation_ids:
            _fail(
                "invalid_manager_audit",
                f"{path}.observation_id",
                "tenure observation identifiers must be unique",
            )
        observation_ids.add(observation_id)
        tenure_id = _identifier(item["tenure_id"], path=f"{path}.tenure_id")
        if tenure_id not in tenure_ids:
            _fail(
                "invalid_manager_audit",
                f"{path}.tenure_id",
                "tenure observation must reference a closed tenure",
            )
        referenced_tenures.add(tenure_id)
        metric_id = _identifier(
            item["metric_id"], path=f"{path}.metric_id", metric=True
        )
        try:
            window_start = date.fromisoformat(item["window_start"])
            window_end = date.fromisoformat(item["window_end"])
        except (TypeError, ValueError):
            _fail(
                "invalid_manager_audit",
                path,
                "tenure observation window must use ISO dates",
            )
        if window_start > window_end:
            _fail(
                "invalid_manager_audit", path, "tenure observation window is reversed"
            )
        if window_end > manager_as_of_date:
            _fail(
                "invalid_manager_audit",
                f"{path}.window_end",
                "tenure observation window cannot exceed manager as_of",
            )
        identifiers = item["evidence_ids"]
        if (
            type(identifiers) is not list
            or not identifiers
            or len(identifiers) != len(set(identifiers))
        ):
            _fail(
                "invalid_manager_audit",
                f"{path}.evidence_ids",
                "tenure observation requires unique evidence",
            )
        checked_ids = tuple(
            _identifier(identifier, path=f"{path}.evidence_ids[{evidence_index}]")
            for evidence_index, identifier in enumerate(identifiers)
        )
        if not set(checked_ids).issubset(tenure_evidence):
            _fail(
                "invalid_manager_audit",
                f"{path}.evidence_ids",
                "tenure observation evidence must bind the scored component",
            )
        checked_observations.append(
            ManagerTenureObservationAudit(
                observation_id=observation_id,
                tenure_id=tenure_id,
                metric_id=metric_id,
                window_start=window_start.isoformat(),
                window_end=window_end.isoformat(),
                evidence_ids=checked_ids,
            )
        )
    if referenced_tenures != tenure_ids:
        _fail(
            "invalid_manager_audit",
            "$manager_audit.tenure_attribution",
            "every attributed tenure requires an observation",
        )

    audit = ManagerScoreAudit(
        manager_id=_identifier(
            snapshot["manager_id"], path="$manager_audit.manager_id"
        ),
        as_of=_iso_z(manager_as_of),
        model_version=snapshot["model_version"],
        status=snapshot["status"],
        score=score,
        confidence=snapshot["confidence"],
        manager_input_assertion_status="caller_provided",
        component_weights=tuple(
            (component, weights[component]) for component in _MANAGER_COMPONENTS
        ),
        component_raw_scores=tuple(raw_score_pairs),
        component_contributions=tuple(contribution_pairs),
        component_evidence_ids=tuple(evidence_pairs),
        component_evidence=tuple(checked_provenance),
        tenure_aggregate_factor=factor,
        tenures=tuple(checked_tenures),
        observations=tuple(checked_observations),
        tenure_attribution_sha256=_json_digest(tenure),
    )
    if audit.status != "scored" or not 0 <= score <= 100:
        _fail(
            "invalid_manager_audit",
            "$manager_audit",
            "manager audit must be a scored result from zero through 100",
        )
    if audit.confidence != "low":
        _fail(
            "invalid_manager_audit",
            "$manager_audit.confidence",
            "caller-provided manager assertions require low confidence",
        )
    if audit.model_version != model_version:
        _fail(
            "manager_model_mismatch",
            "$manager_audit.model_version",
            "manager model version does not match the category model",
        )
    return audit


def _ledger_snapshot(value: object) -> dict[str, Any]:
    snapshot = _canonical_json_object(value, path="$evidence_ledger")
    try:
        validate_record("score_evidence_usage", snapshot, schema_version="0.2.0")
        validate_score_evidence_usage(snapshot)
    except (RecordValidationError, EvidenceUsageValidationError):
        _fail(
            "invalid_evidence_ledger",
            "$evidence_ledger",
            "evidence ledger failed schema or semantic validation",
        )
    return snapshot


def _validate_observation(value: object, *, path: str) -> MetricObservation:
    if type(value) is not MetricObservation:
        _fail("invalid_observation", path, "observation must use MetricObservation")
    observation = value
    _identifier(observation.metric_id, path=f"{path}.metric_id", metric=True)
    _identifier(observation.fund_id, path=f"{path}.fund_id")
    _identifier(observation.series_id, path=f"{path}.series_id")
    _identifier(observation.evidence_id, path=f"{path}.evidence_id")
    _identifier(observation.lineage_id, path=f"{path}.lineage_id")
    if type(observation.state) is not MetricState:
        _fail("invalid_state", f"{path}.state", "metric state is unsupported")
    sample_size = _bounded_integer(
        observation.sample_size,
        path=f"{path}.sample_size",
        maximum=10_000_000,
    )
    _bounded_integer(
        observation.window_months,
        path=f"{path}.window_months",
        maximum=_MAX_MONTHS,
    )
    if observation.uncertainty is not None and (
        type(observation.uncertainty) is not str
        or not observation.uncertainty
        or len(observation.uncertainty) > _MAX_TEXT_LENGTH
    ):
        _fail(
            "invalid_uncertainty",
            f"{path}.uncertainty",
            "uncertainty must be bounded text",
        )
    as_of = _aware_datetime(observation.as_of, path=f"{path}.as_of")
    published = _aware_datetime(observation.published_at, path=f"{path}.published_at")
    evaluation = _aware_datetime(
        observation.evaluation_timestamp,
        path=f"{path}.evaluation_timestamp",
    )
    if as_of > published:
        _fail(
            "invalid_chronology",
            f"{path}.as_of",
            "as_of must be on or before publication",
        )
    if published > evaluation:
        _fail(
            "future_publication",
            f"{path}.published_at",
            "publication exceeds evaluation time",
        )
    if observation.state is MetricState.OBSERVED:
        _finite_number(observation.raw_value, path=f"{path}.raw_value")
        if sample_size == 0:
            _fail(
                "invalid_observation",
                path,
                "observed metrics require a positive sample",
            )
    elif observation.raw_value is not None:
        _fail(
            "invalid_state_value",
            f"{path}.raw_value",
            "missing and NA metrics cannot carry raw values",
        )
    _validate_capture_denominator(
        observation.capture_denominator,
        metric_id=observation.metric_id,
        observed=observation.state is MetricState.OBSERVED,
        sample_size=sample_size,
        path=f"{path}.capture_denominator",
    )
    return observation


def _validate_peer(value: object, *, path: str) -> PeerObservation:
    if type(value) is not PeerObservation:
        _fail("invalid_peer", path, "peer must use PeerObservation")
    peer = value
    _identifier(peer.peer_id, path=f"{path}.peer_id")
    _identifier(peer.metric_id, path=f"{path}.metric_id", metric=True)
    _identifier(peer.series_id, path=f"{path}.series_id")
    _identifier(peer.source_id, path=f"{path}.source_id")
    _identifier(peer.lineage_id, path=f"{path}.lineage_id")
    _identifier(peer.peer_bucket, path=f"{path}.peer_bucket")
    _version(peer.peer_bucket_version, path=f"{path}.peer_bucket_version")
    _identifier(peer.category_profile, path=f"{path}.category_profile", metric=True)
    _version(
        peer.admission_contract_version,
        path=f"{path}.admission_contract_version",
    )
    if (
        type(peer.admission_contract_sha256) is not str
        or _SHA256.fullmatch(peer.admission_contract_sha256) is None
    ):
        _fail(
            "invalid_peer_admission",
            f"{path}.admission_contract_sha256",
            "peer admission provenance must use SHA-256",
        )
    _finite_number(peer.raw_value, path=f"{path}.raw_value")
    peer_sample_size = _bounded_integer(
        peer.sample_size,
        path=f"{path}.sample_size",
        maximum=10_000_000,
    )
    if peer_sample_size == 0:
        _fail(
            "invalid_peer",
            f"{path}.sample_size",
            "observed peer metrics require a positive sample",
        )
    _validate_capture_denominator(
        peer.capture_denominator,
        metric_id=peer.metric_id,
        observed=True,
        sample_size=peer_sample_size,
        path=f"{path}.capture_denominator",
    )
    as_of = _aware_datetime(peer.as_of, path=f"{path}.as_of")
    published = _aware_datetime(peer.published_at, path=f"{path}.published_at")
    evaluation = _aware_datetime(
        peer.evaluation_timestamp, path=f"{path}.evaluation_timestamp"
    )
    if as_of > published or published > evaluation:
        _fail(
            "invalid_peer_chronology",
            path,
            "peer chronology must be as_of <= published <= evaluation",
        )
    window_months = _bounded_integer(
        peer.window_months,
        path=f"{path}.window_months",
        maximum=_MAX_MONTHS,
    )
    try:
        window_start = date.fromisoformat(peer.window_start)
        window_end = date.fromisoformat(peer.window_end)
    except (TypeError, ValueError):
        _fail("invalid_peer", path, "peer window must use ISO dates")
    observation_date = as_of.astimezone(UTC).date()
    if window_start > window_end or window_end > observation_date:
        _fail("invalid_peer", path, "peer window must end by its observation date")
    if peer.window_basis == "point_in_time":
        valid_window = (
            window_months == 0
            and window_start == observation_date
            and window_end == observation_date
        )
    elif peer.window_basis == "calendar_months":
        valid_window = (
            window_months > 0
            and window_end == observation_date
            and window_start == _subtract_months(observation_date, window_months)
        )
    elif peer.window_basis == "actual_dates":
        valid_window = window_months == complete_months_between(
            window_start, window_end
        )
    else:
        valid_window = False
    if not valid_window:
        _fail(
            "invalid_peer",
            f"{path}.window_basis",
            "peer window basis, months, and endpoints must reconcile",
        )
    for field, digest in (
        ("snapshot_hash", peer.snapshot_hash),
        ("document_hash", peer.document_hash),
    ):
        if type(digest) is not str or _SHA256.fullmatch(digest) is None:
            _fail(
                "invalid_peer_provenance",
                f"{path}.{field}",
                "peer provenance must use SHA-256",
            )
    return peer


def _register_unique_peer_identity(
    peer: PeerObservation,
    *,
    path: str,
    peer_ids: set[tuple[str, str]],
    series_ids: set[tuple[str, str]],
    lineage_ids: set[tuple[str, str]],
) -> None:
    """Require each economic identity dimension to be unique within a metric."""
    identities = (
        ("peer_id", peer.peer_id, peer_ids),
        ("series_id", peer.series_id, series_ids),
        ("lineage_id", peer.lineage_id, lineage_ids),
    )
    for field, value, seen in identities:
        if (peer.metric_id, value) in seen:
            _fail(
                "duplicate_peer",
                f"{path}.{field}",
                "peer_id, series_id, and lineage_id must each be unique per metric",
            )
    for _, value, seen in identities:
        seen.add((peer.metric_id, value))


def _peer_set_audit(
    peers: tuple[PeerObservation, ...],
    *,
    metric_id: str,
    peer_bucket: str,
    peer_bucket_version: str,
    category_profile: str,
    admission_contract_version: str,
    admission_contract_sha256: str,
    evaluation: datetime,
    path: str,
) -> PeerSetAudit:
    ordered = tuple(sorted(peers, key=lambda item: item.peer_id))
    rows: list[dict[str, Any]] = []
    records: list[PeerAuditRecord] = []
    for index, peer in enumerate(ordered):
        if (
            peer.metric_id != metric_id
            or peer.peer_bucket != peer_bucket
            or peer.peer_bucket_version != peer_bucket_version
            or peer.category_profile != category_profile
            or peer.admission_contract_version != admission_contract_version
            or peer.admission_contract_sha256 != admission_contract_sha256
            or peer.evaluation_timestamp != evaluation
        ):
            _fail(
                "peer_snapshot_mismatch",
                f"{path}[{index}]",
                "peer metric, bucket, profile, admission contract, and evaluation must match",
            )
        row = {
            "peer_id": peer.peer_id,
            "metric_id": peer.metric_id,
            "raw_value": peer.raw_value,
            "series_id": peer.series_id,
            "source_id": peer.source_id,
            "lineage_id": peer.lineage_id,
            "as_of": _iso_z(peer.as_of),
            "published_at": _iso_z(peer.published_at),
            "evaluation_timestamp": _iso_z(peer.evaluation_timestamp),
            "peer_bucket": peer.peer_bucket,
            "peer_bucket_version": peer.peer_bucket_version,
            "category_profile": peer.category_profile,
            "admission_contract_version": peer.admission_contract_version,
            "admission_contract_sha256": peer.admission_contract_sha256,
            "snapshot_hash": peer.snapshot_hash,
            "document_hash": peer.document_hash,
            "sample_size": peer.sample_size,
            "window_basis": peer.window_basis,
            "window_months": peer.window_months,
            "window_start": peer.window_start,
            "window_end": peer.window_end,
            "capture_denominator": (
                {
                    "denominator_status": peer.capture_denominator.denominator_status,
                    "benchmark_downside_sample_count": (
                        peer.capture_denominator.benchmark_downside_sample_count
                    ),
                    "evidence_id": peer.capture_denominator.evidence_id,
                    "lineage_id": peer.capture_denominator.lineage_id,
                    "series_id": peer.capture_denominator.series_id,
                }
                if peer.capture_denominator is not None
                else None
            ),
        }
        rows.append(row)
        records.append(
            PeerAuditRecord(
                peer_id=row["peer_id"],
                metric_id=row["metric_id"],
                raw_value=row["raw_value"],
                series_id=row["series_id"],
                source_id=row["source_id"],
                lineage_id=row["lineage_id"],
                as_of=row["as_of"],
                published_at=row["published_at"],
                evaluation_timestamp=row["evaluation_timestamp"],
                peer_bucket=row["peer_bucket"],
                peer_bucket_version=row["peer_bucket_version"],
                category_profile=row["category_profile"],
                admission_contract_version=row["admission_contract_version"],
                admission_contract_sha256=row["admission_contract_sha256"],
                snapshot_hash=row["snapshot_hash"],
                document_hash=row["document_hash"],
                sample_size=peer.sample_size,
                window_basis=peer.window_basis,
                window_months=peer.window_months,
                window_start=peer.window_start,
                window_end=peer.window_end,
                capture_denominator=peer.capture_denominator,
            )
        )
    document = {
        "evaluation_timestamp": _iso_z(evaluation),
        "metric_id": metric_id,
        "peer_bucket": peer_bucket,
        "peer_bucket_version": peer_bucket_version,
        "category_profile": category_profile,
        "admission_contract_version": admission_contract_version,
        "admission_contract_sha256": admission_contract_sha256,
        "peers": rows,
    }
    return PeerSetAudit(
        metric_id=metric_id,
        peer_bucket=peer_bucket,
        peer_bucket_version=peer_bucket_version,
        category_profile=category_profile,
        admission_contract_version=admission_contract_version,
        admission_contract_sha256=admission_contract_sha256,
        evaluation_timestamp=_iso_z(evaluation),
        peer_ids=tuple(peer.peer_id for peer in ordered),
        series_ids=tuple(peer.series_id for peer in ordered),
        snapshot_hashes=tuple(peer.snapshot_hash for peer in ordered),
        records=tuple(records),
        digest=_json_digest(document),
    )


def _finite_intermediate(value: float, *, path: str) -> float:
    if not math.isfinite(value):
        _fail(
            "nonfinite_intermediate", path, "numeric scoring intermediate is not finite"
        )
    return value


def _quantile(values: tuple[float, ...], probability: float) -> float:
    position = _finite_intermediate(
        (len(values) - 1) * probability, path="$normalization.quantile.position"
    )
    lower_index = int(position)
    fraction = _finite_intermediate(
        position - lower_index, path="$normalization.quantile.fraction"
    )
    if fraction == 0:
        return _finite_intermediate(
            values[lower_index], path="$normalization.quantile.value"
        )
    difference = _finite_intermediate(
        values[lower_index + 1] - values[lower_index],
        path="$normalization.quantile.difference",
    )
    scaled = _finite_intermediate(
        fraction * difference,
        path="$normalization.quantile.scaled_difference",
    )
    return _finite_intermediate(
        values[lower_index] + scaled,
        path="$normalization.quantile.result",
    )


def _not_scored(
    observation: MetricObservation,
    *,
    direction: MetricDirection,
    peer_bucket: str,
    peer_bucket_version: str,
    formula_version: str,
    catalog_version: str,
    catalog_sha256: str,
    method: str,
) -> NormalizedMetric:
    raw = (
        _finite_number(observation.raw_value, path="$observation.raw_value")
        if observation.state is MetricState.OBSERVED
        else None
    )
    return NormalizedMetric(
        metric_id=observation.metric_id,
        fund_id=observation.fund_id,
        series_id=observation.series_id,
        evidence_id=observation.evidence_id,
        lineage_id=observation.lineage_id,
        as_of=_iso_z(observation.as_of),
        published_at=_iso_z(observation.published_at),
        evaluation_timestamp=_iso_z(observation.evaluation_timestamp),
        state=observation.state,
        raw_value=raw,
        adjusted_value=None,
        lower_bound=None,
        upper_bound=None,
        peer_sample_size=0,
        direction=direction,
        score=None,
        adjustment_method=method,
        formula_version=formula_version,
        catalog_version=catalog_version,
        catalog_sha256=catalog_sha256,
        peer_bucket=peer_bucket,
        peer_bucket_version=peer_bucket_version,
        sample_size=observation.sample_size,
        window_months=observation.window_months,
        uncertainty=observation.uncertainty,
        peer_set_digest=None,
        capture_denominator=observation.capture_denominator,
    )


def _normalize_metric(
    observation: object,
    peers: object,
    *,
    direction: object,
    peer_bucket: object,
    peer_bucket_version: object,
    profile_id: object,
    peer_admission_version: object,
    metric_catalog_version: object,
) -> NormalizedMetric:
    checked_observation = _validate_observation(observation, path="$observation")
    if type(direction) is not MetricDirection:
        _fail("invalid_direction", "$direction", "metric direction is unsupported")
    checked_bucket = _identifier(peer_bucket, path="$peer_bucket")
    checked_bucket_version = _version(peer_bucket_version, path="$peer_bucket_version")
    checked_profile = _identifier(profile_id, path="$profile_id", metric=True)
    checked_admission_version = _version(
        peer_admission_version, path="$peer_admission_version"
    )
    checked_catalog_version = _version(
        metric_catalog_version,
        path="$metric_catalog_version",
    )
    catalog, catalog_sha256 = load_metric_catalog(checked_catalog_version)
    metric_definition = next(
        (
            definition
            for metrics in catalog["profiles"]
            .get(checked_profile, {})
            .get("dimensions", {})
            .values()
            for definition in metrics
            if definition["id"] == checked_observation.metric_id
        ),
        None,
    )
    admission, admission_sha256 = load_peer_admission_contract(
        checked_admission_version
    )
    profile_admission = admission["profiles"].get(checked_profile)
    if (
        profile_admission is None
        or checked_bucket not in profile_admission["allowed_peer_buckets"]
        or profile_admission["peer_bucket_versions"].get(checked_bucket)
        != checked_bucket_version
    ):
        _fail(
            "peer_admission_mismatch",
            "$peer_bucket",
            "peer bucket is not admitted for the category profile",
        )
    contract = catalog["engine_contract"]
    formula_version = contract["formula_version"]
    if type(peers) is not tuple:
        _fail("invalid_collection", "$peers", "peers must be an immutable tuple")
    if len(peers) > contract["maximum_peer_sample"]:
        _fail("input_too_large", "$peers", "peer sample exceeds the catalog limit")
    if checked_observation.state is not MetricState.OBSERVED:
        if peers:
            _fail("unexpected_peers", "$peers", "unscored metrics must not carry peers")
        return _not_scored(
            checked_observation,
            direction=direction,
            peer_bucket=checked_bucket,
            peer_bucket_version=checked_bucket_version,
            formula_version=formula_version,
            catalog_version=checked_catalog_version,
            catalog_sha256=catalog_sha256,
            method="not_scored",
        )
    if len(peers) < contract["minimum_peer_sample"]:
        _fail(
            "insufficient_peer_sample",
            "$peers",
            "peer sample is below the catalog minimum",
        )

    peer_ids: set[tuple[str, str]] = set()
    series_ids: set[tuple[str, str]] = set()
    lineage_ids: set[tuple[str, str]] = set()
    validated_peers: list[PeerObservation] = []
    values_list: list[float] = []
    for index, item in enumerate(peers):
        peer = _validate_peer(item, path=f"$peers[{index}]")
        if peer.metric_id != checked_observation.metric_id:
            _fail(
                "unknown_peer_metric",
                f"$peers[{index}].metric_id",
                "peer metric must match the target metric",
            )
        expected_basis = (
            "point_in_time"
            if checked_observation.window_months == 0
            else "calendar_months"
        )
        if (
            peer.window_basis != expected_basis
            or peer.window_months != checked_observation.window_months
        ):
            _fail(
                "peer_window_mismatch",
                f"$peers[{index}]",
                "peer observation window must match the target metric contract",
            )
        if metric_definition is not None:
            try:
                validate_formula_cross_fields(
                    formula=metric_definition["formula"],
                    raw_value=peer.raw_value,
                    sample_size=peer.sample_size,
                    window_months=peer.window_months,
                    observation_as_of=peer.as_of,
                )
            except FormulaCrossFieldValidationError as exc:
                _fail(
                    "peer_cross_field_mismatch",
                    f"$peers[{index}]",
                    str(exc),
                )
        if peer.peer_id == checked_observation.fund_id:
            _fail(
                "subject_in_peers",
                f"$peers[{index}].peer_id",
                "target fund must not appear in peers",
            )
        _register_unique_peer_identity(
            peer,
            path=f"$peers[{index}]",
            peer_ids=peer_ids,
            series_ids=series_ids,
            lineage_ids=lineage_ids,
        )
        validated_peers.append(peer)
        values_list.append(
            _finite_number(peer.raw_value, path=f"$peers[{index}].raw_value")
        )
    peer_audit = _peer_set_audit(
        tuple(validated_peers),
        metric_id=checked_observation.metric_id,
        peer_bucket=checked_bucket,
        peer_bucket_version=checked_bucket_version,
        category_profile=checked_profile,
        admission_contract_version=checked_admission_version,
        admission_contract_sha256=admission_sha256,
        evaluation=checked_observation.evaluation_timestamp,
        path="$peers",
    )
    values = tuple(sorted(values_list))
    first_quartile = _quantile(values, 0.25)
    third_quartile = _quantile(values, 0.75)
    spread = _finite_intermediate(
        third_quartile - first_quartile,
        path="$normalization.iqr",
    )
    adjustment_method = "iqr_1.5"
    if spread <= _IQR_ZERO_TOLERANCE:
        median = _quantile(values, 0.5)
        deviations_list: list[float] = []
        for value in values:
            difference = _finite_intermediate(
                value - median,
                path="$normalization.mad.difference",
            )
            deviations_list.append(
                _finite_intermediate(
                    abs(difference), path="$normalization.mad.deviation"
                )
            )
        deviations = tuple(sorted(deviations_list))
        mad = _quantile(deviations, 0.5)
        if mad == 0:
            lower_bound = upper_bound = median
            adjustment_method = "zero_dispersion_neutral"
        else:
            robust_sigma = _finite_intermediate(
                1.4826 * mad,
                path="$normalization.mad.robust_sigma",
            )
            lower_bound = _finite_intermediate(
                median
                - _finite_intermediate(
                    3.0 * robust_sigma, path="$normalization.mad.lower_scale"
                ),
                path="$normalization.lower_bound",
            )
            upper_bound = _finite_intermediate(
                median
                + _finite_intermediate(
                    3.0 * robust_sigma, path="$normalization.mad.upper_scale"
                ),
                path="$normalization.upper_bound",
            )
            adjustment_method = "mad_3.0"
    else:
        scale = _finite_intermediate(1.5 * spread, path="$normalization.iqr.scale")
        lower_bound = _finite_intermediate(
            first_quartile - scale,
            path="$normalization.lower_bound",
        )
        upper_bound = _finite_intermediate(
            third_quartile + scale,
            path="$normalization.upper_bound",
        )
    raw_value = _finite_number(
        checked_observation.raw_value, path="$observation.raw_value"
    )
    adjusted_value = _finite_intermediate(
        min(max(raw_value, lower_bound), upper_bound),
        path="$normalization.adjusted_value",
    )
    adjusted_peers = tuple(
        _finite_intermediate(
            min(max(value, lower_bound), upper_bound),
            path="$normalization.adjusted_peer",
        )
        for value in values
    )
    below = sum(value < adjusted_value for value in adjusted_peers)
    equal = sum(value == adjusted_value for value in adjusted_peers)
    midrank = _finite_intermediate(
        below + _finite_intermediate(0.5 * equal, path="$normalization.midrank.tie"),
        path="$normalization.midrank",
    )
    percentile = _finite_intermediate(
        _finite_intermediate(
            100.0 * midrank, path="$normalization.percentile.numerator"
        )
        / len(adjusted_peers),
        path="$normalization.percentile",
    )
    normalized_score = (
        percentile
        if direction is MetricDirection.HIGHER_IS_BETTER
        else _finite_intermediate(100.0 - percentile, path="$normalization.score")
    )
    normalized_score = _finite_intermediate(
        normalized_score, path="$normalization.score"
    )
    return NormalizedMetric(
        metric_id=checked_observation.metric_id,
        fund_id=checked_observation.fund_id,
        series_id=checked_observation.series_id,
        evidence_id=checked_observation.evidence_id,
        lineage_id=checked_observation.lineage_id,
        as_of=_iso_z(checked_observation.as_of),
        published_at=_iso_z(checked_observation.published_at),
        evaluation_timestamp=_iso_z(checked_observation.evaluation_timestamp),
        state=checked_observation.state,
        raw_value=raw_value,
        adjusted_value=adjusted_value,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        peer_sample_size=len(values),
        direction=direction,
        score=normalized_score,
        adjustment_method=adjustment_method,
        formula_version=formula_version,
        catalog_version=checked_catalog_version,
        catalog_sha256=catalog_sha256,
        peer_bucket=checked_bucket,
        peer_bucket_version=checked_bucket_version,
        sample_size=checked_observation.sample_size,
        window_months=checked_observation.window_months,
        uncertainty=checked_observation.uncertainty,
        peer_set_digest=peer_audit.digest,
        capture_denominator=checked_observation.capture_denominator,
    )


def normalize_metric(
    observation: MetricObservation,
    peers: tuple[PeerObservation, ...],
    *,
    direction: MetricDirection,
    peer_bucket: str,
    peer_bucket_version: str,
    profile_id: str = "active_equity_mixed",
    peer_admission_version: str = "0.1.0",
    metric_catalog_version: str = "0.1.0",
) -> NormalizedMetric:
    """Normalize one audited raw metric using the catalog's robust contract."""
    try:
        return _normalize_metric(
            observation,
            peers,
            direction=direction,
            peer_bucket=peer_bucket,
            peer_bucket_version=peer_bucket_version,
            profile_id=profile_id,
            peer_admission_version=peer_admission_version,
            metric_catalog_version=metric_catalog_version,
        )
    except CategoryMetricError:
        raise
    except (
        MetricCatalogValidationError,
        PeerAdmissionValidationError,
        ResourceError,
        ConfigValidationError,
    ):
        _fail("resource_error", "$resource", "required scoring resource is unavailable")
    except Exception:  # noqa: BLE001 - stable public error boundary
        _fail("invalid_input", "$", "category metric input validation failed")


def _history_stage(history_months: int, adequate_regime_coverage: bool) -> HistoryStage:
    if history_months < 6:
        return HistoryStage.INSUFFICIENT
    if history_months < 12:
        return HistoryStage.OBSERVATION
    if history_months < 36 or not adequate_regime_coverage:
        return HistoryStage.PROVISIONAL
    return HistoryStage.ELIGIBLE


def _score_category_metrics(
    *,
    profile_id: object,
    peer_bucket: object,
    peer_bucket_version: object,
    peer_admission_version: object,
    history_months: object,
    adequate_regime_coverage: object,
    applicability_context: object,
    observations: object,
    peers: object,
    manager_handoff: object,
    legacy_manager_audit: object,
    evidence_ledger: object,
    legacy_manager_score: object,
    config_version: object,
    metric_catalog_version: object,
    final_precision: object,
) -> CategoryScoreResult:
    checked_profile_id = _identifier(profile_id, path="$profile_id", metric=True)
    checked_bucket = _identifier(peer_bucket, path="$peer_bucket")
    checked_bucket_version = _version(peer_bucket_version, path="$peer_bucket_version")
    checked_admission_version = _version(
        peer_admission_version, path="$peer_admission_version"
    )
    checked_config_version = _version(config_version, path="$config_version")
    checked_catalog_version = _version(
        metric_catalog_version, path="$metric_catalog_version"
    )
    checked_history = _bounded_integer(
        history_months, path="$history_months", maximum=_MAX_MONTHS
    )
    if type(adequate_regime_coverage) is not bool:
        _fail(
            "invalid_boolean",
            "$adequate_regime_coverage",
            "coverage flag must be boolean",
        )
    checked_coverage = adequate_regime_coverage
    if type(applicability_context) is not ApplicabilityContext or any(
        type(getattr(applicability_context, field)) is not bool
        for field in _APPLICABILITY_PREREQUISITE.values()
    ):
        _fail(
            "invalid_applicability_context",
            "$applicability_context",
            "conditional prerequisites require the closed typed context",
        )
    checked_precision = _bounded_integer(
        final_precision, path="$final_precision", maximum=8
    )
    if legacy_manager_score is not _LEGACY_MANAGER_UNSET:
        _fail(
            "legacy_manager_score_rejected",
            "$manager_score",
            "bare manager scores are not auditable; provide manager_handoff",
        )
    if legacy_manager_audit is not None:
        _fail(
            "legacy_manager_audit_rejected",
            "$manager_audit",
            "manager result summaries cannot authorize scoring; provide manager_handoff",
        )
    if manager_handoff is None:
        _fail(
            "manager_handoff_required",
            "$manager_handoff",
            "a recomputable manager handoff is required",
        )
    if evidence_ledger is None:
        _fail(
            "evidence_ledger_required",
            "$evidence_ledger",
            "a complete evidence ledger is required",
        )

    try:
        config_resource = resolve_resource(
            resource_type="scoring-config",
            name="openfundscore-core",
            version=checked_config_version,
        )
        config = config_resource.load_json()
        validate_score_config(config)
        catalog, catalog_sha256 = load_metric_catalog(checked_catalog_version)
        admission, admission_sha256 = load_peer_admission_contract(
            checked_admission_version
        )
    except (
        ResourceError,
        ConfigValidationError,
        MetricCatalogValidationError,
        PeerAdmissionValidationError,
    ):
        _fail("resource_error", "$resource", "required scoring resource is unavailable")
    if catalog["scoring_config"] != {
        "name": "openfundscore-core",
        "version": checked_config_version,
    }:
        _fail(
            "resource_mismatch",
            "$resource",
            "catalog and scoring config versions do not match",
        )
    if (
        checked_profile_id not in config["category_profiles"]
        or checked_profile_id not in catalog["profiles"]
        or checked_profile_id not in admission["profiles"]
    ):
        _fail(
            "unknown_profile",
            "$profile_id",
            "profile is not declared by all scoring resources",
        )
    profile_admission = admission["profiles"][checked_profile_id]
    if (
        checked_bucket not in profile_admission["allowed_peer_buckets"]
        or profile_admission["peer_bucket_versions"].get(checked_bucket)
        != checked_bucket_version
    ):
        _fail(
            "peer_admission_mismatch",
            "$peer_bucket",
            "peer bucket is not admitted for the category profile",
        )
    profile = config["category_profiles"][checked_profile_id]
    definitions = catalog["profiles"][checked_profile_id]["dimensions"]
    definition_by_id = {
        metric["id"]: (dimension, metric)
        for dimension, metrics in definitions.items()
        for metric in metrics
    }
    expected_ids = tuple(definition_by_id)
    expected_set = set(expected_ids)

    if type(observations) is not tuple:
        _fail(
            "invalid_collection",
            "$observations",
            "observations must be an immutable tuple",
        )
    if len(observations) != len(expected_ids):
        _fail(
            "observation_set_mismatch",
            "$observations",
            "every catalog metric must appear exactly once",
        )
    by_metric: dict[str, MetricObservation] = {}
    economic_signatures: set[tuple[str, str, datetime, int]] = set()
    score_fund_id: str | None = None
    evaluation: datetime | None = None
    for index, item in enumerate(observations):
        checked = _validate_observation(item, path=f"$observations[{index}]")
        if checked.metric_id not in expected_set:
            _fail(
                "unknown_observation",
                f"$observations[{index}].metric_id",
                "metric is not declared for the profile",
            )
        if checked.metric_id in by_metric:
            _fail(
                "duplicate_observation",
                f"$observations[{index}].metric_id",
                "metric observations must be unique",
            )
        if checked.window_months > checked_history:
            _fail(
                "inconsistent_window",
                f"$observations[{index}].window_months",
                "metric window exceeds fund history",
            )
        if score_fund_id is None:
            score_fund_id = checked.fund_id
            evaluation = checked.evaluation_timestamp
        elif (
            checked.fund_id != score_fund_id
            or checked.evaluation_timestamp != evaluation
        ):
            _fail(
                "target_snapshot_mismatch",
                f"$observations[{index}]",
                "all target observations must share one fund and evaluation",
            )
        dimension, definition = definition_by_id[checked.metric_id]
        applicability = definition["applicability"]
        prerequisite_field = _APPLICABILITY_PREREQUISITE.get(applicability)
        if prerequisite_field is not None:
            prerequisite = getattr(applicability_context, prerequisite_field)
            if prerequisite == (checked.state is MetricState.NOT_APPLICABLE):
                _fail(
                    "invalid_applicability",
                    f"$observations[{index}].state",
                    "conditional metric state contradicts its prerequisite fact",
                )
        if checked.state is MetricState.NOT_APPLICABLE and definition[
            "applicability"
        ] in {"required", "all_profile_funds"}:
            _fail(
                "invalid_applicability",
                f"$observations[{index}].state",
                "catalog-required metrics cannot be marked not applicable",
            )
        if checked.state is MetricState.OBSERVED:
            value_range = definition["value_range"]
            raw_input = checked.raw_value
            if raw_input is None:
                _fail(
                    "invalid_observation",
                    f"$observations[{index}].raw_value",
                    "observed metric requires a raw value",
                )
            raw = _finite_number(raw_input, path=f"$observations[{index}].raw_value")
            if not value_range["minimum"] <= raw <= value_range["maximum"]:
                _fail(
                    "metric_out_of_range",
                    f"$observations[{index}].raw_value",
                    "raw metric violates its catalog range",
                )
            window = definition["observation_window"]
            minimum_months, maximum_months = _window_month_bounds(window)
            if not minimum_months <= checked.window_months <= maximum_months:
                _fail(
                    "metric_window_mismatch",
                    f"$observations[{index}].window_months",
                    "metric history violates its catalog window",
                )
            try:
                validate_formula_cross_fields(
                    formula=definition["formula"],
                    raw_value=raw_input,
                    sample_size=checked.sample_size,
                    window_months=checked.window_months,
                    observation_as_of=checked.as_of,
                )
            except FormulaCrossFieldValidationError as exc:
                _fail(
                    "metric_cross_field_mismatch",
                    f"$observations[{index}]",
                    str(exc),
                )
            signature = (
                checked.lineage_id,
                checked.series_id,
                checked.as_of,
                checked.window_months,
            )
            if signature in economic_signatures:
                _fail(
                    "duplicate_metric_evidence",
                    f"$observations[{index}]",
                    "one economic observation cannot contribute twice",
                )
            economic_signatures.add(signature)
        by_metric[checked.metric_id] = checked
    if set(by_metric) != expected_set or score_fund_id is None or evaluation is None:
        _fail(
            "observation_set_mismatch",
            "$observations",
            "every catalog metric must appear exactly once",
        )

    if type(manager_handoff) is not ManagerResearchHandoff:
        _fail(
            "invalid_manager_handoff",
            "$manager_handoff",
            "manager input must use the closed ManagerResearchHandoff type",
        )
    if manager_handoff.fund_strategy_id != score_fund_id:
        _fail(
            "manager_target_mismatch",
            "$manager_handoff.fund_strategy_id",
            "manager handoff target must exactly match the category target",
        )
    try:
        manager_result = recompute_manager_handoff(manager_handoff)
    except ManagerResearchValidationError:
        _fail(
            "invalid_manager_handoff",
            "$manager_handoff",
            "manager handoff failed recomputation or provenance validation",
        )
    checked_manager_audit = _manager_audit(
        manager_result,
        evaluation=evaluation,
        model_version=config["model_version"],
        configured_components=config["manager_model"]["components"],
    )
    checked_manager = checked_manager_audit.score
    ledger = _ledger_snapshot(evidence_ledger)
    if (
        ledger["fund_strategy_id"] != score_fund_id
        or ledger["category_profile"] != checked_profile_id
        or ledger["model_version"] != config["model_version"]
        or _parse_timestamp_text(ledger["as_of"], path="$evidence_ledger.as_of")
        != evaluation
    ):
        _fail(
            "evidence_ledger_mismatch",
            "$evidence_ledger",
            "ledger identity must match this score",
        )
    canonical_ledger = canonicalize_score_evidence_ledger_for_digest(ledger)
    usage = canonical_ledger["usage"]
    expected_fund_usage = {
        (
            item.evidence_id,
            "primary",
            item.lineage_id,
            item.series_id,
            definition["evidence_family"],
            _FUND_LEDGER_COMPONENT[dimension],
            "current_fund",
            "raw",
            _iso_z(item.as_of),
            "point_in_time" if item.window_months == 0 else "calendar_months",
            item.window_months,
            _subtract_months(
                item.as_of.astimezone(UTC).date(), item.window_months
            ).isoformat(),
            item.as_of.astimezone(UTC).date().isoformat(),
        )
        for metric_id, item in by_metric.items()
        for dimension, definition in (definition_by_id[metric_id],)
        if item.state is MetricState.OBSERVED
    }
    actual_fund_usage = [
        (
            item["evidence_id"],
            item["evidence_role"],
            item["lineage_id"],
            item["series_id"],
            item["evidence_family"],
            item["target_component"],
            item["source_scope"],
            item["usage_mode"],
            item["observation_as_of"],
            item["window_basis"],
            item["window_months"],
            item["window_start"],
            item["window_end"],
        )
        for item in usage
        if item["target_component"] in set(_FUND_LEDGER_COMPONENT.values())
        and item["evidence_role"] == "primary"
    ]
    if Counter(actual_fund_usage) != Counter(expected_fund_usage):
        _fail(
            "evidence_ledger_fund_mismatch",
            "$evidence_ledger.usage",
            "ledger must identify every observed fund metric exactly once",
        )
    expected_manager_usage = [
        (
            item.evidence_id,
            item.evidence_role,
            item.lineage_id,
            item.series_id,
            item.source_facts_sha256,
            item.evidence_family,
            item.target_component,
            item.source_scope,
            item.usage_mode,
            item.observation_as_of,
            item.window_basis,
            item.window_months,
            item.window_start,
            item.window_end,
        )
        for item in checked_manager_audit.component_evidence
    ]
    actual_manager_usage = [
        (
            item["evidence_id"],
            item["evidence_role"],
            item["lineage_id"],
            item["series_id"],
            item["source_facts_sha256"],
            item["evidence_family"],
            item["target_component"],
            item["source_scope"],
            item["usage_mode"],
            item["observation_as_of"],
            item["window_basis"],
            item["window_months"],
            item["window_start"],
            item["window_end"],
        )
        for item in usage
        if item["target_component"] in set(_MANAGER_LEDGER_COMPONENT.values())
        and item["evidence_role"] == "primary"
    ]
    if Counter(actual_manager_usage) != Counter(expected_manager_usage):
        _fail(
            "evidence_ledger_manager_mismatch",
            "$evidence_ledger.usage",
            "ledger manager entries must match every component evidence ID exactly once",
        )
    expected_denominator_usage = [
        (
            denominator.evidence_id,
            "capture_denominator",
            denominator.benchmark_downside_sample_count,
            denominator.lineage_id,
            denominator.series_id,
            f"benchmark_downside.{item.metric_id}",
            _FUND_LEDGER_COMPONENT[dimension],
            "current_fund",
            "raw",
            _iso_z(item.as_of),
            "point_in_time" if item.window_months == 0 else "calendar_months",
            item.window_months,
            _subtract_months(
                item.as_of.astimezone(UTC).date(), item.window_months
            ).isoformat(),
            item.as_of.astimezone(UTC).date().isoformat(),
        )
        for metric_id, item in by_metric.items()
        for dimension, _ in (definition_by_id[metric_id],)
        if item.state is MetricState.OBSERVED and item.capture_denominator is not None
        for denominator in (item.capture_denominator,)
    ]
    actual_denominator_usage = [
        (
            item["evidence_id"],
            item["evidence_role"],
            item["benchmark_downside_sample_count"],
            item["lineage_id"],
            item["series_id"],
            item["evidence_family"],
            item["target_component"],
            item["source_scope"],
            item["usage_mode"],
            item["observation_as_of"],
            item["window_basis"],
            item["window_months"],
            item["window_start"],
            item["window_end"],
        )
        for item in usage
        if item["evidence_role"] == "capture_denominator"
    ]
    if Counter(actual_denominator_usage) != Counter(expected_denominator_usage):
        _fail(
            "evidence_ledger_denominator_mismatch",
            "$evidence_ledger.usage",
            "ledger must bind every observed capture denominator exactly once",
        )
    if len(usage) != (
        len(expected_fund_usage)
        + len(expected_manager_usage)
        + len(expected_denominator_usage)
    ):
        _fail(
            "evidence_ledger_mismatch",
            "$evidence_ledger.usage",
            "ledger contains evidence not consumed by this score",
        )

    if type(peers) is not tuple:
        _fail("invalid_collection", "$peers", "peers must be an immutable tuple")
    maximum_total_peers = (
        len(expected_ids) * catalog["engine_contract"]["maximum_peer_sample"]
    )
    if len(peers) > maximum_total_peers:
        _fail("input_too_large", "$peers", "peer input exceeds the catalog limit")
    peers_by_metric: dict[str, list[PeerObservation]] = {
        metric_id: [] for metric_id in expected_ids
    }
    seen_peer_keys: set[tuple[str, str]] = set()
    seen_peer_series: set[tuple[str, str]] = set()
    seen_peer_lineage: set[tuple[str, str]] = set()
    for index, item in enumerate(peers):
        checked = _validate_peer(item, path=f"$peers[{index}]")
        if checked.metric_id not in expected_set:
            _fail(
                "unknown_peer_metric",
                f"$peers[{index}].metric_id",
                "peer metric is not declared for the profile",
            )
        _register_unique_peer_identity(
            checked,
            path=f"$peers[{index}]",
            peer_ids=seen_peer_keys,
            series_ids=seen_peer_series,
            lineage_ids=seen_peer_lineage,
        )
        if checked.peer_id == by_metric[checked.metric_id].fund_id:
            _fail(
                "subject_in_peers",
                f"$peers[{index}].peer_id",
                "target fund must not appear in peers",
            )
        if by_metric[checked.metric_id].state is not MetricState.OBSERVED:
            _fail(
                "unexpected_peers",
                f"$peers[{index}]",
                "unscored metrics must not carry peers",
            )
        if (
            checked.peer_bucket != checked_bucket
            or checked.peer_bucket_version != checked_bucket_version
            or checked.category_profile != checked_profile_id
            or checked.admission_contract_version != checked_admission_version
            or checked.admission_contract_sha256 != admission_sha256
            or checked.evaluation_timestamp != evaluation
        ):
            _fail(
                "peer_snapshot_mismatch",
                f"$peers[{index}]",
                "peer bucket, profile, admission contract, and evaluation must match the score",
            )
        definition = definition_by_id[checked.metric_id][1]
        value_range = definition["value_range"]
        peer_raw = _finite_number(checked.raw_value, path=f"$peers[{index}].raw_value")
        if not value_range["minimum"] <= peer_raw <= value_range["maximum"]:
            _fail(
                "metric_out_of_range",
                f"$peers[{index}].raw_value",
                "peer metric violates its catalog range",
            )
        peers_by_metric[checked.metric_id].append(checked)
    peer_set_audits = tuple(
        _peer_set_audit(
            tuple(peers_by_metric[metric_id]),
            metric_id=metric_id,
            peer_bucket=checked_bucket,
            peer_bucket_version=checked_bucket_version,
            category_profile=checked_profile_id,
            admission_contract_version=checked_admission_version,
            admission_contract_sha256=admission_sha256,
            evaluation=evaluation,
            path=f"$peers.{metric_id}",
        )
        for metric_id in expected_ids
        if by_metric[metric_id].state is MetricState.OBSERVED
    )

    stage = _history_stage(checked_history, checked_coverage)
    metric_results: list[MetricScore] = []
    dimension_results: list[DimensionScore] = []
    missing_ids: list[str] = []
    na_ids: list[str] = []
    reasons: list[str] = []
    for dimension, dimension_weight in profile["weights"].items():
        if dimension == "manager_capability":
            manager_scaled = _finite_intermediate(
                checked_manager * dimension_weight,
                path="$dimensions.manager_capability.scaled",
            )
            contribution = _finite_intermediate(
                manager_scaled / 100.0,
                path="$dimensions.manager_capability.contribution",
            )
            dimension_results.append(
                DimensionScore(
                    dimension=dimension,
                    weight=dimension_weight,
                    status="scored",
                    score=checked_manager,
                    contribution=contribution,
                    metrics=(),
                )
            )
            continue
        scores: list[MetricScore] = []
        for definition in definitions[dimension]:
            item = by_metric[definition["id"]]
            direction = MetricDirection(definition["direction"])
            if (
                dimension == "performance_evidence"
                and checked_history < 12
                and item.state is MetricState.OBSERVED
            ):
                normalized = _not_scored(
                    item,
                    direction=direction,
                    peer_bucket=checked_bucket,
                    peer_bucket_version=checked_bucket_version,
                    formula_version=catalog["engine_contract"]["formula_version"],
                    catalog_version=checked_catalog_version,
                    catalog_sha256=catalog_sha256,
                    method="insufficient_history",
                )
            else:
                normalized = normalize_metric(
                    item,
                    tuple(peers_by_metric[definition["id"]])
                    if item.state is MetricState.OBSERVED
                    else (),
                    direction=direction,
                    peer_bucket=checked_bucket,
                    peer_bucket_version=checked_bucket_version,
                    profile_id=checked_profile_id,
                    peer_admission_version=checked_admission_version,
                    metric_catalog_version=checked_catalog_version,
                )
            minimum_months, maximum_months = _window_month_bounds(
                definition["observation_window"]
            )
            metric_score = MetricScore(
                dimension=dimension,
                weight=definition["weight"],
                core=definition["core"],
                evidence_family=definition["evidence_family"],
                formula=definition["formula"],
                formula_owner=definition["formula_owner"],
                domain=definition["domain"],
                unit=definition["unit"],
                value_minimum=definition["value_range"]["minimum"],
                value_maximum=definition["value_range"]["maximum"],
                observation_window_kind=definition["observation_window"]["kind"],
                observation_window_minimum_months=minimum_months,
                observation_window_maximum_months=maximum_months,
                applicability=definition["applicability"],
                data_source=definition["data_source"],
                normalized=normalized,
            )
            scores.append(metric_score)
            metric_results.append(metric_score)
            if item.state is MetricState.MISSING:
                missing_ids.append(item.metric_id)
            elif item.state is MetricState.NOT_APPLICABLE:
                na_ids.append(item.metric_id)
        history_blocked = dimension == "performance_evidence" and checked_history < 12
        core_blocked = any(
            metric.core and metric.normalized.score is None for metric in scores
        )
        dimension_score: float | None = None
        if not history_blocked and not core_blocked:
            dimension_score = 0.0
            for metric in scores:
                metric_value = metric.normalized.score
                if metric_value is None:
                    _fail(
                        "invalid_aggregation",
                        "$dimensions",
                        "scored dimension contains an unscored metric",
                    )
                weighted = _finite_intermediate(
                    metric_value * metric.weight / 100.0,
                    path=f"$dimensions.{dimension}.weighted_metric",
                )
                dimension_score = _finite_intermediate(
                    dimension_score + weighted,
                    path=f"$dimensions.{dimension}.score",
                )
        contribution = (
            None
            if dimension_score is None
            else _finite_intermediate(
                dimension_score * dimension_weight / 100.0,
                path=f"$dimensions.{dimension}.contribution",
            )
        )
        status = (
            "insufficient_history"
            if history_blocked
            else "insufficient"
            if core_blocked
            else "scored"
        )
        dimension_results.append(
            DimensionScore(
                dimension=dimension,
                weight=dimension_weight,
                status=status,
                score=dimension_score,
                contribution=contribution,
                metrics=tuple(scores),
            )
        )
    if missing_ids:
        reasons.append("core_metric_missing")
    if na_ids:
        reasons.append("core_metric_not_applicable")
    if checked_history < 6:
        reasons.append("history_under_6_months")
    elif checked_history < 12:
        reasons.append("performance_history_under_12_months")
    elif checked_history >= 36 and not checked_coverage:
        reasons.append("adequate_regime_coverage_not_confirmed")

    insufficient_dimensions = tuple(
        item.dimension for item in dimension_results if item.score is None
    )
    can_score = (
        stage not in {HistoryStage.INSUFFICIENT, HistoryStage.OBSERVATION}
        and not insufficient_dimensions
    )
    open_score: float | None = None
    if can_score:
        total = 0.0
        for item in dimension_results:
            if item.contribution is None:
                _fail(
                    "invalid_aggregation",
                    "$score",
                    "scored result contains an unscored contribution",
                )
            total = _finite_intermediate(total + item.contribution, path="$score.total")
        open_score = _finite_intermediate(
            round(total, checked_precision), path="$score.open_score"
        )
    confidence = (
        "medium"
        if stage is HistoryStage.ELIGIBLE and can_score
        else "low"
        if stage is HistoryStage.PROVISIONAL and can_score
        else "insufficient"
    )
    if confidence != "insufficient" and checked_manager_audit.confidence == "low":
        confidence = "low"
    return CategoryScoreResult(
        profile_id=checked_profile_id,
        fund_strategy_id=score_fund_id,
        as_of=_iso_z(evaluation),
        model_version=config["model_version"],
        formula_version=catalog["engine_contract"]["formula_version"],
        config_version=checked_config_version,
        config_sha256=config_resource.info.sha256,
        catalog_version=checked_catalog_version,
        catalog_sha256=catalog_sha256,
        peer_bucket=checked_bucket,
        peer_bucket_version=checked_bucket_version,
        peer_admission_version=checked_admission_version,
        peer_admission_sha256=admission_sha256,
        history_months=checked_history,
        adequate_regime_coverage=checked_coverage,
        history_stage=stage,
        status="scored" if open_score is not None else "insufficient",
        confidence=confidence,
        open_score=open_score,
        manager_score=checked_manager,
        manager_audit=checked_manager_audit,
        evidence_ledger_record_id=ledger["score_record_id"],
        evidence_ledger_sha256=_json_digest(canonical_ledger),
        peer_sets=peer_set_audits,
        dimensions=tuple(dimension_results),
        metrics=tuple(metric_results),
        insufficient_dimensions=insufficient_dimensions,
        missing_metric_ids=tuple(missing_ids),
        not_applicable_metric_ids=tuple(na_ids),
        insufficiency_reasons=tuple(dict.fromkeys(reasons)),
    )


def score_category_metrics(
    *,
    profile_id: str,
    peer_bucket: str,
    peer_bucket_version: str,
    peer_admission_version: str = "0.1.0",
    history_months: int,
    adequate_regime_coverage: bool,
    applicability_context: ApplicabilityContext | None = None,
    observations: tuple[MetricObservation, ...],
    peers: tuple[PeerObservation, ...],
    manager_handoff: ManagerResearchHandoff | None = None,
    manager_audit: ManagerScoreAudit | Mapping[str, Any] | None = None,
    evidence_ledger: Mapping[str, Any] | None = None,
    manager_score: object = _LEGACY_MANAGER_UNSET,
    config_version: str = "0.1.0",
    metric_catalog_version: str = "0.1.0",
    final_precision: int = 2,
) -> CategoryScoreResult:
    """Score audited category inputs with manager and evidence-ledger closure.

    ``evidence_ledger`` must satisfy ``score_evidence_usage@0.2.0``. The legacy
    0.1.0 Schema remains independently valid but is not a category-score input.
    """
    try:
        return _score_category_metrics(
            profile_id=profile_id,
            peer_bucket=peer_bucket,
            peer_bucket_version=peer_bucket_version,
            peer_admission_version=peer_admission_version,
            history_months=history_months,
            adequate_regime_coverage=adequate_regime_coverage,
            applicability_context=applicability_context,
            observations=observations,
            peers=peers,
            manager_handoff=manager_handoff,
            legacy_manager_audit=manager_audit,
            evidence_ledger=evidence_ledger,
            legacy_manager_score=manager_score,
            config_version=config_version,
            metric_catalog_version=metric_catalog_version,
            final_precision=final_precision,
        )
    except CategoryMetricError:
        raise
    except Exception:  # noqa: BLE001 - stable public error boundary
        _fail("invalid_input", "$", "category score input validation failed")
