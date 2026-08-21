from __future__ import annotations

import unittest
from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

from openfundscore.resources import resolve_resource

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


class ManagerSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = resolve_resource(
            resource_type="schema",
            name="manager_research",
            version="0.1.0",
        ).load_json()
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)

    def _record(self) -> dict[str, Any]:
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
            "research_platform": {},
            "compliance_assessment": {},
            "compliance_events": [],
            "evidence": [],
            "score_components": {name: deepcopy(component) for name in COMPONENT_IDS},
        }

    def _assert_invalid(self, record: dict[str, Any]) -> None:
        with self.assertRaises(ValidationError):
            self.validator.validate(record)

    def test_minimal_record_with_explicit_empty_research_blocks_is_valid(self) -> None:
        self.validator.validate(self._record())

    def test_domain_fact_strings_must_be_nonempty(self) -> None:
        for field in ("organisation", "role"):
            with self.subTest(employment_field=field):
                record = self._record()
                record["employment_history"] = [
                    {
                        "organisation": "Example Asset Manager",
                        "role": "Portfolio Manager",
                        "start_date": "2020-01-01",
                        "evidence_ids": [],
                    }
                ]
                record["employment_history"][0][field] = ""
                self._assert_invalid(record)

        record = self._record()
        record["workload"] = {"team_coverage": "", "evidence_ids": []}
        self._assert_invalid(record)

    def test_numeric_component_score_cannot_claim_insufficient_confidence(self) -> None:
        record = self._record()
        record["evidence"] = [
            {
                "evidence_id": "e-score",
                "tier": "A",
                "source_url": "https://example.com/score",
                "published_at": "2026-08-20T00:00:00Z",
                "fetched_at": "2026-08-21T00:00:00Z",
                "fact_excerpt": "Auditable public professional evidence.",
            }
        ]
        record["score_components"]["career_track_record"] = {
            "score": 80,
            "confidence": "insufficient",
            "evidence_ids": ["e-score"],
        }
        self._assert_invalid(record)

    def test_evidence_reference_and_support_lists_are_unique(self) -> None:
        record = self._record()
        record["evidence"] = [
            {
                "evidence_id": "e-score",
                "tier": "A",
                "source_url": "https://example.com/score",
                "published_at": "2026-08-20T00:00:00Z",
                "fetched_at": "2026-08-21T00:00:00Z",
                "fact_excerpt": "Auditable public professional evidence.",
                "supports_components": [
                    "career_track_record",
                    "career_track_record",
                ],
            }
        ]
        self._assert_invalid(record)

        record = self._record()
        record["employment_history"] = [
            {
                "organisation": "Example Asset Manager",
                "role": "Portfolio Manager",
                "start_date": "2020-01-01",
                "evidence_ids": ["e-score", "e-score"],
            }
        ]
        self._assert_invalid(record)

    def test_all_professional_research_blocks_are_required(self) -> None:
        required_blocks = {
            "professional_profile",
            "employment_history",
            "performance_evidence",
            "style_fingerprint",
            "workload",
            "research_platform",
            "compliance_assessment",
            "compliance_events",
        }
        self.assertTrue(required_blocks.issubset(self.schema["required"]))
        for block in required_blocks:
            with self.subTest(block=block):
                record = self._record()
                del record[block]
                self._assert_invalid(record)

    def test_every_nested_object_schema_is_closed(self) -> None:
        open_object_paths: list[str] = []

        def walk(node: Any, path: str = "$") -> None:
            if isinstance(node, dict):
                node_type = node.get("type")
                is_object = node_type == "object" or (
                    isinstance(node_type, list) and "object" in node_type
                )
                if (
                    is_object
                    and path != "$"
                    and node.get("additionalProperties") is not False
                ):
                    open_object_paths.append(path)
                for key, value in node.items():
                    walk(value, f"{path}/{key}")
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, f"{path}/{index}")

        walk(self.schema)
        self.assertEqual([], open_object_paths)

    def test_style_fingerprint_accepts_timestamped_quantitative_snapshots(self) -> None:
        record = self._record()
        record["style_fingerprint"] = {
            "factor_exposures": {
                "as_of": "2026-08-20T00:00:00Z",
                "measures": [
                    {"name": "value", "value": 0.4},
                    {"name": "momentum", "value": -0.1},
                ],
                "methodology": "rolling regression",
            },
            "change_points": [
                {
                    "effective_date": "2025-01-01",
                    "known_at": "2026-08-20T00:00:00Z",
                    "kind": "mandate_change",
                    "explanation": "Officially documented mandate change.",
                    "evidence_ids": ["e-style"],
                }
            ],
            "evidence_ids": ["e-style"],
        }
        record["evidence"] = [
            {
                "evidence_id": "e-style",
                "tier": "A",
                "source_url": "https://example.com/style",
                "published_at": "2026-08-19T00:00:00Z",
                "fetched_at": "2026-08-20T00:00:00Z",
                "fact_excerpt": "Public professional style evidence.",
            }
        ]
        self.validator.validate(record)

    def test_performance_observations_require_unique_ids(self) -> None:
        record = self._record()
        item = {
            "observation_id": "observation-1",
            "tenure_id": "tenure-1",
            "window_start": "2020-01-01",
            "window_end": "2020-12-31",
            "metric_id": "factor_residual",
            "value": 0.01,
            "confidence": "medium",
        }
        record["performance_evidence"] = [item, deepcopy(item)]
        self._assert_invalid(record)

        missing = self._record()
        del item["observation_id"]
        missing["performance_evidence"] = [item]
        self._assert_invalid(missing)

    def test_private_or_unknown_fields_are_rejected(self) -> None:
        cases = []

        top_level = self._record()
        top_level["home_address"] = "private"
        cases.append(("top-level home address", top_level))

        profile = self._record()
        profile["professional_profile"]["private_life"] = "private"
        cases.append(("professional private life", profile))

        workload = self._record()
        workload["workload"]["home_address"] = "private"
        cases.append(("workload home address", workload))

        style = self._record()
        style["style_fingerprint"]["factor_exposures"] = {"private_life": True}
        cases.append(("nested style field", style))

        for label, record in cases:
            with self.subTest(label=label):
                self._assert_invalid(record)

    def test_role_weighted_tenure_requires_bounded_attribution_share(self) -> None:
        tenure = {
            "tenure_id": "tenure-1",
            "fund_strategy_id": "strategy-1",
            "start_date": "2020-01-01",
            "role": "lead",
            "attribution_mode": "role_weighted",
            "co_manager_ids": [],
            "evidence_ids": [],
        }
        for share in ("missing", None, -0.01, 0, 1, 1.01):
            with self.subTest(share=share):
                record = self._record()
                record["tenures"] = [deepcopy(tenure)]
                if share != "missing":
                    record["tenures"][0]["attribution_share"] = share
                self._assert_invalid(record)

        for share in (0.25, 0.5, 0.75):
            with self.subTest(valid_share=share):
                record = self._record()
                record["tenures"] = [deepcopy(tenure)]
                record["tenures"][0]["attribution_share"] = share
                self.validator.validate(record)

    def test_null_performance_value_requires_nonempty_missing_reason(self) -> None:
        evidence = {
            "observation_id": "observation-1",
            "tenure_id": "tenure-1",
            "window_start": "2020-01-01",
            "window_end": "2021-01-01",
            "metric_id": "return",
            "value": None,
            "confidence": "insufficient",
        }
        for reason in ("missing", None, ""):
            with self.subTest(reason=reason):
                record = self._record()
                record["performance_evidence"] = [deepcopy(evidence)]
                if reason != "missing":
                    record["performance_evidence"][0]["missing_reason"] = reason
                self._assert_invalid(record)

        record = self._record()
        evidence["missing_reason"] = "not_disclosed"
        record["performance_evidence"] = [evidence]
        self.validator.validate(record)

    def test_null_score_requires_insufficient_confidence(self) -> None:
        for confidence in ("high", "medium", "low"):
            with self.subTest(confidence=confidence):
                record = self._record()
                record["score_components"]["downside_control"]["confidence"] = (
                    confidence
                )
                self._assert_invalid(record)

    def test_scored_components_require_nonempty_evidence_ids(self) -> None:
        for evidence_ids in ([], [""]):
            with self.subTest(evidence_ids=evidence_ids):
                record = self._record()
                record["score_components"]["downside_control"].update(
                    {"score": 75, "confidence": "high", "evidence_ids": evidence_ids}
                )
                self._assert_invalid(record)

        record = self._record()
        record["score_components"]["downside_control"].update(
            {"score": 75, "confidence": "high", "evidence_ids": ["evidence-1"]}
        )
        self.validator.validate(record)

    def test_evidence_requires_auditable_excerpt_or_content_hash(self) -> None:
        evidence = {
            "evidence_id": "evidence-1",
            "tier": "A",
            "source_url": "https://example.com/source",
            "published_at": "2026-08-20T00:00:00Z",
            "fetched_at": "2026-08-21T00:00:00Z",
        }
        for fields in (
            {},
            {"fact_excerpt": None},
            {"fact_excerpt": "", "content_hash": ""},
        ):
            with self.subTest(fields=fields):
                record = self._record()
                record["evidence"] = [{**evidence, **fields}]
                self._assert_invalid(record)

        for field in ("fact_excerpt", "content_hash"):
            with self.subTest(field=field):
                record = self._record()
                record["evidence"] = [{**evidence, field: "auditable-value"}]
                self.validator.validate(record)

    def test_all_relevant_ids_must_be_nonempty(self) -> None:
        record = self._record()
        record.update(
            {
                "source_identities": [
                    {
                        "provider_id": "provider-1",
                        "source_manager_id": "source-manager-1",
                    }
                ],
                "employment_history": [
                    {
                        "organisation": "Firm",
                        "role": "Manager",
                        "start_date": "2020-01-01",
                        "evidence_ids": ["evidence-1"],
                    }
                ],
                "tenures": [
                    {
                        "tenure_id": "tenure-1",
                        "fund_strategy_id": "strategy-1",
                        "start_date": "2020-01-01",
                        "role": "lead",
                        "attribution_mode": "individual",
                        "co_manager_ids": ["manager-2"],
                        "evidence_ids": ["evidence-1"],
                    }
                ],
                "performance_evidence": [
                    {
                        "observation_id": "observation-1",
                        "tenure_id": "tenure-1",
                        "window_start": "2020-01-01",
                        "window_end": "2021-01-01",
                        "metric_id": "return",
                        "value": 1.0,
                        "confidence": "medium",
                    }
                ],
                "compliance_events": [
                    {
                        "event_id": "event-1",
                        "jurisdiction": "CN",
                        "status": "final_verified",
                        "evidence_ids": ["evidence-1"],
                    }
                ],
                "evidence": [
                    {
                        "evidence_id": "evidence-1",
                        "tier": "A",
                        "source_url": "https://example.com/source",
                        "published_at": "2026-08-20T00:00:00Z",
                        "fetched_at": "2026-08-21T00:00:00Z",
                        "fact_excerpt": "Auditable fact",
                    }
                ],
            }
        )
        self.validator.validate(record)

        paths = (
            ("manager_id",),
            ("source_identities", 0, "provider_id"),
            ("source_identities", 0, "source_manager_id"),
            ("employment_history", 0, "evidence_ids", 0),
            ("tenures", 0, "tenure_id"),
            ("tenures", 0, "fund_strategy_id"),
            ("tenures", 0, "co_manager_ids", 0),
            ("tenures", 0, "evidence_ids", 0),
            ("performance_evidence", 0, "observation_id"),
            ("performance_evidence", 0, "tenure_id"),
            ("performance_evidence", 0, "metric_id"),
            ("compliance_events", 0, "event_id"),
            ("compliance_events", 0, "evidence_ids", 0),
            ("evidence", 0, "evidence_id"),
        )
        for path in paths:
            with self.subTest(path=path):
                invalid = deepcopy(record)
                target: Any = invalid
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = ""
                self._assert_invalid(invalid)


if __name__ == "__main__":
    unittest.main()
