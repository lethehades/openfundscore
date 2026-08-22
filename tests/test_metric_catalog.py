from __future__ import annotations

import unittest
from copy import deepcopy

from openfundscore.formula_cross_fields import (
    FORMULA_CROSS_FIELD_RULES,
    FormulaCrossFieldManifestError,
    FormulaCrossFieldRule,
    FormulaCrossFieldValidationError,
    validate_formula_cross_fields,
    validate_formula_rule_manifest,
)
from openfundscore.metric_taxonomy import FORMULA_SEMANTICS
from openfundscore.resources import resolve_resource

REQUIRED_METRIC_FIELDS = {
    "id",
    "weight",
    "direction",
    "core",
    "evidence_family",
    "formula",
    "formula_owner",
    "domain",
    "unit",
    "value_range",
    "observation_window",
    "applicability",
    "data_source",
    "provenance_required",
}

EXPECTED_FORMULA_NAMES = frozenset(
    [
        "absolute_tracking_difference",
        "allocation_effect",
        "allocation_process_disclosure",
        "annualized_benchmark_excess",
        "asset_quality",
        "asset_valuation_governance",
        "below_investment_grade_exposure",
        "benchmark_coverage",
        "benchmark_excess",
        "benchmark_excess_return",
        "benchmark_return_gap",
        "benchmark_yield_excess",
        "carry_efficiency",
        "carry_roll_excess",
        "collateral_quality",
        "concentration_deviation",
        "concentration_hhi",
        "contract_concentration",
        "country_weight_deviation",
        "credit_concentration",
        "credit_drawdown",
        "credit_event_disclosure",
        "credit_valuation_controls",
        "cross_border_custody_controls",
        "cross_border_disclosure",
        "currency_adjusted_excess",
        "currency_adjusted_tracking_gap",
        "currency_concentration",
        "currency_downside_capture",
        "currency_stress_loss",
        "custody_or_collateral_controls",
        "disclosure_timeliness",
        "distribution_growth",
        "distribution_stability",
        "distribution_stress_loss",
        "downside_capture",
        "duration_mandate_fit",
        "expected_shortfall",
        "factor_residual_alpha",
        "futures_stress_loss",
        "fx_hedge_stability",
        "fx_implementation_cost",
        "fx_tracking_error",
        "global_regime_persistence",
        "high_quality_liquid_assets",
        "index_method_disclosure",
        "lifecycle_regime_persistence",
        "liquidity_cost",
        "liquidity_governance_quality",
        "liquidity_regime_persistence",
        "liquidity_stress_loss",
        "lookthrough_concentration",
        "lookthrough_total_cost",
        "mandate_active_share",
        "mandate_country_fit",
        "market_liquidity_cost",
        "maximum_drawdown",
        "negative_return_days",
        "occupancy_persistence",
        "ongoing_charge",
        "policy_benchmark_excess",
        "rate_credit_regime_persistence",
        "rate_regime_persistence",
        "recovery_months",
        "redemption_liquidity_buffer",
        "regime_persistence",
        "related_party_controls",
        "replication_method_stability",
        "roll_implementation_cost",
        "roll_regime_persistence",
        "roll_yield_efficiency",
        "rolling_excess_hit_rate",
        "rolling_goal_hit_rate",
        "rolling_positive_excess",
        "rolling_tracking_stability",
        "rolling_yield_rank_stability",
        "securities_lending_controls",
        "settlement_delay",
        "seven_day_yield_stability",
        "shadow_nav_disclosure",
        "spot_tracking_gap",
        "tenant_concentration",
        "total_expense",
        "total_return_excess",
        "tracking_error",
        "underlying_diversification",
        "underlying_due_diligence",
        "underlying_liquidity_cost",
        "valuation_control_quality",
        "valuation_cutoff_controls",
        "valuation_method_disclosure",
        "weighted_average_maturity",
    ]
)

EXPECTED_SEMANTIC_EXAMPLES = {
    "upstream_audited_raw/recovery_months/0.1.0": {
        "applicability": "all_profile_funds",
        "data_source": "fund_nav_and_market_series",
        "domain": "downside_risk",
        "formula_owner": "upstream_audited_provider",
        "observation_window": {
            "kind": "cumulative_period",
            "maximum": 1200,
            "minimum": 0,
            "unit": "months",
        },
        "unit": "months",
        "value_range": {"maximum": 1200.0, "minimum": 0.0},
    },
    "upstream_audited_raw/ongoing_charge/0.1.0": {
        "applicability": "all_profile_funds",
        "data_source": "fee_and_execution_records",
        "domain": "implementation_cost",
        "formula_owner": "upstream_audited_provider",
        "observation_window": {
            "kind": "reporting_period",
            "maximum": 12,
            "minimum": 12,
            "unit": "months",
        },
        "unit": "basis_points",
        "value_range": {"maximum": 1000.0, "minimum": 0.0},
    },
    "upstream_audited_raw/rolling_goal_hit_rate/0.1.0": {
        "applicability": "all_profile_funds",
        "data_source": "fund_nav_and_market_series",
        "domain": "consistency_stability",
        "formula_owner": "upstream_audited_provider",
        "observation_window": {
            "kind": "rolling_period",
            "maximum": 60,
            "minimum": 12,
            "unit": "months",
        },
        "unit": "ratio",
        "value_range": {"maximum": 1.0, "minimum": 0.0},
    },
    "upstream_audited_raw/benchmark_coverage/0.1.0": {
        "applicability": "requires_declared_benchmark",
        "data_source": "portfolio_holdings_and_lookthrough",
        "domain": "portfolio_exposure",
        "formula_owner": "upstream_audited_provider",
        "observation_window": {
            "kind": "point_in_time",
            "maximum": 0,
            "minimum": 0,
            "unit": "instant",
        },
        "unit": "ratio",
        "value_range": {"maximum": 1.0, "minimum": 0.0},
    },
    "upstream_audited_raw/negative_return_days/0.1.0": {
        "applicability": "all_profile_funds",
        "data_source": "fund_nav_and_market_series",
        "domain": "downside_risk",
        "formula_owner": "upstream_audited_provider",
        "observation_window": {
            "kind": "rolling_period",
            "maximum": 12,
            "minimum": 1,
            "unit": "months",
        },
        "unit": "count",
        "value_range": {"maximum": 366.0, "minimum": 0.0},
    },
}


class MetricCatalogTests(unittest.TestCase):
    def _catalog(self) -> dict:
        return resolve_resource(
            resource_type="metric-catalog",
            name="openfundscore-category-metrics",
            version="0.1.0",
        ).load_json()

    def test_packaged_catalog_validates_complete_contract(self) -> None:
        from openfundscore.metric_catalog import validate_metric_catalog

        catalog = self._catalog()
        validate_metric_catalog(catalog)
        self.assertEqual(
            set(catalog["profiles"]),
            {
                "active_equity_mixed",
                "fixed_income_plus",
                "index_etf",
                "bond",
                "money_market",
                "qdii_active",
                "qdii_index",
                "fof_pension",
                "gold_commodity",
                "public_reit",
            },
        )
        for profile in catalog["profiles"].values():
            self.assertEqual(len(profile["dimensions"]), 6)
            self.assertTrue(
                all(len(metrics) == 2 for metrics in profile["dimensions"].values())
            )
            self.assertTrue(
                all(
                    metric["core"] is True
                    for metrics in profile["dimensions"].values()
                    for metric in metrics
                )
            )

    def test_all_120_entries_have_closed_auditable_formula_taxonomy(self) -> None:
        catalog = self._catalog()
        metrics = [
            metric
            for profile in catalog["profiles"].values()
            for dimension_metrics in profile["dimensions"].values()
            for metric in dimension_metrics
        ]
        self.assertEqual(len(metrics), 120)
        self.assertEqual(len({metric["formula"] for metric in metrics}), 92)
        self.assertEqual(len(catalog["formula_semantics"]), 92)
        self.assertEqual(len(EXPECTED_FORMULA_NAMES), 92)
        self.assertEqual(
            set(catalog["formula_semantics"]),
            {f"upstream_audited_raw/{name}/0.1.0" for name in EXPECTED_FORMULA_NAMES},
        )
        self.assertEqual(
            set(catalog["formula_semantics"]),
            {metric["formula"] for metric in metrics},
        )
        contracts_by_formula: dict[str, tuple[object, ...]] = {}
        sources: set[str] = set()
        for metric in metrics:
            self.assertEqual(set(metric), REQUIRED_METRIC_FIELDS)
            value_range = metric["value_range"]
            window = metric["observation_window"]
            self.assertEqual(set(value_range), {"minimum", "maximum"})
            self.assertEqual(
                set(window),
                {"kind", "unit", "minimum", "maximum"},
            )
            self.assertGreaterEqual(window["maximum"], window["minimum"])
            sources.add(metric["data_source"])
            taxonomy = (
                metric["domain"],
                metric["unit"],
                tuple(sorted(value_range.items())),
                tuple(sorted(window.items())),
                metric["applicability"],
                metric["formula_owner"],
                metric["data_source"],
            )
            prior = contracts_by_formula.setdefault(metric["formula"], taxonomy)
            self.assertEqual(prior, taxonomy)
        self.assertGreaterEqual(len(sources), 6)
        self.assertNotIn("audited_upstream_observation", sources)

    def test_all_92_formulas_have_explicit_reviewed_rule_kinds_and_reasons(
        self,
    ) -> None:
        validate_formula_rule_manifest(FORMULA_CROSS_FIELD_RULES, FORMULA_SEMANTICS)
        self.assertEqual(len(FORMULA_CROSS_FIELD_RULES), 92)
        self.assertEqual(
            set(FORMULA_CROSS_FIELD_RULES),
            {formula.split("/")[-2] for formula in FORMULA_SEMANTICS},
        )
        kinds = {rule.kind for rule in FORMULA_CROSS_FIELD_RULES.values()}
        self.assertEqual(
            kinds,
            {
                "independent_range",
                "period_sample",
                "negative_day_count",
                "recovery_duration_months",
                "event_duration_days",
                "point_in_time_maturity_days",
            },
        )
        self.assertTrue(
            all(rule.reason.strip() for rule in FORMULA_CROSS_FIELD_RULES.values())
        )
        self.assertNotIn("window_only", kinds)
        self.assertNotIn("unknown", kinds)

    def test_formula_rule_manifest_validator_rejects_review_bypasses(self) -> None:
        base = dict(FORMULA_CROSS_FIELD_RULES)
        cases: list[dict[str, FormulaCrossFieldRule]] = []
        missing = dict(base)
        missing.pop("ongoing_charge")
        cases.append(missing)
        unknown = dict(base)
        unknown["ongoing_charge"] = FormulaCrossFieldRule(
            kind="unknown",
            reason="attempted placeholder",  # type: ignore[arg-type]
        )
        cases.append(unknown)
        empty_reason = dict(base)
        empty_reason["ongoing_charge"] = FormulaCrossFieldRule(
            kind="period_sample", reason="   "
        )
        cases.append(empty_reason)
        incompatible = dict(base)
        incompatible["ongoing_charge"] = FormulaCrossFieldRule(
            kind="independent_range",
            reason="attempt to bypass reporting-period sample review",
        )
        cases.append(incompatible)

        for index, invalid in enumerate(cases):
            with (
                self.subTest(index=index),
                self.assertRaises(FormulaCrossFieldManifestError),
            ):
                validate_formula_rule_manifest(invalid, FORMULA_SEMANTICS)

    def test_worked_examples_cover_every_formula_rule_kind(self) -> None:
        from datetime import UTC, datetime

        as_of = datetime(2026, 8, 20, tzinfo=UTC)
        accepted = (
            ("benchmark_coverage", 0.8, 50, 0),
            ("ongoing_charge", 80.0, 12, 12),
            ("negative_return_days", 10, 20, 1),
            ("recovery_months", 6, 36, 36),
            ("settlement_delay", 5, 12, 1),
            ("weighted_average_maturity", 60, 80, 0),
        )
        self.assertEqual(
            {FORMULA_CROSS_FIELD_RULES[name].kind for name, *_ in accepted},
            {rule.kind for rule in FORMULA_CROSS_FIELD_RULES.values()},
        )
        for name, raw_value, sample_size, window_months in accepted:
            with self.subTest(name=name):
                validate_formula_cross_fields(
                    formula=f"upstream_audited_raw/{name}/0.1.0",
                    raw_value=raw_value,
                    sample_size=sample_size,
                    window_months=window_months,
                    observation_as_of=as_of,
                )

        rejected = (
            ("ongoing_charge", 80.0, 11, 12),
            ("negative_return_days", 21, 20, 1),
            ("recovery_months", 37, 36, 36),
            ("settlement_delay", 33, 12, 1),
            ("weighted_average_maturity", 60, 80, 1),
        )
        for name, raw_value, sample_size, window_months in rejected:
            with (
                self.subTest(rejected=name),
                self.assertRaises(FormulaCrossFieldValidationError),
            ):
                validate_formula_cross_fields(
                    formula=f"upstream_audited_raw/{name}/0.1.0",
                    raw_value=raw_value,
                    sample_size=sample_size,
                    window_months=window_months,
                    observation_as_of=as_of,
                )

    def test_integer_units_reject_bool_and_fractional_values(self) -> None:
        from datetime import UTC, datetime

        as_of = datetime(2026, 8, 22, tzinfo=UTC)
        cases = (
            ("negative_return_days", 12, 36),
            ("recovery_months", 12, 36),
            ("settlement_delay", 1, 12),
            ("weighted_average_maturity", 0, 1),
        )
        for formula, window_months, sample_size in cases:
            for raw_value in (True, 0.5):
                with (
                    self.subTest(formula=formula, raw_value=raw_value),
                    self.assertRaises(FormulaCrossFieldValidationError),
                ):
                    validate_formula_cross_fields(
                        formula=f"upstream_audited_raw/{formula}/0.1.0",
                        raw_value=raw_value,
                        sample_size=sample_size,
                        window_months=window_months,
                        observation_as_of=as_of,
                    )

    def test_negative_day_count_inherits_period_coverage_and_inclusive_day_capacity(
        self,
    ) -> None:
        from datetime import UTC, datetime

        as_of = datetime(2026, 2, 28, tzinfo=UTC)
        validate_formula_cross_fields(
            formula="upstream_audited_raw/negative_return_days/0.1.0",
            raw_value=32,
            sample_size=32,
            window_months=1,
            observation_as_of=as_of,
        )
        for raw_value, sample_size, window_months in (
            (0, 11, 12),
            (13, 12, 12),
            (0, 33, 1),
        ):
            with self.assertRaises(FormulaCrossFieldValidationError):
                validate_formula_cross_fields(
                    formula="upstream_audited_raw/negative_return_days/0.1.0",
                    raw_value=raw_value,
                    sample_size=sample_size,
                    window_months=window_months,
                    observation_as_of=as_of,
                )

    def test_independent_range_still_enforces_point_in_time_window_contract(
        self,
    ) -> None:
        from datetime import UTC, datetime

        with self.assertRaises(FormulaCrossFieldValidationError):
            validate_formula_cross_fields(
                formula="upstream_audited_raw/benchmark_coverage/0.1.0",
                raw_value=0.8,
                sample_size=1,
                window_months=1,
                observation_as_of=datetime(2026, 8, 22, tzinfo=UTC),
            )

    def test_formula_manifest_matches_independent_worked_examples(self) -> None:
        catalog = self._catalog()
        manifest = catalog["formula_semantics"]
        for formula, expected in EXPECTED_SEMANTIC_EXAMPLES.items():
            with self.subTest(formula=formula):
                self.assertEqual(manifest[formula], expected)
                occurrences = [
                    metric
                    for profile in catalog["profiles"].values()
                    for metrics in profile["dimensions"].values()
                    for metric in metrics
                    if metric["formula"] == formula
                ]
                self.assertTrue(occurrences)
                for metric in occurrences:
                    self.assertEqual(
                        {field: metric[field] for field in expected}, expected
                    )

        charge_range = manifest["upstream_audited_raw/ongoing_charge/0.1.0"][
            "value_range"
        ]
        hit_rate_range = manifest["upstream_audited_raw/rolling_goal_hit_rate/0.1.0"][
            "value_range"
        ]
        pit_window = manifest["upstream_audited_raw/benchmark_coverage/0.1.0"][
            "observation_window"
        ]
        for formula in ("downside_capture", "currency_downside_capture"):
            capture = manifest[f"upstream_audited_raw/{formula}/0.1.0"]
            self.assertEqual(capture["unit"], "ratio")
            self.assertEqual(capture["value_range"], {"minimum": -5.0, "maximum": 5.0})
        wam = manifest["upstream_audited_raw/weighted_average_maturity/0.1.0"]
        self.assertEqual(wam["unit"], "days")
        self.assertEqual(wam["value_range"], {"minimum": 0.0, "maximum": 180.0})
        self.assertEqual(charge_range["minimum"], 0.0)
        self.assertEqual(hit_rate_range, {"minimum": 0.0, "maximum": 1.0})
        self.assertEqual(pit_window["kind"], "point_in_time")
        self.assertFalse(charge_range["minimum"] <= -0.01 <= charge_range["maximum"])
        self.assertFalse(hit_rate_range["minimum"] <= 1.01 <= hit_rate_range["maximum"])

    def test_validator_rejects_malformed_taxonomy_and_nonfinite_ranges(self) -> None:
        from openfundscore.metric_catalog import (
            MetricCatalogValidationError,
            validate_metric_catalog,
        )

        for field, value in (
            ("domain", "unknown"),
            ("unit", "mystery"),
            ("formula_owner", "engine"),
            ("data_source", "audited_upstream_observation"),
            ("applicability", "anything"),
            ("value_range", {"minimum": float("nan"), "maximum": 10}),
            (
                "observation_window",
                {
                    "kind": "rolling",
                    "unit": "months",
                    "minimum": 0,
                    "maximum": 36,
                },
            ),
        ):
            with self.subTest(field=field):
                invalid = deepcopy(self._catalog())
                metric = invalid["profiles"]["bond"]["dimensions"][
                    "performance_evidence"
                ][0]
                metric[field] = value
                with self.assertRaises(MetricCatalogValidationError):
                    validate_metric_catalog(invalid)

    def test_validator_rejects_semantically_wrong_known_values(self) -> None:
        from openfundscore.metric_catalog import (
            MetricCatalogValidationError,
            validate_metric_catalog,
        )

        base = self._catalog()
        formula = "upstream_audited_raw/ongoing_charge/0.1.0"
        occurrences = [
            metric
            for profile in base["profiles"].values()
            for metrics in profile["dimensions"].values()
            for metric in metrics
            if metric["formula"] == formula
        ]
        cases = (
            ("unit", "ratio"),
            ("value_range", {"minimum": -1.0, "maximum": 1000.0}),
            (
                "observation_window",
                {
                    "kind": "rolling_period",
                    "unit": "months",
                    "minimum": 1,
                    "maximum": 1200,
                },
            ),
            ("data_source", "fund_nav_and_market_series"),
        )
        for field, wrong_value in cases:
            with self.subTest(field=field):
                invalid = deepcopy(base)
                invalid_occurrences = [
                    metric
                    for profile in invalid["profiles"].values()
                    for metrics in profile["dimensions"].values()
                    for metric in metrics
                    if metric["formula"] == formula
                ]
                invalid["formula_semantics"][formula][field] = deepcopy(wrong_value)
                for metric in invalid_occurrences:
                    metric[field] = deepcopy(wrong_value)
                self.assertEqual(len(invalid_occurrences), len(occurrences))
                with self.assertRaises(MetricCatalogValidationError):
                    validate_metric_catalog(invalid)

    def test_validator_rejects_unknown_fields_bad_contracts_and_duplicates(
        self,
    ) -> None:
        from openfundscore.metric_catalog import (
            MetricCatalogValidationError,
            validate_metric_catalog,
        )

        base = self._catalog()
        cases = []
        unknown = deepcopy(base)
        unknown["unexpected"] = True
        cases.append(unknown)
        bad_sample = deepcopy(base)
        bad_sample["engine_contract"]["minimum_peer_sample"] = True
        cases.append(bad_sample)
        duplicate = deepcopy(base)
        metrics = duplicate["profiles"]["bond"]["dimensions"]["performance_evidence"]
        metrics[1]["id"] = metrics[0]["id"]
        cases.append(duplicate)
        optional = deepcopy(base)
        optional["profiles"]["bond"]["dimensions"]["performance_evidence"][0][
            "core"
        ] = False
        cases.append(optional)

        for invalid in cases:
            with (
                self.subTest(case=len(cases)),
                self.assertRaises(MetricCatalogValidationError),
            ):
                validate_metric_catalog(invalid)


if __name__ == "__main__":
    unittest.main()
