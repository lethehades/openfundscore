from __future__ import annotations

import importlib
import unittest
from copy import deepcopy
from typing import Any
from unittest.mock import Mock, patch

COMPONENT_IDS = (
    "tenure_attributed_performance",
    "downside_control",
    "cross_cycle_consistency",
    "style_discipline",
    "career_track_record",
    "workload_capacity",
    "research_platform_team",
    "compliance_integrity",
)


def manager_record() -> dict[str, Any]:
    component = {"score": None, "confidence": "insufficient", "evidence_ids": []}
    return {
        "manager_id": "manager-1",
        "canonical_name": "Example Manager",
        "public_professional_only": True,
        "as_of": "2026-08-21T00:00:00Z",
        "professional_profile": {},
        "employment_history": [],
        "tenures": [],
        "performance_evidence": [],
        "style_fingerprint": {},
        "workload": {},
        "compliance_events": [],
        "evidence": [],
        "score_components": {name: deepcopy(component) for name in COMPONENT_IDS},
    }


def provider_record() -> dict[str, Any]:
    return {
        "provider_id": "provider-1",
        "provider_record_id": "record-1",
        "namespace": "canonical_observation",
        "source_type": "regulator",
        "jurisdiction": "CN",
        "entity_type": "manager",
        "entity_id": "manager-1",
        "field": "canonical_name",
        "value": "Example Manager",
        "as_of": "2026-08-20T00:00:00Z",
        "published_at": "2026-08-20T00:00:00Z",
        "fetched_at": "2026-08-21T00:00:00Z",
        "source_url": "https://example.com/manager-1",
        "source_document_hash": "sha256:synthetic-record",
        "point_in_time_status": "verified",
        "quality_state": "verified",
        "rights": {
            "mode": "open_redistributable",
            "cache_allowed": True,
            "derived_works_allowed": True,
            "redistribution_allowed": True,
            "attribution_required": True,
            "public_display_allowed": True,
        },
    }


def provider_contract() -> dict[str, Any]:
    return {
        "provider_id": "provider-1",
        "source_type": "regulator",
        "jurisdictions": ["CN"],
        "authentication_mode": "none",
        "public_display_allowed": True,
        "rate_limit": {"requests_per_period": 10, "period_seconds": 1},
        "rights": {
            "mode": "open_redistributable",
            "cache_allowed": True,
            "derived_works_allowed": True,
            "redistribution_allowed": True,
            "attribution_required": True,
        },
    }


def external_rating() -> dict[str, Any]:
    return {
        "external_rating_id": "rating-1",
        "provider_id": "provider-1",
        "subject_type": "manager",
        "subject_id": "manager-1",
        "rating_type": "stars",
        "value": 5,
        "scale": "1-5",
        "as_of": "2026-08-20T00:00:00Z",
        "fetched_at": "2026-08-21T00:00:00Z",
        "source_url": "https://example.com/rating-1",
        "affects_open_score": False,
        "rights_mode": "open_redistributable",
        "display_status": "allowed",
    }


def score_evidence_usage() -> dict[str, Any]:
    return {
        "score_record_id": "score-1",
        "model_version": "0.1.0",
        "fund_strategy_id": "strategy-1",
        "category_profile": "active_equity_mixed",
        "as_of": "2026-08-21T00:00:00Z",
        "usage": [
            {
                "lineage_id": "lineage-1",
                "series_id": "series-1",
                "evidence_family": "total_return",
                "target_component": "fund_d1_performance_evidence",
                "source_scope": "current_fund",
                "usage_mode": "raw",
                "window_start": "2023-01-01",
                "window_end": "2025-12-31",
            }
        ],
    }


class RecordValidationTests(unittest.TestCase):
    def _api(self):
        try:
            return importlib.import_module("openfundscore.validation")
        except ModuleNotFoundError:
            self.fail("openfundscore.validation unified API is missing")

    def test_manager_research_runs_schema_then_semantic_validation(self) -> None:
        api = self._api()
        valid = manager_record()
        self.assertIsNone(
            api.validate_record(
                "manager_research",
                valid,
                schema_version="0.1.0",
            )
        )

        unresolved = manager_record()
        unresolved["score_components"]["downside_control"]["evidence_ids"] = [
            "private-marker"
        ]
        with self.assertRaises(api.RecordValidationError) as raised:
            api.validate_record(
                "manager_research",
                unresolved,
                schema_version="0.1.0",
            )

        self.assertEqual("semantic", raised.exception.stage)
        self.assertEqual("semantic_violation", raised.exception.code)
        self.assertEqual(
            "$.score_components.downside_control.evidence_ids[0]",
            raised.exception.path,
        )
        self.assertNotIn("private-marker", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_provider_record_requires_format_and_chronology_semantics(self) -> None:
        api = self._api()
        valid = provider_record()
        self.assertIsNone(
            api.validate_record(
                "provider_record",
                valid,
                schema_version="0.1.0",
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )
        )

        malformed_time = provider_record()
        malformed_time["as_of"] = "2026-08-20"
        with self.assertRaises(api.RecordValidationError) as schema_failure:
            api.validate_record(
                "provider_record",
                malformed_time,
                schema_version="0.1.0",
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )
        self.assertEqual("schema", schema_failure.exception.stage)
        self.assertEqual("schema_format", schema_failure.exception.code)
        self.assertEqual("$.as_of", schema_failure.exception.path)

        reversed_chronology = provider_record()
        reversed_chronology["published_at"] = "2026-08-22T00:00:00Z"
        with self.assertRaises(api.RecordValidationError) as semantic_failure:
            api.validate_record(
                "provider_record",
                reversed_chronology,
                schema_version="0.1.0",
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )
        self.assertEqual("semantic", semantic_failure.exception.stage)
        self.assertEqual("chronology_violation", semantic_failure.exception.code)
        self.assertEqual("$.published_at", semantic_failure.exception.path)

        with self.assertRaises(api.RecordValidationError) as missing_timestamp:
            api.validate_record(
                "provider_record",
                valid,
                schema_version="0.1.0",
            )
        self.assertEqual(
            "missing_evaluation_timestamp", missing_timestamp.exception.code
        )
        self.assertEqual("$evaluation_timestamp", missing_timestamp.exception.path)

    def test_contract_and_external_rating_semantics_are_not_schema_only(self) -> None:
        api = self._api()
        self.assertIsNone(
            api.validate_record(
                "provider_contract",
                provider_contract(),
                schema_version="0.1.0",
            )
        )
        self.assertIsNone(
            api.validate_record(
                "external_rating",
                external_rating(),
                schema_version="0.1.0",
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )
        )

        rating = external_rating()
        rating["as_of"] = "2026-08-22T00:00:00Z"
        with self.assertRaises(api.RecordValidationError) as chronology:
            api.validate_record(
                "external_rating",
                rating,
                schema_version="0.1.0",
                evaluation_timestamp="2026-08-23T00:00:00Z",
            )
        self.assertEqual("semantic", chronology.exception.stage)
        self.assertEqual("chronology_violation", chronology.exception.code)
        self.assertEqual("$.as_of", chronology.exception.path)

        semantics = importlib.import_module("openfundscore.contract_semantics")
        contradictory = provider_contract()
        contradictory["rights"]["redistribution_allowed"] = False
        with self.assertRaises(semantics.ContractValidationError) as rights:
            semantics.validate_provider_contract_semantics(contradictory)
        self.assertEqual("rights_mismatch", rights.exception.code)
        self.assertEqual("$.rights.redistribution_allowed", rights.exception.path)

    def test_score_evidence_usage_runs_duplicate_contribution_semantics(self) -> None:
        api = self._api()
        valid = score_evidence_usage()
        self.assertIsNone(
            api.validate_record(
                "score_evidence_usage",
                valid,
                schema_version="0.1.0",
            )
        )

        duplicated = score_evidence_usage()
        manager_usage = dict(duplicated["usage"][0])
        manager_usage["target_component"] = "manager_tenure_attributed_performance"
        duplicated["usage"].append(manager_usage)
        with self.assertRaises(api.RecordValidationError) as raised:
            api.validate_record(
                "score_evidence_usage",
                duplicated,
                schema_version="0.1.0",
            )
        self.assertEqual("semantic", raised.exception.stage)
        self.assertEqual("semantic_violation", raised.exception.code)
        self.assertEqual("$.usage[0]", raised.exception.path)
        self.assertNotIn("series-1", str(raised.exception))

    def test_boundary_errors_are_stable_and_do_not_echo_untrusted_values(self) -> None:
        api = self._api()

        invalid_uri = external_rating()
        invalid_uri["source_url"] = "private-marker"
        with self.assertRaises(api.RecordValidationError) as format_error:
            api.validate_record(
                "external_rating",
                invalid_uri,
                schema_version="0.1.0",
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )
        self.assertEqual("schema_format", format_error.exception.code)
        self.assertEqual("$.source_url", format_error.exception.path)
        self.assertNotIn("private-marker", str(format_error.exception))

        with self.assertRaises(api.RecordValidationError) as invalid_type:
            api.validate_record("private-marker", {}, schema_version="0.1.0")
        self.assertEqual("invalid_record_type", invalid_type.exception.code)
        self.assertEqual("$record_type", invalid_type.exception.path)
        self.assertNotIn("private-marker", str(invalid_type.exception))

        with self.assertRaises(api.RecordValidationError) as missing_schema:
            api.validate_record(
                "manager_research",
                manager_record(),
                schema_version="9.9.9",
            )
        self.assertEqual("schema_unavailable", missing_schema.exception.code)
        self.assertEqual("$schema", missing_schema.exception.path)
        self.assertNotIn("9.9.9", str(missing_schema.exception))

    def test_public_package_exports_validation_boundary(self) -> None:
        package = importlib.import_module("openfundscore")
        self.assertTrue(hasattr(package, "RecordType"))
        self.assertTrue(hasattr(package, "RecordValidationError"))
        self.assertTrue(hasattr(package, "validate_record"))
        self.assertIsNone(
            package.validate_record(
                package.RecordType.MANAGER_RESEARCH,
                manager_record(),
                schema_version="0.1.0",
            )
        )

    def test_api_rejects_non_json_values_before_schema_validation(self) -> None:
        api = self._api()
        non_finite = provider_record()
        non_finite["value"] = float("nan")
        with self.assertRaises(api.RecordValidationError) as raised:
            api.validate_record(
                "provider_record",
                non_finite,
                schema_version="0.1.0",
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )
        self.assertEqual("schema", raised.exception.stage)
        self.assertEqual("non_json_value", raised.exception.code)
        self.assertEqual("$.value", raised.exception.path)

    def test_schema_version_is_explicit_and_shared_json_subobjects_are_allowed(
        self,
    ) -> None:
        api = self._api()
        with self.assertRaises(TypeError):
            api.validate_record("manager_research", manager_record())

        shared_component = {
            "score": None,
            "confidence": "insufficient",
            "evidence_ids": [],
        }
        shared_document = manager_record()
        shared_document["score_components"]["tenure_attributed_performance"] = (
            shared_component
        )
        shared_document["score_components"]["downside_control"] = shared_component
        self.assertIsNone(
            api.validate_record(
                "manager_research",
                shared_document,
                schema_version="0.1.0",
            )
        )

        cyclic_document = manager_record()
        cyclic_document["professional_profile"]["cycle"] = cyclic_document
        with self.assertRaises(api.RecordValidationError) as cyclic:
            api.validate_record(
                "manager_research",
                cyclic_document,
                schema_version="0.1.0",
            )
        self.assertEqual("non_json_value", cyclic.exception.code)

    def test_invalid_schema_and_validator_recursion_fail_closed(self) -> None:
        api = self._api()
        invalid_resource = Mock()
        invalid_resource.load_json.return_value = {"type": "private-marker"}
        with (
            patch(
                "openfundscore.validation.resolve_resource",
                return_value=invalid_resource,
            ),
            self.assertRaises(api.RecordValidationError) as invalid_schema,
        ):
            api.validate_record(
                "manager_research",
                manager_record(),
                schema_version="0.1.0",
            )
        self.assertEqual("schema_unavailable", invalid_schema.exception.code)
        self.assertEqual("$schema", invalid_schema.exception.path)
        self.assertNotIn("private-marker", str(invalid_schema.exception))
        self.assertIsNone(invalid_schema.exception.__context__)

        malformed = manager_record()
        del malformed["manager_id"]
        with (
            patch(
                "openfundscore.validation._first_schema_error",
                side_effect=RecursionError("private-marker"),
            ),
            self.assertRaises(api.RecordValidationError) as recursion,
        ):
            api.validate_record(
                "manager_research",
                malformed,
                schema_version="0.1.0",
            )
        self.assertEqual("schema_validation_failed", recursion.exception.code)
        self.assertEqual("$", recursion.exception.path)
        self.assertNotIn("private-marker", str(recursion.exception))
        self.assertIsNone(recursion.exception.__context__)


if __name__ == "__main__":
    unittest.main()
