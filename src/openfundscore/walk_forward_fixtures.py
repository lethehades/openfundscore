"""Deterministic, synthetic-only fixtures for point-in-time validation tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .walk_forward import (
    CandidateFund,
    FoldWindow,
    FutureOutcome,
    LifecycleInterval,
    PrecomputedScore,
    ScoreComponent,
    VersionedSnapshot,
    WalkForwardConfig,
)


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class SyntheticWalkForwardFixture:
    config: WalkForwardConfig
    candidates: tuple[CandidateFund, ...]
    snapshots: tuple[VersionedSnapshot, ...]
    outcomes: tuple[FutureOutcome, ...]
    precomputed_scores: tuple[PrecomputedScore, ...]


def _candidate(strategy_id: str, terminal_status: str | None) -> CandidateFund:
    same_effective_revision = terminal_status == "closed"
    lifecycle = (
        LifecycleInterval(
            status="active",
            effective_from=_dt(2018, 1, 1),
            effective_to=(
                _dt(2021, 2, 1)
                if terminal_status and not same_effective_revision
                else None
            ),
            published_at=_dt(2018, 1, 1),
            knowledge_at=_dt(2018, 1, 1),
            revision_id=("lifecycle-r1" if same_effective_revision else "original"),
        ),
    )
    if terminal_status is not None:
        lifecycle += (
            LifecycleInterval(
                status=terminal_status,
                effective_from=(
                    _dt(2018, 1, 1) if same_effective_revision else _dt(2021, 2, 1)
                ),
                published_at=_dt(2021, 2, 20),
                knowledge_at=_dt(2021, 2, 20),
                revision_id=("lifecycle-r2" if same_effective_revision else "original"),
                supersedes_revision_id=(
                    "lifecycle-r1" if same_effective_revision else None
                ),
                successor_strategy_id=(
                    f"{strategy_id}-successor"
                    if terminal_status in {"merged", "transformed"}
                    else None
                ),
            ),
        )
    return CandidateFund(
        share_class_id=f"{strategy_id}-A",
        strategy_id=strategy_id,
        inception_at=_dt(2018, 1, 1),
        lifecycle=lifecycle,
    )


def _snapshot(
    strategy_id: str,
    domain: str,
    value: str | float | bool,
    *,
    version: str,
    effective_from: datetime,
    effective_to: datetime | None = None,
    published_at: datetime,
    revision_label: str = "original",
    supersedes_revision_label: str | None = None,
) -> VersionedSnapshot:
    return VersionedSnapshot(
        snapshot_id=f"snapshot-{strategy_id}-{domain}-{version}",
        provider_id="synthetic-provider",
        provider_snapshot_id=f"provider-snapshot-{version}",
        provider_version=version,
        strategy_id=strategy_id,
        domain=domain,
        value=value,
        as_of=published_at,
        published_at=published_at,
        knowledge_at=published_at,
        effective_from=effective_from,
        effective_to=effective_to,
        revision_id=f"{domain}-{revision_label}",
        supersedes_revision_id=(
            f"{domain}-{supersedes_revision_label}"
            if supersedes_revision_label is not None
            else None
        ),
    )


def _domain_snapshots(
    strategy_id: str,
    *,
    version: str,
    effective_from: datetime,
    effective_to: datetime | None,
    published_at: datetime,
    suffix: str,
    revision_label: str = "original",
    supersedes_revision_label: str | None = None,
) -> tuple[VersionedSnapshot, ...]:
    return tuple(
        _snapshot(
            strategy_id,
            domain,
            value,
            version=version,
            effective_from=effective_from,
            effective_to=effective_to,
            published_at=published_at,
            revision_label=revision_label,
            supersedes_revision_label=supersedes_revision_label,
        )
        for domain, value in (
            ("classification", f"equity-{suffix}" if suffix == "old" else "mixed-new"),
            ("benchmark", f"benchmark-{suffix}"),
            ("manager", f"manager-{suffix}"),
            ("fee_bps", 100 if suffix == "old" else 80),
            ("availability", True),
            ("feature:downside_risk", 20.0 if suffix == "old" else 15.0),
        )
    )


def synthetic_walk_forward_fixture() -> SyntheticWalkForwardFixture:
    """Return the same local fixture on every call; no network or real fund data."""
    first_fold = FoldWindow(
        fold_id="synthetic-fold-1",
        train_start=_dt(2018, 1, 1),
        train_end=_dt(2019, 6, 30),
        validation_start=_dt(2019, 7, 1),
        validation_end=_dt(2020, 12, 20),
        decision_at=_dt(2021, 1, 1),
        outcome_start=_dt(2021, 1, 2),
        outcome_end=_dt(2021, 1, 31),
        embargo_seconds=86_400,
    )
    second_fold = FoldWindow(
        fold_id="synthetic-fold-2",
        train_start=_dt(2018, 2, 1),
        train_end=_dt(2019, 7, 31),
        validation_start=_dt(2019, 8, 1),
        validation_end=_dt(2021, 2, 20),
        decision_at=_dt(2021, 3, 1),
        outcome_start=_dt(2021, 3, 2),
        outcome_end=_dt(2021, 3, 31),
        embargo_seconds=86_400,
    )
    candidates = (
        _candidate("synthetic-active", None),
        _candidate("synthetic-closed", "closed"),
        _candidate("synthetic-merged", "merged"),
        _candidate("synthetic-transformed", "transformed"),
        CandidateFund(
            share_class_id="synthetic-future-A",
            strategy_id="synthetic-future",
            inception_at=_dt(2022, 1, 1),
            lifecycle=(
                LifecycleInterval(
                    status="active",
                    effective_from=_dt(2022, 1, 1),
                    published_at=_dt(2022, 1, 1),
                    knowledge_at=_dt(2022, 1, 1),
                ),
            ),
        ),
    )
    old_start = _dt(2018, 1, 1)
    old_published = _dt(2020, 12, 20)
    new_published = _dt(2021, 2, 20)
    snapshots: list[VersionedSnapshot] = []
    snapshots.extend(
        _domain_snapshots(
            "synthetic-active",
            version="v1",
            effective_from=old_start,
            effective_to=None,
            published_at=old_published,
            suffix="old",
            revision_label="r1",
        )
    )
    snapshots.extend(
        _domain_snapshots(
            "synthetic-active",
            version="v2",
            effective_from=old_start,
            effective_to=None,
            published_at=new_published,
            suffix="new",
            revision_label="r2",
            supersedes_revision_label="r1",
        )
    )
    for strategy_id in (
        "synthetic-closed",
        "synthetic-merged",
        "synthetic-transformed",
    ):
        snapshots.extend(
            _domain_snapshots(
                strategy_id,
                version="v1",
                effective_from=old_start,
                effective_to=None,
                published_at=old_published,
                suffix="old",
            )
        )
    score_values = {
        "synthetic-active": 90.0,
        "synthetic-closed": 80.0,
        "synthetic-merged": 70.0,
        "synthetic-transformed": 60.0,
    }
    scores = tuple(
        PrecomputedScore(
            score_id=f"score-{strategy_id}-v1",
            strategy_id=strategy_id,
            total_score=value,
            components=(
                ScoreComponent(
                    name="synthetic_total",
                    contribution=value,
                    component_version="synthetic-components-v1",
                ),
            ),
            model_version="synthetic-model-v1",
            provider_id="synthetic-provider",
            provider_snapshot_id="provider-snapshot-v1",
            provider_version="v1",
            score_as_of=old_published,
            published_at=old_published,
            knowledge_at=old_published,
            effective_from=old_start,
            effective_to=None,
            revision_id=(
                "score-revision-r1" if strategy_id == "synthetic-active" else "original"
            ),
        )
        for strategy_id, value in score_values.items()
    ) + (
        PrecomputedScore(
            score_id="score-synthetic-active-v2",
            strategy_id="synthetic-active",
            total_score=88.0,
            components=(
                ScoreComponent(
                    name="synthetic_total",
                    contribution=88.0,
                    component_version="synthetic-components-v1",
                ),
            ),
            model_version="synthetic-model-v1",
            provider_id="synthetic-provider",
            provider_snapshot_id="provider-snapshot-v2",
            provider_version="v2",
            score_as_of=new_published,
            published_at=new_published,
            knowledge_at=new_published,
            effective_from=old_start,
            revision_id="score-revision-r2",
            supersedes_revision_id="score-revision-r1",
        ),
    )
    outcomes = (
        FutureOutcome(
            outcome_id="outcome-active-fold-1",
            strategy_id="synthetic-active",
            window_start=first_fold.outcome_start,
            window_end=first_fold.outcome_end,
            period_returns=(-0.02, 0.03),
            peer_period_returns=(-0.01, 0.01),
        ),
        FutureOutcome(
            outcome_id="outcome-closed-fold-1",
            strategy_id="synthetic-closed",
            window_start=first_fold.outcome_start,
            window_end=first_fold.outcome_end,
            period_returns=(-0.01, 0.01),
            peer_period_returns=(-0.01, 0.01),
        ),
        FutureOutcome(
            outcome_id="outcome-active-fold-2",
            strategy_id="synthetic-active",
            window_start=second_fold.outcome_start,
            window_end=second_fold.outcome_end,
            period_returns=(-0.03, 0.02),
            peer_period_returns=(-0.01, 0.01),
        ),
    )
    return SyntheticWalkForwardFixture(
        config=WalkForwardConfig(folds=(first_fold, second_fold), select_count=2),
        candidates=candidates,
        snapshots=tuple(snapshots),
        outcomes=outcomes,
        precomputed_scores=scores,
    )
