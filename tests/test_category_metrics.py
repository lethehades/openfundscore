from __future__ import annotations

import unittest
from calendar import monthrange
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, cast

from openfundscore.category_metrics import (
    ApplicabilityContext,
    CaptureDenominatorAudit,
    CaptureDenominatorStatus,
    CategoryMetricError,
    HistoryStage,
    MetricDirection,
    MetricObservation,
    MetricState,
    PeerObservation,
    normalize_metric,
    score_category_metrics,
)
from openfundscore.metric_catalog import load_metric_catalog
from openfundscore.peer_admission import load_peer_admission_contract
from openfundscore.resources import resolve_resource

EVALUATION = datetime(2026, 8, 22, tzinfo=UTC)
AS_OF = datetime(2026, 8, 20, tzinfo=UTC)
PUBLISHED = datetime(2026, 8, 21, tzinfo=UTC)
MANAGER_COMPONENTS = (
    "tenure_attributed_performance",
    "downside_control",
    "cross_cycle_consistency",
    "style_discipline",
    "career_track_record",
    "workload_capacity",
    "research_platform_team",
    "compliance_integrity",
)


def observation(
    metric_id: str,
    *,
    state: MetricState = MetricState.OBSERVED,
    raw: float | None = 3.0,
    fund_id: str = "fund-1",
    sample_size: int = 36,
    window_months: int = 36,
    as_of: datetime = AS_OF,
    published_at: datetime = PUBLISHED,
    evaluation_timestamp: datetime = EVALUATION,
) -> MetricObservation:
    capture_denominator = (
        CaptureDenominatorAudit(
            denominator_status=(
                CaptureDenominatorStatus.PRESENT
                if state is MetricState.OBSERVED
                else CaptureDenominatorStatus.ABSENT
            ),
            benchmark_downside_sample_count=(
                sample_size if state is MetricState.OBSERVED else 0
            ),
            evidence_id=f"denominator-evidence-{metric_id}",
            lineage_id=f"denominator-lineage-{metric_id}",
            series_id=f"denominator-series-{metric_id}",
        )
        if metric_id.endswith("_capture")
        else None
    )
    return MetricObservation(
        metric_id=metric_id,
        state=state,
        raw_value=raw,
        fund_id=fund_id,
        series_id=f"series-{metric_id}",
        evidence_id=f"evidence-{metric_id}",
        lineage_id=f"lineage-{metric_id}",
        as_of=as_of,
        published_at=published_at,
        evaluation_timestamp=evaluation_timestamp,
        sample_size=sample_size,
        window_months=window_months,
        uncertainty="synthetic peer fixture",
        capture_denominator=capture_denominator,
    )


def peer_set(
    metric_id: str,
    values: tuple[float, ...] = (1, 2, 3, 4, 5),
    *,
    peer_bucket: str = "active-equity-cn",
    profile_id: str = "active_equity_mixed",
    window_months: int = 36,
) -> tuple[PeerObservation, ...]:
    _, admission_digest = load_peer_admission_contract()
    month_index = AS_OF.date().year * 12 + AS_OF.date().month - 1 - window_months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    window_start = date(year, month, min(AS_OF.date().day, monthrange(year, month)[1]))
    return tuple(
        PeerObservation(
            peer_id=f"peer-{index}",
            metric_id=metric_id,
            raw_value=value,
            series_id=f"peer-series-{index}-{metric_id}",
            source_id=f"source-{index}",
            lineage_id=f"peer-lineage-{index}-{metric_id}",
            as_of=AS_OF,
            published_at=PUBLISHED,
            evaluation_timestamp=EVALUATION,
            peer_bucket=peer_bucket,
            peer_bucket_version="0.1.0",
            category_profile=profile_id,
            admission_contract_version="0.1.0",
            admission_contract_sha256=admission_digest,
            snapshot_hash=f"{index:064x}",
            document_hash=f"{index + 100:064x}",
            sample_size=36,
            window_basis="point_in_time" if window_months == 0 else "calendar_months",
            window_months=window_months,
            window_start=window_start.isoformat(),
            window_end=AS_OF.date().isoformat(),
            capture_denominator=(
                CaptureDenominatorAudit(
                    denominator_status=CaptureDenominatorStatus.PRESENT,
                    benchmark_downside_sample_count=36,
                    evidence_id=f"peer-denominator-evidence-{index}-{metric_id}",
                    lineage_id=f"peer-denominator-lineage-{index}-{metric_id}",
                    series_id=f"peer-denominator-series-{index}-{metric_id}",
                )
                if metric_id.endswith("_capture")
                else None
            ),
        )
        for index, value in enumerate(values, 1)
    )


def profile_fixture(
    profile_id: str, *, history_months: int = 36
) -> tuple[tuple[MetricObservation, ...], tuple[PeerObservation, ...]]:
    catalog, _ = load_metric_catalog()
    admission, _ = load_peer_admission_contract()
    peer_bucket = admission["profiles"][profile_id]["allowed_peer_buckets"][0]
    definitions = tuple(
        metric
        for metrics in catalog["profiles"][profile_id]["dimensions"].values()
        for metric in metrics
    )
    values = {
        metric["id"]: tuple(
            metric["value_range"]["minimum"]
            + (metric["value_range"]["maximum"] - metric["value_range"]["minimum"])
            * fraction
            for fraction in (0.0, 0.25, 0.5, 0.75, 1.0)
        )
        for metric in definitions
    }
    for metric in definitions:
        if metric["unit"] in {"count", "days", "months"}:
            values[metric["id"]] = tuple(round(value) for value in values[metric["id"]])
    for metric_id in {"negative_return_days", "recovery_months"} & set(values):
        economic_maximum = history_months
        values[metric_id] = tuple(
            round(economic_maximum * fraction)
            for fraction in (0.0, 0.25, 0.5, 0.75, 1.0)
        )
    observations_list: list[MetricObservation] = []
    observed_metric_ids: set[str] = set()
    for metric in definitions:
        window = metric["observation_window"]
        minimum_window = window.get("minimum_months", window.get("minimum", 0))
        maximum_window = window.get("maximum_months", window.get("maximum", 0))
        if window.get("unit") == "instant":
            minimum_window = maximum_window = 0
        if history_months < minimum_window:
            observations_list.append(
                observation(
                    metric["id"],
                    state=MetricState.MISSING,
                    raw=None,
                    sample_size=0,
                    window_months=0,
                )
            )
            continue
        metric_window = min(history_months, maximum_window)
        raw_value = values[metric["id"]][2]
        if metric["id"] == "recovery_months":
            raw_value = min(raw_value, metric_window)
        elif metric["id"] == "negative_return_days":
            raw_value = min(raw_value, history_months)
        observations_list.append(
            observation(
                metric["id"],
                raw=raw_value,
                sample_size=history_months,
                window_months=metric_window,
            )
        )
        observed_metric_ids.add(metric["id"])
    observations = tuple(observations_list)
    observation_by_id = {item.metric_id: item for item in observations}
    peers = tuple(
        peer
        for metric in definitions
        if metric["id"] in observed_metric_ids
        for peer in peer_set(
            metric["id"],
            values[metric["id"]],
            peer_bucket=peer_bucket,
            profile_id=profile_id,
            window_months=observation_by_id[metric["id"]].window_months,
        )
    )
    return observations, peers


def manager_result() -> dict[str, object]:
    from openfundscore.manager_research import recompute_manager_handoff
    from tests.test_manager_handoff import manager_handoff

    return cast(dict[str, object], recompute_manager_handoff(manager_handoff()))


def evidence_ledger(
    profile_id: str, observations: tuple[MetricObservation, ...]
) -> dict[str, object]:
    catalog, _ = load_metric_catalog()
    dimension_components = {
        "performance_evidence": "fund_d1_performance_evidence",
        "downside_risk": "fund_d2_downside_risk",
        "consistency": "fund_d3_consistency",
        "portfolio_structure": "fund_d5_portfolio_structure",
        "implementation_efficiency": "fund_d6_implementation_efficiency",
        "governance_operations": "fund_d7_governance_operations",
    }
    by_id = {item.metric_id: item for item in observations}

    def subtract_months(value: date, months: int) -> date:
        month_index = value.year * 12 + value.month - 1 - months
        year, zero_based_month = divmod(month_index, 12)
        month = zero_based_month + 1
        return date(year, month, min(value.day, monthrange(year, month)[1]))

    usage = []
    for dimension, metrics in catalog["profiles"][profile_id]["dimensions"].items():
        for metric in metrics:
            item = by_id[metric["id"]]
            if item.state is not MetricState.OBSERVED:
                continue
            usage.append(
                {
                    "evidence_id": item.evidence_id,
                    "evidence_role": "primary",
                    "lineage_id": item.lineage_id,
                    "series_id": item.series_id,
                    "evidence_family": metric["evidence_family"],
                    "target_component": dimension_components[dimension],
                    "source_scope": "current_fund",
                    "usage_mode": "raw",
                    "observation_as_of": item.as_of.astimezone(UTC)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "window_basis": (
                        "point_in_time"
                        if item.window_months == 0
                        else "calendar_months"
                    ),
                    "window_months": item.window_months,
                    "window_start": subtract_months(
                        item.as_of.astimezone(UTC).date(), item.window_months
                    ).isoformat(),
                    "window_end": item.as_of.astimezone(UTC).date().isoformat(),
                }
            )
            if (
                item.state is MetricState.OBSERVED
                and item.capture_denominator is not None
            ):
                denominator = item.capture_denominator
                usage.append(
                    {
                        "evidence_id": denominator.evidence_id,
                        "evidence_role": "capture_denominator",
                        "benchmark_downside_sample_count": (
                            denominator.benchmark_downside_sample_count
                        ),
                        "lineage_id": denominator.lineage_id,
                        "series_id": denominator.series_id,
                        "evidence_family": f"benchmark_downside.{item.metric_id}",
                        "target_component": dimension_components[dimension],
                        "source_scope": "current_fund",
                        "usage_mode": "raw",
                        "observation_as_of": item.as_of.astimezone(UTC)
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "window_basis": (
                            "point_in_time"
                            if item.window_months == 0
                            else "calendar_months"
                        ),
                        "window_months": item.window_months,
                        "window_start": subtract_months(
                            item.as_of.astimezone(UTC).date(), item.window_months
                        ).isoformat(),
                        "window_end": item.as_of.astimezone(UTC).date().isoformat(),
                    }
                )
    usage.extend(deepcopy(cast(dict[str, Any], manager_result())["component_evidence"]))
    return {
        "score_record_id": f"score-{profile_id}-fund-1-20260822",
        "model_version": "0.1.0",
        "fund_strategy_id": "fund-1",
        "category_profile": profile_id,
        "as_of": "2026-08-22T00:00:00Z",
        "usage": usage,
    }


def score(profile_id: str = "active_equity_mixed", **overrides: object):
    observations, peers = profile_fixture(
        profile_id, history_months=int(overrides.get("history_months", 36))
    )
    admission, _ = load_peer_admission_contract()
    arguments = {
        "profile_id": profile_id,
        "peer_bucket": admission["profiles"][profile_id]["allowed_peer_buckets"][0],
        "peer_bucket_version": "0.1.0",
        "peer_admission_version": "0.1.0",
        "history_months": 36,
        "adequate_regime_coverage": True,
        "applicability_context": ApplicabilityContext(
            declared_benchmark=True,
            cross_border_or_currency_exposure=True,
            derivative_or_commodity_exposure=True,
            income_distributing_assets=True,
            lookthrough_portfolio=True,
            securities_lending_program=True,
        ),
        "observations": observations,
        "peers": peers,
        "manager_handoff": __import__(
            "tests.test_manager_handoff", fromlist=["manager_handoff"]
        ).manager_handoff(),
        "evidence_ledger": evidence_ledger(profile_id, observations),
    }
    arguments.update(overrides)
    if "observations" in overrides:
        selected = arguments["observations"]
        if isinstance(selected, tuple):
            if "peers" not in overrides:
                observed_ids = {
                    item.metric_id
                    for item in selected
                    if isinstance(item, MetricObservation)
                    and item.state is MetricState.OBSERVED
                }
                arguments["peers"] = tuple(
                    item for item in peers if item.metric_id in observed_ids
                )
            catalog, _ = load_metric_catalog()
            expected_ids = {
                metric["id"]
                for metrics in catalog["profiles"][profile_id]["dimensions"].values()
                for metric in metrics
            }
            selected_ids = [
                item.metric_id
                for item in selected
                if isinstance(item, MetricObservation)
            ]
            if (
                "evidence_ledger" not in overrides
                and len(selected_ids) == len(expected_ids)
                and set(selected_ids) == expected_ids
            ):
                arguments["evidence_ledger"] = evidence_ledger(profile_id, selected)
    return score_category_metrics(**arguments)


class CategoryMetricNormalizationTests(unittest.TestCase):
    def test_iqr_winsorization_preserves_raw_and_audit_fields(self) -> None:
        result = normalize_metric(
            observation("excess_return", raw=1000.0),
            peer_set(
                "excess_return",
                (1, 2, 3, 4, 100),
                peer_bucket="active-equity-cn",
            ),
            direction=MetricDirection.HIGHER_IS_BETTER,
            peer_bucket="active-equity-cn",
            peer_bucket_version="0.1.0",
        )

        self.assertEqual(result.raw_value, 1000.0)
        self.assertEqual(result.adjusted_value, 7.0)
        self.assertEqual((result.lower_bound, result.upper_bound), (-1.0, 7.0))
        self.assertEqual(result.peer_sample_size, 5)
        self.assertEqual(result.score, 90.0)
        self.assertEqual(result.adjustment_method, "iqr_1.5")
        self.assertEqual(result.formula_version, "robust-percentile-iqr-mad/0.1.0")
        self.assertEqual(result.catalog_version, "0.1.0")
        self.assertRegex(result.catalog_sha256, r"^[0-9a-f]{64}$")

    def test_midrank_ties_constant_and_directions_are_deterministic(self) -> None:
        higher = normalize_metric(
            observation("metric", raw=2.0),
            peer_set("metric", (1, 2, 2, 4, 5)),
            direction=MetricDirection.HIGHER_IS_BETTER,
            peer_bucket="active-equity-cn",
            peer_bucket_version="0.1.0",
        )
        lower = normalize_metric(
            observation("metric", raw=2.0),
            peer_set("metric", (1, 2, 2, 4, 5)),
            direction=MetricDirection.LOWER_IS_BETTER,
            peer_bucket="active-equity-cn",
            peer_bucket_version="0.1.0",
        )
        constant = normalize_metric(
            observation("metric", raw=999.0),
            peer_set("metric", (1, 1, 1, 1, 1)),
            direction=MetricDirection.LOWER_IS_BETTER,
            peer_bucket="active-equity-cn",
            peer_bucket_version="0.1.0",
        )

        self.assertEqual(higher.score, 40.0)
        self.assertEqual(lower.score, 60.0)
        self.assertEqual(constant.score, 50.0)
        self.assertEqual(constant.adjustment_method, "zero_dispersion_neutral")

    def test_numerically_zero_iqr_falls_back_to_mad(self) -> None:
        result = normalize_metric(
            observation("metric", raw=1.0),
            peer_set("metric", (-1.0, 0.0, 0.0, 1e-16, 1.0)),
            direction=MetricDirection.HIGHER_IS_BETTER,
            peer_bucket="active-equity-cn",
            peer_bucket_version="0.1.0",
        )
        self.assertEqual(result.adjustment_method, "mad_3.0")
        self.assertLess(result.adjusted_value, 1e-12)
        self.assertEqual(result.raw_value, 1.0)

    def test_missing_and_na_are_distinct_and_never_numeric(self) -> None:
        for state in (MetricState.MISSING, MetricState.NOT_APPLICABLE):
            with self.subTest(state=state):
                result = normalize_metric(
                    observation(
                        "metric", state=state, raw=None, sample_size=0, window_months=0
                    ),
                    (),
                    direction=MetricDirection.HIGHER_IS_BETTER,
                    peer_bucket="active-equity-cn",
                    peer_bucket_version="0.1.0",
                )
                self.assertEqual(result.state, state)
                self.assertIsNone(result.score)
                self.assertIsNone(result.adjusted_value)
                self.assertEqual(result.adjustment_method, "not_scored")

    def test_normalize_rejects_invalid_values_states_ids_peers_and_subject_leakage(
        self,
    ) -> None:
        valid = observation("metric")
        valid_peers = peer_set("metric")
        invalid_cases = (
            (
                observation("metric", raw=True),
                valid_peers,
                MetricDirection.HIGHER_IS_BETTER,
            ),
            (
                observation("metric", raw=float("nan")),
                valid_peers,
                MetricDirection.HIGHER_IS_BETTER,
            ),
            (
                observation("metric", state=MetricState.OBSERVED, raw=None),
                valid_peers,
                MetricDirection.HIGHER_IS_BETTER,
            ),
            (
                observation("metric", state=MetricState.MISSING, raw=1.0),
                (),
                MetricDirection.HIGHER_IS_BETTER,
            ),
            (observation("ｍetric"), valid_peers, MetricDirection.HIGHER_IS_BETTER),
            (
                valid,
                valid_peers[:-1]
                + (replace(valid_peers[-1], peer_id="peer-x", metric_id="unknown"),),
                MetricDirection.HIGHER_IS_BETTER,
            ),
            (
                valid,
                valid_peers[:-1] + (replace(valid_peers[-1], peer_id="peer-1"),),
                MetricDirection.HIGHER_IS_BETTER,
            ),
            (
                valid,
                valid_peers[:-1] + (replace(valid_peers[-1], peer_id="fund-1"),),
                MetricDirection.HIGHER_IS_BETTER,
            ),
            (
                valid,
                valid_peers[:-1]
                + (replace(valid_peers[-1], peer_id="peer-x", raw_value=float("inf")),),
                MetricDirection.HIGHER_IS_BETTER,
            ),
            (valid, valid_peers, "sideways"),
        )
        for item, peers, direction in invalid_cases:
            with (
                self.subTest(item=item, direction=direction),
                self.assertRaises(CategoryMetricError),
            ):
                normalize_metric(
                    item,
                    peers,
                    direction=direction,
                    peer_bucket="active-equity-cn",
                    peer_bucket_version="0.1.0",
                )

    def test_normalize_rejects_non_tuple_and_oversized_input(self) -> None:
        with self.assertRaises(CategoryMetricError):
            normalize_metric(
                observation("metric"),
                list(peer_set("metric")),
                direction=MetricDirection.HIGHER_IS_BETTER,
                peer_bucket="active-equity-cn",
                peer_bucket_version="0.1.0",
            )
        huge = (peer_set("metric")[0],) * 10001
        with self.assertRaises(CategoryMetricError):
            normalize_metric(
                observation("metric"),
                huge,
                direction=MetricDirection.HIGHER_IS_BETTER,
                peer_bucket="active-equity-cn",
                peer_bucket_version="0.1.0",
            )

    def test_normalize_rejects_each_duplicate_peer_economic_identity(self) -> None:
        peers = peer_set("metric")
        for field in ("peer_id", "series_id", "lineage_id"):
            duplicated = tuple(
                replace(peer, **{field: getattr(peers[0], field)}) for peer in peers
            )
            with (
                self.subTest(field=field),
                self.assertRaises(CategoryMetricError) as raised,
            ):
                normalize_metric(
                    observation("metric"),
                    duplicated,
                    direction=MetricDirection.HIGHER_IS_BETTER,
                    peer_bucket="active-equity-cn",
                    peer_bucket_version="0.1.0",
                )
            self.assertEqual(raised.exception.code, "duplicate_peer")

    def test_pit_fields_are_timezone_aware_and_not_future_known(self) -> None:
        cases = (
            observation("metric", as_of=AS_OF.replace(tzinfo=None)),
            observation("metric", published_at=PUBLISHED.replace(tzinfo=None)),
            observation("metric", evaluation_timestamp=EVALUATION.replace(tzinfo=None)),
            observation("metric", as_of=EVALUATION + timedelta(days=1)),
            observation("metric", published_at=EVALUATION + timedelta(days=1)),
        )
        for invalid in cases:
            with self.subTest(invalid=invalid), self.assertRaises(CategoryMetricError):
                normalize_metric(
                    invalid,
                    peer_set("metric"),
                    direction=MetricDirection.HIGHER_IS_BETTER,
                    peer_bucket="active-equity-cn",
                    peer_bucket_version="0.1.0",
                )

    def test_peer_digest_commits_to_pit_times_and_retains_complete_records(
        self,
    ) -> None:
        peers = peer_set("metric")
        baseline = normalize_metric(
            observation("metric"),
            peers,
            direction=MetricDirection.HIGHER_IS_BETTER,
            peer_bucket="active-equity-cn",
            peer_bucket_version="0.1.0",
        )
        shifted = normalize_metric(
            observation("metric"),
            (
                replace(
                    peers[0],
                    as_of=peers[0].as_of - timedelta(days=1),
                    window_start="2023-08-19",
                    window_end="2026-08-19",
                ),
            )
            + peers[1:],
            direction=MetricDirection.HIGHER_IS_BETTER,
            peer_bucket="active-equity-cn",
            peer_bucket_version="0.1.0",
        )
        self.assertNotEqual(baseline.peer_set_digest, shifted.peer_set_digest)

        result = score()
        audit = result.peer_sets[0]
        self.assertEqual(len(audit.records), 5)
        record = audit.records[0]
        self.assertEqual(record.metric_id, audit.metric_id)
        self.assertEqual(record.as_of, "2026-08-20T00:00:00Z")
        self.assertEqual(record.published_at, "2026-08-21T00:00:00Z")
        self.assertEqual(record.evaluation_timestamp, "2026-08-22T00:00:00Z")


class CategoryMetricScoringTests(unittest.TestCase):
    def test_all_ten_profiles_run_with_exact_dimensions_weights_metrics_and_directions(
        self,
    ) -> None:
        catalog, catalog_digest = load_metric_catalog()
        config = resolve_resource(
            resource_type="scoring-config", name="openfundscore-core", version="0.1.0"
        ).load_json()
        for profile_id, catalog_profile in catalog["profiles"].items():
            with self.subTest(profile=profile_id):
                result = score(profile_id)
                expected_manager_weight = config["category_profiles"][profile_id][
                    "weights"
                ]["manager_capability"]
                self.assertEqual(
                    result.open_score, round(50 + 0.3 * expected_manager_weight, 2)
                )
                self.assertEqual(result.status, "scored")
                self.assertEqual(result.history_stage, HistoryStage.ELIGIBLE)
                self.assertEqual(len(result.dimensions), 7)
                self.assertEqual(len(result.metrics), 12)
                self.assertEqual(result.catalog_sha256, catalog_digest)
                self.assertEqual(result.catalog_version, "0.1.0")
                self.assertEqual(
                    result.config_sha256,
                    "e0f9f8ed58e840a078924cce2c5acae661e5a903d82402ecaf152c1ac7c85a16",
                )
                self.assertEqual(
                    {d.dimension: d.weight for d in result.dimensions},
                    config["category_profiles"][profile_id]["weights"],
                )
                expected = {
                    (dimension, metric["id"], metric["direction"])
                    for dimension, metrics in catalog_profile["dimensions"].items()
                    for metric in metrics
                }
                actual = {
                    (
                        metric.dimension,
                        metric.normalized.metric_id,
                        metric.normalized.direction.value,
                    )
                    for metric in result.metrics
                }
                self.assertEqual(actual, expected)
                self.assertEqual(
                    len({metric.normalized.metric_id for metric in result.metrics}), 12
                )
                self.assertEqual(
                    len({metric.evidence_family for metric in result.metrics}), 12
                )

    def test_fixed_worked_example_is_57_2(self) -> None:
        result = score()
        self.assertEqual(result.open_score, 57.2)
        self.assertTrue(
            all(metric.normalized.score == 50.0 for metric in result.metrics)
        )
        with self.assertRaises(FrozenInstanceError):
            result.open_score = 0.0  # type: ignore[misc]

    def test_full_score_rejects_each_duplicate_peer_economic_identity(self) -> None:
        observations, peers = profile_fixture("active_equity_mixed")
        metric_id = observations[0].metric_id
        metric_peers = tuple(peer for peer in peers if peer.metric_id == metric_id)
        self.assertEqual(len(metric_peers), 5)

        for field in ("peer_id", "series_id", "lineage_id"):
            duplicated = tuple(
                replace(peer, **{field: getattr(metric_peers[0], field)})
                if peer.metric_id == metric_id
                else peer
                for peer in peers
            )
            with (
                self.subTest(field=field),
                self.assertRaises(CategoryMetricError) as raised,
            ):
                score(peers=duplicated)
            self.assertEqual(raised.exception.code, "duplicate_peer")

    def test_full_score_allows_peer_identity_reuse_across_metrics(self) -> None:
        _, peers = profile_fixture("active_equity_mixed")
        first = peers[0]
        second_index = next(
            index
            for index, peer in enumerate(peers)
            if peer.metric_id != first.metric_id
        )
        reused = list(peers)
        reused[second_index] = replace(
            reused[second_index],
            peer_id=first.peer_id,
            series_id=first.series_id,
            lineage_id=first.lineage_id,
        )

        result = score(peers=tuple(reused))

        self.assertEqual(result.status, "scored")
        self.assertEqual(result.open_score, 57.2)

    def test_history_boundaries_and_regime_coverage_follow_rfc(self) -> None:
        cases = (
            (5, False, HistoryStage.INSUFFICIENT, None),
            (6, False, HistoryStage.OBSERVATION, None),
            (11, False, HistoryStage.OBSERVATION, None),
            (12, False, HistoryStage.PROVISIONAL, 57.2),
            (35, False, HistoryStage.PROVISIONAL, 57.2),
            (36, False, HistoryStage.PROVISIONAL, 57.2),
            (36, True, HistoryStage.ELIGIBLE, 57.2),
        )
        for months, coverage, stage, expected_score in cases:
            with self.subTest(months=months, coverage=coverage):
                result = score(history_months=months, adequate_regime_coverage=coverage)
                self.assertEqual(result.history_stage, stage)
                self.assertEqual(result.open_score, expected_score)
                performance = next(
                    dimension
                    for dimension in result.dimensions
                    if dimension.dimension == "performance_evidence"
                )
                if months < 12:
                    self.assertIsNone(performance.score)
                    self.assertIsNone(performance.contribution)
                    self.assertTrue(
                        all(
                            metric.normalized.score is None
                            for metric in performance.metrics
                        )
                    )

    def test_missing_and_conditional_na_core_metrics_block_dimension_and_total_without_reweighting(
        self,
    ) -> None:
        observations, _ = profile_fixture("bond")
        catalog, _ = load_metric_catalog()
        benchmark_metric_ids = {
            metric["id"]
            for metrics in catalog["profiles"]["bond"]["dimensions"].values()
            for metric in metrics
            if metric["applicability"] == "requires_declared_benchmark"
        }
        missing_id = next(
            item.metric_id
            for item in observations
            if item.metric_id not in benchmark_metric_ids
        )
        changed = tuple(
            observation(
                item.metric_id,
                state=MetricState.MISSING,
                raw=None,
                sample_size=0,
                window_months=0,
            )
            if item.metric_id == missing_id
            else observation(
                item.metric_id,
                state=MetricState.NOT_APPLICABLE,
                raw=None,
                sample_size=0,
                window_months=0,
            )
            if item.metric_id in benchmark_metric_ids
            else item
            for item in observations
        )
        result = score(
            "bond",
            observations=changed,
            applicability_context=ApplicabilityContext(
                declared_benchmark=False,
                cross_border_or_currency_exposure=True,
                derivative_or_commodity_exposure=True,
                income_distributing_assets=True,
                lookthrough_portfolio=True,
                securities_lending_program=True,
            ),
        )
        self.assertIsNone(result.open_score)
        self.assertEqual(result.status, "insufficient")
        self.assertEqual(result.missing_metric_ids, (missing_id,))
        self.assertEqual(
            set(result.not_applicable_metric_ids),
            {
                item.metric_id
                for item in changed
                if item.state is MetricState.NOT_APPLICABLE
            },
        )
        self.assertIn("core_metric_missing", result.insufficiency_reasons)
        self.assertIn("core_metric_not_applicable", result.insufficiency_reasons)
        self.assertEqual(sum(d.weight for d in result.dimensions), 100)

    def test_unconditionally_applicable_metric_rejects_not_applicable_state(
        self,
    ) -> None:
        observations, _ = profile_fixture("bond")
        unconditional = observations[2]
        changed = tuple(
            replace(
                item,
                state=MetricState.NOT_APPLICABLE,
                raw_value=None,
                sample_size=0,
                window_months=0,
            )
            if item.metric_id == unconditional.metric_id
            else item
            for item in observations
        )
        with self.assertRaises(CategoryMetricError) as raised:
            score("bond", observations=changed)
        self.assertEqual(raised.exception.code, "invalid_applicability")

    def test_conditional_applicability_requires_closed_prerequisite_truth(self) -> None:
        observations, _ = profile_fixture("index_etf")
        catalog, _ = load_metric_catalog()
        benchmark_metric_ids = {
            metric["id"]
            for metrics in catalog["profiles"]["index_etf"]["dimensions"].values()
            for metric in metrics
            if metric["applicability"] == "requires_declared_benchmark"
        }
        benchmark_metric = next(
            item for item in observations if item.metric_id == "benchmark_coverage"
        )
        not_applicable = tuple(
            replace(
                item,
                state=MetricState.NOT_APPLICABLE,
                raw_value=None,
                sample_size=0,
                window_months=0,
                capture_denominator=(
                    replace(
                        item.capture_denominator,
                        denominator_status=CaptureDenominatorStatus.ABSENT,
                        benchmark_downside_sample_count=0,
                    )
                    if item.capture_denominator is not None
                    else None
                ),
            )
            if item.metric_id in benchmark_metric_ids
            else item
            for item in observations
        )
        prerequisites = ApplicabilityContext(
            declared_benchmark=True,
            cross_border_or_currency_exposure=True,
            derivative_or_commodity_exposure=True,
            income_distributing_assets=True,
            lookthrough_portfolio=True,
            securities_lending_program=True,
        )
        with self.assertRaises(CategoryMetricError) as required_error:
            score(
                "index_etf",
                observations=not_applicable,
                applicability_context=prerequisites,
            )
        self.assertEqual(required_error.exception.code, "invalid_applicability")

        absent_benchmark = replace(prerequisites, declared_benchmark=False)
        result = score(
            "index_etf",
            observations=not_applicable,
            applicability_context=absent_benchmark,
        )
        self.assertIn(benchmark_metric.metric_id, result.not_applicable_metric_ids)

        with self.assertRaises(CategoryMetricError) as scored_error:
            score("index_etf", applicability_context=absent_benchmark)
        self.assertEqual(scored_error.exception.code, "invalid_applicability")

    def test_manager_handoff_is_required_and_legacy_bare_scores_are_rejected(
        self,
    ) -> None:
        with self.assertRaises(CategoryMetricError) as missing:
            score(manager_handoff=None)
        self.assertEqual(missing.exception.code, "manager_handoff_required")
        for value in (None, True, -0.1, 80.0, 100.1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(CategoryMetricError):
                score(manager_score=value)

    def test_legacy_manager_audit_mappings_are_rejected_without_authorization(
        self,
    ) -> None:
        impossible = cast(dict[str, Any], manager_result())
        impossible["component_contributions"]["tenure_attributed_performance"] = 76.0
        impossible["component_contributions"]["downside_control"] = 0.0
        impossible["component_contributions"]["cross_cycle_consistency"] = 0.0
        impossible["component_contributions"]["style_discipline"] = 0.0
        impossible["component_contributions"]["career_track_record"] = 0.0
        impossible["component_contributions"]["workload_capacity"] = 0.0
        impossible["component_contributions"]["research_platform_team"] = 0.0
        with self.assertRaises(CategoryMetricError) as contribution_error:
            score(manager_audit=impossible)
        self.assertEqual(
            contribution_error.exception.code, "legacy_manager_audit_rejected"
        )

        hollow = cast(dict[str, Any], deepcopy(manager_result()))
        hollow["tenure_attribution"]["tenures"] = [{}]
        hollow["tenure_attribution"]["observations"] = [{}]
        with self.assertRaises(CategoryMetricError) as tenure_error:
            score(manager_audit=hollow)
        self.assertEqual(tenure_error.exception.code, "legacy_manager_audit_rejected")

    def test_legacy_typed_manager_audit_is_rejected_without_authorization(self) -> None:
        valid = score()
        forged = replace(valid.manager_audit, score=99.0)
        with self.assertRaises(CategoryMetricError) as raised:
            score(manager_audit=forged)
        self.assertEqual(raised.exception.code, "legacy_manager_audit_rejected")

    def test_legacy_future_window_audits_are_rejected_without_authorization(
        self,
    ) -> None:
        future = cast(dict[str, Any], deepcopy(manager_result()))
        future["tenure_attribution"]["observations"][0].update(
            {"window_start": "2030-01-01", "window_end": "2030-12-31"}
        )
        with self.assertRaises(CategoryMetricError) as mapping_error:
            score(manager_audit=future)
        self.assertEqual(mapping_error.exception.code, "legacy_manager_audit_rejected")

        valid = score().manager_audit
        future_observation = replace(
            valid.observations[0],
            window_start="2030-01-01",
            window_end="2030-12-31",
        )
        typed = replace(valid, observations=(future_observation,))
        with self.assertRaises(CategoryMetricError) as typed_error:
            score(manager_audit=typed)
        self.assertEqual(typed_error.exception.code, "legacy_manager_audit_rejected")

    def test_fund_ledger_uses_canonical_utc_date_for_equivalent_offsets(self) -> None:
        baseline_observations, _ = profile_fixture("bond")
        baseline = score("bond", observations=baseline_observations)
        offset_observations = tuple(
            replace(
                item,
                as_of=item.as_of.astimezone(timezone(timedelta(hours=-5))),
            )
            for item in baseline_observations
        )
        shifted = score(
            "bond",
            observations=offset_observations,
            evidence_ledger=evidence_ledger("bond", offset_observations),
        )

        self.assertEqual(
            baseline.evidence_ledger_sha256, shifted.evidence_ledger_sha256
        )
        self.assertEqual(
            tuple(metric.normalized.as_of for metric in baseline.metrics),
            tuple(metric.normalized.as_of for metric in shifted.metrics),
        )

    def test_ledger_digest_canonicalizes_equivalent_offsets_without_mutating_rows(
        self,
    ) -> None:
        observations, _ = profile_fixture("bond")
        baseline = score("bond", observations=observations)
        ledger = cast(dict[str, Any], evidence_ledger("bond", observations))
        plus_eight = timezone(timedelta(hours=8))
        ledger["as_of"] = (
            datetime.fromisoformat(ledger["as_of"]).astimezone(plus_eight).isoformat()
        )
        for row in ledger["usage"]:
            row["observation_as_of"] = (
                datetime.fromisoformat(row["observation_as_of"])
                .astimezone(plus_eight)
                .isoformat()
            )
        raw_ledger = deepcopy(ledger)

        shifted = score("bond", observations=observations, evidence_ledger=ledger)

        self.assertEqual(ledger, raw_ledger)
        self.assertEqual(
            baseline.evidence_ledger_sha256, shifted.evidence_ledger_sha256
        )

    def test_capture_denominator_has_one_exact_independent_ledger_row(self) -> None:
        observations, _ = profile_fixture("active_equity_mixed")
        capture = next(
            item for item in observations if item.metric_id == "downside_capture"
        )
        denominator = capture.capture_denominator
        assert denominator is not None
        ledger = cast(
            dict[str, Any], evidence_ledger("active_equity_mixed", observations)
        )
        denominator_rows = [
            item
            for item in ledger["usage"]
            if item["evidence_role"] == "capture_denominator"
            and item["target_component"] == "fund_d2_downside_risk"
        ]
        self.assertEqual(len(denominator_rows), 1)
        self.assertEqual(
            denominator_rows[0],
            {
                "evidence_id": denominator.evidence_id,
                "evidence_role": "capture_denominator",
                "benchmark_downside_sample_count": (
                    denominator.benchmark_downside_sample_count
                ),
                "lineage_id": denominator.lineage_id,
                "series_id": denominator.series_id,
                "evidence_family": "benchmark_downside.downside_capture",
                "target_component": "fund_d2_downside_risk",
                "source_scope": "current_fund",
                "usage_mode": "raw",
                "observation_as_of": "2026-08-20T00:00:00Z",
                "window_basis": "calendar_months",
                "window_months": capture.window_months,
                "window_start": "2023-08-20",
                "window_end": "2026-08-20",
            },
        )

    def test_capture_denominator_ledger_rejects_missing_replaced_extra_and_duplicate_rows(
        self,
    ) -> None:
        observations, _ = profile_fixture("active_equity_mixed")
        baseline = cast(
            dict[str, Any], evidence_ledger("active_equity_mixed", observations)
        )
        denominator_index = next(
            index
            for index, item in enumerate(baseline["usage"])
            if item["evidence_role"] == "capture_denominator"
        )
        mutations = []
        missing = deepcopy(baseline)
        del missing["usage"][denominator_index]
        mutations.append(missing)
        replaced = deepcopy(baseline)
        replaced["usage"][denominator_index]["series_id"] = "forged-benchmark-series"
        mutations.append(replaced)
        extra = deepcopy(baseline)
        extra["usage"].append(
            deepcopy(extra["usage"][denominator_index])
            | {"evidence_id": "extra-denominator"}
        )
        mutations.append(extra)
        duplicate = deepcopy(baseline)
        duplicate["usage"].append(deepcopy(duplicate["usage"][denominator_index]))
        mutations.append(duplicate)

        for ledger in mutations:
            with self.subTest(ledger=ledger), self.assertRaises(CategoryMetricError):
                score(
                    "active_equity_mixed",
                    observations=observations,
                    evidence_ledger=ledger,
                )

    def test_missing_capture_has_no_denominator_ledger_row(self) -> None:
        observations, peers = profile_fixture("active_equity_mixed")
        changed = tuple(
            replace(
                item,
                state=MetricState.MISSING,
                raw_value=None,
                sample_size=0,
                window_months=0,
                capture_denominator=replace(
                    cast(CaptureDenominatorAudit, item.capture_denominator),
                    denominator_status=CaptureDenominatorStatus.ABSENT,
                    benchmark_downside_sample_count=0,
                ),
            )
            if item.metric_id == "downside_capture"
            else item
            for item in observations
        )
        ledger = cast(dict[str, Any], evidence_ledger("active_equity_mixed", changed))
        self.assertFalse(
            any(
                item["evidence_role"] == "capture_denominator"
                for item in ledger["usage"]
            )
        )
        result = score(
            observations=changed,
            peers=tuple(item for item in peers if item.metric_id != "downside_capture"),
            evidence_ledger=ledger,
        )
        self.assertIn("downside_capture", result.missing_metric_ids)

    def test_fund_ledger_binds_evidence_id_as_of_and_exact_window(self) -> None:
        observations, _ = profile_fixture("bond")
        for field, value in (
            ("evidence_id", "evidence-forged"),
            ("observation_as_of", "2026-08-19T00:00:00Z"),
            ("window_months", 1),
            ("window_start", "2026-08-20"),
        ):
            with self.subTest(field=field):
                ledger = cast(dict[str, Any], evidence_ledger("bond", observations))
                ledger["usage"][0][field] = value
                with self.assertRaises(CategoryMetricError) as raised:
                    score("bond", observations=observations, evidence_ledger=ledger)
                expected = (
                    "evidence_ledger_fund_mismatch"
                    if field == "evidence_id"
                    else "invalid_evidence_ledger"
                )
                self.assertEqual(raised.exception.code, expected)

    def test_manager_ledger_binds_each_component_evidence_id_exactly_once(self) -> None:
        observations, _ = profile_fixture("bond")
        ledger = cast(dict[str, Any], evidence_ledger("bond", observations))
        manager_entry = next(
            item
            for item in ledger["usage"]
            if item["target_component"] == "manager_downside_control"
        )
        manager_entry["evidence_id"] = "e-manager-style_discipline"
        with self.assertRaises(CategoryMetricError) as raised:
            score("bond", observations=observations, evidence_ledger=ledger)
        self.assertEqual(raised.exception.code, "evidence_ledger_manager_mismatch")

    def test_manager_ledger_binds_every_canonical_provenance_field(self) -> None:
        observations, _ = profile_fixture("bond")
        baseline = cast(dict[str, Any], evidence_ledger("bond", observations))
        manager_rows = [
            item
            for item in baseline["usage"]
            if item["target_component"].startswith("manager_")
        ]
        self.assertEqual(len(manager_rows), 8)
        self.assertEqual({"primary"}, {item["evidence_role"] for item in manager_rows})
        replacements = {
            "lineage_id": "forged-lineage",
            "series_id": "forged-series",
            "source_facts_sha256": "f" * 64,
            "evidence_family": "manager.forged",
            "source_scope": "team_platform",
            "usage_mode": "orthogonal",
            "observation_as_of": "2026-08-21T00:00:00Z",
            "window_basis": "point_in_time",
            "window_months": 35,
            "window_start": "2023-08-19",
            "window_end": "2026-08-19",
        }
        for field, value in replacements.items():
            with self.subTest(field=field):
                ledger = cast(dict[str, Any], evidence_ledger("bond", observations))
                manager_entry = next(
                    item
                    for item in ledger["usage"]
                    if item["target_component"]
                    == "manager_tenure_attributed_performance"
                )
                manager_entry[field] = value
                with self.assertRaises(CategoryMetricError) as raised:
                    score("bond", observations=observations, evidence_ledger=ledger)
                expected = (
                    "invalid_evidence_ledger"
                    if field in {"window_months", "window_start", "window_end"}
                    else "evidence_ledger_manager_mismatch"
                )
                self.assertEqual(raised.exception.code, expected)

    def test_score_rejects_unknown_missing_duplicate_observations_and_unknown_peers(
        self,
    ) -> None:
        observations, peers = profile_fixture("bond")
        with self.assertRaises(CategoryMetricError):
            score_category_metrics(
                profile_id="unknown",
                peer_bucket="active-equity-cn",
                peer_bucket_version="0.1.0",
                history_months=36,
                adequate_regime_coverage=True,
                observations=observations,
                peers=peers,
                manager_handoff=__import__(
                    "tests.test_manager_handoff", fromlist=["manager_handoff"]
                ).manager_handoff(),
                evidence_ledger=evidence_ledger("bond", observations),
            )
        cases = (
            {"observations": observations[:-1]},
            {"observations": observations[:-1] + (observations[0],)},
            {"observations": observations + (observation("unknown_metric"),)},
            {
                "peers": peers
                + (replace(peers[0], peer_id="peer-x", metric_id="unknown_metric"),)
            },
            {"peers": peers + (peers[0],)},
        )
        for overrides in cases:
            with (
                self.subTest(overrides=overrides),
                self.assertRaises(CategoryMetricError),
            ):
                score("bond", **overrides)

    def test_exact_catalog_window_cannot_be_shortened_to_fund_history(self) -> None:
        observations, _ = profile_fixture("bond", history_months=6)
        ongoing_charge = next(
            item for item in observations if item.metric_id == "ongoing_charge"
        )
        self.assertIs(ongoing_charge.state, MetricState.MISSING)
        forged_short_window = tuple(
            observation(
                item.metric_id,
                raw=3.0,
                sample_size=6,
                window_months=6,
            )
            if item.metric_id == "ongoing_charge"
            else item
            for item in observations
        )

        with self.assertRaises(CategoryMetricError) as raised:
            score("bond", history_months=6, observations=forged_short_window)

        self.assertEqual(raised.exception.code, "metric_window_mismatch")

    def test_formula_cross_fields_reject_impossible_recovery_and_day_counts(
        self,
    ) -> None:
        bond_observations, _ = profile_fixture("bond")
        impossible_recovery = tuple(
            replace(item, raw_value=1.0, window_months=0)
            if item.metric_id == "recovery_months"
            else item
            for item in bond_observations
        )
        with self.assertRaises(CategoryMetricError) as recovery_error:
            score("bond", observations=impossible_recovery)
        self.assertEqual(recovery_error.exception.code, "metric_cross_field_mismatch")

        money_observations, _ = profile_fixture("money_market")
        impossible_days = tuple(
            replace(item, raw_value=31.0, window_months=1, sample_size=1)
            if item.metric_id == "negative_return_days"
            else item
            for item in money_observations
        )
        with self.assertRaises(CategoryMetricError) as day_error:
            score("money_market", observations=impossible_days)
        self.assertEqual(day_error.exception.code, "metric_cross_field_mismatch")

    def test_peer_resource_version_and_positive_sample_are_enforced(self) -> None:
        peers = peer_set("excess_return")

        with self.assertRaises(CategoryMetricError) as version_error:
            normalize_metric(
                observation("excess_return"),
                tuple(
                    replace(item, peer_bucket_version="999.999.999") for item in peers
                ),
                direction=MetricDirection.HIGHER_IS_BETTER,
                peer_bucket="active-equity-cn",
                peer_bucket_version="999.999.999",
            )
        self.assertEqual(version_error.exception.code, "peer_admission_mismatch")

        zero_sample = (replace(peers[0], sample_size=0),) + peers[1:]
        with self.assertRaises(CategoryMetricError) as sample_error:
            normalize_metric(
                observation("excess_return"),
                zero_sample,
                direction=MetricDirection.HIGHER_IS_BETTER,
                peer_bucket="active-equity-cn",
                peer_bucket_version="0.1.0",
            )
        self.assertEqual(sample_error.exception.code, "invalid_peer")

    def test_peer_window_and_formula_contract_matches_target(self) -> None:
        peers = peer_set("excess_return")
        forged_window = (
            replace(
                peers[0],
                window_months=1,
                window_start="2026-07-20",
            ),
        ) + peers[1:]

        with self.assertRaises(CategoryMetricError) as raised:
            normalize_metric(
                observation("excess_return"),
                forged_window,
                direction=MetricDirection.HIGHER_IS_BETTER,
                peer_bucket="active-equity-cn",
                peer_bucket_version="0.1.0",
            )
        self.assertEqual(raised.exception.code, "peer_window_mismatch")

    def test_score_rejects_bad_scalars_windows_and_collection_shapes(self) -> None:
        observations, peers = profile_fixture("bond")
        cycle: list[object] = []
        cycle.append(cycle)
        cases = (
            {"history_months": True},
            {"history_months": -1},
            {"final_precision": True},
            {"final_precision": -1},
            {"final_precision": 9},
            {"adequate_regime_coverage": 1},
            {"peer_bucket": ""},
            {"peer_bucket": "b" * 65},
            {"peer_bucket": "ｂucket"},
            {"observations": list(observations)},
            {"peers": list(peers)},
            {"observations": {"cycle": cycle}},
        )
        for overrides in cases:
            with (
                self.subTest(overrides=overrides),
                self.assertRaises(CategoryMetricError),
            ):
                score("bond", **overrides)

        too_long_window = (
            observation(observations[0].metric_id, sample_size=37, window_months=37),
        ) + observations[1:]
        with self.assertRaises(CategoryMetricError):
            score("bond", observations=too_long_window, peers=peers, history_months=36)

    def test_every_public_input_failure_is_category_metric_error(self) -> None:
        malformed = MetricObservation(
            metric_id="metric",
            state="broken",
            raw_value=1.0,
            fund_id="fund-1",
            series_id="series",
            evidence_id="evidence",
            lineage_id="lineage",
            as_of=AS_OF,
            published_at=PUBLISHED,
            evaluation_timestamp=EVALUATION,
            sample_size=1,
            window_months=1,
        )
        with self.assertRaises(CategoryMetricError) as raised:
            normalize_metric(
                malformed,
                peer_set("metric"),
                direction=MetricDirection.HIGHER_IS_BETTER,
                peer_bucket="active-equity-cn",
                peer_bucket_version="0.1.0",
            )
        self.assertNotIsInstance(raised.exception, KeyError)
        self.assertNotIsInstance(raised.exception, TypeError)


if __name__ == "__main__":
    unittest.main()
