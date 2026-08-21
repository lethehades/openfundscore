from __future__ import annotations

from copy import deepcopy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openfundscore.score_config import (
    ConfigValidationError,
    load_score_config,
    validate_score_config,
)


CONFIG_PATH = Path(__file__).parents[1] / "configs" / "scoring" / "v0.1.0.json"


class ScoreConfigTests(unittest.TestCase):
    def test_every_category_and_manager_model_totals_100(self) -> None:
        config = load_score_config(CONFIG_PATH)
        validate_score_config(config)

        for category, profile in config["category_profiles"].items():
            with self.subTest(category=category):
                self.assertEqual(100, sum(profile["weights"].values()))

        self.assertEqual(
            100,
            sum(item["weight"] for item in config["manager_model"]["components"]),
        )

    def test_data_confidence_is_a_gate_not_a_score_dimension(self) -> None:
        config = load_score_config(CONFIG_PATH)
        score_dimensions = set(config["score_dimensions"])

        self.assertNotIn("data_confidence", score_dimensions)
        self.assertEqual("publication_gate", config["data_confidence"]["role"])

    def test_model_metadata_must_match_the_public_contract(self) -> None:
        base = load_score_config(CONFIG_PATH)
        cases = []

        for field in ("model_id", "model_version"):
            missing = deepcopy(base)
            del missing[field]
            cases.append((f"missing {field}", missing, field))

            empty = deepcopy(base)
            empty[field] = ""
            cases.append((f"empty {field}", empty, field))

            non_string = deepcopy(base)
            non_string[field] = 1
            cases.append((f"non-string {field}", non_string, field))

        missing_status = deepcopy(base)
        del missing_status["status"]
        cases.append(("missing status", missing_status, "status"))

        unsupported_status = deepcopy(base)
        unsupported_status["status"] = "production"
        cases.append(("unsupported status", unsupported_status, "status"))

        for label, config, message in cases:
            with self.subTest(case=label):
                with self.assertRaisesRegex(ConfigValidationError, message):
                    validate_score_config(config)

    def test_v0_1_model_identity_is_exact(self) -> None:
        base = load_score_config(CONFIG_PATH)
        for field, value in (
            ("model_id", "renamed-openfundscore-core"),
            ("model_version", "0.1.1"),
        ):
            with self.subTest(field=field):
                invalid = deepcopy(base)
                invalid[field] = value
                with self.assertRaisesRegex(ConfigValidationError, field):
                    validate_score_config(invalid)

    def test_score_dimension_names_and_descriptions_must_be_non_empty_strings(self) -> None:
        base = load_score_config(CONFIG_PATH)
        cases = []

        empty_name = deepcopy(base)
        description = empty_name["score_dimensions"].pop("performance_evidence")
        empty_name["score_dimensions"][""] = description
        cases.append(("empty name", empty_name))

        non_string_name = deepcopy(base)
        description = non_string_name["score_dimensions"].pop("performance_evidence")
        non_string_name["score_dimensions"][1] = description
        cases.append(("non-string name", non_string_name))

        empty_description = deepcopy(base)
        empty_description["score_dimensions"]["performance_evidence"] = ""
        cases.append(("empty description", empty_description))

        non_string_description = deepcopy(base)
        non_string_description["score_dimensions"]["performance_evidence"] = 1
        cases.append(("non-string description", non_string_description))

        for label, config in cases:
            with self.subTest(case=label):
                with self.assertRaisesRegex(ConfigValidationError, "score_dimensions"):
                    validate_score_config(config)

    def test_manager_components_must_match_exact_v0_1_mapping(self) -> None:
        base = load_score_config(CONFIG_PATH)
        expected = {
            "tenure_attributed_performance": 25,
            "downside_control": 15,
            "cross_cycle_consistency": 15,
            "style_discipline": 15,
            "career_track_record": 10,
            "workload_capacity": 8,
            "research_platform_team": 7,
            "compliance_integrity": 5,
        }
        self.assertEqual(
            expected,
            {
                component["id"]: component["weight"]
                for component in base["manager_model"]["components"]
            },
        )

        renamed = deepcopy(base)
        renamed["manager_model"]["components"][0]["id"] = "renamed_performance"

        reweighted = deepcopy(base)
        reweighted["manager_model"]["components"][0]["weight"] = 24
        reweighted["manager_model"]["components"][1]["weight"] = 16

        for label, invalid in (("renamed", renamed), ("reweighted", reweighted)):
            with self.subTest(case=label):
                with self.assertRaisesRegex(
                    ConfigValidationError, "manager_model.components"
                ):
                    validate_score_config(invalid)

    def test_manager_declared_total_must_be_integer_100(self) -> None:
        base = load_score_config(CONFIG_PATH)
        cases = []

        for value in (None, True, 999):
            invalid = deepcopy(base)
            if value is None:
                del invalid["manager_model"]["total"]
            else:
                invalid["manager_model"]["total"] = value
            cases.append((repr(value), invalid))

        for label, config in cases:
            with self.subTest(case=label):
                with self.assertRaisesRegex(ConfigValidationError, "manager_model.total"):
                    validate_score_config(config)

    def test_data_confidence_must_match_the_public_v0_1_contract(self) -> None:
        base = load_score_config(CONFIG_PATH)
        expected = {
            "role": "publication_gate",
            "levels": ["high", "medium", "low", "insufficient"],
            "missing_data_policy": "not_zero",
            "conflict_policy": "preserve_and_flag",
            "short_history_policy": "lower_confidence_not_higher_score",
        }

        for field, value in expected.items():
            with self.subTest(field=field, case="missing"):
                invalid = deepcopy(base)
                del invalid["data_confidence"][field]
                with self.assertRaisesRegex(ConfigValidationError, f"data_confidence.{field}"):
                    validate_score_config(invalid)

            with self.subTest(field=field, case="invalid"):
                invalid = deepcopy(base)
                invalid["data_confidence"][field] = ["invalid"] if field == "levels" else "invalid"
                with self.assertRaisesRegex(ConfigValidationError, f"data_confidence.{field}"):
                    validate_score_config(invalid)

    def test_v0_1_dimension_and_category_ids_are_exact(self) -> None:
        base = load_score_config(CONFIG_PATH)
        expected_dimensions = {
            "performance_evidence",
            "downside_risk",
            "consistency",
            "manager_capability",
            "portfolio_structure",
            "implementation_efficiency",
            "governance_operations",
        }
        expected_profiles = {
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
        }

        self.assertEqual(expected_dimensions, set(base["score_dimensions"]))
        self.assertEqual(expected_profiles, set(base["category_profiles"]))

        replaced_dimension = deepcopy(base)
        description = replaced_dimension["score_dimensions"].pop("manager_capability")
        replaced_dimension["score_dimensions"]["investor_suitability"] = description
        for profile in replaced_dimension["category_profiles"].values():
            weight = profile["weights"].pop("manager_capability")
            profile["weights"]["investor_suitability"] = weight

        replaced_profile = deepcopy(base)
        replaced_profile["category_profiles"]["arbitrary_strategy"] = (
            replaced_profile["category_profiles"].pop("public_reit")
        )

        for label, invalid in (
            ("dimension", replaced_dimension),
            ("profile", replaced_profile),
        ):
            with self.subTest(label=label):
                with self.assertRaisesRegex(ConfigValidationError, "exact"):
                    validate_score_config(invalid)

    def test_unknown_fields_are_rejected_at_every_config_object_boundary(self) -> None:
        base = load_score_config(CONFIG_PATH)
        cases = []

        top_level = deepcopy(base)
        top_level["unexpected"] = True
        cases.append(("top-level", top_level))

        profile = deepcopy(base)
        profile["category_profiles"]["bond"]["unexpected"] = True
        cases.append(("profile", profile))

        manager_model = deepcopy(base)
        manager_model["manager_model"]["unexpected"] = True
        cases.append(("manager model", manager_model))

        component = deepcopy(base)
        component["manager_model"]["components"][0]["unexpected"] = True
        cases.append(("component", component))

        confidence = deepcopy(base)
        confidence["data_confidence"]["unexpected"] = True
        cases.append(("data confidence", confidence))

        for label, invalid in cases:
            with self.subTest(label=label):
                with self.assertRaisesRegex(ConfigValidationError, "unknown field"):
                    validate_score_config(invalid)

    def test_load_wraps_all_file_and_text_decoding_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            undecodable = root / "undecodable.json"
            undecodable.write_bytes(b"\xff")

            with self.subTest(error="directory"):
                with self.assertRaises(ConfigValidationError):
                    load_score_config(root)

            with self.subTest(error="unicode"):
                with self.assertRaises(ConfigValidationError):
                    load_score_config(undecodable)

        for error in (PermissionError("denied"), OSError("device failure")):
            with self.subTest(error=type(error).__name__):
                with patch("openfundscore.score_config.Path.read_text", side_effect=error):
                    with self.assertRaises(ConfigValidationError):
                        load_score_config("config.json")

    def test_invalid_weight_and_confidence_contracts_are_rejected(self) -> None:
        base = load_score_config(CONFIG_PATH)
        cases = []

        wrong_total = deepcopy(base)
        wrong_total["category_profiles"]["bond"]["weights"]["governance_operations"] = 4
        cases.append(("total", wrong_total, "total 99"))

        missing_dimension = deepcopy(base)
        del missing_dimension["category_profiles"]["bond"]["weights"]["consistency"]
        cases.append(("missing dimension", missing_dimension, "total 88"))

        boolean_weight = deepcopy(base)
        boolean_weight["category_profiles"]["bond"]["weights"]["governance_operations"] = True
        cases.append(("boolean", boolean_weight, "non-negative integer"))

        negative_weight = deepcopy(base)
        negative_weight["category_profiles"]["bond"]["weights"]["governance_operations"] = -1
        cases.append(("negative", negative_weight, "non-negative integer"))

        duplicate_manager = deepcopy(base)
        duplicate_manager["manager_model"]["components"][1]["id"] = duplicate_manager[
            "manager_model"
        ]["components"][0]["id"]
        cases.append(("duplicate manager", duplicate_manager, "duplicate manager component"))

        confidence_as_score = deepcopy(base)
        confidence_as_score["score_dimensions"]["data_confidence"] = "must not be here"
        cases.append(("confidence dimension", confidence_as_score, "exactly seven"))

        wrong_confidence_role = deepcopy(base)
        wrong_confidence_role["data_confidence"]["role"] = "score_dimension"
        cases.append(("confidence role", wrong_confidence_role, "publication_gate"))

        for label, config, message in cases:
            with self.subTest(case=label):
                with self.assertRaisesRegex(ConfigValidationError, message):
                    validate_score_config(config)


if __name__ == "__main__":
    unittest.main()
