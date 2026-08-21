from __future__ import annotations

import importlib
import unittest
from copy import deepcopy
from typing import Any, Callable


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


class ManagerSemanticsTests(unittest.TestCase):
    def _validator(self) -> Callable[[dict[str, Any]], None]:
        try:
            module = importlib.import_module("openfundscore.manager_research")
        except ModuleNotFoundError:
            self.fail("openfundscore.manager_research validation API is missing")
        return module.validate_manager_research

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
            "compliance_events": [],
            "evidence": [],
            "score_components": {
                name: deepcopy(component) for name in COMPONENT_IDS
            },
        }

    def _evidence(self, evidence_id: str = "evidence-1", tier: str = "A") -> dict:
        return {
            "evidence_id": evidence_id,
            "tier": tier,
            "source_url": "https://example.com/source",
            "published_at": "2026-08-20T00:00:00Z",
            "fetched_at": "2026-08-21T00:00:00Z",
            "fact_excerpt": "Public professional fact",
        }

    def test_minimal_public_professional_record_is_semantically_valid(self) -> None:
        self._validator()(self._record())

    def test_sensitive_private_markers_and_values_are_rejected_with_json_path(self) -> None:
        sensitive_texts = (
            "Home address withheld",
            "Residential address unavailable",
            "家庭住址未披露",
            "家庭地址未知",
            "住址不详",
            "Private life details",
            "私人生活信息",
            "Phone withheld",
            "联系电话未披露",
            "手机号未知",
            "Email withheld",
            "电子邮箱未披露",
            "身份证信息",
            "Social security number unavailable",
            "Contact: analyst@example.com",
            "Contact: 13800138000",
            "Identity: 11010519491231002X",
            "Contact: +1 (212) 555-0198",
        )

        for text in sensitive_texts:
            with self.subTest(text=text):
                record = self._record()
                record["professional_profile"]["official_biography"] = text
                with self.assertRaisesRegex(
                    ValueError,
                    r"\$\.professional_profile\.official_biography",
                ):
                    self._validator()(record)

    def test_sensitive_text_detection_recurses_into_arrays(self) -> None:
        record = self._record()
        record["professional_profile"]["public_education"] = [
            "Public university",
            "私人生活信息",
        ]

        with self.assertRaisesRegex(
            ValueError,
            r"\$\.professional_profile\.public_education\[1\]",
        ):
            self._validator()(record)

    def test_ordinary_dates_are_not_misclassified_as_phone_numbers(self) -> None:
        record = self._record()
        record["professional_profile"]["official_biography"] = (
            "Official appointment date: 2026-08-21; prior role ended 2025/12/31."
        )

        self._validator()(record)

    def test_all_nested_evidence_references_must_resolve_to_top_level_evidence(self) -> None:
        cases = (
            (
                "employment_history",
                lambda record: record["employment_history"].append(
                    {
                        "organisation": "Firm",
                        "role": "Manager",
                        "start_date": "2020-01-01",
                        "evidence_ids": ["missing-evidence"],
                    }
                ),
                r"\$\.employment_history\[0\]\.evidence_ids\[0\]",
            ),
            (
                "tenures",
                lambda record: record["tenures"].append(
                    {
                        "tenure_id": "tenure-1",
                        "fund_strategy_id": "strategy-1",
                        "start_date": "2020-01-01",
                        "role": "lead",
                        "attribution_mode": "individual",
                        "co_manager_ids": [],
                        "evidence_ids": ["missing-evidence"],
                    }
                ),
                r"\$\.tenures\[0\]\.evidence_ids\[0\]",
            ),
            (
                "compliance_events",
                lambda record: record["compliance_events"].append(
                    {
                        "event_id": "event-1",
                        "jurisdiction": "CN",
                        "status": "final_verified",
                        "evidence_ids": ["missing-evidence"],
                    }
                ),
                r"\$\.compliance_events\[0\]\.evidence_ids\[0\]",
            ),
            (
                "score_components",
                lambda record: record["score_components"]["downside_control"].update(
                    {"evidence_ids": ["missing-evidence"]}
                ),
                r"\$\.score_components\.downside_control\.evidence_ids\[0\]",
            ),
        )

        for label, add_reference, expected_path in cases:
            with self.subTest(location=label):
                record = self._record()
                add_reference(record)
                with self.assertRaisesRegex(ValueError, expected_path):
                    self._validator()(record)

    def test_existing_nested_evidence_references_are_accepted(self) -> None:
        record = self._record()
        record["evidence"] = [self._evidence()]
        record["score_components"]["downside_control"]["evidence_ids"] = [
            "evidence-1"
        ]

        self._validator()(record)

    def test_scored_or_high_confidence_compliance_rejects_tier_d_only_support(self) -> None:
        for score, confidence in ((80, "medium"), (None, "high")):
            with self.subTest(score=score, confidence=confidence):
                record = self._record()
                record["evidence"] = [self._evidence(tier="D")]
                record["score_components"]["compliance_integrity"].update(
                    {
                        "score": score,
                        "confidence": confidence,
                        "evidence_ids": ["evidence-1"],
                    }
                )

                with self.assertRaisesRegex(
                    ValueError,
                    r"\$\.score_components\.compliance_integrity\.evidence_ids",
                ):
                    self._validator()(record)

    def test_compliance_accepts_at_least_one_tier_a_b_or_c_reference(self) -> None:
        for qualifying_tier in ("A", "B", "C"):
            with self.subTest(tier=qualifying_tier):
                record = self._record()
                record["evidence"] = [
                    self._evidence("tier-d", "D"),
                    self._evidence("qualifying", qualifying_tier),
                ]
                record["score_components"]["compliance_integrity"].update(
                    {
                        "score": 80,
                        "confidence": "high",
                        "evidence_ids": ["tier-d", "qualifying"],
                    }
                )

                self._validator()(record)

    def test_tier_d_only_limit_is_specific_to_compliance_integrity(self) -> None:
        record = self._record()
        record["evidence"] = [self._evidence(tier="D")]
        record["score_components"]["downside_control"].update(
            {
                "score": 80,
                "confidence": "medium",
                "evidence_ids": ["evidence-1"],
            }
        )

        self._validator()(record)


if __name__ == "__main__":
    unittest.main()
