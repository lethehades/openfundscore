from __future__ import annotations

import unittest
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from openfundscore.evidence_usage import (
    EvidenceUsageValidationError,
    canonicalize_score_evidence_ledger_for_digest,
    validate_score_evidence_usage,
)
from openfundscore.resources import resolve_resource


def _usage(target_component: str, **overrides: Any) -> dict[str, Any]:
    usage = {
        "lineage_id": "lineage-current-fund",
        "series_id": "series-total-return",
        "evidence_family": "total_return",
        "target_component": target_component,
        "source_scope": "current_fund",
        "usage_mode": "raw",
        "window_start": "2023-01-01",
        "window_end": "2025-12-31",
    }
    usage.update(overrides)
    return usage


def _record(*usages: dict[str, Any]) -> dict[str, Any]:
    return {
        "score_record_id": "score-2026-08-21-fund-1",
        "model_version": "0.1.0",
        "fund_strategy_id": "fund-strategy-1",
        "category_profile": "active_equity_mixed",
        "as_of": "2026-08-21T00:00:00Z",
        "usage": list(usages),
    }


def _usage_v020(target_component: str, **overrides: Any) -> dict[str, Any]:
    usage = _usage(
        target_component,
        evidence_id="evidence-total-return",
        evidence_role="primary",
        observation_as_of="2025-12-31T00:00:00Z",
        window_basis="calendar_months",
        window_months=36,
        window_start="2022-12-31",
        window_end="2025-12-31",
    )
    if target_component.startswith("manager_"):
        usage["source_facts_sha256"] = "a" * 64
    usage.update(overrides)
    return usage


class EvidenceUsageSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = resolve_resource(
            resource_type="schema",
            name="score_evidence_usage",
            version="0.1.0",
        ).load_json()
        self.validator = Draft202012Validator(
            self.schema,
            format_checker=FormatChecker(),
        )

    def test_schema_is_valid_draft_2020_12_and_accepts_complete_record(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validator.validate(_record(_usage("fund_d1_performance_evidence")))

    def test_schema_requires_non_empty_record_and_usage_fields(self) -> None:
        required_top_level = (
            "score_record_id",
            "model_version",
            "fund_strategy_id",
            "category_profile",
            "as_of",
            "usage",
        )
        for field in required_top_level:
            with self.subTest(scope="record", field=field):
                invalid = _record(_usage("fund_d1_performance_evidence"))
                del invalid[field]
                with self.assertRaises(ValidationError):
                    self.validator.validate(invalid)

        required_usage = (
            "lineage_id",
            "series_id",
            "evidence_family",
            "target_component",
            "source_scope",
            "usage_mode",
            "window_start",
            "window_end",
        )
        for field in required_usage:
            with self.subTest(scope="usage", field=field):
                invalid = _record(_usage("fund_d1_performance_evidence"))
                del invalid["usage"][0][field]
                with self.assertRaises(ValidationError):
                    self.validator.validate(invalid)

        for field in ("score_record_id", "model_version", "fund_strategy_id"):
            with self.subTest(scope="record", empty=field):
                invalid = _record(_usage("fund_d1_performance_evidence"))
                invalid[field] = ""
                with self.assertRaises(ValidationError):
                    self.validator.validate(invalid)

        for field in ("lineage_id", "series_id", "evidence_family"):
            with self.subTest(scope="usage", empty=field):
                invalid = _record(_usage("fund_d1_performance_evidence"))
                invalid["usage"][0][field] = ""
                with self.assertRaises(ValidationError):
                    self.validator.validate(invalid)

    def test_schema_accepts_all_seven_fund_dimension_components(self) -> None:
        fund_components = (
            "fund_d1_performance_evidence",
            "fund_d2_downside_risk",
            "fund_d3_consistency",
            "fund_d4_manager_capability",
            "fund_d5_portfolio_structure",
            "fund_d6_implementation_efficiency",
            "fund_d7_governance_operations",
        )
        for component in fund_components:
            with self.subTest(component=component):
                self.validator.validate(_record(_usage(component)))

    def test_schema_rejects_unknown_enum_values_and_invalid_dates(self) -> None:
        cases = (
            ("category_profile", None, "unknown_profile"),
            ("target_component", 0, "manager_unknown_component"),
            ("source_scope", 0, "current_manager"),
            ("usage_mode", 0, "adjusted"),
            ("as_of", None, "2026-08-21"),
            ("window_start", 0, "2026-99-99"),
        )
        for field, usage_index, value in cases:
            with self.subTest(field=field, value=value):
                invalid = _record(_usage("fund_d1_performance_evidence"))
                target = (
                    invalid if usage_index is None else invalid["usage"][usage_index]
                )
                target[field] = value
                with self.assertRaises(ValidationError):
                    self.validator.validate(invalid)


class EvidenceUsageV020SchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = resolve_resource(
            resource_type="schema",
            name="score_evidence_usage",
            version="0.2.0",
        ).load_json()
        self.validator = Draft202012Validator(
            self.schema,
            format_checker=FormatChecker(),
        )

    @staticmethod
    def usage() -> dict[str, Any]:
        return _usage_v020("fund_d1_performance_evidence")

    def test_schema_requires_explicit_consumed_observation_identity(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validator.validate(_record(self.usage()))
        for field in (
            "evidence_id",
            "evidence_role",
            "observation_as_of",
            "window_basis",
            "window_months",
        ):
            with self.subTest(field=field):
                invalid = _record(self.usage())
                del invalid["usage"][0][field]
                with self.assertRaises(ValidationError):
                    self.validator.validate(invalid)

    def test_schema_requires_facts_digest_only_for_manager_primary_rows(self) -> None:
        manager_primary = _usage_v020(
            "manager_tenure_attributed_performance",
            source_facts_sha256="a" * 64,
        )
        self.validator.validate(_record(manager_primary))

        missing_manager_digest = _usage_v020("manager_tenure_attributed_performance")
        del missing_manager_digest["source_facts_sha256"]
        invalid_rows = (
            missing_manager_digest,
            self.usage() | {"source_facts_sha256": "a" * 64},
            self.usage() | {"source_facts_sha256": None},
            self.usage()
            | {
                "evidence_role": "capture_denominator",
                "benchmark_downside_sample_count": 12,
                "source_facts_sha256": "a" * 64,
            },
        )
        for row in invalid_rows:
            with self.subTest(row=row), self.assertRaises(ValidationError):
                self.validator.validate(_record(row))

    def test_schema_closes_evidence_role_to_primary_or_capture_denominator(
        self,
    ) -> None:
        primary = self.usage() | {"evidence_role": "primary"}
        denominator = self.usage() | {
            "evidence_role": "capture_denominator",
            "benchmark_downside_sample_count": 12,
        }
        self.validator.validate(_record(primary))
        self.validator.validate(_record(denominator))

        invalid_rows = (
            self.usage() | {"evidence_role": "implicit_primary"},
            self.usage() | {"evidence_role": "capture_denominator"},
            primary | {"benchmark_downside_sample_count": 12},
        )
        for row in invalid_rows:
            with self.subTest(row=row), self.assertRaises(ValidationError):
                self.validator.validate(_record(row))

    def test_published_v010_schema_bytes_remain_unchanged(self) -> None:
        resource = resolve_resource(
            resource_type="schema",
            name="score_evidence_usage",
            version="0.1.0",
        )
        self.assertEqual(
            resource.info.sha256,
            "9ff9acffb1a19a8d6c0691d7dc99895211dd8224dac308f29f9270b56f7430f5",
        )


class EvidenceUsageSemanticTests(unittest.TestCase):
    def test_digest_canonicalizer_normalizes_only_declared_date_times(self) -> None:
        raw = _record(
            _usage_v020(
                "manager_tenure_attributed_performance",
                source_facts_sha256="a" * 64,
                observation_as_of="2026-01-01T08:00:00+08:00",
                window_basis="actual_dates",
                window_months=36,
                window_start="2023-01-01",
                window_end="2025-12-31",
            )
        )
        raw["as_of"] = "2026-08-21T08:00:00+08:00"
        untouched = __import__("copy").deepcopy(raw)

        canonical = canonicalize_score_evidence_ledger_for_digest(raw)

        self.assertEqual(raw, untouched)
        self.assertIsNot(canonical, raw)
        self.assertEqual(canonical["as_of"], "2026-08-21T00:00:00Z")
        self.assertEqual(
            canonical["usage"][0]["observation_as_of"], "2026-01-01T00:00:00Z"
        )
        self.assertEqual(canonical["usage"][0]["window_start"], "2023-01-01")
        self.assertEqual(canonical["usage"][0]["window_end"], "2025-12-31")
        self.assertEqual(
            canonical,
            canonicalize_score_evidence_ledger_for_digest(
                untouched
                | {
                    "as_of": "2026-08-20T19:00:00-05:00",
                    "usage": [
                        untouched["usage"][0]
                        | {"observation_as_of": "2025-12-31T19:00:00-05:00"}
                    ],
                }
            ),
        )
        shifted = __import__("copy").deepcopy(untouched)
        shifted["usage"][0]["observation_as_of"] = "2026-01-01T00:00:01Z"
        self.assertNotEqual(
            canonical, canonicalize_score_evidence_ledger_for_digest(shifted)
        )
        invalid = __import__("copy").deepcopy(raw)
        invalid["as_of"] = "2026-08-21"
        with self.assertRaises(EvidenceUsageValidationError):
            canonicalize_score_evidence_ledger_for_digest(invalid)

    def test_v020_rejects_observation_after_ledger_as_of_for_fund_and_manager(
        self,
    ) -> None:
        for component in (
            "fund_d1_performance_evidence",
            "manager_tenure_attributed_performance",
        ):
            with self.subTest(component=component):
                record = _record(
                    _usage_v020(
                        component,
                        observation_as_of="2026-08-22T00:00:00Z",
                    )
                )
                with self.assertRaisesRegex(
                    EvidenceUsageValidationError,
                    r"usage\[0\]\.observation_as_of.*on or before.*\$\.as_of",
                ):
                    validate_score_evidence_usage(record)

    def test_v020_uses_utc_observation_date_and_exact_calendar_month_window(
        self,
    ) -> None:
        valid = _record(
            _usage_v020(
                "manager_workload_capacity",
                observation_as_of="2024-03-01T00:30:00+14:00",
                window_months=1,
                window_start="2024-01-29",
                window_end="2024-02-29",
            )
        )
        validate_score_evidence_usage(valid)

        cases = (
            {"window_end": "2024-03-01", "window_start": "2024-02-01"},
            {"window_start": "2024-01-31"},
            {"window_months": 0, "window_start": "2024-02-28"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                invalid_usage = _usage_v020(
                    "manager_workload_capacity",
                    observation_as_of="2024-03-01T00:30:00+14:00",
                    window_months=1,
                    window_start="2024-01-29",
                    window_end="2024-02-29",
                )
                invalid_usage.update(overrides)
                with self.assertRaises(EvidenceUsageValidationError):
                    validate_score_evidence_usage(_record(invalid_usage))

    def test_v020_instant_window_is_zero_months_on_utc_observation_date(self) -> None:
        valid = _record(
            _usage_v020(
                "manager_research_platform_team",
                observation_as_of="2024-03-01T00:30:00+14:00",
                window_basis="point_in_time",
                window_months=0,
                window_start="2024-02-29",
                window_end="2024-02-29",
            )
        )
        validate_score_evidence_usage(valid)

    def test_v020_actual_dates_preserve_real_endpoints_without_reverse_clamp(
        self,
    ) -> None:
        valid = _record(
            _usage_v020(
                "manager_tenure_attributed_performance",
                observation_as_of="2024-03-31T00:00:00Z",
                window_basis="actual_dates",
                window_months=1,
                window_start="2024-02-01",
                window_end="2024-03-30",
            )
        )
        validate_score_evidence_usage(valid)

        invalid = _record(
            _usage_v020(
                "manager_tenure_attributed_performance",
                observation_as_of="2024-03-29T00:00:00Z",
                window_basis="actual_dates",
                window_months=1,
                window_start="2024-02-01",
                window_end="2024-03-30",
            )
        )
        with self.assertRaisesRegex(EvidenceUsageValidationError, "window_end"):
            validate_score_evidence_usage(invalid)

    def test_v020_actual_dates_recompute_months_from_real_endpoints(self) -> None:
        invalid = _record(
            _usage_v020(
                "manager_tenure_attributed_performance",
                observation_as_of="2026-01-02T00:00:00Z",
                window_basis="actual_dates",
                window_months=1200,
                window_start="2026-01-01",
                window_end="2026-01-02",
            )
        )

        with self.assertRaisesRegex(EvidenceUsageValidationError, "window_months"):
            validate_score_evidence_usage(invalid)

    def test_v010_semantics_remain_legacy_without_v020_fields(self) -> None:
        legacy = _record(
            _usage(
                "fund_d1_performance_evidence",
                window_start="2023-01-01",
                window_end="2025-12-31",
            )
        )
        validate_score_evidence_usage(legacy)

    def test_accepts_all_seven_fund_dimension_components(self) -> None:
        fund_components = (
            "fund_d1_performance_evidence",
            "fund_d2_downside_risk",
            "fund_d3_consistency",
            "fund_d4_manager_capability",
            "fund_d5_portfolio_structure",
            "fund_d6_implementation_efficiency",
            "fund_d7_governance_operations",
        )
        for component in fund_components:
            with self.subTest(component=component):
                validate_score_evidence_usage(_record(_usage(component)))

    def test_rejects_overlapping_raw_current_fund_series_across_fund_and_manager(
        self,
    ) -> None:
        record = _record(
            _usage("fund_d1_performance_evidence"),
            _usage("manager_tenure_attributed_performance"),
        )

        with self.assertRaisesRegex(
            EvidenceUsageValidationError,
            r"double-counted raw current_fund evidence.*series-total-return.*total_return",
        ):
            validate_score_evidence_usage(record)

    def test_rejects_same_lineage_despite_renamed_series_and_family(self) -> None:
        fund_components = (
            "fund_d1_performance_evidence",
            "fund_d2_downside_risk",
            "fund_d3_consistency",
            "fund_d4_manager_capability",
            "fund_d5_portfolio_structure",
            "fund_d6_implementation_efficiency",
            "fund_d7_governance_operations",
        )
        manager_tenure_components = (
            "manager_tenure_attributed_performance",
            "manager_downside_control",
            "manager_cross_cycle_consistency",
        )
        for fund_component in fund_components:
            for manager_component in manager_tenure_components:
                with self.subTest(
                    fund_component=fund_component,
                    manager_component=manager_component,
                ):
                    record = _record(
                        _usage(fund_component),
                        _usage(
                            manager_component,
                            series_id="renamed-series",
                            evidence_family="renamed_family",
                        ),
                    )
                    with self.assertRaisesRegex(
                        EvidenceUsageValidationError,
                        r"double-counted raw current_fund evidence.*lineage-current-fund",
                    ):
                        validate_score_evidence_usage(record)

    def test_rejects_same_series_despite_renamed_family(self) -> None:
        record = _record(
            _usage("fund_d1_performance_evidence"),
            _usage(
                "manager_tenure_attributed_performance",
                lineage_id="renamed-lineage",
                evidence_family="renamed_family",
            ),
        )

        with self.assertRaisesRegex(
            EvidenceUsageValidationError,
            r"double-counted raw current_fund evidence.*series-total-return",
        ):
            validate_score_evidence_usage(record)

    def test_rejects_same_evidence_id_despite_renamed_lineage_and_series(self) -> None:
        record = _record(
            _usage_v020("fund_d1_performance_evidence"),
            _usage_v020(
                "manager_tenure_attributed_performance",
                lineage_id="renamed-lineage",
                series_id="renamed-series",
            ),
        )

        with self.assertRaisesRegex(
            EvidenceUsageValidationError,
            r"double-counted raw current_fund evidence.*evidence-total-return",
        ):
            validate_score_evidence_usage(record)

    def test_rejects_unknown_target_component_with_clear_error(self) -> None:
        record = _record(_usage("manager_unknown_component"))

        with self.assertRaisesRegex(
            EvidenceUsageValidationError,
            r"usage\[0\]\.target_component.*manager_unknown_component.*unknown",
        ):
            validate_score_evidence_usage(record)

    def test_rejects_fully_duplicate_usage_entries_with_indexes(self) -> None:
        usage = _usage("fund_d2_downside_risk")
        record = _record(usage, dict(usage))

        with self.assertRaisesRegex(
            EvidenceUsageValidationError,
            r"duplicate usage entries.*usage\[0\].*usage\[1\]",
        ):
            validate_score_evidence_usage(record)

    def test_allows_residualized_and_orthogonal_manager_tenure_evidence(self) -> None:
        for mode in ("residualized", "orthogonal"):
            with self.subTest(usage_mode=mode):
                record = _record(
                    _usage("fund_d1_performance_evidence"),
                    _usage("manager_tenure_attributed_performance", usage_mode=mode),
                )
                validate_score_evidence_usage(record)

    def test_allows_raw_external_career_evidence_for_manager(self) -> None:
        record = _record(
            _usage("fund_d3_consistency"),
            _usage(
                "manager_cross_cycle_consistency",
                source_scope="external_career",
            ),
        )

        validate_score_evidence_usage(record)

    def test_allows_non_overlapping_raw_current_fund_windows(self) -> None:
        record = _record(
            _usage(
                "fund_d2_downside_risk",
                window_start="2020-01-01",
                window_end="2021-12-31",
            ),
            _usage(
                "manager_downside_control",
                window_start="2022-01-01",
                window_end="2023-12-31",
            ),
        )

        validate_score_evidence_usage(record)

    def test_boundary_touch_is_overlap_for_inclusive_windows(self) -> None:
        record = _record(
            _usage(
                "fund_d1_performance_evidence",
                window_start="2023-01-01",
                window_end="2024-01-01",
            ),
            _usage(
                "manager_tenure_attributed_performance",
                window_start="2024-01-01",
                window_end="2025-01-01",
            ),
        )

        with self.assertRaisesRegex(
            EvidenceUsageValidationError,
            r"double-counted raw current_fund evidence.*overlapping windows",
        ):
            validate_score_evidence_usage(record)

    def test_rejects_reversed_window_with_usage_index(self) -> None:
        record = _record(
            _usage(
                "fund_d1_performance_evidence",
                window_start="2025-01-01",
                window_end="2024-01-01",
            )
        )

        with self.assertRaisesRegex(
            EvidenceUsageValidationError,
            r"usage\[0\].*window_start.*window_end",
        ):
            validate_score_evidence_usage(record)


if __name__ == "__main__":
    unittest.main()
