from __future__ import annotations

import importlib
import unittest
from collections.abc import Callable
from copy import deepcopy
from typing import Any, cast

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


class SplitManagerRecord(dict):
    def __getitem__(self, key):
        if key == "manager_id":
            return "forged-manager"
        return super().__getitem__(key)


class SplitAsOfRecord(dict):
    def get(self, key, default=None):
        if key == "as_of":
            return "2099-01-01T00:00:00Z"
        return dict.get(self, key, default)


class ManagerSemanticsTests(unittest.TestCase):
    def test_manager_scoring_api_is_public(self) -> None:
        package = importlib.import_module("openfundscore")
        self.assertIn("score_manager_research", package.__all__)
        self.assertTrue(callable(package.score_manager_research))

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
            "research_platform": {},
            "compliance_assessment": {},
            "compliance_events": [],
            "evidence": [],
            "score_components": {name: deepcopy(component) for name in COMPONENT_IDS},
        }

    def _evidence(
        self,
        evidence_id: str = "evidence-1",
        tier: str = "A",
        *,
        supports_components: list[str] | None = None,
    ) -> dict:
        return {
            "evidence_id": evidence_id,
            "tier": tier,
            "source_url": "https://example.com/source",
            "published_at": "2026-08-20T00:00:00Z",
            "fetched_at": "2026-08-21T00:00:00Z",
            "fact_excerpt": "Public professional fact",
            "supports_components": (
                list(COMPONENT_IDS)
                if supports_components is None
                else supports_components
            ),
        }

    def _tenure(self) -> dict:
        return {
            "tenure_id": "tenure-1",
            "fund_strategy_id": "strategy-1",
            "start_date": "2020-01-01",
            "end_date": "2020-12-31",
            "role": "lead",
            "attribution_mode": "individual",
            "co_manager_ids": [],
            "transition_window_days": 30,
            "evidence_ids": [],
        }

    def _performance(self) -> dict:
        return {
            "observation_id": "observation-1",
            "tenure_id": "tenure-1",
            "window_start": "2020-01-31",
            "window_end": "2020-12-31",
            "metric_id": "benchmark_relative_return",
            "value": 0.01,
            "confidence": "medium",
        }

    def test_minimal_public_professional_record_is_semantically_valid(self) -> None:
        self._validator()(self._record())

    def test_sensitive_private_markers_and_values_are_rejected_with_json_path(
        self,
    ) -> None:
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

    def test_unicode_controls_cannot_hide_private_contact_information(self) -> None:
        controls = ("\u200b", "\u2060", "\ufeff", "\u0301")
        for control in controls:
            cases = (
                f"e{control}mail: analyst{control}@example.com",
                f"home{control} address: 123 Main Street",
                f"手{control}机号：138{control}0013{control}8000",
                f"身份证：110105194{control}91231002X",
            )
            for text in cases:
                with self.subTest(control=repr(control), text=repr(text)):
                    record = self._record()
                    record["professional_profile"]["official_biography"] = text
                    with self.assertRaisesRegex(
                        ValueError,
                        r"\$\.professional_profile\.official_biography",
                    ):
                        self._validator()(record)

    def test_common_email_obfuscation_cannot_hide_an_address(self) -> None:
        for text in (
            "Official source contact: analyst@example。com",
            "Official source contact: analyst [at] example.com",
            "Official source contact: analyst (at) example.com",
        ):
            with self.subTest(text=text):
                record = self._record()
                record["professional_profile"]["official_biography"] = text
                with self.assertRaisesRegex(
                    ValueError,
                    r"\$\.professional_profile\.official_biography",
                ):
                    self._validator()(record)

    def test_grouped_chinese_contact_numbers_are_rejected(self) -> None:
        for text in (
            "Number: 138 0013 8000",
            "Number: 138-0013-8000",
            "Identifier: 110105 19491231 002X",
            "Identifier: 110105-19491231-002X",
        ):
            with self.subTest(text=text):
                record = self._record()
                record["professional_profile"]["official_biography"] = text
                with self.assertRaisesRegex(
                    ValueError,
                    r"\$\.professional_profile\.official_biography",
                ):
                    self._validator()(record)

    def test_ordinary_dates_are_not_misclassified_as_phone_numbers(self) -> None:
        record = self._record()
        record["professional_profile"]["official_biography"] = (
            "Official appointment date: 2026-08-21; prior role ended 2025/12/31."
        )

        self._validator()(record)

    def test_public_phone_meetings_and_ten_digit_aum_are_not_private_contact(
        self,
    ) -> None:
        for text in (
            "主持季度电话会议与机构路演",
            "参加季度业绩电话会并回答分析师问题",
            "Hosted a quarterly phone conference for analysts.",
            "Joined the earnings phone call with institutional analysts.",
            "管理规模 2125550198 元",
        ):
            with self.subTest(text=text):
                record = self._record()
                record["professional_profile"]["official_biography"] = text
                self._validator()(record)

    def test_manager_evidence_source_urls_use_strict_privacy_boundary(self) -> None:
        module = importlib.import_module("openfundscore.manager_research")
        for api_name in ("validate_manager_research", "score_manager_research"):
            api = getattr(module, api_name)
            for source_url in (
                "https://example.com/2125550198",
                "https://example.com/212-555-0198",
                "https://example.com/212%2D555%2D0198",
                "https://example.com/person%2540example.com",
            ):
                with self.subTest(api=api_name, source_url=source_url):
                    record = self._record()
                    evidence = self._evidence()
                    evidence["source_url"] = source_url
                    record["evidence"] = [evidence]
                    with self.assertRaisesRegex(
                        ValueError,
                        r"\$\.evidence\[0\]\.source_url",
                    ):
                        api(record)

    def test_all_nested_evidence_references_must_resolve_to_top_level_evidence(
        self,
    ) -> None:
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
        record["score_components"]["downside_control"]["evidence_ids"] = ["evidence-1"]

        self._validator()(record)

    def test_scored_or_high_confidence_compliance_rejects_tier_d_only_support(
        self,
    ) -> None:
        for score, confidence in ((80, "medium"), (None, "high")):
            with self.subTest(score=score, confidence=confidence):
                record = self._record()
                record["evidence"] = [self._evidence(tier="D")]
                record["compliance_assessment"] = {
                    "review_status": "no_verified_events",
                    "reviewed_at": "2026-08-21T00:00:00Z",
                    "evidence_ids": ["evidence-1"],
                }
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
                record["compliance_assessment"] = {
                    "review_status": "no_verified_events",
                    "reviewed_at": "2026-08-21T00:00:00Z",
                    "evidence_ids": ["qualifying"],
                }
                record["score_components"]["compliance_integrity"].update(
                    {
                        "score": 80,
                        "confidence": "high",
                        "evidence_ids": ["tier-d", "qualifying"],
                    }
                )

                self._validator()(record)

    def test_compliance_tier_must_belong_to_the_structured_assessment(self) -> None:
        record = self._record()
        record["evidence"] = [
            self._evidence("assessment-tier-d", "D"),
            self._evidence("unrelated-tier-a", "A"),
        ]
        record["compliance_assessment"] = {
            "review_status": "no_verified_events",
            "reviewed_at": "2026-08-21T00:00:00Z",
            "evidence_ids": ["assessment-tier-d"],
        }
        record["score_components"]["compliance_integrity"].update(
            {
                "score": 80,
                "confidence": "high",
                "evidence_ids": ["assessment-tier-d", "unrelated-tier-a"],
            }
        )

        with self.assertRaisesRegex(
            ValueError,
            r"\$\.score_components\.compliance_integrity\.evidence_ids",
        ):
            self._validator()(record)

    def test_compliance_qualifying_tier_must_support_the_component(self) -> None:
        record = self._record()
        record["evidence"] = [
            self._evidence(
                "assessment-tier-d",
                "D",
                supports_components=["compliance_integrity"],
            ),
            self._evidence("arbitrary-tier-a", "A", supports_components=[]),
        ]
        record["compliance_assessment"] = {
            "review_status": "no_verified_events",
            "reviewed_at": "2026-08-21T00:00:00Z",
            "evidence_ids": ["assessment-tier-d", "arbitrary-tier-a"],
        }
        record["score_components"]["compliance_integrity"].update(
            {
                "score": 80,
                "confidence": "high",
                "evidence_ids": ["assessment-tier-d", "arbitrary-tier-a"],
            }
        )

        with self.assertRaisesRegex(
            ValueError,
            r"\$\.score_components\.compliance_integrity\.evidence_ids",
        ):
            self._validator()(record)

    def test_compliance_assessment_cannot_use_evidence_learned_later(self) -> None:
        record = self._record()
        record["evidence"] = [self._evidence("e-future", "A")]
        record["compliance_assessment"] = {
            "review_status": "no_verified_events",
            "reviewed_at": "2020-01-01T00:00:00Z",
            "evidence_ids": ["e-future"],
        }

        with self.assertRaisesRegex(
            ValueError,
            r"\$\.compliance_assessment\.reviewed_at",
        ):
            self._validator()(record)

    def test_no_verified_events_cannot_hide_a_final_verified_event(self) -> None:
        record = self._record()
        record["evidence"] = [
            self._evidence(
                "e-compliance",
                supports_components=["compliance_integrity"],
            )
        ]
        record["compliance_assessment"] = {
            "review_status": "no_verified_events",
            "reviewed_at": "2026-08-21T00:00:00Z",
            "evidence_ids": ["e-compliance"],
        }
        record["compliance_events"] = [
            {
                "event_id": "event-1",
                "jurisdiction": "CN",
                "status": "final_verified",
                "evidence_ids": ["e-compliance"],
            }
        ]
        record["score_components"]["compliance_integrity"] = {
            "score": 80,
            "confidence": "high",
            "evidence_ids": ["e-compliance"],
        }

        with self.assertRaisesRegex(
            ValueError,
            r"\$\.compliance_assessment\.review_status",
        ):
            self._validator()(record)

    def test_tier_d_only_limit_is_specific_to_compliance_integrity(self) -> None:
        record = self._record()
        record["evidence"] = [self._evidence(tier="D")]
        record["employment_history"] = [
            {
                "organisation": "Example Asset Manager",
                "role": "Portfolio Manager",
                "start_date": "2020-01-01",
                "evidence_ids": ["evidence-1"],
            }
        ]
        record["score_components"]["career_track_record"].update(
            {
                "score": 80,
                "confidence": "medium",
                "evidence_ids": ["evidence-1"],
            }
        )

        self._validator()(record)

    def test_performance_windows_resolve_to_exact_tenure_after_transition(self) -> None:
        cases = []

        missing_tenure = self._performance()
        missing_tenure["tenure_id"] = "missing"
        cases.append((missing_tenure, "tenure_id"))

        before_tenure = self._performance()
        before_tenure["window_start"] = "2019-12-31"
        cases.append((before_tenure, "window_start"))

        inside_transition = self._performance()
        inside_transition["window_start"] = "2020-01-30"
        cases.append((inside_transition, "window_start"))

        after_tenure = self._performance()
        after_tenure["window_end"] = "2021-01-01"
        cases.append((after_tenure, "window_end"))

        for performance, expected_path in cases:
            with self.subTest(expected_path=expected_path):
                record = self._record()
                record["tenures"] = [self._tenure()]
                record["performance_evidence"] = [performance]
                with self.assertRaisesRegex(ValueError, expected_path):
                    self._validator()(record)

        valid = self._record()
        valid["tenures"] = [self._tenure()]
        valid["performance_evidence"] = [self._performance()]
        self._validator()(valid)

        transition_observation = self._record()
        transition_observation["tenures"] = [self._tenure()]
        low_confidence = self._performance()
        low_confidence["window_start"] = "2020-01-15"
        low_confidence["confidence"] = "low"
        transition_observation["performance_evidence"] = [low_confidence]
        self._validator()(transition_observation)

    def test_tenure_attribution_cannot_duplicate_or_forge_individual_credit(
        self,
    ) -> None:
        valid = self._record()
        valid["tenures"] = [self._tenure()]
        self._validator()(valid)

        cases = []
        for changes in (
            {"co_manager_ids": ["manager-2"]},
            {"role": "co_manager", "attribution_mode": "individual"},
            {"attribution_mode": "role_weighted", "attribution_share": 0.5},
            {
                "attribution_mode": "role_weighted",
                "attribution_share": 0.0,
                "co_manager_ids": ["manager-2"],
            },
            {
                "attribution_mode": "role_weighted",
                "attribution_share": 1.0,
                "co_manager_ids": ["manager-2"],
            },
            {
                "attribution_mode": "team",
                "attribution_share": 0.5,
                "co_manager_ids": ["manager-2"],
            },
            {"co_manager_ids": ["manager-1"]},
            {"co_manager_ids": ["manager-2", "manager-2"]},
        ):
            record = self._record()
            tenure = self._tenure()
            tenure.update(changes)
            record["tenures"] = [tenure]
            cases.append(record)

        error_type = importlib.import_module(
            "openfundscore.manager_research"
        ).ManagerResearchValidationError
        for record in cases:
            with (
                self.subTest(tenure=record["tenures"][0]),
                self.assertRaises(error_type),
            ):
                self._validator()(record)

    def test_duplicate_tenures_and_overlapping_metric_windows_are_rejected(
        self,
    ) -> None:
        error_type = importlib.import_module(
            "openfundscore.manager_research"
        ).ManagerResearchValidationError

        duplicate_id = self._record()
        duplicate_id["tenures"] = [self._tenure(), self._tenure()]

        overlapping_tenures = self._record()
        first = self._tenure()
        second = self._tenure()
        second["tenure_id"] = "tenure-2"
        second["start_date"] = "2020-06-01"
        overlapping_tenures["tenures"] = [first, second]

        overlapping_metric = self._record()
        overlapping_metric["tenures"] = [self._tenure()]
        first_metric = self._performance()
        second_metric = self._performance()
        second_metric["window_start"] = "2020-06-01"
        overlapping_metric["performance_evidence"] = [first_metric, second_metric]

        for record in (duplicate_id, overlapping_tenures, overlapping_metric):
            with self.subTest(record=record), self.assertRaises(error_type):
                self._validator()(record)

        adjacent = self._record()
        earlier = self._tenure()
        earlier["end_date"] = "2020-06-30"
        later = self._tenure()
        later["tenure_id"] = "tenure-2"
        later["start_date"] = "2020-07-01"
        later["transition_window_days"] = 0
        adjacent["tenures"] = [earlier, later]
        self._validator()(adjacent)

    def test_manager_score_is_weighted_auditable_and_missing_data_is_not_zero(
        self,
    ) -> None:
        module = importlib.import_module("openfundscore.manager_research")
        scorer = getattr(module, "score_manager_research", None)
        assert callable(scorer)
        scorer = cast(Callable[[dict[str, Any]], dict[str, Any]], scorer)

        record = self._record()
        record["evidence"] = [
            {
                "evidence_id": "e-score",
                "tier": "A",
                "source_url": "https://example.com/score",
                "published_at": "2019-12-30T00:00:00Z",
                "fetched_at": "2019-12-31T00:00:00Z",
                "fact_excerpt": "Auditable public professional evidence.",
                "supports_components": list(COMPONENT_IDS),
            }
        ]
        for component in record["score_components"].values():
            component.update(
                {
                    "score": 0,
                    "confidence": "high",
                    "evidence_ids": ["e-score"],
                }
            )
        record["score_components"]["tenure_attributed_performance"]["score"] = 100
        record["tenures"] = [self._tenure()]
        record["tenures"][0]["evidence_ids"] = ["e-score"]
        residual = self._performance()
        residual.update(
            {
                "factor_residual": 0.01,
                "window_end": "2020-01-31",
                "regime": "bull",
                "evidence_ids": ["e-score"],
            }
        )
        downside = self._performance()
        downside.update(
            {
                "observation_id": "observation-2",
                "metric_id": "max_drawdown",
                "window_start": "2020-02-01",
                "window_end": "2020-06-30",
                "regime": "bear",
                "evidence_ids": ["e-score"],
            }
        )
        record["performance_evidence"] = [residual, downside]
        record["style_fingerprint"] = {
            "factor_exposures": {
                "as_of": "2020-12-31T00:00:00Z",
                "measures": [{"name": "value", "value": 0.4}],
            },
            "evidence_ids": ["e-score"],
        }
        record["workload"] = {
            "concurrent_strategy_count": 1,
            "evidence_ids": ["e-score"],
        }
        record["research_platform"] = {
            "team_size": 6,
            "decision_process": "Documented investment committee process.",
            "evidence_ids": ["e-score"],
        }
        record["compliance_assessment"] = {
            "review_status": "no_verified_events",
            "reviewed_at": "2020-01-01T00:00:00Z",
            "evidence_ids": ["e-score"],
        }

        result = scorer(record)
        self.assertEqual("scored", result["status"])
        self.assertEqual(25.0, result["score"])
        self.assertEqual("high", result["confidence"])
        self.assertEqual(
            25.0,
            result["component_contributions"]["tenure_attributed_performance"],
        )
        self.assertEqual("0.1.0", result["model_version"])
        self.assertEqual("manager-1", result["manager_id"])
        self.assertEqual("2026-08-21T00:00:00Z", result["as_of"])
        self.assertEqual(
            ["e-score"],
            result["component_evidence_ids"]["tenure_attributed_performance"],
        )

        split_result = scorer(SplitManagerRecord(record))
        self.assertEqual("manager-1", split_result["manager_id"])

        role_weighted = deepcopy(record)
        role_weighted["tenures"][0].update(
            {
                "attribution_mode": "role_weighted",
                "attribution_share": 0.25,
                "co_manager_ids": ["manager-2"],
            }
        )
        result = scorer(role_weighted)
        self.assertEqual(
            6.25,
            result["component_contributions"]["tenure_attributed_performance"],
        )
        self.assertEqual(0.25, result["tenure_attribution"]["aggregate_factor"])
        self.assertEqual(
            ["observation-1"],
            [
                item["observation_id"]
                for item in result["tenure_attribution"]["observations"]
            ],
        )

        team = deepcopy(record)
        team["tenures"][0].update(
            {
                "attribution_mode": "team",
                "co_manager_ids": ["manager-2"],
            }
        )
        result = scorer(team)
        self.assertEqual(
            12.5,
            result["component_contributions"]["tenure_attributed_performance"],
        )
        self.assertEqual(0.5, result["tenure_attribution"]["aggregate_factor"])

        unresolved = deepcopy(record)
        unresolved["tenures"][0]["attribution_mode"] = "unresolved"
        with self.assertRaises(
            importlib.import_module("openfundscore.validation").RecordValidationError
        ):
            scorer(unresolved)

        missing = deepcopy(record)
        missing["score_components"]["workload_capacity"].update(
            {"score": None, "confidence": "insufficient", "evidence_ids": []}
        )
        result = scorer(missing)
        self.assertEqual("insufficient", result["status"])
        self.assertIsNone(result["score"])
        self.assertIn("workload_capacity", result["insufficient_components"])
        self.assertNotEqual(0, result["score"])

    def test_tenure_attribution_uses_only_component_qualified_observations(
        self,
    ) -> None:
        module = importlib.import_module("openfundscore.manager_research")
        scorer = cast(
            Callable[[dict[str, Any]], dict[str, Any]],
            module.score_manager_research,
        )
        record = self._record()
        record["evidence"] = [
            self._evidence(
                "e-qualified",
                supports_components=["tenure_attributed_performance"],
            ),
            self._evidence("e-audit-noise", supports_components=["downside_control"]),
            self._evidence("e-inject", supports_components=["downside_control"]),
        ]
        first_tenure = self._tenure()
        first_tenure.update(
            {
                "attribution_mode": "role_weighted",
                "attribution_share": 0.1,
                "co_manager_ids": ["manager-2"],
            }
        )
        second_tenure = self._tenure()
        second_tenure.update(
            {
                "tenure_id": "tenure-2",
                "fund_strategy_id": "strategy-2",
                "start_date": "2021-01-01",
                "end_date": "2021-12-31",
            }
        )
        record["tenures"] = [first_tenure, second_tenure]
        qualified = self._performance()
        qualified.update(
            {
                "factor_residual": 0.01,
                "evidence_ids": ["e-qualified", "e-audit-noise"],
            }
        )
        noise = self._performance()
        noise.update(
            {
                "observation_id": "observation-2",
                "tenure_id": "tenure-2",
                "window_start": "2021-01-31",
                "window_end": "2021-12-31",
                "factor_residual": 0.02,
                "evidence_ids": ["e-inject"],
            }
        )
        record["performance_evidence"] = [qualified, noise]
        record["score_components"]["tenure_attributed_performance"] = {
            "score": 100,
            "confidence": "medium",
            "evidence_ids": ["e-qualified", "e-audit-noise", "e-inject"],
        }

        result = scorer(record)

        self.assertEqual(0.1, result["tenure_attribution"]["aggregate_factor"])
        self.assertEqual(
            ["tenure-1"],
            [item["tenure_id"] for item in result["tenure_attribution"]["tenures"]],
        )
        self.assertEqual(
            [
                {
                    "observation_id": "observation-1",
                    "tenure_id": "tenure-1",
                    "metric_id": "benchmark_relative_return",
                    "window_start": "2020-01-31",
                    "window_end": "2020-12-31",
                    "evidence_ids": ["e-qualified"],
                }
            ],
            result["tenure_attribution"]["observations"],
        )

    def test_every_scored_component_requires_semantically_matched_evidence(
        self,
    ) -> None:
        error_type = importlib.import_module(
            "openfundscore.manager_research"
        ).ManagerResearchValidationError
        for component_id in (
            "career_track_record",
            "research_platform_team",
            "compliance_integrity",
        ):
            record = self._record()
            record["evidence"] = [
                self._evidence("arbitrary", supports_components=[component_id])
            ]
            record["score_components"][component_id] = {
                "score": 80,
                "confidence": "medium",
                "evidence_ids": ["arbitrary"],
            }
            with self.subTest(component_id=component_id), self.assertRaises(error_type):
                self._validator()(record)

    def test_empty_domain_facts_cannot_back_a_numeric_component(self) -> None:
        error_type = importlib.import_module(
            "openfundscore.manager_research"
        ).ManagerResearchValidationError
        cases: list[tuple[str, dict[str, Any]]] = []

        for field in ("organisation", "role"):
            career = self._record()
            career["evidence"] = [
                self._evidence(
                    "e-career",
                    supports_components=["career_track_record"],
                )
            ]
            career["employment_history"] = [
                {
                    "organisation": "Example Asset Manager",
                    "role": "Portfolio Manager",
                    "start_date": "2020-01-01",
                    "evidence_ids": ["e-career"],
                }
            ]
            career["employment_history"][0][field] = ""
            career["score_components"]["career_track_record"] = {
                "score": 80,
                "confidence": "medium",
                "evidence_ids": ["e-career"],
            }
            cases.append((f"career-{field}", career))

        workload = self._record()
        workload["evidence"] = [
            self._evidence(
                "e-workload",
                supports_components=["workload_capacity"],
            )
        ]
        workload["workload"] = {
            "team_coverage": "",
            "evidence_ids": ["e-workload"],
        }
        workload["score_components"]["workload_capacity"] = {
            "score": 80,
            "confidence": "medium",
            "evidence_ids": ["e-workload"],
        }
        cases.append(("workload-team-coverage", workload))

        for label, record in cases:
            with self.subTest(label=label), self.assertRaises(error_type):
                self._validator()(record)

    def test_invisible_domain_facts_cannot_back_a_numeric_component(self) -> None:
        error_type = importlib.import_module(
            "openfundscore.manager_research"
        ).ManagerResearchValidationError
        invisible_values = ("\u200b", "\u2060", "\ufeff", "\u0301", " \u200b\u0301 ")

        for invisible in invisible_values:
            for field in ("organisation", "role"):
                with self.subTest(value=repr(invisible), employment_field=field):
                    career = self._record()
                    career["evidence"] = [
                        self._evidence(
                            "e-career",
                            supports_components=["career_track_record"],
                        )
                    ]
                    career["employment_history"] = [
                        {
                            "organisation": "Example Asset Manager",
                            "role": "Portfolio Manager",
                            "start_date": "2020-01-01",
                            "evidence_ids": ["e-career"],
                        }
                    ]
                    career["employment_history"][0][field] = invisible
                    career["score_components"]["career_track_record"] = {
                        "score": 80,
                        "confidence": "medium",
                        "evidence_ids": ["e-career"],
                    }
                    with self.assertRaises(error_type):
                        self._validator()(career)

            with self.subTest(value=repr(invisible), block="workload"):
                workload = self._record()
                workload["evidence"] = [
                    self._evidence(
                        "e-workload",
                        supports_components=["workload_capacity"],
                    )
                ]
                workload["workload"] = {
                    "team_coverage": invisible,
                    "evidence_ids": ["e-workload"],
                }
                workload["score_components"]["workload_capacity"] = {
                    "score": 80,
                    "confidence": "medium",
                    "evidence_ids": ["e-workload"],
                }
                with self.assertRaises(error_type):
                    self._validator()(workload)

            with self.subTest(value=repr(invisible), block="research_platform"):
                platform = self._record()
                platform["evidence"] = [
                    self._evidence(
                        "e-platform",
                        supports_components=["research_platform_team"],
                    )
                ]
                platform["research_platform"] = {
                    "decision_process": invisible,
                    "succession_status": "unknown",
                    "evidence_ids": ["e-platform"],
                }
                platform["score_components"]["research_platform_team"] = {
                    "score": 80,
                    "confidence": "medium",
                    "evidence_ids": ["e-platform"],
                }
                with self.assertRaises(error_type):
                    self._validator()(platform)

    def test_unknown_succession_status_alone_cannot_back_platform_score(self) -> None:
        error_type = importlib.import_module(
            "openfundscore.manager_research"
        ).ManagerResearchValidationError
        record = self._record()
        record["evidence"] = [
            self._evidence(
                "e-platform",
                supports_components=["research_platform_team"],
            )
        ]
        record["research_platform"] = {
            "succession_status": "unknown",
            "evidence_ids": ["e-platform"],
        }
        record["score_components"]["research_platform_team"] = {
            "score": 80,
            "confidence": "medium",
            "evidence_ids": ["e-platform"],
        }

        with self.assertRaises(error_type):
            self._validator()(record)

    def test_component_and_domain_must_share_the_same_supporting_evidence(self) -> None:
        error_type = importlib.import_module(
            "openfundscore.manager_research"
        ).ManagerResearchValidationError
        cases: list[dict[str, Any]] = []

        performance = self._record()
        performance["evidence"] = [
            self._evidence(
                "e-support",
                supports_components=["tenure_attributed_performance"],
            ),
            self._evidence("e-domain", supports_components=[]),
        ]
        performance["tenures"] = [self._tenure()]
        item = self._performance()
        item.update({"factor_residual": 0.01, "evidence_ids": ["e-domain"]})
        performance["performance_evidence"] = [item]
        performance["score_components"]["tenure_attributed_performance"] = {
            "score": 80,
            "confidence": "medium",
            "evidence_ids": ["e-support", "e-domain"],
        }
        cases.append(performance)

        style = self._record()
        style["evidence"] = [
            self._evidence("e-support", supports_components=["style_discipline"]),
            self._evidence("e-domain", supports_components=[]),
        ]
        style["style_fingerprint"] = {
            "factor_exposures": {
                "as_of": "2026-08-21T00:00:00Z",
                "measures": [{"name": "value", "value": 0.4}],
            },
            "evidence_ids": ["e-domain"],
        }
        style["score_components"]["style_discipline"] = {
            "score": 80,
            "confidence": "medium",
            "evidence_ids": ["e-support", "e-domain"],
        }
        cases.append(style)

        workload = self._record()
        workload["evidence"] = [
            self._evidence("e-support", supports_components=["workload_capacity"]),
            self._evidence("e-domain", supports_components=[]),
        ]
        workload["workload"] = {
            "concurrent_strategy_count": 2,
            "evidence_ids": ["e-domain"],
        }
        workload["score_components"]["workload_capacity"] = {
            "score": 80,
            "confidence": "medium",
            "evidence_ids": ["e-support", "e-domain"],
        }
        cases.append(workload)

        for record in cases:
            with self.subTest(record=record), self.assertRaises(error_type):
                self._validator()(record)

    def test_unified_manager_validation_canonicalizes_before_schema_and_semantics(
        self,
    ) -> None:
        validation = importlib.import_module("openfundscore.validation")
        record = self._record()
        record["as_of"] = "2020-01-01T00:00:00Z"
        record["evidence"] = [self._evidence("future-evidence")]
        with self.assertRaises(validation.RecordValidationError):
            validation.validate_record(
                "manager_research",
                SplitAsOfRecord(record),
                schema_version="0.1.0",
            )

    def test_duplicate_ids_overlapping_regimes_and_non_pit_style_are_rejected(
        self,
    ) -> None:
        error_type = importlib.import_module(
            "openfundscore.manager_research"
        ).ManagerResearchValidationError

        duplicate_evidence = self._record()
        duplicate_evidence["evidence"] = [
            self._evidence("duplicate", "D"),
            self._evidence("duplicate", "A"),
        ]

        duplicate_events = self._record()
        duplicate_events["evidence"] = [self._evidence("e-compliance")]
        event = {
            "event_id": "event-1",
            "jurisdiction": "CN",
            "status": "final_verified",
            "evidence_ids": ["e-compliance"],
        }
        duplicate_events["compliance_events"] = [event, deepcopy(event)]

        overlapping_regimes = self._record()
        overlapping_regimes["evidence"] = [self._evidence("e-cycle")]
        overlapping_regimes["tenures"] = [self._tenure()]
        first = self._performance()
        first.update(
            {
                "metric_id": "rolling_return",
                "regime": "bull",
                "evidence_ids": ["e-cycle"],
            }
        )
        second = deepcopy(first)
        second.update({"metric_id": "downside_capture", "regime": "bear"})
        overlapping_regimes["performance_evidence"] = [first, second]
        overlapping_regimes["score_components"]["cross_cycle_consistency"] = {
            "score": 80,
            "confidence": "medium",
            "evidence_ids": ["e-cycle"],
        }

        non_pit_style = self._record()
        non_pit_style["evidence"] = [self._evidence("e-style")]
        non_pit_style["style_fingerprint"] = {
            "factor_exposures": {
                "as_of": "2020-01-01T00:00:00Z",
                "measures": [{"name": "value", "value": 0.4}],
            },
            "evidence_ids": ["e-style"],
        }

        empty_currency = self._record()
        empty_currency["evidence"] = [self._evidence("e-workload")]
        empty_currency["workload"] = {
            "assets_under_management": 1_000_000,
            "aum_currency": "",
            "evidence_ids": ["e-workload"],
        }

        for record in (
            duplicate_evidence,
            duplicate_events,
            overlapping_regimes,
            non_pit_style,
            empty_currency,
        ):
            with self.subTest(record=record), self.assertRaises(error_type):
                self._validator()(record)

    def test_style_and_workload_research_require_cited_consistent_evidence(
        self,
    ) -> None:
        error_type = importlib.import_module(
            "openfundscore.manager_research"
        ).ManagerResearchValidationError

        cases = []
        workload_uncited = self._record()
        workload_uncited["workload"] = {"concurrent_strategy_count": 2}
        cases.append(workload_uncited)

        workload_currency = self._record()
        workload_currency["workload"] = {
            "assets_under_management": 1_000_000,
            "aum_currency": None,
            "evidence_ids": [],
        }
        cases.append(workload_currency)

        style_uncited = self._record()
        style_uncited["style_fingerprint"] = {"factor_exposures": {"value": 0.4}}
        cases.append(style_uncited)

        for record in cases:
            with self.subTest(record=record), self.assertRaises(error_type):
                self._validator()(record)

        cited = self._record()
        cited["evidence"] = [
            {
                "evidence_id": "e-style",
                "tier": "B",
                "source_url": "https://example.com/style",
                "published_at": "2026-01-01T00:00:00Z",
                "fetched_at": "2026-01-02T00:00:00Z",
                "fact_excerpt": "Auditable style and capacity evidence.",
            }
        ]
        cited["style_fingerprint"] = {
            "factor_exposures": {
                "as_of": "2026-01-02T00:00:00Z",
                "measures": [{"name": "value", "value": 0.4}],
            },
            "evidence_ids": ["e-style"],
        }
        cited["workload"] = {
            "concurrent_strategy_count": 2,
            "assets_under_management": 1_000_000,
            "aum_currency": "CNY",
            "evidence_ids": ["e-style"],
        }
        self._validator()(cited)

    def test_scored_performance_components_require_domain_evidence(self) -> None:
        error_type = importlib.import_module(
            "openfundscore.manager_research"
        ).ManagerResearchValidationError

        base = self._record()
        base["evidence"] = [self._evidence("e-performance")]
        for component_id in (
            "tenure_attributed_performance",
            "downside_control",
            "cross_cycle_consistency",
            "style_discipline",
            "workload_capacity",
        ):
            record = deepcopy(base)
            record["score_components"][component_id] = {
                "score": 80,
                "confidence": "medium",
                "evidence_ids": ["e-performance"],
            }
            with self.subTest(component_id=component_id), self.assertRaises(error_type):
                self._validator()(record)

        valid = deepcopy(base)
        valid["tenures"] = [self._tenure()]
        residual = self._performance()
        residual["factor_residual"] = 0.01
        residual["regime"] = "bull"
        residual["evidence_ids"] = ["e-performance"]
        downside = self._performance()
        downside.update(
            {
                "observation_id": "observation-2",
                "metric_id": "max_drawdown",
                "window_start": "2020-02-01",
                "window_end": "2020-06-30",
                "regime": "bear",
                "evidence_ids": ["e-performance"],
            }
        )
        cross_cycle = self._performance()
        cross_cycle.update(
            {
                "observation_id": "observation-3",
                "metric_id": "rolling_consistency",
                "window_start": "2020-07-01",
                "window_end": "2020-12-31",
                "regime": "rate_rise",
                "evidence_ids": ["e-performance"],
            }
        )
        valid["performance_evidence"] = [residual, downside, cross_cycle]
        for component_id in (
            "tenure_attributed_performance",
            "downside_control",
            "cross_cycle_consistency",
        ):
            valid["score_components"][component_id] = {
                "score": 80,
                "confidence": "medium",
                "evidence_ids": ["e-performance"],
            }
        self._validator()(valid)

    def test_numeric_performance_scores_reject_insufficient_observations(self) -> None:
        error_type = importlib.import_module(
            "openfundscore.manager_research"
        ).ManagerResearchValidationError
        cases: list[tuple[str, dict[str, Any]]] = []

        attribution = self._record()
        attribution["evidence"] = [
            self._evidence(
                "e-performance",
                supports_components=["tenure_attributed_performance"],
            )
        ]
        attribution["tenures"] = [self._tenure()]
        observation = self._performance()
        observation.update(
            {
                "value": None,
                "missing_reason": "insufficient_history",
                "confidence": "insufficient",
                "factor_residual": 0.01,
                "evidence_ids": ["e-performance"],
            }
        )
        attribution["performance_evidence"] = [observation]
        attribution["score_components"]["tenure_attributed_performance"] = {
            "score": 80,
            "confidence": "medium",
            "evidence_ids": ["e-performance"],
        }
        cases.append(("tenure_attributed_performance", attribution))

        downside = self._record()
        downside["evidence"] = [
            self._evidence("e-performance", supports_components=["downside_control"])
        ]
        downside["tenures"] = [self._tenure()]
        observation = self._performance()
        observation.update(
            {
                "metric_id": "max_drawdown",
                "value": None,
                "missing_reason": "insufficient_history",
                "confidence": "insufficient",
                "evidence_ids": ["e-performance"],
            }
        )
        downside["performance_evidence"] = [observation]
        downside["score_components"]["downside_control"] = {
            "score": 80,
            "confidence": "medium",
            "evidence_ids": ["e-performance"],
        }
        cases.append(("downside_control", downside))

        cross_cycle = self._record()
        cross_cycle["evidence"] = [
            self._evidence(
                "e-performance",
                supports_components=["cross_cycle_consistency"],
            )
        ]
        cross_cycle["tenures"] = [self._tenure()]
        first = self._performance()
        first.update(
            {
                "window_end": "2020-05-31",
                "value": None,
                "missing_reason": "insufficient_history",
                "confidence": "insufficient",
                "regime": "bull",
                "evidence_ids": ["e-performance"],
            }
        )
        second = self._performance()
        second.update(
            {
                "observation_id": "observation-2",
                "window_start": "2020-06-01",
                "value": None,
                "missing_reason": "insufficient_history",
                "confidence": "insufficient",
                "regime": "bear",
                "evidence_ids": ["e-performance"],
            }
        )
        cross_cycle["performance_evidence"] = [first, second]
        cross_cycle["score_components"]["cross_cycle_consistency"] = {
            "score": 80,
            "confidence": "medium",
            "evidence_ids": ["e-performance"],
        }
        cases.append(("cross_cycle_consistency", cross_cycle))

        for component_id, record in cases:
            with self.subTest(component_id=component_id), self.assertRaises(error_type):
                self._validator()(record)

    def test_factor_residual_evidence_cannot_be_reused_across_tenures(self) -> None:
        error_type = importlib.import_module(
            "openfundscore.manager_research"
        ).ManagerResearchValidationError
        record = self._record()
        record["evidence"] = [
            self._evidence(
                "e-shared",
                supports_components=["tenure_attributed_performance"],
            )
        ]
        first_tenure = self._tenure()
        first_tenure["evidence_ids"] = ["e-shared"]
        second_tenure = self._tenure()
        second_tenure.update(
            {
                "tenure_id": "tenure-2",
                "fund_strategy_id": "strategy-2",
                "start_date": "2021-01-01",
                "end_date": "2021-12-31",
                "attribution_mode": "team",
                "co_manager_ids": ["manager-2"],
                "evidence_ids": ["e-shared"],
            }
        )
        record["tenures"] = [first_tenure, second_tenure]
        first = self._performance()
        first.update(
            {
                "observation_id": "observation-1",
                "factor_residual": 0.01,
                "evidence_ids": ["e-shared"],
            }
        )
        second = self._performance()
        second.update(
            {
                "observation_id": "observation-2",
                "tenure_id": "tenure-2",
                "window_start": "2021-01-31",
                "window_end": "2021-12-31",
                "factor_residual": 0.02,
                "evidence_ids": ["e-shared"],
            }
        )
        record["performance_evidence"] = [first, second]
        record["score_components"]["tenure_attributed_performance"] = {
            "score": 80,
            "confidence": "medium",
            "evidence_ids": ["e-shared"],
        }

        with self.assertRaises(error_type):
            self._validator()(record)

    def test_factor_residual_observation_cannot_be_duplicated_across_tenures(
        self,
    ) -> None:
        error_type = importlib.import_module(
            "openfundscore.manager_research"
        ).ManagerResearchValidationError
        record = self._record()
        record["evidence"] = [
            self._evidence(
                "e-first",
                supports_components=["tenure_attributed_performance"],
            ),
            self._evidence(
                "e-second",
                supports_components=["tenure_attributed_performance"],
            ),
        ]
        first_tenure = self._tenure()
        first_tenure["evidence_ids"] = ["e-first"]
        second_tenure = self._tenure()
        second_tenure.update(
            {
                "tenure_id": "tenure-2",
                "fund_strategy_id": "strategy-2",
                "evidence_ids": ["e-second"],
            }
        )
        record["tenures"] = [first_tenure, second_tenure]
        first = self._performance()
        first.update(
            {
                "factor_residual": 0.01,
                "evidence_ids": ["e-first"],
            }
        )
        second = deepcopy(first)
        second.update(
            {
                "observation_id": "observation-2",
                "tenure_id": "tenure-2",
                "evidence_ids": ["e-second"],
            }
        )
        record["performance_evidence"] = [first, second]
        record["score_components"]["tenure_attributed_performance"] = {
            "score": 80,
            "confidence": "medium",
            "evidence_ids": ["e-first", "e-second"],
        }

        with self.assertRaises(error_type):
            self._validator()(record)

        module = importlib.import_module("openfundscore.manager_research")
        for metric_id in (
            "benchmark\u200b_relative_return",
            "benchmark\u2060_relative_return",
            "benchmark\ufeff_relative_return",
            "benchmark\u0301_relative_return",
            "benchmark＿relative＿return",
        ):
            for api_name in ("validate_manager_research", "score_manager_research"):
                with self.subTest(metric_id=repr(metric_id), api=api_name):
                    attacked = deepcopy(record)
                    attacked["performance_evidence"][1]["metric_id"] = metric_id
                    with self.assertRaisesRegex(
                        ValueError,
                        r"\$\.performance_evidence\[1\]\.metric_id",
                    ):
                        getattr(module, api_name)(attacked)

    def test_style_change_point_requires_the_same_component_support_evidence(
        self,
    ) -> None:
        error_type = importlib.import_module(
            "openfundscore.manager_research"
        ).ManagerResearchValidationError
        record = self._record()
        record["evidence"] = [
            self._evidence("e-support", supports_components=["style_discipline"]),
            self._evidence("e-domain", supports_components=[]),
        ]
        record["style_fingerprint"] = {
            "change_points": [
                {
                    "effective_date": "2026-08-20",
                    "known_at": "2026-08-21T00:00:00Z",
                    "kind": "style_shift",
                    "evidence_ids": ["e-domain"],
                }
            ],
            "evidence_ids": ["e-support"],
        }
        record["score_components"]["style_discipline"] = {
            "score": 80,
            "confidence": "medium",
            "evidence_ids": ["e-support", "e-domain"],
        }

        with self.assertRaises(error_type):
            self._validator()(record)

    def test_style_change_point_evidence_must_be_known_at_that_point(self) -> None:
        error_type = importlib.import_module(
            "openfundscore.manager_research"
        ).ManagerResearchValidationError
        record = self._record()
        record["evidence"] = [self._evidence("e-future")]
        record["style_fingerprint"] = {
            "change_points": [
                {
                    "effective_date": "2020-01-01",
                    "known_at": "2020-01-02T00:00:00Z",
                    "kind": "style_shift",
                    "evidence_ids": ["e-future"],
                }
            ],
            "evidence_ids": ["e-future"],
        }

        with self.assertRaises(error_type):
            self._validator()(record)

    def test_style_snapshots_are_point_in_time_and_measure_names_are_unique(
        self,
    ) -> None:
        error_type = importlib.import_module(
            "openfundscore.manager_research"
        ).ManagerResearchValidationError
        cases = []

        future_snapshot = self._record()
        future_snapshot["style_fingerprint"] = {
            "factor_exposures": {
                "as_of": "2026-08-22T00:00:00Z",
                "measures": [{"name": "value", "value": 0.4}],
            },
            "evidence_ids": ["e-style"],
        }
        future_snapshot["evidence"] = [self._evidence("e-style")]
        cases.append(future_snapshot)

        duplicate_measure = deepcopy(future_snapshot)
        duplicate_measure["style_fingerprint"]["factor_exposures"].update(
            {
                "as_of": "2026-08-20T00:00:00Z",
                "measures": [
                    {"name": "value", "value": 0.4},
                    {"name": "value", "value": 0.5},
                ],
            }
        )
        cases.append(duplicate_measure)

        future_change = self._record()
        future_change["style_fingerprint"] = {
            "change_points": [
                {
                    "effective_date": "2026-08-22",
                    "known_at": "2026-08-22T00:00:00Z",
                    "kind": "style_shift",
                    "evidence_ids": ["e-style"],
                }
            ],
            "evidence_ids": ["e-style"],
        }
        future_change["evidence"] = [self._evidence("e-style")]
        cases.append(future_change)

        for record in cases:
            with self.subTest(record=record), self.assertRaises(error_type):
                self._validator()(record)


if __name__ == "__main__":
    unittest.main()
