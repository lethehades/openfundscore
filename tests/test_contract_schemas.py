from __future__ import annotations

import unittest
from copy import deepcopy

from jsonschema import Draft202012Validator, ValidationError

from openfundscore.resources import resolve_resource


class ContractSchemaTests(unittest.TestCase):
    def _load(self, name: str) -> dict:
        resource_name = name.removesuffix(".schema.json")
        return resolve_resource(
            resource_type="schema",
            name=resource_name,
            version="0.1.0",
        ).load_json()

    def _manager_record(self) -> dict:
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
            "score_components": {
                name: deepcopy(component)
                for name in (
                    "tenure_attributed_performance",
                    "downside_control",
                    "cross_cycle_consistency",
                    "style_discipline",
                    "career_track_record",
                    "workload_capacity",
                    "research_platform_team",
                    "compliance_integrity",
                )
            },
        }

    def _provider_record(self, mode: str, **rights_overrides: bool) -> dict:
        rights = {
            "mode": mode,
            "cache_allowed": False,
            "derived_works_allowed": mode == "derived_only",
            "redistribution_allowed": False,
            "attribution_required": False,
            "public_display_allowed": mode == "display_only",
        }
        rights.update(rights_overrides)
        return {
            "provider_id": "provider-1",
            "namespace": "canonical_observation",
            "source_type": "official_registry",
            "jurisdiction": "CN",
            "entity_type": "manager",
            "entity_id": "manager-1",
            "field": "canonical_name",
            "value": "Example Manager",
            "as_of": "2026-08-21T00:00:00Z",
            "published_at": "2026-08-21T00:00:00Z",
            "fetched_at": "2026-08-21T00:00:00Z",
            "source_url": "https://example.com/manager-1",
            "point_in_time_status": "verified",
            "quality_state": "verified",
            "rights": rights,
        }

    def test_schemas_are_valid_draft_2020_12(self) -> None:
        for name in (
            "external_rating.schema.json",
            "manager_research.schema.json",
            "provider_record.schema.json",
        ):
            with self.subTest(schema=name):
                Draft202012Validator.check_schema(self._load(name))

    def test_provider_record_requires_provenance_and_rights(self) -> None:
        schema = self._load("provider_record.schema.json")
        required = set(schema["required"])
        self.assertTrue(
            {
                "provider_id",
                "entity_id",
                "field",
                "value",
                "as_of",
                "published_at",
                "fetched_at",
                "source_url",
                "rights",
            }.issubset(required)
        )

    def test_manager_research_is_public_professional_and_tenure_aware(self) -> None:
        schema = self._load("manager_research.schema.json")
        required = set(schema["required"])
        self.assertTrue(
            {"manager_id", "tenures", "evidence", "score_components"}.issubset(required)
        )
        self.assertTrue(schema["properties"]["public_professional_only"]["const"])
        tenure = schema["properties"]["tenures"]["items"]["properties"]
        self.assertIn("attribution_share", tenure)

    def test_scored_or_high_confidence_manager_components_require_evidence(
        self,
    ) -> None:
        validator = Draft202012Validator(self._load("manager_research.schema.json"))

        scored = self._manager_record()
        scored["score_components"]["downside_control"]["score"] = 75
        with self.subTest(case="non-null score"), self.assertRaises(ValidationError):
            validator.validate(scored)

        high_confidence = self._manager_record()
        high_confidence["score_components"]["downside_control"]["confidence"] = "high"
        with self.subTest(case="high confidence"), self.assertRaises(ValidationError):
            validator.validate(high_confidence)

        evidenced = self._manager_record()
        evidenced["score_components"]["downside_control"].update(
            {"score": 75, "confidence": "high", "evidence_ids": ["evidence-1"]}
        )
        validator.validate(evidenced)

    def test_unknown_blocked_disallows_all_rights(self) -> None:
        validator = Draft202012Validator(self._load("provider_record.schema.json"))

        for permission in (
            "cache_allowed",
            "derived_works_allowed",
            "redistribution_allowed",
            "attribution_required",
        ):
            with self.subTest(permission=permission):
                record = self._provider_record("unknown_blocked", **{permission: True})
                with self.assertRaises(ValidationError):
                    validator.validate(record)

        validator.validate(self._provider_record("unknown_blocked"))

    def test_restricted_rights_modes_disallow_raw_redistribution(self) -> None:
        validator = Draft202012Validator(self._load("provider_record.schema.json"))

        for mode in ("derived_only", "display_only", "local_entitlement"):
            with self.subTest(mode=mode):
                record = self._provider_record(mode, redistribution_allowed=True)
                with self.assertRaises(ValidationError):
                    validator.validate(record)

                validator.validate(self._provider_record(mode))

    def test_external_ratings_are_a_non_scoring_side_channel(self) -> None:
        external = self._load("external_rating.schema.json")
        provider = self._load("provider_record.schema.json")

        self.assertFalse(external["properties"]["affects_open_score"]["const"])
        self.assertIn(
            "external_rating",
            provider["properties"]["entity_type"]["enum"],
        )


if __name__ == "__main__":
    unittest.main()
