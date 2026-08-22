"""Immutable point-in-time walk-forward research harness.

The scorer boundary deliberately contains no future-outcome object. Outcome data
is joined only after selections have been frozen by the evaluation harness.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime, timedelta
from itertools import pairwise
from typing import NoReturn, TypeAlias, cast

SnapshotValue: TypeAlias = str | int | float | bool | None
_REQUIRED_DOMAINS = frozenset(
    {"classification", "benchmark", "manager", "fee_bps", "availability"}
)
_MAX_INPUT_ITEMS = 100_000
_MAX_OUTCOME_PERIODS = 256
_MAX_SIMPLE_RETURN = 1.0
_MAX_IDENTIFIER_LENGTH = 256
_MAX_TEXT_LENGTH = 4_096
_MAX_ABS_SCALAR = 1e308


class WalkForwardError(ValueError):
    """Stable, redacted validation or evaluation failure."""

    def __init__(self, *, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        super().__init__(f"{path}: {code}: {message}")


def _fail(code: str, path: str, message: str) -> NoReturn:
    raise WalkForwardError(code=code, path=path, message=message)


def _non_empty(value: object, path: str) -> None:
    if not isinstance(value, str) or not value.strip():
        _fail("invalid_identifier", path, "identifier must be a non-empty string")
    if len(value) > _MAX_IDENTIFIER_LENGTH:
        _fail("invalid_identifier", path, "identifier exceeds the length limit")


def _aware(value: object, path: str) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        _fail("timezone_required", path, "timestamp must include a timezone")


def _finite_number(value: object, path: str, *, code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(code, path, "value must be a finite number and not boolean")
    try:
        numeric = float(value)
    except (OverflowError, ValueError):
        _fail(code, path, "value must be a finite number and not boolean")
    if not math.isfinite(numeric) or abs(numeric) > _MAX_ABS_SCALAR:
        _fail(code, path, "value must be a finite number and not boolean")
    return numeric


def _derived_number(value: float, path: str) -> float:
    if not math.isfinite(value):
        _fail("calculation_overflow", path, "derived calculation is not finite")
    return value


def _safe_sum(values: tuple[float, ...], path: str) -> float:
    total = 0.0
    for value in values:
        total = _derived_number(total + value, path)
    return total


def _safe_mean(values: tuple[float, ...], path: str) -> float | None:
    if not values:
        return None
    return _derived_number(_safe_sum(values, path) / len(values), path)


def _safe_subtract(left: float, right: float, path: str) -> float:
    return _derived_number(left - right, path)


def _safe_multiply(left: float, right: float, path: str) -> float:
    return _derived_number(left * right, path)


@dataclass(frozen=True, slots=True, kw_only=True)
class LifecycleInterval:
    status: str
    effective_from: datetime
    published_at: datetime
    knowledge_at: datetime
    effective_to: datetime | None = None
    successor_strategy_id: str | None = None
    revision_id: str = "original"
    supersedes_revision_id: str | None = None

    def __post_init__(self) -> None:
        _non_empty(self.revision_id, "$.lifecycle.revision_id")
        if self.supersedes_revision_id is not None:
            _non_empty(
                self.supersedes_revision_id,
                "$.lifecycle.supersedes_revision_id",
            )
            if self.supersedes_revision_id == self.revision_id:
                _fail(
                    "revision_chain_conflict",
                    "$.lifecycle.supersedes_revision_id",
                    "a revision cannot supersede itself",
                )
        if not isinstance(self.status, str) or self.status not in {
            "active",
            "closed",
            "merged",
            "transformed",
        }:
            _fail("invalid_lifecycle", "$.lifecycle.status", "status is unsupported")
        _aware(self.effective_from, "$.lifecycle.effective_from")
        _aware(self.published_at, "$.lifecycle.published_at")
        _aware(self.knowledge_at, "$.lifecycle.knowledge_at")
        if self.published_at > self.knowledge_at:
            _fail("lifecycle_chronology", "$.lifecycle", "chronology is invalid")
        if self.effective_to is not None:
            _aware(self.effective_to, "$.lifecycle.effective_to")
            if self.effective_from >= self.effective_to:
                _fail("lifecycle_order", "$.lifecycle", "interval is invalid")
        if self.status in {"merged", "transformed"}:
            _non_empty(self.successor_strategy_id, "$.lifecycle.successor_strategy_id")
        elif self.successor_strategy_id is not None:
            _fail(
                "invalid_lifecycle",
                "$.lifecycle.successor_strategy_id",
                "successor is not allowed for this status",
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class CandidateFund:
    share_class_id: str
    strategy_id: str
    inception_at: datetime
    lifecycle: tuple[LifecycleInterval, ...]

    def __post_init__(self) -> None:
        _non_empty(self.share_class_id, "$.candidate.share_class_id")
        _non_empty(self.strategy_id, "$.candidate.strategy_id")
        _aware(self.inception_at, "$.candidate.inception_at")
        if type(self.lifecycle) is not tuple or not self.lifecycle:
            _fail(
                "invalid_container",
                "$.candidate.lifecycle",
                "lifecycle must be a tuple",
            )
        if len(self.lifecycle) > _MAX_INPUT_ITEMS:
            _fail(
                "input_too_large",
                "$.candidate.lifecycle",
                "lifecycle exceeds the size limit",
            )
        if any(type(item) is not LifecycleInterval for item in self.lifecycle):
            _fail("invalid_type", "$.candidate.lifecycle", "lifecycle entry is invalid")
        ordered = tuple(
            sorted(
                self.lifecycle,
                key=lambda item: (
                    item.effective_from,
                    item.published_at,
                    item.knowledge_at,
                    item.status,
                    item.revision_id,
                ),
            )
        )
        if ordered != self.lifecycle:
            _fail(
                "lifecycle_order", "$.candidate.lifecycle", "intervals must be sorted"
            )
        if len(ordered) != len(set(ordered)):
            _fail(
                "duplicate_lifecycle",
                "$.candidate.lifecycle",
                "lifecycle records repeat",
            )
        groups: dict[
            tuple[datetime, datetime | None],
            list[LifecycleInterval],
        ] = {}
        for item in ordered:
            groups.setdefault((item.effective_from, item.effective_to), []).append(item)
        for group in groups.values():
            by_revision = {item.revision_id: item for item in group}
            if len(by_revision) != len(group):
                _fail(
                    "revision_chain_conflict",
                    "$.candidate.lifecycle",
                    "revision identifiers repeat within one economic record",
                )
            roots = [item for item in group if item.supersedes_revision_id is None]
            children: dict[str, list[LifecycleInterval]] = {}
            for item in group:
                if item.supersedes_revision_id is None:
                    continue
                parent = by_revision.get(item.supersedes_revision_id)
                if parent is None:
                    _fail(
                        "revision_chain_conflict",
                        "$.candidate.lifecycle",
                        "a superseded revision is missing or belongs to another record",
                    )
                    continue
                if (
                    item.published_at < parent.published_at
                    or item.knowledge_at <= parent.knowledge_at
                ):
                    _fail(
                        "revision_chronology",
                        "$.candidate.lifecycle",
                        "a revision cannot supersede a future or equally-known revision",
                    )
                children.setdefault(parent.revision_id, []).append(item)
            if len(roots) != 1 or any(len(items) != 1 for items in children.values()):
                _fail(
                    "revision_chain_conflict",
                    "$.candidate.lifecycle",
                    "revisions must form one unbranched chain",
                )
            visited: set[str] = set()
            current: LifecycleInterval | None = roots[0]
            while current is not None and current.revision_id not in visited:
                visited.add(current.revision_id)
                next_items = children.get(current.revision_id, [])
                current = next_items[0] if next_items else None
            if len(visited) != len(group):
                _fail(
                    "revision_chain_conflict",
                    "$.candidate.lifecycle",
                    "revisions must form one complete acyclic chain",
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class VersionedSnapshot:
    snapshot_id: str
    provider_id: str
    provider_snapshot_id: str
    provider_version: str
    strategy_id: str
    domain: str
    value: SnapshotValue
    as_of: datetime
    published_at: datetime
    knowledge_at: datetime
    effective_from: datetime
    effective_to: datetime | None = None
    revision_id: str = "original"
    supersedes_revision_id: str | None = None

    def __post_init__(self) -> None:
        for path, value in (
            ("$.snapshot.snapshot_id", self.snapshot_id),
            ("$.snapshot.provider_id", self.provider_id),
            ("$.snapshot.provider_snapshot_id", self.provider_snapshot_id),
            ("$.snapshot.provider_version", self.provider_version),
            ("$.snapshot.strategy_id", self.strategy_id),
            ("$.snapshot.revision_id", self.revision_id),
        ):
            _non_empty(value, path)
        if self.supersedes_revision_id is not None:
            _non_empty(
                self.supersedes_revision_id,
                "$.snapshot.supersedes_revision_id",
            )
            if self.supersedes_revision_id == self.revision_id:
                _fail(
                    "revision_chain_conflict",
                    "$.snapshot.supersedes_revision_id",
                    "a revision cannot supersede itself",
                )
        if not isinstance(self.domain, str) or (
            self.domain not in _REQUIRED_DOMAINS
            and not self.domain.startswith("feature:")
        ):
            _fail("unknown_domain", "$.snapshot.domain", "domain is unsupported")
        if len(self.domain) > _MAX_IDENTIFIER_LENGTH:
            _fail(
                "invalid_identifier",
                "$.snapshot.domain",
                "domain exceeds the length limit",
            )
        for path, value in (
            ("$.snapshot.as_of", self.as_of),
            ("$.snapshot.published_at", self.published_at),
            ("$.snapshot.knowledge_at", self.knowledge_at),
            ("$.snapshot.effective_from", self.effective_from),
        ):
            _aware(value, path)
        if self.effective_to is not None:
            _aware(self.effective_to, "$.snapshot.effective_to")
            if self.effective_from >= self.effective_to:
                _fail(
                    "snapshot_chronology",
                    "$.snapshot.effective_from",
                    "interval is invalid",
                )
        if not self.as_of <= self.published_at <= self.knowledge_at:
            _fail("snapshot_chronology", "$.snapshot.as_of", "chronology is invalid")
        if type(self.value) not in {str, int, float, bool, type(None)}:
            _fail("invalid_snapshot_value", "$.snapshot.value", "value must be scalar")
        if isinstance(self.value, (int, float)) and not isinstance(self.value, bool):
            _finite_number(
                self.value,
                "$.snapshot.value",
                code="invalid_snapshot_value",
            )
        if isinstance(self.value, str) and len(self.value) > _MAX_TEXT_LENGTH:
            _fail(
                "invalid_snapshot_value",
                "$.snapshot.value",
                "text value exceeds the length limit",
            )
        if self.domain == "availability" and type(self.value) not in {bool, type(None)}:
            _fail(
                "invalid_snapshot_value", "$.snapshot.value", "availability is invalid"
            )
        if (
            self.domain in {"classification", "benchmark", "manager"}
            and self.value is not None
            and (not isinstance(self.value, str) or not self.value.strip())
        ):
            _fail("invalid_snapshot_value", "$.snapshot.value", "text value is invalid")
        if self.domain == "fee_bps" and self.value is not None:
            fee = _finite_number(
                self.value,
                "$.snapshot.value",
                code="invalid_snapshot_value",
            )
            if not 0.0 <= fee <= 100_000.0:
                _fail("invalid_snapshot_value", "$.snapshot.value", "fee is invalid")


@dataclass(frozen=True, slots=True, kw_only=True)
class ScoreComponent:
    """One named additive contribution to a total score."""

    name: str
    contribution: float | None
    component_version: str

    def __post_init__(self) -> None:
        _non_empty(self.name, "$.score.components.name")
        _non_empty(self.component_version, "$.score.components.component_version")
        if self.contribution is not None:
            _finite_number(
                self.contribution,
                "$.score.components.contribution",
                code="invalid_component",
            )


def _validate_score_components(
    total_score: object,
    components: object,
    *,
    path: str,
) -> None:
    total = _finite_number(total_score, f"{path}.total_score", code="invalid_score")
    if type(components) is not tuple or not components:
        _fail(
            "invalid_components", f"{path}.components", "components must be non-empty"
        )
    typed_components = cast(tuple[ScoreComponent, ...], components)
    if len(typed_components) > _MAX_INPUT_ITEMS:
        _fail(
            "input_too_large", f"{path}.components", "components exceed the size limit"
        )
    if any(type(item) is not ScoreComponent for item in typed_components):
        _fail("invalid_components", f"{path}.components", "component entry is invalid")
    names = tuple(item.name for item in typed_components)
    if len(names) != len(set(names)):
        _fail(
            "duplicate_component",
            f"{path}.components",
            "component names must be unique",
        )
    contributions = tuple(
        float(item.contribution)
        for item in typed_components
        if item.contribution is not None
    )
    if len(contributions) == len(typed_components):
        contribution_total = _safe_sum(contributions, f"{path}.components")
        if not math.isclose(
            contribution_total,
            total,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            _fail(
                "component_sum_mismatch",
                f"{path}.components",
                "complete component contributions must sum to total score",
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ScoreResult:
    """Auditable callback result containing total and additive components."""

    total_score: float
    components: tuple[ScoreComponent, ...]
    model_version: str
    provider_id: str
    provider_snapshot_id: str
    provider_version: str
    score_as_of: datetime
    published_at: datetime
    knowledge_at: datetime
    strategy_id: str | None = None
    audit_id: str = "callback-score"
    revision_id: str = "original"
    supersedes_revision_id: str | None = None

    def __post_init__(self) -> None:
        _validate_score_components(self.total_score, self.components, path="$.score")
        if self.strategy_id is not None:
            _non_empty(self.strategy_id, "$.score.strategy_id")
        for path, value in (
            ("$.score.audit_id", self.audit_id),
            ("$.score.revision_id", self.revision_id),
            ("$.score.model_version", self.model_version),
            ("$.score.provider_id", self.provider_id),
            ("$.score.provider_snapshot_id", self.provider_snapshot_id),
            ("$.score.provider_version", self.provider_version),
        ):
            _non_empty(value, path)
        if self.supersedes_revision_id is not None:
            _non_empty(
                self.supersedes_revision_id,
                "$.score.supersedes_revision_id",
            )
            if self.supersedes_revision_id == self.revision_id:
                _fail(
                    "revision_chain_conflict",
                    "$.score.supersedes_revision_id",
                    "a revision cannot supersede itself",
                )
        for path, value in (
            ("$.score.score_as_of", self.score_as_of),
            ("$.score.published_at", self.published_at),
            ("$.score.knowledge_at", self.knowledge_at),
        ):
            _aware(value, path)
        if not self.score_as_of <= self.published_at <= self.knowledge_at:
            _fail("score_chronology", "$.score.score_as_of", "chronology is invalid")


@dataclass(frozen=True, slots=True, kw_only=True)
class PrecomputedScore:
    score_id: str
    strategy_id: str
    total_score: float
    components: tuple[ScoreComponent, ...]
    model_version: str
    provider_id: str
    provider_snapshot_id: str
    provider_version: str
    score_as_of: datetime
    published_at: datetime
    knowledge_at: datetime
    effective_from: datetime
    effective_to: datetime | None = None
    revision_id: str = "original"
    supersedes_revision_id: str | None = None

    def __post_init__(self) -> None:
        for path, value in (
            ("$.score.score_id", self.score_id),
            ("$.score.strategy_id", self.strategy_id),
            ("$.score.model_version", self.model_version),
            ("$.score.provider_id", self.provider_id),
            ("$.score.provider_snapshot_id", self.provider_snapshot_id),
            ("$.score.provider_version", self.provider_version),
            ("$.score.revision_id", self.revision_id),
        ):
            _non_empty(value, path)
        if self.supersedes_revision_id is not None:
            _non_empty(
                self.supersedes_revision_id,
                "$.score.supersedes_revision_id",
            )
            if self.supersedes_revision_id == self.revision_id:
                _fail(
                    "revision_chain_conflict",
                    "$.score.supersedes_revision_id",
                    "a revision cannot supersede itself",
                )
        _validate_score_components(self.total_score, self.components, path="$.score")
        for path, value in (
            ("$.score.score_as_of", self.score_as_of),
            ("$.score.published_at", self.published_at),
            ("$.score.knowledge_at", self.knowledge_at),
            ("$.score.effective_from", self.effective_from),
        ):
            _aware(value, path)
        if self.effective_to is not None:
            _aware(self.effective_to, "$.score.effective_to")
            if self.effective_from >= self.effective_to:
                _fail(
                    "score_chronology", "$.score.effective_from", "interval is invalid"
                )
        if not self.score_as_of <= self.published_at <= self.knowledge_at:
            _fail("score_chronology", "$.score.score_as_of", "chronology is invalid")

    def as_score_result(self) -> ScoreResult:
        """Return the common immutable audit shape used by diagnostics."""
        return ScoreResult(
            strategy_id=self.strategy_id,
            audit_id=self.score_id,
            revision_id=self.revision_id,
            supersedes_revision_id=self.supersedes_revision_id,
            total_score=self.total_score,
            components=self.components,
            model_version=self.model_version,
            provider_id=self.provider_id,
            provider_snapshot_id=self.provider_snapshot_id,
            provider_version=self.provider_version,
            score_as_of=self.score_as_of,
            published_at=self.published_at,
            knowledge_at=self.knowledge_at,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class FoldWindow:
    fold_id: str
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    decision_at: datetime
    outcome_start: datetime
    outcome_end: datetime
    embargo_seconds: int

    def __post_init__(self) -> None:
        _non_empty(self.fold_id, "$.fold.fold_id")
        values = (
            self.train_start,
            self.train_end,
            self.validation_start,
            self.validation_end,
            self.decision_at,
            self.outcome_start,
            self.outcome_end,
        )
        for index, value in enumerate(values):
            _aware(value, f"$.fold.timestamps[{index}]")
        if not (
            self.train_start
            <= self.train_end
            < self.validation_start
            <= self.validation_end
            < self.decision_at
            < self.outcome_start
            <= self.outcome_end
        ):
            _fail("window_order", "$.fold", "windows must be chronological")
        if (
            isinstance(self.embargo_seconds, bool)
            or not isinstance(self.embargo_seconds, int)
            or self.embargo_seconds < 0
        ):
            _fail("invalid_embargo", "$.fold.embargo_seconds", "embargo is invalid")
        try:
            embargo_end = self.decision_at + timedelta(seconds=self.embargo_seconds)
        except OverflowError:
            _fail("invalid_embargo", "$.fold.embargo_seconds", "embargo is invalid")
        if embargo_end > self.outcome_start:
            _fail(
                "embargo_violation", "$.fold.outcome_start", "embargo is not satisfied"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkForwardConfig:
    folds: tuple[FoldWindow, ...]
    select_count: int

    def __post_init__(self) -> None:
        if type(self.folds) is not tuple or not self.folds:
            _fail(
                "invalid_container", "$.config.folds", "folds must be a non-empty tuple"
            )
        if len(self.folds) > _MAX_INPUT_ITEMS:
            _fail("input_too_large", "$.config.folds", "folds exceed the size limit")
        if any(type(item) is not FoldWindow for item in self.folds):
            _fail("invalid_type", "$.config.folds", "fold entry is invalid")
        if (
            isinstance(self.select_count, bool)
            or not isinstance(self.select_count, int)
            or self.select_count < 1
        ):
            _fail(
                "invalid_select_count",
                "$.config.select_count",
                "selection size is invalid",
            )
        decisions = tuple(item.decision_at for item in self.folds)
        if len(decisions) != len(set(decisions)):
            _fail("duplicate_decision", "$.config.folds", "decisions must be unique")
        if decisions != tuple(sorted(decisions)):
            _fail("window_order", "$.config.folds", "folds must be time sorted")
        identifiers = tuple(item.fold_id for item in self.folds)
        if len(identifiers) != len(set(identifiers)):
            _fail(
                "duplicate_entity", "$.config.folds", "fold identifiers must be unique"
            )
        for previous, current in pairwise(self.folds):
            if current.outcome_start <= previous.outcome_end:
                _fail(
                    "overlapping_outcome_window",
                    "$.config.folds",
                    "outcome windows must not overlap",
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class ScoringView:
    strategy_id: str
    decision_at: datetime
    fold: FoldWindow
    snapshots: tuple[VersionedSnapshot, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class FutureOutcome:
    """Future data that is visible only to the post-selection evaluator."""

    outcome_id: str
    strategy_id: str
    window_start: datetime
    window_end: datetime
    period_returns: tuple[float, ...]
    peer_period_returns: tuple[float, ...]

    def __post_init__(self) -> None:
        _non_empty(self.outcome_id, "$.outcome.outcome_id")
        _non_empty(self.strategy_id, "$.outcome.strategy_id")
        _aware(self.window_start, "$.outcome.window_start")
        _aware(self.window_end, "$.outcome.window_end")
        if self.window_start > self.window_end:
            _fail("window_order", "$.outcome", "outcome window is reversed")
        if (
            type(self.period_returns) is not tuple
            or type(self.peer_period_returns) is not tuple
            or not self.period_returns
            or len(self.period_returns) != len(self.peer_period_returns)
            or len(self.period_returns) > _MAX_OUTCOME_PERIODS
        ):
            _fail("invalid_outcome", "$.outcome.returns", "return series are invalid")
        for path, values in (
            ("$.outcome.period_returns", self.period_returns),
            ("$.outcome.peer_period_returns", self.peer_period_returns),
        ):
            for value in values:
                numeric = _finite_number(value, path, code="invalid_outcome")
                if not -1.0 <= numeric <= _MAX_SIMPLE_RETURN:
                    _fail(
                        "invalid_outcome",
                        path,
                        "simple return is outside the supported range",
                    )


@dataclass(frozen=True, slots=True, kw_only=True)
class FoldFailure:
    code: str
    strategy_id: str
    detail: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Coverage:
    complete: int
    total: int
    ratio: float


@dataclass(frozen=True, slots=True, kw_only=True)
class ComponentCoverage:
    component_name: str
    component_versions: tuple[str, ...]
    sample_size: int
    missing_count: int
    total_count: int
    status: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ComponentCorrelation:
    left_component: str
    right_component: str
    method: str
    sample_size: int
    status: str
    value: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ComponentDiagnostics:
    coverage: tuple[ComponentCoverage, ...]
    correlations: tuple[ComponentCorrelation, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class Metric:
    metric: str
    status: str
    value: float | None
    sample_size: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Uncertainty:
    status: str
    sample_size: int
    confidence_level: float | None
    lower: float | None
    upper: float | None
    method: str


@dataclass(frozen=True, slots=True, kw_only=True)
class OutcomeEvaluation:
    status: str
    mean_peer_relative_return: float | None
    evaluated_count: int
    uncertainty: Uncertainty


@dataclass(frozen=True, slots=True, kw_only=True)
class WealthMetrics:
    wealth_curve: tuple[float, ...]
    max_drawdown: float
    recovery_status: str
    recovery_periods: int | None


@dataclass(frozen=True, slots=True, kw_only=True)
class SensitivityScenario:
    omitted_component: str
    method: str
    status: str
    baseline_selected_strategy_ids: tuple[str, ...]
    perturbed_selected_strategy_ids: tuple[str, ...]
    baseline_ranks: tuple[tuple[str, float], ...]
    perturbed_ranks: tuple[tuple[str, float], ...]
    selection_turnover: Metric
    rank_correlation: Metric
    selected_mean_score_delta: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class SensitivityDiagnostics:
    definition: str
    scenarios: tuple[SensitivityScenario, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class SummarySensitivity:
    component_name: str
    method: str
    status: str
    fold_count: int
    mean_selection_turnover: float | None
    mean_rank_correlation: float | None
    mean_selected_score_delta: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class FoldReport:
    fold_id: str
    decision_at: datetime
    universe_count: int
    eligible_count: int
    selected_count: int
    selected_strategy_ids: tuple[str, ...]
    score_source: str
    audit_score_ids: tuple[tuple[str, str, str], ...]
    score_audit_trail: tuple[ScoreResult, ...]
    selection_breadth: tuple[tuple[str, int], ...]
    score_stability: Metric
    selection_turnover: Metric
    outcome: OutcomeEvaluation
    wealth: WealthMetrics
    audit_snapshot_ids: tuple[str, ...]
    audit_trail: tuple[VersionedSnapshot, ...]
    audit_lifecycle: tuple[tuple[str, LifecycleInterval], ...]
    retained_terminal_count: int
    failures: tuple[FoldFailure, ...]
    coverage: Coverage
    component_diagnostics: ComponentDiagnostics
    sensitivity: SensitivityDiagnostics


@dataclass(frozen=True, slots=True, kw_only=True)
class SummaryReport:
    fold_count: int
    mean_score_stability: float | None
    mean_selection_turnover: float | None
    mean_peer_relative_return: float | None
    uncertainty: Uncertainty
    wealth: WealthMetrics
    component_diagnostics: ComponentDiagnostics
    sensitivity: tuple[SummarySensitivity, ...]
    disclaimer: str


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkForwardReport:
    folds: tuple[FoldReport, ...]
    summary: SummaryReport


def _validate_report_finite(value: object) -> None:
    stack = [value]
    while stack:
        item = stack.pop()
        if type(item) is float:
            _derived_number(cast(float, item), "$.report")
        elif isinstance(item, tuple):
            stack.extend(item)
        elif is_dataclass(item) and not isinstance(item, type):
            stack.extend(getattr(item, field.name) for field in fields(item))


ScoreCallback: TypeAlias = Callable[[ScoringView], ScoreResult | None]


def _score_covers_provider_time(
    score: ScoreResult | PrecomputedScore,
    snapshots: tuple[VersionedSnapshot, ...],
) -> bool:
    return (
        score.score_as_of >= max(item.as_of for item in snapshots)
        and score.published_at >= max(item.published_at for item in snapshots)
        and score.knowledge_at >= max(item.knowledge_at for item in snapshots)
    )


def _effective(snapshot: VersionedSnapshot, decision: datetime) -> bool:
    return snapshot.effective_from <= decision and (
        snapshot.effective_to is None or decision < snapshot.effective_to
    )


def _validate_snapshot_revision_groups(
    records: tuple[VersionedSnapshot, ...],
) -> None:
    groups: dict[
        tuple[str, str, datetime, datetime | None],
        list[VersionedSnapshot],
    ] = {}
    for item in records:
        key = (item.strategy_id, item.domain, item.effective_from, item.effective_to)
        groups.setdefault(key, []).append(item)
    for group in groups.values():
        by_revision = {item.revision_id: item for item in group}
        if len(by_revision) != len(group):
            _fail(
                "revision_chain_conflict",
                "$.snapshots",
                "revision identifiers repeat within one economic record",
            )
        children: dict[str, list[str]] = {}
        roots: list[str] = []
        for item in group:
            parent_id = item.supersedes_revision_id
            if parent_id is None:
                roots.append(item.revision_id)
                continue
            parent = by_revision.get(parent_id)
            if parent is None:
                _fail(
                    "revision_chain_conflict",
                    "$.snapshots",
                    "a superseded revision is missing or belongs to another record",
                )
                continue
            if (
                item.published_at < parent.published_at
                or item.knowledge_at <= parent.knowledge_at
            ):
                _fail(
                    "revision_chronology",
                    "$.snapshots",
                    "a revision cannot supersede a future or equally-known revision",
                )
            children.setdefault(parent_id, []).append(item.revision_id)
        if len(roots) != 1 or any(len(items) != 1 for items in children.values()):
            _fail(
                "revision_chain_conflict",
                "$.snapshots",
                "revisions must form one unbranched chain",
            )
        visited: set[str] = set()
        current: str | None = roots[0]
        while current is not None and current not in visited:
            visited.add(current)
            next_items = children.get(current, [])
            current = next_items[0] if next_items else None
        if len(visited) != len(group):
            _fail(
                "revision_chain_conflict",
                "$.snapshots",
                "revisions must form one complete acyclic chain",
            )


def _resolve_snapshot_revisions(
    records: tuple[VersionedSnapshot, ...],
) -> tuple[VersionedSnapshot, ...]:
    groups: dict[
        tuple[str, str, datetime, datetime | None],
        list[VersionedSnapshot],
    ] = {}
    for item in records:
        groups.setdefault(
            (item.strategy_id, item.domain, item.effective_from, item.effective_to),
            [],
        ).append(item)
    resolved: list[VersionedSnapshot] = []
    for group in groups.values():
        superseded = {
            item.supersedes_revision_id
            for item in group
            if item.supersedes_revision_id is not None
        }
        resolved.extend(item for item in group if item.revision_id not in superseded)
    return tuple(resolved)


def _validate_score_revision_groups(records: tuple[PrecomputedScore, ...]) -> None:
    groups: dict[
        tuple[str, datetime, datetime | None],
        list[PrecomputedScore],
    ] = {}
    for item in records:
        groups.setdefault(
            (item.strategy_id, item.effective_from, item.effective_to), []
        ).append(item)
    for group in groups.values():
        by_revision = {item.revision_id: item for item in group}
        if len(by_revision) != len(group):
            _fail(
                "revision_chain_conflict",
                "$.precomputed_scores",
                "revision identifiers repeat within one economic record",
            )
        roots = [item for item in group if item.supersedes_revision_id is None]
        children: dict[str, list[PrecomputedScore]] = {}
        for item in group:
            if item.supersedes_revision_id is None:
                continue
            parent = by_revision.get(item.supersedes_revision_id)
            if parent is None:
                _fail(
                    "revision_chain_conflict",
                    "$.precomputed_scores",
                    "a superseded revision is missing or belongs to another record",
                )
                continue
            if (
                item.published_at < parent.published_at
                or item.knowledge_at <= parent.knowledge_at
            ):
                _fail(
                    "revision_chronology",
                    "$.precomputed_scores",
                    "a revision cannot supersede a future or equally-known revision",
                )
            children.setdefault(parent.revision_id, []).append(item)
        if len(roots) != 1 or any(len(items) != 1 for items in children.values()):
            _fail(
                "revision_chain_conflict",
                "$.precomputed_scores",
                "revisions must form one unbranched chain",
            )
        visited: set[str] = set()
        current: PrecomputedScore | None = roots[0]
        while current is not None and current.revision_id not in visited:
            visited.add(current.revision_id)
            next_items = children.get(current.revision_id, [])
            current = next_items[0] if next_items else None
        if len(visited) != len(group):
            _fail(
                "revision_chain_conflict",
                "$.precomputed_scores",
                "revisions must form one complete acyclic chain",
            )


def _resolve_score_revisions(
    records: tuple[PrecomputedScore, ...],
) -> tuple[PrecomputedScore, ...]:
    groups: dict[
        tuple[str, datetime, datetime | None],
        list[PrecomputedScore],
    ] = {}
    for item in records:
        groups.setdefault(
            (item.strategy_id, item.effective_from, item.effective_to), []
        ).append(item)
    resolved: list[PrecomputedScore] = []
    for group in groups.values():
        superseded = {
            item.supersedes_revision_id
            for item in group
            if item.supersedes_revision_id is not None
        }
        resolved.extend(item for item in group if item.revision_id not in superseded)
    return tuple(resolved)


def _lifecycle_at(candidate: CandidateFund, decision: datetime) -> str | None:
    known = tuple(
        interval
        for interval in candidate.lifecycle
        if interval.published_at <= decision
        and interval.knowledge_at <= decision
        and interval.effective_from <= decision
        and (interval.effective_to is None or decision < interval.effective_to)
    )
    if not known:
        return None
    groups: dict[
        tuple[datetime, datetime | None],
        list[LifecycleInterval],
    ] = {}
    for item in known:
        groups.setdefault((item.effective_from, item.effective_to), []).append(item)
    revision_tips_list: list[LifecycleInterval] = []
    for group in groups.values():
        superseded = {
            item.supersedes_revision_id
            for item in group
            if item.supersedes_revision_id is not None
        }
        revision_tips_list.extend(
            item for item in group if item.revision_id not in superseded
        )
    revision_tips = tuple(revision_tips_list)
    latest_effective = max(interval.effective_from for interval in revision_tips)
    resolved = tuple(
        interval
        for interval in revision_tips
        if interval.effective_from == latest_effective
    )
    return resolved[0].status if len(resolved) == 1 else None


def _compound(returns: tuple[float, ...]) -> float:
    wealth = 1.0
    for value in returns:
        growth = _derived_number(1.0 + value, "$.outcomes.compound")
        wealth = _safe_multiply(wealth, growth, "$.outcomes.compound")
    return _safe_subtract(wealth, 1.0, "$.outcomes.compound")


def _uncertainty(values: tuple[float, ...]) -> Uncertainty:
    if len(values) < 2:
        return Uncertainty(
            status="insufficient_sample",
            sample_size=len(values),
            confidence_level=None,
            lower=None,
            upper=None,
            method="normal_approximation_of_mean",
        )
    mean = cast(float, _safe_mean(values, "$.uncertainty.mean"))
    squared_deviations = tuple(
        _safe_multiply(
            _safe_subtract(item, mean, "$.uncertainty.variance"),
            _safe_subtract(item, mean, "$.uncertainty.variance"),
            "$.uncertainty.variance",
        )
        for item in values
    )
    variance = _derived_number(
        _safe_sum(squared_deviations, "$.uncertainty.variance") / (len(values) - 1),
        "$.uncertainty.variance",
    )
    standard_error = _derived_number(
        math.sqrt(_derived_number(variance / len(values), "$.uncertainty.margin")),
        "$.uncertainty.margin",
    )
    margin = _safe_multiply(1.96, standard_error, "$.uncertainty.margin")
    return Uncertainty(
        status="estimated",
        sample_size=len(values),
        confidence_level=0.95,
        lower=_safe_subtract(mean, margin, "$.uncertainty.lower"),
        upper=_derived_number(mean + margin, "$.uncertainty.upper"),
        method="normal_approximation_of_mean",
    )


def _wealth_metrics(period_returns: tuple[float, ...]) -> WealthMetrics:
    curve = [1.0]
    for value in period_returns:
        growth = _derived_number(1.0 + value, "$.wealth")
        wealth = _safe_multiply(curve[-1], growth, "$.wealth")
        curve.append(wealth)
    peak = curve[0]
    peak_index = 0
    max_drawdown = 0.0
    trough_index = 0
    drawdown_peak_index = 0
    for index, wealth in enumerate(curve):
        if wealth > peak:
            peak = wealth
            peak_index = index
        drawdown = _safe_subtract(
            _derived_number(wealth / peak, "$.wealth.drawdown"),
            1.0,
            "$.wealth.drawdown",
        )
        if drawdown < max_drawdown:
            max_drawdown = drawdown
            trough_index = index
            drawdown_peak_index = peak_index
    if max_drawdown == 0.0:
        recovery_status = "not_applicable"
        recovery_periods = 0
    else:
        prior_peak = curve[drawdown_peak_index]
        recovered_at = next(
            (
                index
                for index in range(trough_index + 1, len(curve))
                if curve[index] >= prior_peak
            ),
            None,
        )
        recovery_status = "recovered" if recovered_at is not None else "unrecovered"
        recovery_periods = (
            recovered_at - trough_index if recovered_at is not None else None
        )
    return WealthMetrics(
        wealth_curve=tuple(curve),
        max_drawdown=max_drawdown,
        recovery_status=recovery_status,
        recovery_periods=recovery_periods,
    )


def _ranks(values: dict[str, float], identifiers: tuple[str, ...]) -> dict[str, float]:
    for identifier in identifiers:
        _finite_number(values[identifier], "$.ranking", code="calculation_overflow")
    ordered = sorted(identifiers, key=lambda item: (-values[item], item))
    result: dict[str, float] = {}
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[index]]:
            end += 1
        average_rank = _derived_number((index + 1 + end) / 2.0, "$.ranking")
        for identifier in ordered[index:end]:
            result[identifier] = average_rank
        index = end
    return result


def _score_stability(
    previous: dict[str, float] | None,
    current: dict[str, float],
) -> Metric:
    if previous is None:
        return Metric(
            metric="spearman_rank_correlation",
            status="insufficient_prior_fold",
            value=None,
            sample_size=0,
        )
    common = tuple(sorted(set(previous) & set(current)))
    if len(common) < 2:
        return Metric(
            metric="spearman_rank_correlation",
            status="insufficient_overlap",
            value=None,
            sample_size=len(common),
        )
    prior_ranks = _ranks(previous, common)
    current_ranks = _ranks(current, common)
    prior_mean = cast(
        float,
        _safe_mean(tuple(prior_ranks.values()), "$.score_stability.mean"),
    )
    current_mean = cast(
        float,
        _safe_mean(tuple(current_ranks.values()), "$.score_stability.mean"),
    )
    prior_differences = {
        item: _safe_subtract(
            prior_ranks[item], prior_mean, "$.score_stability.correlation"
        )
        for item in common
    }
    current_differences = {
        item: _safe_subtract(
            current_ranks[item], current_mean, "$.score_stability.correlation"
        )
        for item in common
    }
    numerator = _safe_sum(
        tuple(
            _safe_multiply(
                prior_differences[item],
                current_differences[item],
                "$.score_stability.correlation",
            )
            for item in common
        ),
        "$.score_stability.correlation",
    )
    prior_scale = _safe_sum(
        tuple(
            _safe_multiply(
                prior_differences[item],
                prior_differences[item],
                "$.score_stability.correlation",
            )
            for item in common
        ),
        "$.score_stability.correlation",
    )
    current_scale = _safe_sum(
        tuple(
            _safe_multiply(
                current_differences[item],
                current_differences[item],
                "$.score_stability.correlation",
            )
            for item in common
        ),
        "$.score_stability.correlation",
    )
    denominator = _derived_number(
        math.sqrt(
            _safe_multiply(
                prior_scale,
                current_scale,
                "$.score_stability.correlation",
            )
        ),
        "$.score_stability.correlation",
    )
    if denominator == 0.0:
        return Metric(
            metric="spearman_rank_correlation",
            status="insufficient_variation",
            value=None,
            sample_size=len(common),
        )
    return Metric(
        metric="spearman_rank_correlation",
        status="estimated",
        value=_derived_number(
            numerator / denominator,
            "$.score_stability.correlation",
        ),
        sample_size=len(common),
    )


def _turnover(
    previous: tuple[str, ...] | None,
    current: tuple[str, ...],
) -> Metric:
    if previous is None:
        return Metric(
            metric="jaccard_distance",
            status="insufficient_prior_fold",
            value=None,
            sample_size=0,
        )
    union = set(previous) | set(current)
    value = (
        0.0
        if not union
        else _safe_subtract(
            1.0,
            _derived_number(
                len(set(previous) & set(current)) / len(union),
                "$.selection_turnover",
            ),
            "$.selection_turnover",
        )
    )
    return Metric(
        metric="jaccard_distance",
        status="estimated",
        value=value,
        sample_size=len(union),
    )


def _component_values(audit: ScoreResult) -> dict[str, float | None]:
    return {item.name: item.contribution for item in audit.components}


def _component_diagnostics(audits: tuple[ScoreResult, ...]) -> ComponentDiagnostics:
    names = tuple(sorted({item.name for audit in audits for item in audit.components}))
    maps = tuple(_component_values(audit) for audit in audits)
    coverage: list[ComponentCoverage] = []
    for name in names:
        values = tuple(item.get(name) for item in maps)
        sample_size = sum(value is not None for value in values)
        versions = tuple(
            sorted(
                {
                    component.component_version
                    for audit in audits
                    for component in audit.components
                    if component.name == name
                }
            )
        )
        missing_count = len(audits) - sample_size
        coverage.append(
            ComponentCoverage(
                component_name=name,
                component_versions=versions,
                sample_size=sample_size,
                missing_count=missing_count,
                total_count=len(audits),
                status="complete" if missing_count == 0 else "partial",
            )
        )
    correlations: list[ComponentCorrelation] = []
    for left_index, left in enumerate(names):
        for right in names[left_index:]:
            pairs: tuple[tuple[float, float], ...] = tuple(
                (cast(float, item[left]), cast(float, item[right]))
                for item in maps
                if item.get(left) is not None and item.get(right) is not None
            )
            sample_size = len(pairs)
            value: float | None = None
            if sample_size < 2:
                status = "insufficient_sample"
            else:
                left_max = max(abs(item[0]) for item in pairs)
                right_max = max(abs(item[1]) for item in pairs)
                if left_max == 0.0 or right_max == 0.0:
                    status = "constant_component"
                else:
                    scaled_pairs = tuple(
                        (
                            _derived_number(
                                item[0] / left_max,
                                "$.component_correlation.scaling",
                            ),
                            _derived_number(
                                item[1] / right_max,
                                "$.component_correlation.scaling",
                            ),
                        )
                        for item in pairs
                    )
                    left_mean = cast(
                        float,
                        _safe_mean(
                            tuple(item[0] for item in scaled_pairs),
                            "$.component_correlation.mean",
                        ),
                    )
                    right_mean = cast(
                        float,
                        _safe_mean(
                            tuple(item[1] for item in scaled_pairs),
                            "$.component_correlation.mean",
                        ),
                    )
                    deviations = tuple(
                        (
                            _safe_subtract(
                                item[0],
                                left_mean,
                                "$.component_correlation",
                            ),
                            _safe_subtract(
                                item[1],
                                right_mean,
                                "$.component_correlation",
                            ),
                        )
                        for item in scaled_pairs
                    )
                    numerator = _safe_sum(
                        tuple(
                            _safe_multiply(item[0], item[1], "$.component_correlation")
                            for item in deviations
                        ),
                        "$.component_correlation",
                    )
                    left_scale = _safe_sum(
                        tuple(
                            _safe_multiply(item[0], item[0], "$.component_correlation")
                            for item in deviations
                        ),
                        "$.component_correlation",
                    )
                    right_scale = _safe_sum(
                        tuple(
                            _safe_multiply(item[1], item[1], "$.component_correlation")
                            for item in deviations
                        ),
                        "$.component_correlation",
                    )
                    denominator = _derived_number(
                        math.sqrt(
                            _safe_multiply(
                                left_scale,
                                right_scale,
                                "$.component_correlation",
                            )
                        ),
                        "$.component_correlation",
                    )
                    if denominator == 0.0:
                        status = "constant_component"
                    else:
                        status = "estimated"
                        value = max(
                            -1.0,
                            min(
                                1.0,
                                _derived_number(
                                    numerator / denominator,
                                    "$.component_correlation",
                                ),
                            ),
                        )
            correlations.append(
                ComponentCorrelation(
                    left_component=left,
                    right_component=right,
                    method="pearson_pairwise_complete",
                    sample_size=sample_size,
                    status=status,
                    value=value,
                )
            )
    return ComponentDiagnostics(
        coverage=tuple(coverage),
        correlations=tuple(correlations),
    )


def _sensitivity_diagnostics(
    scores: dict[str, float],
    audits: dict[str, ScoreResult],
    selected: tuple[str, ...],
    select_count: int,
) -> SensitivityDiagnostics:
    names = tuple(
        sorted({item.name for audit in audits.values() for item in audit.components})
    )
    scenarios: list[SensitivityScenario] = []
    score_ids = tuple(sorted(scores))
    baseline_ranks = tuple(sorted(_ranks(scores, score_ids).items()))
    for name in names:
        contributions = {
            strategy_id: _component_values(audit).get(name)
            for strategy_id, audit in audits.items()
        }
        if set(contributions) != set(scores) or any(
            value is None for value in contributions.values()
        ):
            scenarios.append(
                SensitivityScenario(
                    omitted_component=name,
                    method="leave_one_component_out_no_refit",
                    status="insufficient_component_coverage",
                    baseline_selected_strategy_ids=selected,
                    perturbed_selected_strategy_ids=(),
                    baseline_ranks=baseline_ranks,
                    perturbed_ranks=(),
                    selection_turnover=Metric(
                        metric="jaccard_distance",
                        status="insufficient_component_coverage",
                        value=None,
                        sample_size=len(scores),
                    ),
                    rank_correlation=Metric(
                        metric="spearman_rank_correlation",
                        status="insufficient_component_coverage",
                        value=None,
                        sample_size=len(scores),
                    ),
                    selected_mean_score_delta=None,
                )
            )
            continue
        perturbed = {
            strategy_id: _safe_subtract(
                scores[strategy_id],
                cast(float, contribution),
                "$.sensitivity.perturbed_score",
            )
            for strategy_id, contribution in contributions.items()
        }
        perturbed_selected = tuple(
            strategy_id
            for strategy_id, _ in sorted(
                perturbed.items(), key=lambda item: (-item[1], item[0])
            )[:select_count]
        )
        baseline_mean = (
            _safe_mean(
                tuple(scores[item] for item in selected),
                "$.sensitivity.baseline_mean",
            )
            if selected
            else None
        )
        perturbed_mean = (
            _safe_mean(
                tuple(perturbed[item] for item in perturbed_selected),
                "$.sensitivity.perturbed_mean",
            )
            if perturbed_selected
            else None
        )
        scenarios.append(
            SensitivityScenario(
                omitted_component=name,
                method="leave_one_component_out_no_refit",
                status="estimated",
                baseline_selected_strategy_ids=selected,
                perturbed_selected_strategy_ids=perturbed_selected,
                baseline_ranks=baseline_ranks,
                perturbed_ranks=tuple(sorted(_ranks(perturbed, score_ids).items())),
                selection_turnover=_turnover(selected, perturbed_selected),
                rank_correlation=_score_stability(scores, perturbed),
                selected_mean_score_delta=(
                    _safe_subtract(
                        perturbed_mean,
                        baseline_mean,
                        "$.sensitivity.selected_mean_score_delta",
                    )
                    if perturbed_mean is not None and baseline_mean is not None
                    else None
                ),
            )
        )
    return SensitivityDiagnostics(
        definition=(
            "subtract one named contribution from every complete total; do not refit, "
            "use outcomes, or optimize parameters"
        ),
        scenarios=tuple(scenarios),
    )


def _summary_sensitivity(
    folds: tuple[SensitivityDiagnostics, ...],
) -> tuple[SummarySensitivity, ...]:
    names = tuple(
        sorted(
            {
                scenario.omitted_component
                for fold in folds
                for scenario in fold.scenarios
            }
        )
    )
    summaries: list[SummarySensitivity] = []
    for name in names:
        scenarios = tuple(
            scenario
            for fold in folds
            for scenario in fold.scenarios
            if scenario.omitted_component == name
        )
        complete = tuple(item for item in scenarios if item.status == "estimated")
        turnovers = tuple(
            item.selection_turnover.value
            for item in complete
            if item.selection_turnover.value is not None
        )
        correlations = tuple(
            item.rank_correlation.value
            for item in complete
            if item.rank_correlation.value is not None
        )
        deltas = tuple(
            item.selected_mean_score_delta
            for item in complete
            if item.selected_mean_score_delta is not None
        )
        summaries.append(
            SummarySensitivity(
                component_name=name,
                method="leave_one_component_out_no_refit",
                status="estimated" if complete else "insufficient_component_coverage",
                fold_count=len(complete),
                mean_selection_turnover=(
                    _safe_mean(
                        cast(tuple[float, ...], turnovers),
                        "$.summary.sensitivity.turnover",
                    )
                    if turnovers
                    else None
                ),
                mean_rank_correlation=(
                    _safe_mean(
                        cast(tuple[float, ...], correlations),
                        "$.summary.sensitivity.correlation",
                    )
                    if correlations
                    else None
                ),
                mean_selected_score_delta=(
                    _safe_mean(
                        cast(tuple[float, ...], deltas),
                        "$.summary.sensitivity.delta",
                    )
                    if deltas
                    else None
                ),
            )
        )
    return tuple(summaries)


def _evaluate_outcomes(
    fold: FoldWindow,
    selected: tuple[str, ...],
    outcomes: tuple[FutureOutcome, ...],
) -> tuple[OutcomeEvaluation, WealthMetrics, tuple[float, ...], tuple[float, ...]]:
    matched = tuple(
        next(
            (
                item
                for item in outcomes
                if item.strategy_id == strategy_id
                and item.window_start == fold.outcome_start
                and item.window_end == fold.outcome_end
            ),
            None,
        )
        for strategy_id in selected
    )
    usable = tuple(item for item in matched if item is not None)
    relative = tuple(
        _safe_subtract(
            _compound(item.period_returns),
            _compound(item.peer_period_returns),
            "$.outcomes.peer_relative_return",
        )
        for item in usable
    )
    if not usable:
        return (
            OutcomeEvaluation(
                status="insufficient_outcomes",
                mean_peer_relative_return=None,
                evaluated_count=0,
                uncertainty=_uncertainty(()),
            ),
            _wealth_metrics(()),
            (),
            (),
        )
    period_count = min(len(item.period_returns) for item in usable)
    portfolio_returns = tuple(
        cast(
            float,
            _safe_mean(
                tuple(item.period_returns[index] for item in usable),
                "$.outcomes.portfolio_return",
            ),
        )
        for index in range(period_count)
    )
    return (
        OutcomeEvaluation(
            status="evaluated" if len(usable) == len(selected) else "partial",
            mean_peer_relative_return=_safe_mean(
                relative,
                "$.outcomes.mean_peer_relative_return",
            ),
            evaluated_count=len(relative),
            uncertainty=_uncertainty(relative),
        ),
        _wealth_metrics(portfolio_returns),
        portfolio_returns,
        relative,
    )


def _mean_metric(metrics: tuple[Metric, ...]) -> float | None:
    values = tuple(item.value for item in metrics if item.value is not None)
    return (
        _safe_mean(cast(tuple[float, ...], values), "$.summary.metric_mean")
        if values
        else None
    )


def _validate_inputs(
    config: object,
    candidates: object,
    snapshots: object,
    outcomes: object,
    scorer: object,
    precomputed_scores: object,
) -> tuple[
    WalkForwardConfig,
    tuple[CandidateFund, ...],
    tuple[VersionedSnapshot, ...],
    tuple[FutureOutcome, ...],
    ScoreCallback | None,
    tuple[PrecomputedScore, ...],
]:
    if type(config) is not WalkForwardConfig:
        _fail("invalid_type", "$.config", "configuration type is invalid")
    collections = (
        ("$.candidates", candidates, CandidateFund),
        ("$.snapshots", snapshots, VersionedSnapshot),
        ("$.outcomes", outcomes, FutureOutcome),
        ("$.precomputed_scores", precomputed_scores, PrecomputedScore),
    )
    for path, value, item_type in collections:
        if type(value) is not tuple:
            _fail("invalid_container", path, "input collection must be a tuple")
        if len(value) > _MAX_INPUT_ITEMS:
            _fail("input_too_large", path, "input collection exceeds the size limit")
        if any(type(item) is not item_type for item in value):
            _fail("invalid_type", path, "input collection contains an invalid entry")
    typed_config = cast(WalkForwardConfig, config)
    typed_candidates = cast(tuple[CandidateFund, ...], candidates)
    typed_snapshots = cast(tuple[VersionedSnapshot, ...], snapshots)
    typed_outcomes = cast(tuple[FutureOutcome, ...], outcomes)
    typed_scores = cast(tuple[PrecomputedScore, ...], precomputed_scores)
    nested_item_count = (
        len(typed_config.folds)
        + sum(len(item.lifecycle) for item in typed_candidates)
        + sum(
            len(item.period_returns) + len(item.peer_period_returns)
            for item in typed_outcomes
        )
        + sum(len(item.components) for item in typed_scores)
    )
    if nested_item_count > _MAX_INPUT_ITEMS:
        _fail("input_too_large", "$", "nested input exceeds the cumulative size limit")
    if not typed_candidates:
        _fail("empty_universe", "$.candidates", "candidate universe must not be empty")
    if (scorer is None) == (not typed_scores):
        _fail(
            "score_source_required",
            "$.scores",
            "provide exactly one score callback or precomputed score collection",
        )
    if scorer is not None and not callable(scorer):
        _fail("invalid_scorer", "$.scorer", "score callback must be callable")
    share_ids = tuple(item.share_class_id for item in typed_candidates)
    if len(share_ids) != len(set(share_ids)):
        _fail(
            "duplicate_entity", "$.candidates", "share-class identifiers must be unique"
        )
    candidate_ids = {item.strategy_id for item in typed_candidates}
    for strategy_id in candidate_ids:
        versions = tuple(
            item for item in typed_candidates if item.strategy_id == strategy_id
        )
        if len({(item.inception_at, item.lifecycle) for item in versions}) != 1:
            _fail(
                "entity_conflict",
                "$.candidates",
                "share classes disagree on strategy lifecycle",
            )
    for path, items, identifier_name in (
        ("$.snapshots", typed_snapshots, "snapshot_id"),
        ("$.outcomes", typed_outcomes, "outcome_id"),
        ("$.precomputed_scores", typed_scores, "score_id"),
    ):
        identifiers = tuple(getattr(item, identifier_name) for item in items)
        if len(identifiers) != len(set(identifiers)):
            _fail("duplicate_entity", path, "record identifiers must be unique")
        if any(item.strategy_id not in candidate_ids for item in items):
            _fail("unknown_strategy_id", path, "record references an unknown strategy")
    fold_windows = {(item.outcome_start, item.outcome_end) for item in config.folds}
    if any(
        (item.window_start, item.window_end) not in fold_windows
        for item in typed_outcomes
    ):
        _fail("unknown_outcome_window", "$.outcomes", "outcome window is not a fold")
    _validate_snapshot_revision_groups(typed_snapshots)
    _validate_score_revision_groups(typed_scores)
    outcome_keys = tuple(
        (item.strategy_id, item.window_start, item.window_end)
        for item in typed_outcomes
    )
    if len(outcome_keys) != len(set(outcome_keys)):
        _fail("duplicate_outcome", "$.outcomes", "strategy outcome must be unique")
    for window in fold_windows:
        period_counts = {
            len(item.period_returns)
            for item in typed_outcomes
            if (item.window_start, item.window_end) == window
        }
        if len(period_counts) > 1:
            _fail("outcome_alignment", "$.outcomes", "outcome periods must align")
    typed_scorer = cast(ScoreCallback | None, scorer)
    return (
        typed_config,
        typed_candidates,
        typed_snapshots,
        typed_outcomes,
        typed_scorer,
        typed_scores,
    )


def run_walk_forward(
    config: WalkForwardConfig,
    *,
    candidates: tuple[CandidateFund, ...],
    snapshots: tuple[VersionedSnapshot, ...],
    outcomes: tuple[FutureOutcome, ...],
    scorer: ScoreCallback | None = None,
    precomputed_scores: tuple[PrecomputedScore, ...] = (),
) -> WalkForwardReport:
    """Run deterministic point-in-time scoring, then evaluate frozen selections."""
    (
        config,
        candidates,
        snapshots,
        outcomes,
        scorer,
        precomputed_scores,
    ) = _validate_inputs(
        config,
        candidates,
        snapshots,
        outcomes,
        scorer,
        precomputed_scores,
    )
    representatives = {
        strategy_id: min(
            (item for item in candidates if item.strategy_id == strategy_id),
            key=lambda item: item.share_class_id,
        )
        for strategy_id in {item.strategy_id for item in candidates}
    }
    strategies = tuple(sorted(representatives))
    fold_reports: list[FoldReport] = []
    previous_scores: dict[str, float] | None = None
    previous_selection: tuple[str, ...] | None = None
    aggregate_period_returns: list[float] = []
    aggregate_relative: list[float] = []
    aggregate_score_audits: list[ScoreResult] = []
    score_audit_registry: dict[tuple[str, str, str], ScoreResult] = {}
    for fold in config.folds:
        fold_strategies = tuple(
            strategy_id
            for strategy_id in strategies
            if representatives[strategy_id].inception_at <= fold.decision_at
        )
        if not fold_strategies:
            _fail(
                "empty_universe",
                "$.config.folds",
                "no candidate strategy existed at a decision timestamp",
            )
        lifecycle_audit = tuple(
            (strategy_id, interval)
            for strategy_id in fold_strategies
            for interval in representatives[strategy_id].lifecycle
            if interval.published_at <= fold.decision_at
            and interval.knowledge_at <= fold.decision_at
        )
        scores: list[tuple[float, str]] = []
        resolved_by_strategy: dict[str, tuple[VersionedSnapshot, ...]] = {}
        audit_trail: dict[str, VersionedSnapshot] = {}
        score_audit_trail: dict[tuple[str, str, str], ScoreResult] = {}
        component_audits: dict[str, ScoreResult] = {}
        failures: list[FoldFailure] = []
        terminal_count = 0
        for strategy_id in fold_strategies:
            lifecycle = _lifecycle_at(representatives[strategy_id], fold.decision_at)
            if lifecycle is None:
                failures.append(
                    FoldFailure(
                        code="lifecycle_unknown",
                        strategy_id=strategy_id,
                        detail="lifecycle is not uniquely known at the decision timestamp",
                    )
                )
                continue
            if lifecycle in {"closed", "merged", "transformed"}:
                terminal_count += 1
                failures.append(
                    FoldFailure(
                        code="terminal_lifecycle",
                        strategy_id=strategy_id,
                        detail=(
                            "strategy is retained for survivorship control but is not eligible"
                        ),
                    )
                )
                continue
            available = tuple(
                item
                for item in snapshots
                if item.strategy_id == strategy_id
                and item.knowledge_at <= fold.decision_at
                and item.published_at <= fold.decision_at
                and _effective(item, fold.decision_at)
            )
            audit_trail.update((item.snapshot_id, item) for item in available)
            available = _resolve_snapshot_revisions(available)
            grouped = {
                domain: tuple(item for item in available if item.domain == domain)
                for domain in {item.domain for item in available}
            }
            if any(len(items) > 1 for items in grouped.values()):
                failures.append(
                    FoldFailure(
                        code="snapshot_conflict",
                        strategy_id=strategy_id,
                        detail="multiple point-in-time records match a required domain",
                    )
                )
                continue
            if not _REQUIRED_DOMAINS.issubset(grouped):
                failures.append(
                    FoldFailure(
                        code="snapshot_missing",
                        strategy_id=strategy_id,
                        detail="a required point-in-time domain is unavailable",
                    )
                )
                continue
            resolved = tuple(grouped[domain][0] for domain in sorted(grouped))
            provider_versions = {
                (item.provider_id, item.provider_snapshot_id, item.provider_version)
                for item in resolved
            }
            if len(provider_versions) != 1:
                failures.append(
                    FoldFailure(
                        code="provider_snapshot_conflict",
                        strategy_id=strategy_id,
                        detail="resolved domains do not share one provider snapshot version",
                    )
                )
                continue
            provider_version = next(iter(provider_versions))
            if any(item.value is None for item in resolved):
                failures.append(
                    FoldFailure(
                        code="snapshot_unknown",
                        strategy_id=strategy_id,
                        detail="a required point-in-time domain has unknown value",
                    )
                )
                continue
            availability = grouped["availability"][0]
            if availability.value is not True:
                failures.append(
                    FoldFailure(
                        code="unavailable",
                        strategy_id=strategy_id,
                        detail="strategy is not available at the decision timestamp",
                    )
                )
                continue
            if scorer is not None:
                value: object = None
                try:
                    value = scorer(
                        ScoringView(
                            strategy_id=strategy_id,
                            decision_at=fold.decision_at,
                            fold=fold,
                            snapshots=resolved,
                        )
                    )
                except Exception:  # noqa: BLE001 -- callback failures are an explicit boundary.
                    # Deliberately exclude BaseException so process interrupts still propagate.
                    _fail(
                        "score_callback_failed",
                        "$.scorer",
                        "score callback failed without exposing private details",
                    )
                if value is not None and type(value) is not ScoreResult:
                    if isinstance(value, bool):
                        _fail(
                            "invalid_score",
                            "$.score",
                            "value must be a finite number and not boolean",
                        )
                    if isinstance(value, (int, float)):
                        _finite_number(value, "$.score", code="invalid_score")
                    _fail(
                        "invalid_score_result",
                        "$.scorer",
                        "callback must return an auditable ScoreResult or None",
                    )
                if isinstance(value, ScoreResult):
                    if (
                        value.score_as_of > fold.decision_at
                        or value.published_at > fold.decision_at
                        or value.knowledge_at > fold.decision_at
                    ):
                        _fail(
                            "score_not_point_in_time",
                            "$.scorer",
                            "callback score was not known by the decision timestamp",
                        )
                    if (
                        value.provider_id,
                        value.provider_snapshot_id,
                        value.provider_version,
                    ) != provider_version:
                        failures.append(
                            FoldFailure(
                                code="score_provider_mismatch",
                                strategy_id=strategy_id,
                                detail="score audit does not match the resolved provider snapshot",
                            )
                        )
                        continue
                    if not _score_covers_provider_time(value, resolved):
                        failures.append(
                            FoldFailure(
                                code="score_provider_time_mismatch",
                                strategy_id=strategy_id,
                                detail="score audit predates the resolved provider snapshot",
                            )
                        )
                        continue
                    value = replace(value, strategy_id=strategy_id)
                    audit_key = (
                        strategy_id,
                        value.audit_id,
                        value.revision_id,
                    )
                    canonical_audit = score_audit_registry.get(audit_key)
                    if canonical_audit is not None and canonical_audit != value:
                        _fail(
                            "score_audit_conflict",
                            "$.scorer",
                            "score audit identifier has conflicting content within the run",
                        )
                    if canonical_audit is None:
                        score_audit_registry[audit_key] = value
                    existing_audit = score_audit_trail.get(audit_key)
                    if existing_audit is not None and existing_audit != value:
                        failures.append(
                            FoldFailure(
                                code="score_audit_conflict",
                                strategy_id=strategy_id,
                                detail="score audit identifier is not unique within the fold",
                            )
                        )
                        continue
                    score_audit_trail[audit_key] = value
                    component_audits[strategy_id] = value
                    value = value.total_score
            else:
                matching_scores = tuple(
                    item
                    for item in precomputed_scores
                    if item.strategy_id == strategy_id
                    and item.score_as_of <= fold.decision_at
                    and item.published_at <= fold.decision_at
                    and item.knowledge_at <= fold.decision_at
                    and item.effective_from <= fold.decision_at
                    and (
                        item.effective_to is None
                        or fold.decision_at < item.effective_to
                    )
                )
                matching_scores = _resolve_score_revisions(matching_scores)
                if len(matching_scores) != 1:
                    failures.append(
                        FoldFailure(
                            code=(
                                "score_missing"
                                if not matching_scores
                                else "score_conflict"
                            ),
                            strategy_id=strategy_id,
                            detail="precomputed point-in-time score is not uniquely resolved",
                        )
                    )
                    continue
                score_record = matching_scores[0]
                if (
                    score_record.provider_id,
                    score_record.provider_snapshot_id,
                    score_record.provider_version,
                ) != provider_version:
                    failures.append(
                        FoldFailure(
                            code="score_provider_mismatch",
                            strategy_id=strategy_id,
                            detail="score audit does not match the resolved provider snapshot",
                        )
                    )
                    continue
                if not _score_covers_provider_time(score_record, resolved):
                    failures.append(
                        FoldFailure(
                            code="score_provider_time_mismatch",
                            strategy_id=strategy_id,
                            detail="score audit predates the resolved provider snapshot",
                        )
                    )
                    continue
                value = score_record.total_score
                score_audit = score_record.as_score_result()
                score_audit_trail[
                    (
                        score_record.strategy_id,
                        score_record.score_id,
                        score_record.revision_id,
                    )
                ] = score_audit
                component_audits[strategy_id] = score_audit
            if value is None:
                failures.append(
                    FoldFailure(
                        code="score_missing",
                        strategy_id=strategy_id,
                        detail="score callback returned no point-in-time score",
                    )
                )
                continue
            numeric_value = _finite_number(value, "$.score", code="invalid_score")
            scores.append((numeric_value, strategy_id))
            resolved_by_strategy[strategy_id] = resolved
            audit_trail.update((item.snapshot_id, item) for item in resolved)
        scores.sort(key=lambda item: (-item[0], item[1]))
        score_map = {strategy_id: value for value, strategy_id in scores}
        selected = tuple(item[1] for item in scores[: config.select_count])
        component_diagnostics = _component_diagnostics(
            tuple(component_audits[key] for key in sorted(component_audits))
        )
        sensitivity = _sensitivity_diagnostics(
            score_map,
            component_audits,
            selected,
            config.select_count,
        )
        aggregate_score_audits.extend(
            component_audits[key] for key in sorted(component_audits)
        )
        classification_counts: dict[str, int] = {}
        for strategy_id in selected:
            classification = next(
                str(item.value)
                for item in resolved_by_strategy[strategy_id]
                if item.domain == "classification"
            )
            classification_counts[classification] = (
                classification_counts.get(classification, 0) + 1
            )
        stability = _score_stability(previous_scores, score_map)
        turnover = _turnover(previous_selection, selected)
        outcome, wealth, period_returns, relative = _evaluate_outcomes(
            fold, selected, outcomes
        )
        aggregate_period_returns.extend(period_returns)
        aggregate_relative.extend(relative)
        audit_ids = tuple(sorted(audit_trail))
        fold_reports.append(
            FoldReport(
                fold_id=fold.fold_id,
                decision_at=fold.decision_at,
                universe_count=len(fold_strategies),
                eligible_count=len(scores),
                selected_count=len(selected),
                selected_strategy_ids=selected,
                score_source="callback" if scorer is not None else "precomputed",
                audit_score_ids=tuple(sorted(score_audit_trail)),
                score_audit_trail=tuple(
                    score_audit_trail[key] for key in sorted(score_audit_trail)
                ),
                selection_breadth=tuple(sorted(classification_counts.items())),
                score_stability=stability,
                selection_turnover=turnover,
                outcome=outcome,
                wealth=wealth,
                audit_snapshot_ids=audit_ids,
                audit_trail=tuple(audit_trail[key] for key in audit_ids),
                audit_lifecycle=lifecycle_audit,
                retained_terminal_count=terminal_count,
                failures=tuple(failures),
                coverage=Coverage(
                    complete=len(scores),
                    total=len(fold_strategies),
                    ratio=(
                        len(scores) / len(fold_strategies) if fold_strategies else 0.0
                    ),
                ),
                component_diagnostics=component_diagnostics,
                sensitivity=sensitivity,
            )
        )
        previous_scores = score_map
        previous_selection = selected
    relative_values = tuple(aggregate_relative)
    summary = SummaryReport(
        fold_count=len(fold_reports),
        mean_score_stability=_mean_metric(
            tuple(item.score_stability for item in fold_reports)
        ),
        mean_selection_turnover=_mean_metric(
            tuple(item.selection_turnover for item in fold_reports)
        ),
        mean_peer_relative_return=(
            _safe_mean(
                relative_values,
                "$.summary.mean_peer_relative_return",
            )
            if relative_values
            else None
        ),
        uncertainty=_uncertainty(relative_values),
        wealth=_wealth_metrics(tuple(aggregate_period_returns)),
        component_diagnostics=_component_diagnostics(tuple(aggregate_score_audits)),
        sensitivity=_summary_sensitivity(
            tuple(item.sensitivity for item in fold_reports)
        ),
        disclaimer="research_only_not_a_return_guarantee",
    )
    report = WalkForwardReport(folds=tuple(fold_reports), summary=summary)
    _validate_report_finite(report)
    return report
