from __future__ import annotations

import copy
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta, tzinfo
from typing import cast

from openfundscore.walk_forward import (
    CandidateFund,
    FoldWindow,
    FutureOutcome,
    LifecycleInterval,
    PrecomputedScore,
    ScoreComponent,
    ScoreResult,
    VersionedSnapshot,
    WalkForwardConfig,
    WalkForwardError,
    run_walk_forward,
)
from openfundscore.walk_forward_io import (
    synthetic_fixture_document,
    walk_forward_from_document,
    walk_forward_input_document,
    walk_forward_report_document,
)


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


class HostileTimezone(tzinfo):
    def __init__(self, exception_type: type[BaseException]) -> None:
        self.exception_type = exception_type

    def utcoffset(self, value):
        raise self.exception_type("private-marker")

    def dst(self, value):
        return timedelta(0)

    def tzname(self, value):
        return "hostile"


class StatefulTimezone(tzinfo):
    def __init__(
        self,
        *,
        offset: timedelta = timedelta(hours=8),
        exception_type: type[BaseException] = RuntimeError,
    ) -> None:
        self.offset = offset
        self.exception_type = exception_type
        self.calls = 0

    def utcoffset(self, value):
        self.calls += 1
        if self.calls > 1:
            raise self.exception_type("private-marker")
        return self.offset

    def dst(self, value):
        return timedelta(0)

    def tzname(self, value):
        return "stateful"


def hostile_datetime(exception_type: type[BaseException]) -> datetime:
    return datetime(2020, 1, 1, tzinfo=HostileTimezone(exception_type))


def stateful_datetime(
    value: str,
    *,
    exception_type: type[BaseException] = RuntimeError,
) -> tuple[datetime, StatefulTimezone]:
    zone = StatefulTimezone(exception_type=exception_type)
    return datetime.fromisoformat(value).replace(tzinfo=zone), zone


class HostileString(str):
    exception_type: type[BaseException]

    def __new__(cls, exception_type: type[BaseException]):
        value = super().__new__(cls, "private-marker")
        value.exception_type = exception_type
        return value

    def encode(self, encoding="utf-8", errors="strict"):
        raise self.exception_type("private-marker")


def snapshot(
    strategy_id: str,
    domain: str,
    value: str | float | bool | None,
    *,
    snapshot_id: str | None = None,
    published_at: str = "2020-12-20T00:00:00Z",
    knowledge_at: str = "2020-12-21T00:00:00Z",
    effective_from: str = "2020-01-01T00:00:00Z",
    effective_to: str | None = None,
) -> VersionedSnapshot:
    return VersionedSnapshot(
        snapshot_id=snapshot_id or f"snap-{strategy_id}-{domain}",
        provider_id="synthetic-provider",
        provider_snapshot_id="provider-snapshot-1",
        provider_version="v1",
        strategy_id=strategy_id,
        domain=domain,
        value=value,
        as_of=dt(published_at),
        published_at=dt(published_at),
        knowledge_at=dt(knowledge_at),
        effective_from=dt(effective_from),
        effective_to=dt(effective_to) if effective_to else None,
    )


def candidate(
    share_class_id: str,
    strategy_id: str,
    *,
    status: str = "active",
) -> CandidateFund:
    return CandidateFund(
        share_class_id=share_class_id,
        strategy_id=strategy_id,
        inception_at=dt("2019-01-01T00:00:00Z"),
        lifecycle=(
            LifecycleInterval(
                status=status,
                effective_from=dt("2019-01-01T00:00:00Z"),
                published_at=dt("2019-01-01T00:00:00Z"),
                knowledge_at=dt("2019-01-01T00:00:00Z"),
            ),
        ),
    )


def fold() -> FoldWindow:
    return FoldWindow(
        fold_id="fold-1",
        train_start=dt("2019-01-01T00:00:00Z"),
        train_end=dt("2019-12-31T00:00:00Z"),
        validation_start=dt("2020-01-01T00:00:00Z"),
        validation_end=dt("2020-11-30T00:00:00Z"),
        decision_at=dt("2021-01-01T00:00:00Z"),
        outcome_start=dt("2021-01-02T00:00:00Z"),
        outcome_end=dt("2021-01-31T00:00:00Z"),
        embargo_seconds=86_400,
    )


def fold_at(
    fold_id: str,
    decision_at: str,
    outcome_start: str,
    outcome_end: str,
) -> FoldWindow:
    return FoldWindow(
        fold_id=fold_id,
        train_start=dt("2019-01-01T00:00:00Z"),
        train_end=dt("2019-12-31T00:00:00Z"),
        validation_start=dt("2020-01-01T00:00:00Z"),
        validation_end=dt("2020-11-30T00:00:00Z"),
        decision_at=dt(decision_at),
        outcome_start=dt(outcome_start),
        outcome_end=dt(outcome_end),
        embargo_seconds=86_400,
    )


def required_snapshots(strategy_id: str) -> tuple[VersionedSnapshot, ...]:
    return tuple(
        snapshot(strategy_id, domain, value)
        for domain, value in (
            ("classification", "equity"),
            ("benchmark", "benchmark-equity"),
            ("manager", "manager-old"),
            ("fee_bps", 100),
            ("availability", True),
        )
    )


def score_result(
    total_score: float,
    components: tuple[tuple[str, float | None], ...],
) -> ScoreResult:
    return ScoreResult(
        audit_id=f"callback-{total_score}-{components!r}",
        revision_id="callback-revision-1",
        total_score=total_score,
        components=tuple(
            ScoreComponent(
                name=name,
                contribution=contribution,
                component_version="components-v1",
            )
            for name, contribution in components
        ),
        model_version="model-v1",
        provider_id="synthetic-provider",
        provider_snapshot_id="provider-snapshot-1",
        provider_version="v1",
        score_as_of=dt("2020-12-20T00:00:00Z"),
        published_at=dt("2020-12-20T00:00:00Z"),
        knowledge_at=dt("2020-12-21T00:00:00Z"),
    )


class WalkForwardTests(unittest.TestCase):
    def assert_walk_forward_error(self, code, action) -> None:
        with self.assertRaises(WalkForwardError) as raised:
            action()
        self.assertEqual(raised.exception.code, code)
        self.assertNotIn("private-marker", str(raised.exception))

    def assert_timestamp_error(self, path, action) -> None:
        with self.assertRaises(WalkForwardError) as raised:
            action()
        self.assertEqual(raised.exception.code, "invalid_timestamp")
        self.assertEqual(raised.exception.path, path)
        self.assertNotIn("private-marker", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_hostile_timezone_constructor_exceptions_are_stably_redacted(self) -> None:
        for exception_type in (RuntimeError, OverflowError, OSError, ValueError):
            with self.subTest(exception_type=exception_type.__name__):
                self.assert_timestamp_error(
                    "$.lifecycle.effective_from",
                    lambda exception_type=exception_type: LifecycleInterval(
                        status="active",
                        effective_from=hostile_datetime(exception_type),
                        published_at=dt("2020-01-01T00:00:00Z"),
                        knowledge_at=dt("2020-01-01T00:00:00Z"),
                    ),
                )

        for exception_type in (KeyboardInterrupt, SystemExit):
            with (
                self.subTest(exception_type=exception_type.__name__),
                self.assertRaises(exception_type),
            ):
                LifecycleInterval(
                    status="active",
                    effective_from=hostile_datetime(exception_type),
                    published_at=dt("2020-01-01T00:00:00Z"),
                    knowledge_at=dt("2020-01-01T00:00:00Z"),
                )

    def test_lifecycle_constructor_canonicalizes_stateful_timezone_once(self) -> None:
        effective_from, zone = stateful_datetime("2020-01-01T08:00:00")

        interval = LifecycleInterval(
            status="active",
            effective_from=effective_from,
            effective_to=dt("2021-01-01T00:00:00Z"),
            published_at=dt("2020-01-01T00:00:00Z"),
            knowledge_at=dt("2020-01-01T00:00:00Z"),
        )

        self.assertEqual(zone.calls, 1)
        self.assertIs(interval.effective_from.tzinfo, UTC)
        self.assertEqual(interval.effective_from, dt("2020-01-01T00:00:00Z"))

    def test_snapshot_constructor_and_run_canonicalize_stateful_timezone_once(
        self,
    ) -> None:
        as_of, constructor_zone = stateful_datetime("2020-12-20T08:00:00")
        constructed = replace(required_snapshots("alpha")[0], as_of=as_of)
        self.assertEqual(constructor_zone.calls, 1)
        self.assertIs(constructed.as_of.tzinfo, UTC)

        poisoned_snapshot = required_snapshots("alpha")[0]
        knowledge_at, run_zone = stateful_datetime("2020-12-21T08:00:00")
        object.__setattr__(poisoned_snapshot, "knowledge_at", knowledge_at)
        report = run_walk_forward(
            WalkForwardConfig(folds=(fold(),), select_count=1),
            candidates=(candidate("alpha-A", "alpha"),),
            snapshots=(poisoned_snapshot,) + required_snapshots("alpha")[1:],
            outcomes=(),
            scorer=lambda view: score_result(1.0, (("total", 1.0),)),
        )

        self.assertEqual(run_zone.calls, 1)
        self.assertIs(poisoned_snapshot.knowledge_at.tzinfo, UTC)
        self.assertIs(report.folds[0].audit_trail[0].knowledge_at.tzinfo, UTC)

    def test_callback_score_and_report_retain_only_fixed_utc_timestamps(self) -> None:
        callback_zone: StatefulTimezone | None = None

        def scorer(view):
            nonlocal callback_zone
            audit = score_result(1.0, (("total", 1.0),))
            knowledge_at, callback_zone = stateful_datetime("2020-12-21T08:00:00")
            object.__setattr__(audit, "knowledge_at", knowledge_at)
            return audit

        report = run_walk_forward(
            WalkForwardConfig(folds=(fold(),), select_count=1),
            candidates=(candidate("alpha-A", "alpha"),),
            snapshots=required_snapshots("alpha"),
            outcomes=(),
            scorer=scorer,
        )

        self.assertIsNotNone(callback_zone)
        self.assertEqual(cast(StatefulTimezone, callback_zone).calls, 1)
        audit = report.folds[0].score_audit_trail[0]
        self.assertIs(audit.knowledge_at.tzinfo, UTC)
        self.assertIs(report.folds[0].decision_at.tzinfo, UTC)
        document = walk_forward_report_document(report)
        report_document = cast(dict, document["report"])
        fold_document = cast(dict, cast(list, report_document["folds"])[0])
        self.assertEqual(fold_document["decision_at"], "2021-01-01T00:00:00Z")

    def test_hostile_timezone_run_and_report_paths_are_stably_redacted(self) -> None:
        poisoned_snapshot = required_snapshots("alpha")[0]
        object.__setattr__(
            poisoned_snapshot,
            "knowledge_at",
            hostile_datetime(RuntimeError),
        )
        self.assert_timestamp_error(
            "$.snapshot.knowledge_at",
            lambda: run_walk_forward(
                WalkForwardConfig(folds=(fold(),), select_count=1),
                candidates=(candidate("alpha-A", "alpha"),),
                snapshots=(poisoned_snapshot,) + required_snapshots("alpha")[1:],
                outcomes=(),
                scorer=lambda view: score_result(1.0, (("total", 1.0),)),
            ),
        )

        report = run_walk_forward(
            WalkForwardConfig(folds=(fold(),), select_count=1),
            candidates=(candidate("alpha-A", "alpha"),),
            snapshots=required_snapshots("alpha"),
            outcomes=(),
            scorer=lambda view: score_result(1.0, (("total", 1.0),)),
        )
        poisoned_report = copy.deepcopy(report)
        object.__setattr__(
            poisoned_report.folds[0],
            "decision_at",
            hostile_datetime(OSError),
        )
        self.assert_timestamp_error(
            "$report",
            lambda: walk_forward_report_document(poisoned_report),
        )

    def test_hostile_nested_timestamps_are_redacted_by_parent_constructors(
        self,
    ) -> None:
        poisoned_lifecycle = LifecycleInterval(
            status="active",
            effective_from=dt("2019-01-01T00:00:00Z"),
            published_at=dt("2019-01-01T00:00:00Z"),
            knowledge_at=dt("2019-01-01T00:00:00Z"),
        )
        object.__setattr__(
            poisoned_lifecycle,
            "effective_from",
            hostile_datetime(RuntimeError),
        )
        self.assert_timestamp_error(
            "$.lifecycle.effective_from",
            lambda: CandidateFund(
                share_class_id="alpha-A",
                strategy_id="alpha",
                inception_at=dt("2019-01-01T00:00:00Z"),
                lifecycle=(poisoned_lifecycle,),
            ),
        )

        poisoned_fold = fold()
        object.__setattr__(
            poisoned_fold,
            "decision_at",
            hostile_datetime(OverflowError),
        )
        self.assert_timestamp_error(
            "$.fold.timestamps[4]",
            lambda: WalkForwardConfig(folds=(poisoned_fold,), select_count=1),
        )

    def test_callback_receives_only_point_in_time_data_and_share_classes_are_deduplicated(
        self,
    ) -> None:
        import openfundscore

        self.assertIs(openfundscore.run_walk_forward, run_walk_forward)
        self.assertIs(openfundscore.ScoreComponent, ScoreComponent)
        self.assertIs(openfundscore.ScoreResult, ScoreResult)
        seen = []

        def scorer(view):
            seen.append(view)
            self.assertFalse(hasattr(view, "outcomes"))
            self.assertEqual(
                {item.domain for item in view.snapshots},
                {"availability", "benchmark", "classification", "fee_bps", "manager"},
            )
            return score_result(80.0, (("total", 80.0),))

        report = run_walk_forward(
            WalkForwardConfig(folds=(fold(),), select_count=1),
            candidates=(candidate("alpha-A", "alpha"), candidate("alpha-C", "alpha")),
            snapshots=required_snapshots("alpha"),
            outcomes=(),
            scorer=scorer,
        )

        self.assertEqual(len(seen), 1)
        self.assertEqual(report.folds[0].universe_count, 1)
        self.assertEqual(report.folds[0].eligible_count, 1)
        self.assertEqual(report.folds[0].selected_strategy_ids, ("alpha",))
        self.assertEqual(
            report.folds[0].audit_snapshot_ids,
            tuple(sorted(item.snapshot_id for item in required_snapshots("alpha"))),
        )

    def test_historical_versions_and_terminal_lifecycle_are_preserved(self) -> None:
        historical = required_snapshots("alpha")
        future_manager = snapshot(
            "alpha",
            "manager",
            "manager-new",
            snapshot_id="manager-future-publication",
            published_at="2021-02-05T00:00:00Z",
            knowledge_at="2021-02-06T00:00:00Z",
            effective_from="2021-01-15T00:00:00Z",
        )
        fund = CandidateFund(
            share_class_id="alpha-A",
            strategy_id="alpha",
            inception_at=dt("2019-01-01T00:00:00Z"),
            lifecycle=(
                LifecycleInterval(
                    status="active",
                    effective_from=dt("2019-01-01T00:00:00Z"),
                    effective_to=dt("2021-02-01T00:00:00Z"),
                    published_at=dt("2019-01-01T00:00:00Z"),
                    knowledge_at=dt("2019-01-01T00:00:00Z"),
                ),
                LifecycleInterval(
                    status="transformed",
                    effective_from=dt("2021-02-01T00:00:00Z"),
                    published_at=dt("2021-02-01T00:00:00Z"),
                    knowledge_at=dt("2021-02-01T00:00:00Z"),
                    successor_strategy_id="alpha-successor",
                ),
            ),
        )
        views = []

        report = run_walk_forward(
            WalkForwardConfig(
                folds=(
                    fold(),
                    fold_at(
                        "fold-2",
                        "2021-03-01T00:00:00Z",
                        "2021-03-02T00:00:00Z",
                        "2021-03-31T00:00:00Z",
                    ),
                ),
                select_count=1,
            ),
            candidates=(fund,),
            snapshots=historical + (future_manager,),
            outcomes=(),
            scorer=lambda view: (
                views.append(view) or score_result(70.0, (("total", 70.0),))
            ),
        )

        self.assertEqual(len(views), 1)
        self.assertEqual(
            next(item.value for item in views[0].snapshots if item.domain == "manager"),
            "manager-old",
        )
        self.assertEqual(report.folds[1].universe_count, 1)
        self.assertEqual(report.folds[1].retained_terminal_count, 1)
        self.assertEqual(report.folds[1].eligible_count, 0)
        self.assertEqual(report.folds[1].failures[0].code, "terminal_lifecycle")
        self.assertEqual(
            report.folds[0].audit_trail[0].provider_snapshot_id,
            "provider-snapshot-1",
        )

    def test_snapshot_revision_chain_selects_only_the_revision_known_at_decision(
        self,
    ) -> None:
        def revision(
            domain: str,
            value: str | float | bool,
            *,
            revision_id: str,
            supersedes_revision_id: str | None,
            published_at: str,
            provider_version: str,
        ) -> VersionedSnapshot:
            timestamp = dt(published_at)
            return VersionedSnapshot(
                snapshot_id=f"snapshot-{domain}-{revision_id}",
                revision_id=revision_id,
                supersedes_revision_id=supersedes_revision_id,
                provider_id="synthetic-provider",
                provider_snapshot_id=f"provider-snapshot-{provider_version}",
                provider_version=provider_version,
                strategy_id="alpha",
                domain=domain,
                value=value,
                as_of=dt("2020-12-20T00:00:00Z"),
                published_at=timestamp,
                knowledge_at=timestamp,
                effective_from=dt("2020-01-01T00:00:00Z"),
            )

        snapshots = tuple(
            item
            for domain, old_value, revised_value in (
                ("classification", "equity", "mixed"),
                ("benchmark", "benchmark-old", "benchmark-revised"),
                ("manager", "manager-old", "manager-revised"),
                ("fee_bps", 100.0, 80.0),
                ("availability", True, True),
            )
            for item in (
                revision(
                    domain,
                    old_value,
                    revision_id=f"{domain}-r1",
                    supersedes_revision_id=None,
                    published_at="2020-12-20T00:00:00Z",
                    provider_version="v1",
                ),
                revision(
                    domain,
                    revised_value,
                    revision_id=f"{domain}-r2",
                    supersedes_revision_id=f"{domain}-r1",
                    published_at="2021-02-20T00:00:00Z",
                    provider_version="v2",
                ),
            )
        )
        decisions = (
            fold(),
            fold_at(
                "fold-2",
                "2021-03-01T00:00:00Z",
                "2021-03-02T00:00:00Z",
                "2021-03-31T00:00:00Z",
            ),
        )
        seen: list[tuple[str, tuple[str, ...]]] = []

        def scorer(view):
            revisions = tuple(sorted(item.revision_id for item in view.snapshots))
            seen.append((view.fold.fold_id, revisions))
            provider_version = "v1" if view.fold.fold_id == "fold-1" else "v2"
            return replace(
                score_result(1.0, (("total", 1.0),)),
                audit_id=f"callback-{provider_version}",
                provider_snapshot_id=f"provider-snapshot-{provider_version}",
                provider_version=provider_version,
                score_as_of=max(item.as_of for item in view.snapshots),
                published_at=max(item.published_at for item in view.snapshots),
                knowledge_at=max(item.knowledge_at for item in view.snapshots),
            )

        report = run_walk_forward(
            WalkForwardConfig(folds=decisions, select_count=1),
            candidates=(candidate("alpha-A", "alpha"),),
            snapshots=snapshots,
            outcomes=(),
            scorer=scorer,
        )

        self.assertEqual(
            seen,
            [
                (
                    "fold-1",
                    tuple(
                        f"{domain}-r1"
                        for domain in sorted({item.domain for item in snapshots})
                    ),
                ),
                (
                    "fold-2",
                    tuple(
                        f"{domain}-r2"
                        for domain in sorted({item.domain for item in snapshots})
                    ),
                ),
            ],
        )
        self.assertEqual(report.folds[0].eligible_count, 1)
        self.assertEqual(report.folds[1].eligible_count, 1)

    def test_snapshot_revision_chain_rejects_dangling_forks_duplicates_and_future_supersedes(
        self,
    ) -> None:
        base = replace(
            required_snapshots("alpha")[2],
            snapshot_id="manager-r1-snapshot",
            revision_id="manager-r1",
        )
        child = replace(
            base,
            snapshot_id="manager-r2-snapshot",
            revision_id="manager-r2",
            supersedes_revision_id="manager-r1",
            published_at=dt("2020-12-22T00:00:00Z"),
            knowledge_at=dt("2020-12-23T00:00:00Z"),
        )
        cases = (
            (
                "revision_chain_conflict",
                (replace(child, supersedes_revision_id="missing-revision"),),
            ),
            (
                "revision_chain_conflict",
                (
                    base,
                    child,
                    replace(
                        child,
                        snapshot_id="manager-r3-snapshot",
                        revision_id="manager-r3",
                    ),
                ),
            ),
            (
                "revision_chain_conflict",
                (
                    base,
                    child,
                    replace(child, snapshot_id="manager-r2-duplicate-snapshot"),
                ),
            ),
            (
                "revision_chronology",
                (
                    replace(
                        base,
                        published_at=dt("2020-12-24T00:00:00Z"),
                        knowledge_at=dt("2020-12-25T00:00:00Z"),
                    ),
                    child,
                ),
            ),
        )
        non_manager = tuple(
            item for item in required_snapshots("alpha") if item.domain != "manager"
        )
        for code, manager_records in cases:
            with self.subTest(code=code, count=len(manager_records)):
                self.assert_walk_forward_error(
                    code,
                    lambda manager_records=manager_records: run_walk_forward(
                        WalkForwardConfig(folds=(fold(),), select_count=1),
                        candidates=(candidate("alpha-A", "alpha"),),
                        snapshots=non_manager + manager_records,
                        outcomes=(),
                        scorer=lambda view: score_result(1.0, (("total", 1.0),)),
                    ),
                )

    def test_lifecycle_is_resolved_by_knowledge_then_effective_time(self) -> None:
        fund = CandidateFund(
            share_class_id="alpha-A",
            strategy_id="alpha",
            inception_at=dt("2019-01-01T00:00:00Z"),
            lifecycle=(
                LifecycleInterval(
                    revision_id="active-r1",
                    status="active",
                    effective_from=dt("2019-01-01T00:00:00Z"),
                    effective_to=dt("2021-04-01T00:00:00Z"),
                    published_at=dt("2019-01-01T00:00:00Z"),
                    knowledge_at=dt("2019-01-01T00:00:00Z"),
                ),
                LifecycleInterval(
                    revision_id="active-r2",
                    supersedes_revision_id="active-r1",
                    status="closed",
                    effective_from=dt("2019-01-01T00:00:00Z"),
                    effective_to=dt("2021-04-01T00:00:00Z"),
                    published_at=dt("2021-01-02T00:00:00Z"),
                    knowledge_at=dt("2021-01-02T00:00:00Z"),
                ),
                LifecycleInterval(
                    status="transformed",
                    effective_from=dt("2021-04-01T00:00:00Z"),
                    published_at=dt("2020-12-20T00:00:00Z"),
                    knowledge_at=dt("2020-12-21T00:00:00Z"),
                    successor_strategy_id="alpha-successor",
                ),
            ),
        )
        seen: list[str] = []

        report = run_walk_forward(
            WalkForwardConfig(folds=(fold(),), select_count=1),
            candidates=(fund,),
            snapshots=required_snapshots("alpha"),
            outcomes=(),
            scorer=lambda view: (
                seen.append(view.strategy_id) or score_result(1.0, (("total", 1.0),))
            ),
        )

        self.assertEqual(seen, ["alpha"])
        self.assertEqual(report.folds[0].eligible_count, 1)
        self.assertEqual(
            tuple(item.status for _, item in report.folds[0].audit_lifecycle),
            ("active", "transformed"),
        )
        self.assertGreater(
            report.folds[0].audit_lifecycle[1][1].effective_from,
            fold().decision_at,
        )

    def test_lifecycle_revision_replaces_same_effective_state_only_after_publication(
        self,
    ) -> None:
        fund = CandidateFund(
            share_class_id="alpha-A",
            strategy_id="alpha",
            inception_at=dt("2019-01-01T00:00:00Z"),
            lifecycle=(
                LifecycleInterval(
                    revision_id="lifecycle-r1",
                    supersedes_revision_id=None,
                    status="active",
                    effective_from=dt("2019-01-01T00:00:00Z"),
                    published_at=dt("2019-01-01T00:00:00Z"),
                    knowledge_at=dt("2019-01-01T00:00:00Z"),
                ),
                LifecycleInterval(
                    revision_id="lifecycle-r2",
                    supersedes_revision_id="lifecycle-r1",
                    status="closed",
                    effective_from=dt("2019-01-01T00:00:00Z"),
                    published_at=dt("2021-02-20T00:00:00Z"),
                    knowledge_at=dt("2021-02-20T00:00:00Z"),
                ),
            ),
        )
        report = run_walk_forward(
            WalkForwardConfig(
                folds=(
                    fold(),
                    fold_at(
                        "fold-2",
                        "2021-03-01T00:00:00Z",
                        "2021-03-02T00:00:00Z",
                        "2021-03-31T00:00:00Z",
                    ),
                ),
                select_count=1,
            ),
            candidates=(fund,),
            snapshots=required_snapshots("alpha"),
            outcomes=(),
            scorer=lambda view: score_result(1.0, (("total", 1.0),)),
        )

        self.assertEqual(report.folds[0].eligible_count, 1)
        self.assertEqual(report.folds[1].retained_terminal_count, 1)
        self.assertEqual(report.folds[1].failures[0].code, "terminal_lifecycle")

    def test_open_ended_lifecycle_followed_by_later_interval_is_rejected(self) -> None:
        self.assert_walk_forward_error(
            "overlapping_lifecycle",
            lambda: CandidateFund(
                share_class_id="alpha-A",
                strategy_id="alpha",
                inception_at=dt("2018-01-01T00:00:00Z"),
                lifecycle=(
                    LifecycleInterval(
                        status="active",
                        effective_from=dt("2018-01-01T00:00:00Z"),
                        published_at=dt("2018-01-01T00:00:00Z"),
                        knowledge_at=dt("2018-01-01T00:00:00Z"),
                    ),
                    LifecycleInterval(
                        status="closed",
                        effective_from=dt("2020-01-01T00:00:00Z"),
                        published_at=dt("2020-01-01T00:00:00Z"),
                        knowledge_at=dt("2020-01-01T00:00:00Z"),
                    ),
                ),
            ),
        )

    def test_adjacent_lifecycle_intervals_are_valid_at_exact_boundary(self) -> None:
        boundary = dt("2020-01-01T00:00:00Z")
        fund = CandidateFund(
            share_class_id="alpha-A",
            strategy_id="alpha",
            inception_at=dt("2018-01-01T00:00:00Z"),
            lifecycle=(
                LifecycleInterval(
                    status="active",
                    effective_from=dt("2018-01-01T00:00:00Z"),
                    effective_to=boundary,
                    published_at=dt("2018-01-01T00:00:00Z"),
                    knowledge_at=dt("2018-01-01T00:00:00Z"),
                ),
                LifecycleInterval(
                    status="closed",
                    effective_from=boundary,
                    published_at=boundary,
                    knowledge_at=boundary,
                ),
            ),
        )

        self.assertEqual(
            fund.lifecycle[0].effective_to, fund.lifecycle[1].effective_from
        )

    def test_same_effective_range_requires_explicit_revision_replacement(self) -> None:
        fund = CandidateFund(
            share_class_id="alpha-A",
            strategy_id="alpha",
            inception_at=dt("2018-01-01T00:00:00Z"),
            lifecycle=(
                LifecycleInterval(
                    revision_id="lifecycle-r1",
                    status="active",
                    effective_from=dt("2018-01-01T00:00:00Z"),
                    published_at=dt("2018-01-01T00:00:00Z"),
                    knowledge_at=dt("2018-01-01T00:00:00Z"),
                ),
                LifecycleInterval(
                    revision_id="lifecycle-r2",
                    supersedes_revision_id="lifecycle-r1",
                    status="closed",
                    effective_from=dt("2018-01-01T00:00:00Z"),
                    published_at=dt("2020-01-01T00:00:00Z"),
                    knowledge_at=dt("2020-01-01T00:00:00Z"),
                ),
            ),
        )

        self.assertEqual(fund.lifecycle[1].supersedes_revision_id, "lifecycle-r1")

    def test_run_rejects_post_init_overlapping_lifecycle_mutation(self) -> None:
        fund = candidate("alpha-A", "alpha")
        object.__setattr__(
            fund,
            "lifecycle",
            (
                LifecycleInterval(
                    status="active",
                    effective_from=dt("2018-01-01T00:00:00Z"),
                    effective_to=dt("2022-01-01T00:00:00Z"),
                    published_at=dt("2018-01-01T00:00:00Z"),
                    knowledge_at=dt("2018-01-01T00:00:00Z"),
                ),
                LifecycleInterval(
                    status="closed",
                    effective_from=dt("2020-01-01T00:00:00Z"),
                    effective_to=dt("2023-01-01T00:00:00Z"),
                    published_at=dt("2020-01-01T00:00:00Z"),
                    knowledge_at=dt("2020-01-01T00:00:00Z"),
                ),
            ),
        )

        with self.assertRaises(WalkForwardError) as raised:
            run_walk_forward(
                WalkForwardConfig(folds=(fold(),), select_count=1),
                candidates=(fund,),
                snapshots=required_snapshots("alpha"),
                outcomes=(),
                scorer=lambda view: score_result(1.0, (("total", 1.0),)),
            )
        self.assertEqual(raised.exception.code, "overlapping_lifecycle")
        self.assertEqual(raised.exception.path, "$.candidate.lifecycle")
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_run_rejects_post_init_lifecycle_revision_chain_mutations(self) -> None:
        root = LifecycleInterval(
            revision_id="lifecycle-r1",
            status="active",
            effective_from=dt("2018-01-01T00:00:00Z"),
            published_at=dt("2018-01-01T00:00:00Z"),
            knowledge_at=dt("2018-01-01T00:00:00Z"),
        )
        child = replace(
            root,
            revision_id="lifecycle-r2",
            supersedes_revision_id="lifecycle-r1",
            status="closed",
            published_at=dt("2020-01-01T00:00:00Z"),
            knowledge_at=dt("2020-01-01T00:00:00Z"),
        )
        cases = (
            (replace(child, supersedes_revision_id="missing-revision"),),
            (
                root,
                child,
                replace(
                    child,
                    revision_id="lifecycle-r3",
                    published_at=dt("2020-02-01T00:00:00Z"),
                    knowledge_at=dt("2020-02-01T00:00:00Z"),
                ),
            ),
            (root, replace(root, status="closed")),
        )

        for lifecycle in cases:
            with self.subTest(revisions=tuple(item.revision_id for item in lifecycle)):
                fund = candidate("alpha-A", "alpha")
                object.__setattr__(fund, "lifecycle", lifecycle)
                with self.assertRaises(WalkForwardError) as raised:
                    run_walk_forward(
                        WalkForwardConfig(folds=(fold(),), select_count=1),
                        candidates=(fund,),
                        snapshots=required_snapshots("alpha"),
                        outcomes=(),
                        scorer=lambda view: score_result(1.0, (("total", 1.0),)),
                    )
                self.assertEqual(raised.exception.code, "revision_chain_conflict")
                self.assertEqual(raised.exception.path, "$.candidate.lifecycle")
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)

    def test_conflicting_or_unknown_required_snapshots_fail_closed(self) -> None:
        conflicting = required_snapshots("alpha") + (
            snapshot(
                "alpha",
                "manager",
                "manager-conflict",
                snapshot_id="manager-conflict",
            ),
        )
        self.assert_walk_forward_error(
            "revision_chain_conflict",
            lambda: run_walk_forward(
                WalkForwardConfig(folds=(fold(),), select_count=1),
                candidates=(candidate("alpha-A", "alpha"),),
                snapshots=conflicting,
                outcomes=(),
                scorer=lambda view: score_result(99.0, (("total", 99.0),)),
            ),
        )

        unknown = list(required_snapshots("alpha"))
        unknown[2] = snapshot("alpha", "manager", None, snapshot_id="unknown-manager")
        unknown_report = run_walk_forward(
            WalkForwardConfig(folds=(fold(),), select_count=1),
            candidates=(candidate("alpha-A", "alpha"),),
            snapshots=tuple(unknown),
            outcomes=(),
            scorer=lambda view: 99,
        )
        self.assertEqual(unknown_report.folds[0].failures[0].code, "snapshot_unknown")

    def test_reports_stability_turnover_breadth_outcomes_drawdown_and_uncertainty(
        self,
    ) -> None:
        second_fold = FoldWindow(
            fold_id="fold-2",
            train_start=dt("2019-02-01T00:00:00Z"),
            train_end=dt("2020-01-31T00:00:00Z"),
            validation_start=dt("2020-02-01T00:00:00Z"),
            validation_end=dt("2020-12-31T00:00:00Z"),
            decision_at=dt("2021-02-01T00:00:00Z"),
            outcome_start=dt("2021-02-02T00:00:00Z"),
            outcome_end=dt("2021-02-28T00:00:00Z"),
            embargo_seconds=86_400,
        )
        snapshots = []
        for strategy_id, classification in (
            ("alpha", "equity"),
            ("beta", "bond"),
            ("gamma", "equity"),
        ):
            items = list(required_snapshots(strategy_id))
            items[0] = snapshot(strategy_id, "classification", classification)
            snapshots.extend(items)
        scores = {
            "fold-1": {"alpha": 90, "beta": 80, "gamma": 70},
            "fold-2": {"alpha": 85, "beta": 60, "gamma": 84},
        }
        outcomes = (
            FutureOutcome(
                outcome_id="o1-alpha",
                strategy_id="alpha",
                window_start=fold().outcome_start,
                window_end=fold().outcome_end,
                period_returns=(-0.10, 0.20),
                peer_period_returns=(0.0, 0.0),
            ),
            FutureOutcome(
                outcome_id="o1-beta",
                strategy_id="beta",
                window_start=fold().outcome_start,
                window_end=fold().outcome_end,
                period_returns=(0.0, 0.0),
                peer_period_returns=(0.0, 0.0),
            ),
            FutureOutcome(
                outcome_id="o2-alpha",
                strategy_id="alpha",
                window_start=second_fold.outcome_start,
                window_end=second_fold.outcome_end,
                period_returns=(-0.05, 0.01),
                peer_period_returns=(0.0, 0.0),
            ),
            FutureOutcome(
                outcome_id="o2-gamma",
                strategy_id="gamma",
                window_start=second_fold.outcome_start,
                window_end=second_fold.outcome_end,
                period_returns=(-0.05, 0.01),
                peer_period_returns=(0.0, 0.0),
            ),
        )

        report = run_walk_forward(
            WalkForwardConfig(folds=(fold(), second_fold), select_count=2),
            candidates=tuple(candidate(f"{item}-A", item) for item in scores["fold-1"]),
            snapshots=tuple(snapshots),
            outcomes=outcomes,
            scorer=lambda view: score_result(
                scores[view.fold.fold_id][view.strategy_id],
                (("total", scores[view.fold.fold_id][view.strategy_id]),),
            ),
        )

        first, second = report.folds
        self.assertEqual(first.selection_breadth, (("bond", 1), ("equity", 1)))
        self.assertEqual(first.score_stability.status, "insufficient_prior_fold")
        self.assertEqual(second.score_stability.metric, "spearman_rank_correlation")
        self.assertAlmostEqual(second.score_stability.value, 0.5)
        self.assertEqual(second.selection_turnover.metric, "jaccard_distance")
        self.assertAlmostEqual(second.selection_turnover.value, 2 / 3)
        self.assertAlmostEqual(first.outcome.mean_peer_relative_return, 0.04)
        self.assertEqual(first.outcome.uncertainty.status, "estimated")
        self.assertEqual(first.wealth.wealth_curve[0], 1.0)
        self.assertAlmostEqual(first.wealth.max_drawdown, -0.05)
        self.assertEqual(first.wealth.recovery_periods, 1)
        self.assertEqual(report.summary.fold_count, 2)
        self.assertLess(report.summary.wealth.max_drawdown, 0.0)
        self.assertEqual(
            report.summary.disclaimer, "research_only_not_a_return_guarantee"
        )

    def test_component_correlation_and_leave_one_out_sensitivity_are_diagnostic(
        self,
    ) -> None:
        strategies = ("alpha", "beta", "gamma")
        audits = {
            "alpha": score_result(90.0, (("quality", 60.0), ("risk", 30.0))),
            "beta": score_result(80.0, (("quality", 45.0), ("risk", 35.0))),
            "gamma": score_result(70.0, (("quality", 20.0), ("risk", 50.0))),
        }
        report = run_walk_forward(
            WalkForwardConfig(folds=(fold(),), select_count=2),
            candidates=tuple(candidate(f"{item}-A", item) for item in strategies),
            snapshots=tuple(
                point
                for strategy_id in strategies
                for point in required_snapshots(strategy_id)
            ),
            outcomes=(),
            scorer=lambda view: audits[view.strategy_id],
        )

        diagnostics = report.folds[0].component_diagnostics
        self.assertEqual(
            tuple(
                (item.component_name, item.sample_size, item.missing_count)
                for item in diagnostics.coverage
            ),
            (("quality", 3, 0), ("risk", 3, 0)),
        )
        quality_risk = next(
            item
            for item in diagnostics.correlations
            if (item.left_component, item.right_component) == ("quality", "risk")
        )
        self.assertEqual(quality_risk.method, "pearson_pairwise_complete")
        self.assertEqual(quality_risk.sample_size, 3)
        self.assertAlmostEqual(quality_risk.value, -0.9905360646879089)
        risk_omitted = next(
            item
            for item in report.folds[0].sensitivity.scenarios
            if item.omitted_component == "risk"
        )
        self.assertEqual(risk_omitted.method, "leave_one_component_out_no_refit")
        self.assertEqual(risk_omitted.baseline_selected_strategy_ids, ("alpha", "beta"))
        self.assertEqual(
            risk_omitted.perturbed_selected_strategy_ids, ("alpha", "beta")
        )
        self.assertEqual(risk_omitted.selection_turnover.value, 0.0)
        self.assertEqual(
            report.summary.component_diagnostics.coverage[0].sample_size, 3
        )
        self.assertEqual(report.summary.sensitivity[0].fold_count, 1)

    def test_sensitivity_recomputes_ranking_without_using_future_outcomes(self) -> None:
        audits = {
            "alpha": score_result(
                10.0,
                (("base", 4.0), ("boost", 6.0), ("constant", 0.0)),
            ),
            "beta": score_result(
                9.0,
                (("base", 9.0), ("boost", 0.0), ("constant", 0.0)),
            ),
            "gamma": score_result(
                8.0,
                (("base", 8.0), ("boost", 0.0), ("constant", 0.0)),
            ),
        }

        def evaluate(future_return: float):
            return run_walk_forward(
                WalkForwardConfig(folds=(fold(),), select_count=1),
                candidates=tuple(
                    candidate(f"{strategy_id}-A", strategy_id) for strategy_id in audits
                ),
                snapshots=tuple(
                    point
                    for strategy_id in audits
                    for point in required_snapshots(strategy_id)
                ),
                outcomes=(
                    FutureOutcome(
                        outcome_id="alpha-future",
                        strategy_id="alpha",
                        window_start=fold().outcome_start,
                        window_end=fold().outcome_end,
                        period_returns=(future_return,),
                        peer_period_returns=(0.0,),
                    ),
                ),
                scorer=lambda view: audits[view.strategy_id],
            )

        positive = evaluate(1.0)
        negative = evaluate(-1.0)
        scenario = next(
            item
            for item in positive.folds[0].sensitivity.scenarios
            if item.omitted_component == "boost"
        )
        self.assertEqual(scenario.baseline_selected_strategy_ids, ("alpha",))
        self.assertEqual(scenario.perturbed_selected_strategy_ids, ("beta",))
        self.assertEqual(
            scenario.baseline_ranks,
            (("alpha", 1.0), ("beta", 2.0), ("gamma", 3.0)),
        )
        self.assertEqual(
            scenario.perturbed_ranks,
            (("alpha", 3.0), ("beta", 1.0), ("gamma", 2.0)),
        )
        self.assertEqual(scenario.selection_turnover.sample_size, 2)
        self.assertEqual(scenario.selection_turnover.value, 1.0)
        self.assertEqual(scenario.rank_correlation.sample_size, 3)
        self.assertEqual(scenario.rank_correlation.value, -0.5)
        self.assertEqual(scenario.selected_mean_score_delta, -1.0)
        self.assertEqual(positive.folds[0].sensitivity, negative.folds[0].sensitivity)
        self.assertEqual(positive.summary.sensitivity, negative.summary.sensitivity)

    def test_component_diagnostics_report_missing_and_constant_statuses_per_scope(
        self,
    ) -> None:
        audits = {
            "alpha": score_result(10.0, (("constant", 5.0), ("optional", 5.0))),
            "beta": score_result(9.0, (("constant", 5.0), ("optional", None))),
            "gamma": score_result(8.0, (("constant", 5.0), ("optional", 3.0))),
        }
        report = run_walk_forward(
            WalkForwardConfig(folds=(fold(),), select_count=1),
            candidates=tuple(
                candidate(f"{strategy_id}-A", strategy_id) for strategy_id in audits
            ),
            snapshots=tuple(
                point
                for strategy_id in audits
                for point in required_snapshots(strategy_id)
            ),
            outcomes=(),
            scorer=lambda view: audits[view.strategy_id],
        )

        for diagnostics in (
            report.folds[0].component_diagnostics,
            report.summary.component_diagnostics,
        ):
            optional = next(
                item
                for item in diagnostics.coverage
                if item.component_name == "optional"
            )
            self.assertEqual(optional.status, "partial")
            self.assertEqual(optional.sample_size, 2)
            self.assertEqual(optional.missing_count, 1)
            constant = next(
                item
                for item in diagnostics.correlations
                if item.left_component == item.right_component == "constant"
            )
            self.assertEqual(constant.method, "pearson_pairwise_complete")
            self.assertEqual(constant.sample_size, 3)
            self.assertEqual(constant.status, "constant_component")
            self.assertIsNone(constant.value)
        optional_sensitivity = next(
            item
            for item in report.folds[0].sensitivity.scenarios
            if item.omitted_component == "optional"
        )
        self.assertEqual(optional_sensitivity.status, "insufficient_component_coverage")
        self.assertEqual(optional_sensitivity.rank_correlation.sample_size, 3)
        optional_summary = next(
            item
            for item in report.summary.sensitivity
            if item.component_name == "optional"
        )
        self.assertEqual(optional_summary.method, "leave_one_component_out_no_refit")
        self.assertEqual(optional_summary.status, "insufficient_component_coverage")
        self.assertEqual(optional_summary.fold_count, 0)

    def test_component_correlation_is_finite_for_large_finite_values(self) -> None:
        audits = {
            "alpha": score_result(1e308, (("large", 1e308),)),
            "beta": score_result(-1e308, (("large", -1e308),)),
        }
        report = run_walk_forward(
            WalkForwardConfig(folds=(fold(),), select_count=1),
            candidates=tuple(
                candidate(f"{strategy_id}-A", strategy_id) for strategy_id in audits
            ),
            snapshots=tuple(
                point
                for strategy_id in audits
                for point in required_snapshots(strategy_id)
            ),
            outcomes=(),
            scorer=lambda view: audits[view.strategy_id],
        )

        correlation = report.folds[0].component_diagnostics.correlations[0]
        self.assertEqual(correlation.status, "estimated")
        self.assertEqual(correlation.value, 1.0)
        walk_forward_report_document(report)

    def test_huge_integer_inputs_and_finite_sensitivity_overflow_fail_stably(
        self,
    ) -> None:
        huge = 10**400
        for code, action in (
            (
                "invalid_snapshot_value",
                lambda: snapshot("alpha", "feature:huge", huge),
            ),
            (
                "invalid_component",
                lambda: ScoreComponent(
                    name="huge",
                    contribution=huge,  # type: ignore[arg-type]
                    component_version="v1",
                ),
            ),
            (
                "invalid_score",
                lambda: ScoreResult(
                    audit_id="huge-score-audit",
                    revision_id="huge-score-revision",
                    total_score=huge,  # type: ignore[arg-type]
                    components=(
                        ScoreComponent(
                            name="unknown",
                            contribution=None,
                            component_version="v1",
                        ),
                    ),
                    model_version="v1",
                    provider_id="synthetic-provider",
                    provider_snapshot_id="provider-snapshot-1",
                    provider_version="v1",
                    score_as_of=dt("2020-12-20T00:00:00Z"),
                    published_at=dt("2020-12-20T00:00:00Z"),
                    knowledge_at=dt("2020-12-21T00:00:00Z"),
                ),
            ),
        ):
            with self.subTest(code=code):
                self.assert_walk_forward_error(code, action)

        overflowing_audit = score_result(
            1e308,
            (("negative", -1e308), ("unavailable", None)),
        )
        self.assert_walk_forward_error(
            "calculation_overflow",
            lambda: run_walk_forward(
                WalkForwardConfig(folds=(fold(),), select_count=1),
                candidates=(candidate("alpha-A", "alpha"),),
                snapshots=required_snapshots("alpha"),
                outcomes=(),
                scorer=lambda view: overflowing_audit,
            ),
        )

    def test_scalar_and_text_magnitude_bounds_apply_at_api_boundary(self) -> None:
        self.assert_walk_forward_error(
            "invalid_identifier",
            lambda: candidate("x" * 257, "alpha"),
        )
        self.assert_walk_forward_error(
            "invalid_snapshot_value",
            lambda: snapshot("alpha", "manager", "x" * 4097),
        )

    def test_validation_boundary_rejects_ambiguous_or_hostile_inputs(self) -> None:
        base_snapshot = required_snapshots("alpha")[0]
        lifecycle = LifecycleInterval(
            status="active",
            effective_from=dt("2019-01-01T00:00:00Z"),
            published_at=dt("2019-01-01T00:00:00Z"),
            knowledge_at=dt("2019-01-01T00:00:00Z"),
        )
        self.assert_walk_forward_error(
            "input_too_large",
            lambda: CandidateFund(
                share_class_id="oversized-A",
                strategy_id="oversized",
                inception_at=dt("2019-01-01T00:00:00Z"),
                lifecycle=(lifecycle,) * 100_001,
            ),
        )
        self.assert_timestamp_error(
            "$.snapshot.knowledge_at",
            lambda: replace(
                base_snapshot,
                knowledge_at=datetime(2020, 1, 1, tzinfo=UTC).replace(tzinfo=None),
            ),
        )
        self.assert_walk_forward_error(
            "snapshot_chronology",
            lambda: replace(
                base_snapshot,
                as_of=dt("2020-12-22T00:00:00Z"),
            ),
        )
        self.assert_walk_forward_error(
            "window_order",
            lambda: replace(fold(), validation_start=fold().train_end),
        )
        self.assert_walk_forward_error(
            "duplicate_decision",
            lambda: WalkForwardConfig(folds=(fold(), fold()), select_count=1),
        )
        overlapping = FoldWindow(
            fold_id="fold-2",
            train_start=dt("2019-01-02T00:00:00Z"),
            train_end=dt("2020-01-01T00:00:00Z"),
            validation_start=dt("2020-01-02T00:00:00Z"),
            validation_end=dt("2021-01-10T00:00:00Z"),
            decision_at=dt("2021-01-15T00:00:00Z"),
            outcome_start=fold().outcome_end,
            outcome_end=dt("2021-02-28T00:00:00Z"),
            embargo_seconds=86_400,
        )
        self.assert_walk_forward_error(
            "overlapping_outcome_window",
            lambda: WalkForwardConfig(folds=(fold(), overlapping), select_count=1),
        )

        valid_arguments = {
            "config": WalkForwardConfig(folds=(fold(),), select_count=1),
            "candidates": (candidate("alpha-A", "alpha"),),
            "snapshots": required_snapshots("alpha"),
            "outcomes": (),
        }
        for value in (True, float("nan"), float("inf")):
            with self.subTest(score=value):
                self.assert_walk_forward_error(
                    "invalid_score",
                    lambda value=value: run_walk_forward(
                        **valid_arguments,
                        scorer=lambda view: value,
                    ),
                )
        self.assert_walk_forward_error(
            "unknown_strategy_id",
            lambda: run_walk_forward(
                **{
                    **valid_arguments,
                    "snapshots": required_snapshots("alpha")
                    + (snapshot("unknown", "manager", "private-marker"),),
                },
                scorer=lambda view: 1,
            ),
        )
        self.assert_walk_forward_error(
            "duplicate_entity",
            lambda: run_walk_forward(
                **{
                    **valid_arguments,
                    "candidates": (
                        candidate("alpha-A", "alpha"),
                        candidate("alpha-A", "alpha"),
                    ),
                },
                scorer=lambda view: 1,
            ),
        )
        self.assert_walk_forward_error(
            "empty_universe",
            lambda: run_walk_forward(
                **{**valid_arguments, "candidates": ()},
                scorer=lambda view: 1,
            ),
        )
        future_candidate = CandidateFund(
            share_class_id="future-A",
            strategy_id="future",
            inception_at=dt("2022-01-01T00:00:00Z"),
            lifecycle=(
                LifecycleInterval(
                    status="active",
                    effective_from=dt("2022-01-01T00:00:00Z"),
                    published_at=dt("2022-01-01T00:00:00Z"),
                    knowledge_at=dt("2022-01-01T00:00:00Z"),
                ),
            ),
        )
        self.assert_walk_forward_error(
            "empty_universe",
            lambda: run_walk_forward(
                WalkForwardConfig(folds=(fold(),), select_count=1),
                candidates=(future_candidate,),
                snapshots=(),
                outcomes=(),
                scorer=lambda view: 1,
            ),
        )
        self.assert_walk_forward_error(
            "invalid_container",
            lambda: run_walk_forward(
                **{**valid_arguments, "snapshots": {"private-marker": base_snapshot}},
                scorer=lambda view: 1,
            ),
        )

    def test_malformed_enum_values_raise_stable_walk_forward_errors(self) -> None:
        for bad_status in ([], {"active": True}, True, None):
            with self.subTest(status=type(bad_status).__name__):
                self.assert_walk_forward_error(
                    "invalid_lifecycle",
                    lambda bad_status=bad_status: LifecycleInterval(
                        status=bad_status,  # type: ignore[arg-type]
                        effective_from=dt("2019-01-01T00:00:00Z"),
                        published_at=dt("2019-01-01T00:00:00Z"),
                        knowledge_at=dt("2019-01-01T00:00:00Z"),
                    ),
                )
        self.assert_walk_forward_error(
            "unknown_domain",
            lambda: replace(required_snapshots("alpha")[0], domain=[]),  # type: ignore[arg-type]
        )

    def test_future_inception_strategy_never_enters_historical_fold(self) -> None:
        future = CandidateFund(
            share_class_id="future-A",
            strategy_id="future",
            inception_at=dt("2022-01-01T00:00:00Z"),
            lifecycle=(
                LifecycleInterval(
                    status="active",
                    effective_from=dt("2022-01-01T00:00:00Z"),
                    published_at=dt("2022-01-01T00:00:00Z"),
                    knowledge_at=dt("2022-01-01T00:00:00Z"),
                ),
            ),
        )
        calls: list[str] = []
        report = run_walk_forward(
            WalkForwardConfig(folds=(fold(),), select_count=1),
            candidates=(candidate("alpha-A", "alpha"), future),
            snapshots=required_snapshots("alpha") + required_snapshots("future"),
            outcomes=(),
            scorer=lambda view: (
                calls.append(view.strategy_id)
                or score_result(
                    100.0 if view.strategy_id == "future" else 1.0,
                    (("total", 100.0 if view.strategy_id == "future" else 1.0),),
                )
            ),
        )

        self.assertEqual(calls, ["alpha"])
        self.assertEqual(report.folds[0].universe_count, 1)
        self.assertEqual(report.folds[0].coverage.total, 1)
        self.assertEqual(report.folds[0].selected_strategy_ids, ("alpha",))

    def test_provider_snapshot_and_score_audit_versions_must_match_per_fold(
        self,
    ) -> None:
        mismatched_manager = replace(
            required_snapshots("alpha")[2],
            provider_snapshot_id="provider-snapshot-2",
        )
        snapshots = list(required_snapshots("alpha"))
        snapshots[2] = mismatched_manager
        calls: list[str] = []
        report = run_walk_forward(
            WalkForwardConfig(folds=(fold(),), select_count=1),
            candidates=(candidate("alpha-A", "alpha"),),
            snapshots=tuple(snapshots),
            outcomes=(),
            scorer=lambda view: (
                calls.append(view.strategy_id) or score_result(1.0, (("quality", 1.0),))
            ),
        )
        self.assertEqual(calls, [])
        self.assertEqual(report.folds[0].failures[0].code, "provider_snapshot_conflict")

        mismatched_score = replace(
            score_result(1.0, (("quality", 1.0),)),
            provider_snapshot_id="provider-snapshot-2",
        )
        score_report = run_walk_forward(
            WalkForwardConfig(folds=(fold(),), select_count=1),
            candidates=(candidate("alpha-A", "alpha"),),
            snapshots=required_snapshots("alpha"),
            outcomes=(),
            scorer=lambda view: mismatched_score,
        )
        self.assertEqual(score_report.folds[0].eligible_count, 0)
        self.assertEqual(
            score_report.folds[0].failures[0].code, "score_provider_mismatch"
        )

        stale_score_time = replace(
            score_result(1.0, (("quality", 1.0),)),
            score_as_of=dt("2020-12-19T00:00:00Z"),
            published_at=dt("2020-12-19T00:00:00Z"),
            knowledge_at=dt("2020-12-19T00:00:00Z"),
        )
        stale_report = run_walk_forward(
            WalkForwardConfig(folds=(fold(),), select_count=1),
            candidates=(candidate("alpha-A", "alpha"),),
            snapshots=required_snapshots("alpha"),
            outcomes=(),
            scorer=lambda view: stale_score_time,
        )
        self.assertEqual(stale_report.folds[0].eligible_count, 0)
        self.assertEqual(
            stale_report.folds[0].failures[0].code,
            "score_provider_time_mismatch",
        )

    def test_required_snapshot_values_are_semantically_valid(self) -> None:
        for domain, bad_value in (
            ("classification", ""),
            ("benchmark", True),
            ("manager", 3),
            ("fee_bps", -0.01),
        ):
            with self.subTest(domain=domain):
                self.assert_walk_forward_error(
                    "invalid_snapshot_value",
                    lambda domain=domain, bad_value=bad_value: snapshot(
                        "alpha",
                        domain,
                        bad_value,
                    ),
                )

    def test_callback_requires_auditable_score_result(self) -> None:
        arguments = {
            "config": WalkForwardConfig(folds=(fold(),), select_count=1),
            "candidates": (candidate("alpha-A", "alpha"),),
            "snapshots": required_snapshots("alpha"),
            "outcomes": (),
        }
        self.assert_walk_forward_error(
            "invalid_score_result",
            lambda: run_walk_forward(**arguments, scorer=lambda view: 1.0),
        )

    def test_callback_score_audit_is_retained_and_none_is_structured_missing(
        self,
    ) -> None:
        audit = score_result(42.0, (("quality", 42.0),))
        report = run_walk_forward(
            WalkForwardConfig(folds=(fold(),), select_count=1),
            candidates=(candidate("alpha-A", "alpha"),),
            snapshots=required_snapshots("alpha"),
            outcomes=(),
            scorer=lambda view: audit,
        )

        self.assertEqual(
            report.folds[0].audit_score_ids,
            (("alpha", audit.audit_id, audit.revision_id),),
        )
        self.assertEqual(report.folds[0].score_audit_trail[0].strategy_id, "alpha")
        self.assertEqual(
            replace(report.folds[0].score_audit_trail[0], strategy_id=None),
            audit,
        )
        self.assertEqual(
            report.folds[0].score_audit_trail[0].revision_id, "callback-revision-1"
        )

        missing = run_walk_forward(
            WalkForwardConfig(folds=(fold(),), select_count=1),
            candidates=(candidate("alpha-A", "alpha"),),
            snapshots=required_snapshots("alpha"),
            outcomes=(),
            scorer=lambda view: None,
        )
        self.assertEqual(missing.folds[0].eligible_count, 0)
        self.assertEqual(missing.folds[0].failures[0].code, "score_missing")
        self.assertEqual(missing.folds[0].failures[0].strategy_id, "alpha")

    def test_callback_audit_identity_is_bound_per_strategy(self) -> None:
        shared_audit = score_result(42.0, (("quality", 42.0),))
        beta_audit = replace(
            shared_audit,
            total_score=41.0,
            components=(
                ScoreComponent(
                    name="quality",
                    contribution=41.0,
                    component_version="components-v1",
                ),
            ),
        )
        report = run_walk_forward(
            WalkForwardConfig(folds=(fold(),), select_count=2),
            candidates=(
                candidate("alpha-A", "alpha"),
                candidate("beta-A", "beta"),
            ),
            snapshots=required_snapshots("alpha") + required_snapshots("beta"),
            outcomes=(),
            scorer=lambda view: (
                shared_audit if view.strategy_id == "alpha" else beta_audit
            ),
        )

        self.assertEqual(report.folds[0].eligible_count, 2)
        self.assertEqual(
            report.folds[0].audit_score_ids,
            (
                ("alpha", shared_audit.audit_id, shared_audit.revision_id),
                ("beta", shared_audit.audit_id, shared_audit.revision_id),
            ),
        )
        self.assertEqual(
            tuple(audit.strategy_id for audit in report.folds[0].score_audit_trail),
            ("alpha", "beta"),
        )

    def test_callback_audit_identity_conflict_across_folds_fails_closed(self) -> None:
        first_audit = replace(
            score_result(1.0, (("quality", 1.0),)),
            audit_id="shared-audit",
        )
        second_audit = replace(
            first_audit,
            total_score=2.0,
            components=(
                ScoreComponent(
                    name="quality",
                    contribution=2.0,
                    component_version="components-v1",
                ),
            ),
        )

        self.assert_walk_forward_error(
            "score_audit_conflict",
            lambda: run_walk_forward(
                WalkForwardConfig(
                    folds=(
                        fold(),
                        fold_at(
                            "fold-2",
                            "2021-03-01T00:00:00Z",
                            "2021-03-02T00:00:00Z",
                            "2021-03-31T00:00:00Z",
                        ),
                    ),
                    select_count=1,
                ),
                candidates=(candidate("alpha-A", "alpha"),),
                snapshots=required_snapshots("alpha"),
                outcomes=(),
                scorer=lambda view: (
                    first_audit if view.fold.fold_id == "fold-1" else second_audit
                ),
            ),
        )

    def test_callback_audit_identity_reuse_with_same_content_is_retained_per_fold(
        self,
    ) -> None:
        shared_audit = replace(
            score_result(1.0, (("quality", 1.0),)),
            audit_id="shared-audit",
        )

        report = run_walk_forward(
            WalkForwardConfig(
                folds=(
                    fold(),
                    fold_at(
                        "fold-2",
                        "2021-03-01T00:00:00Z",
                        "2021-03-02T00:00:00Z",
                        "2021-03-31T00:00:00Z",
                    ),
                ),
                select_count=1,
            ),
            candidates=(candidate("alpha-A", "alpha"),),
            snapshots=required_snapshots("alpha"),
            outcomes=(),
            scorer=lambda view: shared_audit,
        )

        expected_key = (("alpha", shared_audit.audit_id, shared_audit.revision_id),)
        self.assertEqual(
            tuple(fold_report.audit_score_ids for fold_report in report.folds),
            (expected_key, expected_key),
        )
        self.assertEqual(
            tuple(fold_report.score_audit_trail for fold_report in report.folds),
            (
                (replace(shared_audit, strategy_id="alpha"),),
                (replace(shared_audit, strategy_id="alpha"),),
            ),
        )

    def test_callback_failures_are_redacted_and_base_exceptions_abort(self) -> None:
        arguments = {
            "config": WalkForwardConfig(folds=(fold(),), select_count=1),
            "candidates": (candidate("alpha-A", "alpha"),),
            "snapshots": required_snapshots("alpha"),
            "outcomes": (),
        }

        def ordinary_failure(view):
            raise RuntimeError("private-marker")

        def disguised_walk_forward_failure(view):
            raise WalkForwardError(
                code="private-marker",
                path="$private-marker",
                message="private-marker",
            )

        for callback in (ordinary_failure, disguised_walk_forward_failure):
            with self.subTest(callback=callback.__name__):
                self.assert_walk_forward_error(
                    "score_callback_failed",
                    lambda callback=callback: run_walk_forward(
                        **arguments,
                        scorer=callback,
                    ),
                )
        for exception_type in (KeyboardInterrupt, SystemExit):
            with (
                self.subTest(exception_type=exception_type.__name__),
                self.assertRaises(exception_type),
            ):
                run_walk_forward(
                    **arguments,
                    scorer=lambda view, exception_type=exception_type: (
                        _ for _ in ()
                    ).throw(exception_type("private-marker")),
                )

        cyclic: list[object] = []
        cyclic.append(cyclic)
        for hostile in (cyclic, {"private-marker": []}):
            with self.subTest(hostile=type(hostile).__name__):
                self.assert_walk_forward_error(
                    "invalid_score_result",
                    lambda hostile=hostile: run_walk_forward(
                        **arguments,
                        scorer=lambda view: hostile,
                    ),
                )

    def test_precomputed_scores_are_point_in_time_and_do_not_require_an_engine(
        self,
    ) -> None:
        score = PrecomputedScore(
            score_id="score-alpha-1",
            strategy_id="alpha",
            total_score=88.0,
            components=(
                ScoreComponent(
                    name="quality",
                    contribution=88.0,
                    component_version="components-v1",
                ),
            ),
            model_version="synthetic-v1",
            provider_id="synthetic-provider",
            provider_snapshot_id="provider-snapshot-1",
            provider_version="v1",
            score_as_of=dt("2020-12-20T00:00:00Z"),
            published_at=dt("2020-12-20T00:00:00Z"),
            knowledge_at=dt("2020-12-21T00:00:00Z"),
            effective_from=dt("2020-01-01T00:00:00Z"),
        )
        report = run_walk_forward(
            WalkForwardConfig(folds=(fold(),), select_count=1),
            candidates=(candidate("alpha-A", "alpha"),),
            snapshots=required_snapshots("alpha"),
            outcomes=(),
            precomputed_scores=(score,),
        )
        self.assertEqual(report.folds[0].selected_strategy_ids, ("alpha",))
        self.assertEqual(report.folds[0].score_source, "precomputed")
        self.assertEqual(
            report.folds[0].audit_score_ids,
            (("alpha", "score-alpha-1", "original"),),
        )
        self.assertEqual(report.folds[0].score_audit_trail[0].strategy_id, "alpha")
        self.assertEqual(
            report.folds[0].score_audit_trail[0].provider_snapshot_id,
            "provider-snapshot-1",
        )

        future_knowledge = replace(
            score,
            score_id="score-alpha-future-knowledge",
            knowledge_at=dt("2021-01-02T00:00:00Z"),
        )
        future_effective = replace(
            score,
            score_id="score-alpha-future-effective",
            effective_from=dt("2021-01-02T00:00:00Z"),
        )
        mismatched_provider = replace(
            score,
            score_id="score-alpha-wrong-provider",
            provider_snapshot_id="provider-snapshot-2",
        )
        for excluded in (future_knowledge, future_effective):
            with self.subTest(score_id=excluded.score_id):
                excluded_report = run_walk_forward(
                    WalkForwardConfig(folds=(fold(),), select_count=1),
                    candidates=(candidate("alpha-A", "alpha"),),
                    snapshots=required_snapshots("alpha"),
                    outcomes=(),
                    precomputed_scores=(excluded,),
                )
                self.assertEqual(excluded_report.folds[0].eligible_count, 0)
                self.assertEqual(
                    excluded_report.folds[0].failures[0].code, "score_missing"
                )
        mismatch_report = run_walk_forward(
            WalkForwardConfig(folds=(fold(),), select_count=1),
            candidates=(candidate("alpha-A", "alpha"),),
            snapshots=required_snapshots("alpha"),
            outcomes=(),
            precomputed_scores=(mismatched_provider,),
        )
        self.assertEqual(
            mismatch_report.folds[0].failures[0].code, "score_provider_mismatch"
        )
        self.assert_walk_forward_error(
            "revision_chain_conflict",
            lambda: run_walk_forward(
                WalkForwardConfig(folds=(fold(),), select_count=1),
                candidates=(candidate("alpha-A", "alpha"),),
                snapshots=required_snapshots("alpha"),
                outcomes=(),
                precomputed_scores=(score, replace(score, score_id="score-alpha-2")),
            ),
        )

    def test_precomputed_score_revision_chain_selects_old_then_revised_audit(
        self,
    ) -> None:
        original = PrecomputedScore(
            score_id="score-alpha-original",
            revision_id="score-revision-1",
            supersedes_revision_id=None,
            strategy_id="alpha",
            total_score=88.0,
            components=(
                ScoreComponent(
                    name="quality",
                    contribution=88.0,
                    component_version="components-v1",
                ),
            ),
            model_version="synthetic-v1",
            provider_id="synthetic-provider",
            provider_snapshot_id="provider-snapshot-1",
            provider_version="v1",
            score_as_of=dt("2020-12-20T00:00:00Z"),
            published_at=dt("2020-12-20T00:00:00Z"),
            knowledge_at=dt("2020-12-21T00:00:00Z"),
            effective_from=dt("2020-01-01T00:00:00Z"),
        )
        revised = replace(
            original,
            score_id="score-alpha-revised",
            revision_id="score-revision-2",
            supersedes_revision_id="score-revision-1",
            total_score=77.0,
            components=(
                ScoreComponent(
                    name="quality",
                    contribution=77.0,
                    component_version="components-v2",
                ),
            ),
            published_at=dt("2021-02-20T00:00:00Z"),
            knowledge_at=dt("2021-02-20T00:00:00Z"),
        )
        report = run_walk_forward(
            WalkForwardConfig(
                folds=(
                    fold(),
                    fold_at(
                        "fold-2",
                        "2021-03-01T00:00:00Z",
                        "2021-03-02T00:00:00Z",
                        "2021-03-31T00:00:00Z",
                    ),
                ),
                select_count=1,
            ),
            candidates=(candidate("alpha-A", "alpha"),),
            snapshots=required_snapshots("alpha"),
            outcomes=(),
            precomputed_scores=(original, revised),
        )

        self.assertEqual(
            report.folds[0].audit_score_ids,
            (("alpha", "score-alpha-original", "score-revision-1"),),
        )
        self.assertEqual(
            report.folds[1].audit_score_ids,
            (("alpha", "score-alpha-revised", "score-revision-2"),),
        )
        self.assertEqual(
            report.folds[0].score_audit_trail[0].revision_id, "score-revision-1"
        )
        self.assertEqual(
            report.folds[1].score_audit_trail[0].revision_id, "score-revision-2"
        )

    def test_features_obey_publication_lag_and_unavailable_funds_are_not_scored(
        self,
    ) -> None:
        historical_feature = snapshot(
            "alpha",
            "feature:downside_risk",
            20.0,
            snapshot_id="risk-known",
        )
        historical_feature = replace(
            historical_feature,
            revision_id="risk-revision-1",
        )
        future_feature = snapshot(
            "alpha",
            "feature:downside_risk",
            99.0,
            snapshot_id="risk-not-yet-known",
            published_at="2021-01-02T00:00:00Z",
            knowledge_at="2021-01-03T00:00:00Z",
        )
        future_feature = replace(
            future_feature,
            revision_id="risk-revision-2",
            supersedes_revision_id="risk-revision-1",
        )
        views = []
        report = run_walk_forward(
            WalkForwardConfig(folds=(fold(),), select_count=1),
            candidates=(candidate("alpha-A", "alpha"),),
            snapshots=required_snapshots("alpha")
            + (historical_feature, future_feature),
            outcomes=(),
            scorer=lambda view: (
                views.append(view) or score_result(50.0, (("total", 50.0),))
            ),
        )
        self.assertEqual(
            [
                item.value
                for item in views[0].snapshots
                if item.domain.startswith("feature:")
            ],
            [20.0],
        )
        self.assertIn("risk-known", report.folds[0].audit_snapshot_ids)
        self.assertNotIn("risk-not-yet-known", report.folds[0].audit_snapshot_ids)

        unavailable = list(required_snapshots("alpha"))
        unavailable[-1] = snapshot("alpha", "availability", False)
        calls = []
        unavailable_report = run_walk_forward(
            WalkForwardConfig(folds=(fold(),), select_count=1),
            candidates=(candidate("alpha-A", "alpha"),),
            snapshots=tuple(unavailable),
            outcomes=(),
            scorer=lambda view: calls.append(view) or 100,
        )
        self.assertEqual(calls, [])
        self.assertEqual(unavailable_report.folds[0].failures[0].code, "unavailable")

    def test_future_outcomes_must_be_unique_and_period_aligned(self) -> None:
        alpha = FutureOutcome(
            outcome_id="outcome-alpha",
            strategy_id="alpha",
            window_start=fold().outcome_start,
            window_end=fold().outcome_end,
            period_returns=(0.01, 0.02),
            peer_period_returns=(0.0, 0.0),
        )
        duplicate = replace(alpha, outcome_id="outcome-alpha-duplicate")
        arguments = {
            "config": WalkForwardConfig(folds=(fold(),), select_count=1),
            "candidates": (candidate("alpha-A", "alpha"),),
            "snapshots": required_snapshots("alpha"),
            "scorer": lambda view: 1,
        }
        self.assert_walk_forward_error(
            "duplicate_outcome",
            lambda: run_walk_forward(**arguments, outcomes=(alpha, duplicate)),
        )

        beta = FutureOutcome(
            outcome_id="outcome-beta",
            strategy_id="beta",
            window_start=fold().outcome_start,
            window_end=fold().outcome_end,
            period_returns=(0.01,),
            peer_period_returns=(0.0,),
        )
        self.assert_walk_forward_error(
            "outcome_alignment",
            lambda: run_walk_forward(
                WalkForwardConfig(folds=(fold(),), select_count=2),
                candidates=(
                    candidate("alpha-A", "alpha"),
                    candidate("beta-A", "beta"),
                ),
                snapshots=required_snapshots("alpha") + required_snapshots("beta"),
                outcomes=(alpha, beta),
                scorer=lambda view: 1,
            ),
        )

    def test_future_outcome_series_and_returns_are_bounded(self) -> None:
        too_long = tuple(0.0 for _ in range(257))
        self.assert_walk_forward_error(
            "invalid_outcome",
            lambda: FutureOutcome(
                outcome_id="too-long",
                strategy_id="alpha",
                window_start=fold().outcome_start,
                window_end=fold().outcome_end,
                period_returns=too_long,
                peer_period_returns=too_long,
            ),
        )
        self.assert_walk_forward_error(
            "invalid_outcome",
            lambda: FutureOutcome(
                outcome_id="return-too-large",
                strategy_id="alpha",
                window_start=fold().outcome_start,
                window_end=fold().outcome_end,
                period_returns=(1.01,),
                peer_period_returns=(0.0,),
            ),
        )

    def test_aggregate_wealth_overflow_is_rejected_stably(self) -> None:
        folds = tuple(
            fold_at(
                f"fold-{index}",
                f"202{index}-01-01T00:00:00Z",
                f"202{index}-01-02T00:00:00Z",
                f"202{index}-01-31T00:00:00Z",
            )
            for index in range(1, 6)
        )
        outcomes = tuple(
            FutureOutcome(
                outcome_id=f"outcome-{item.fold_id}",
                strategy_id="alpha",
                window_start=item.outcome_start,
                window_end=item.outcome_end,
                period_returns=(1.0,) * 256,
                peer_period_returns=(0.0,) * 256,
            )
            for item in folds
        )

        self.assert_walk_forward_error(
            "calculation_overflow",
            lambda: run_walk_forward(
                WalkForwardConfig(folds=folds, select_count=1),
                candidates=(candidate("alpha-A", "alpha"),),
                snapshots=required_snapshots("alpha"),
                outcomes=outcomes,
                scorer=lambda view: score_result(1.0, (("total", 1.0),)),
            ),
        )

    def test_first_period_loss_is_included_in_drawdown_and_recovery(self) -> None:
        outcome = FutureOutcome(
            outcome_id="first-loss",
            strategy_id="alpha",
            window_start=fold().outcome_start,
            window_end=fold().outcome_end,
            period_returns=(-0.20, 0.25),
            peer_period_returns=(0.0, 0.0),
        )
        report = run_walk_forward(
            WalkForwardConfig(folds=(fold(),), select_count=1),
            candidates=(candidate("alpha-A", "alpha"),),
            snapshots=required_snapshots("alpha"),
            outcomes=(outcome,),
            scorer=lambda view: score_result(1.0, (("total", 1.0),)),
        )

        self.assertEqual(report.folds[0].wealth.wealth_curve, (1.0, 0.8, 1.0))
        self.assertAlmostEqual(report.folds[0].wealth.max_drawdown, -0.2)
        self.assertEqual(report.folds[0].wealth.recovery_status, "recovered")
        self.assertEqual(report.folds[0].wealth.recovery_periods, 1)

    def test_report_serialization_rejects_non_finite_numbers_stably(self) -> None:
        report = run_walk_forward(
            WalkForwardConfig(folds=(fold(),), select_count=1),
            candidates=(candidate("alpha-A", "alpha"),),
            snapshots=required_snapshots("alpha"),
            outcomes=(),
            scorer=lambda view: score_result(1.0, (("total", 1.0),)),
        )
        poisoned = replace(
            report,
            summary=replace(report.summary, mean_score_stability=float("inf")),
        )
        self.assert_walk_forward_error(
            "serialization_failed",
            lambda: walk_forward_report_document(poisoned),
        )

    def test_json_object_boundary_rejects_depth_width_cycles_and_invalid_unicode(
        self,
    ) -> None:
        deep: list[object] = []
        cursor = deep
        for _ in range(65):
            child: list[object] = []
            cursor.append(child)
            cursor = child
        cyclic: list[object] = []
        cyclic.append(cyclic)
        hostile = (
            ("json_too_deep", deep),
            ("json_too_wide", {str(index): None for index in range(100_001)}),
            ("cyclic_json", cyclic),
            ("invalid_unicode", {"private-marker": "\ud800"}),
        )
        for code, document in hostile:
            with self.subTest(code=code):
                self.assert_walk_forward_error(
                    code,
                    lambda document=document: walk_forward_from_document(document),
                )

    def test_shared_acyclic_json_container_matches_duplicated_canonical_output(
        self,
    ) -> None:
        shared_document = synthetic_fixture_document()
        shared_candidates = cast(list[dict[str, object]], shared_document["candidates"])
        self.assertIsInstance(shared_candidates, list)
        shared_lifecycle = shared_candidates[0]["lifecycle"]
        shared_candidates[1]["lifecycle"] = shared_lifecycle

        duplicated_document = copy.deepcopy(shared_document)
        duplicated_candidates = cast(
            list[dict[str, object]], duplicated_document["candidates"]
        )
        duplicated_candidates[1]["lifecycle"] = copy.deepcopy(
            duplicated_candidates[0]["lifecycle"]
        )

        shared = walk_forward_from_document(shared_document)
        duplicated = walk_forward_from_document(duplicated_document)

        self.assertEqual(
            walk_forward_input_document(*shared),
            walk_forward_input_document(*duplicated),
        )

    def test_hostile_json_scalar_exceptions_are_redacted_but_base_exceptions_propagate(
        self,
    ) -> None:
        with self.assertRaises(WalkForwardError) as raised:
            walk_forward_from_document({HostileString(RuntimeError): None})
        self.assertEqual(raised.exception.code, "invalid_unicode")
        self.assertEqual(raised.exception.path, "$")
        self.assertNotIn("private-marker", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

        for exception_type in (KeyboardInterrupt, SystemExit):
            with (
                self.subTest(exception_type=exception_type.__name__),
                self.assertRaises(exception_type),
            ):
                walk_forward_from_document({HostileString(exception_type): None})


if __name__ == "__main__":
    unittest.main()
