from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import unittest

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from openfundscore.evidence_usage import (
    EvidenceUsageValidationError,
    validate_score_evidence_usage,
)


def _usage(target_component: str, **overrides: str) -> dict[str, str]:
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


def _record(*usages: dict[str, str]) -> dict[str, Any]:
    return {
        "score_record_id": "score-2026-08-21-fund-1",
        "model_version": "0.1.0",
        "fund_strategy_id": "fund-strategy-1",
        "category_profile": "active_equity_mixed",
        "as_of": "2026-08-21T00:00:00Z",
        "usage": list(usages),
    }


ROOT = Path(__file__).parents[1]


class EvidenceUsageSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = ROOT / "schemas" / "score_evidence_usage.schema.json"
        self.schema = json.loads(schema_path.read_text(encoding="utf-8"))
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
                target = invalid if usage_index is None else invalid["usage"][usage_index]
                target[field] = value
                with self.assertRaises(ValidationError):
                    self.validator.validate(invalid)


class EvidenceUsageSemanticTests(unittest.TestCase):
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

    def test_rejects_overlapping_raw_current_fund_series_across_fund_and_manager(self) -> None:
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
