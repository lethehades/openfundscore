from __future__ import annotations

import unittest
from collections.abc import Iterator, Mapping
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime
from unittest.mock import patch

from openfundscore.category_metrics import (
    ApplicabilityContext,
    CategoryMetricError,
    score_category_metrics,
)
from openfundscore.manager_research import (
    MANAGER_COMPONENT_SOURCE_MANIFEST,
    ManagerEvidenceSource,
    ManagerResearchHandoff,
    ManagerResearchValidationError,
    build_manager_evidence_sources,
    derive_manager_evidence_source_binding,
    derive_manager_evidence_sources,
    recompute_manager_handoff,
)
from openfundscore.peer_admission import load_peer_admission_contract
from tests.test_category_metrics import evidence_ledger, profile_fixture

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


def manager_document(*, score: int = 80) -> dict[str, object]:
    evidence_ids = {
        component: f"e-manager-{component}" for component in MANAGER_COMPONENTS
    }
    evidence = [
        {
            "evidence_id": evidence_id,
            "tier": "A",
            "source_url": f"https://example.com/{component}",
            "published_at": "2009-12-30T00:00:00Z",
            "fetched_at": "2009-12-31T00:00:00Z",
            "fact_excerpt": f"Public professional evidence for {component}.",
            "supports_components": [component],
        }
        for component, evidence_id in evidence_ids.items()
    ]
    components = {
        component: {
            "score": score,
            "confidence": "high",
            "evidence_ids": [evidence_ids[component]],
        }
        for component in MANAGER_COMPONENTS
    }
    return {
        "manager_id": "manager-1",
        "canonical_name": "Example Manager",
        "public_professional_only": True,
        "as_of": "2026-08-22T00:00:00Z",
        "professional_profile": {},
        "employment_history": [
            {
                "organisation": "Example Asset Manager",
                "role": "Portfolio Manager",
                "start_date": "2010-01-01",
                "end_date": "2019-12-31",
                "evidence_ids": [evidence_ids["career_track_record"]],
            }
        ],
        "tenures": [
            {
                "tenure_id": "tenure-1",
                "fund_strategy_id": "fund-1",
                "start_date": "2020-01-01",
                "end_date": "2020-12-31",
                "role": "lead",
                "attribution_mode": "individual",
                "co_manager_ids": [],
                "transition_window_days": 30,
                "evidence_ids": [evidence_ids["tenure_attributed_performance"]],
            }
        ],
        "performance_evidence": [
            {
                "observation_id": "observation-tenure",
                "tenure_id": "tenure-1",
                "window_start": "2020-01-31",
                "window_end": "2020-01-31",
                "metric_id": "benchmark_relative_return",
                "value": 0.01,
                "factor_residual": 0.01,
                "confidence": "high",
                "evidence_ids": [evidence_ids["tenure_attributed_performance"]],
            },
            {
                "observation_id": "observation-downside",
                "tenure_id": "tenure-1",
                "window_start": "2020-02-01",
                "window_end": "2020-06-30",
                "metric_id": "max_drawdown",
                "value": -0.05,
                "confidence": "high",
                "evidence_ids": [evidence_ids["downside_control"]],
            },
            {
                "observation_id": "observation-cycle-bull",
                "tenure_id": "tenure-1",
                "window_start": "2020-07-01",
                "window_end": "2020-09-30",
                "metric_id": "rolling_consistency",
                "value": 0.7,
                "regime": "bull",
                "confidence": "high",
                "evidence_ids": [evidence_ids["cross_cycle_consistency"]],
            },
            {
                "observation_id": "observation-cycle-bear",
                "tenure_id": "tenure-1",
                "window_start": "2020-10-01",
                "window_end": "2020-12-31",
                "metric_id": "downside_capture",
                "value": 0.8,
                "regime": "bear",
                "confidence": "high",
                "evidence_ids": [evidence_ids["cross_cycle_consistency"]],
            },
        ],
        "style_fingerprint": {
            "factor_exposures": {
                "as_of": "2020-12-31T00:00:00Z",
                "measures": [{"name": "value", "value": 0.4}],
            },
            "evidence_ids": [evidence_ids["style_discipline"]],
        },
        "workload": {
            "concurrent_strategy_count": 1,
            "evidence_ids": [evidence_ids["workload_capacity"]],
        },
        "research_platform": {
            "team_size": 6,
            "decision_process": "Documented investment committee process.",
            "evidence_ids": [evidence_ids["research_platform_team"]],
        },
        "compliance_assessment": {
            "review_status": "no_verified_events",
            "reviewed_at": "2020-01-01T00:00:00Z",
            "evidence_ids": [evidence_ids["compliance_integrity"]],
        },
        "compliance_events": [],
        "evidence": evidence,
        "score_components": components,
    }


def manager_sources() -> tuple[ManagerEvidenceSource, ...]:
    document = manager_document()
    contracts = {
        "tenure_attributed_performance": ("external_career", "residualized"),
        "downside_control": ("external_career", "orthogonal"),
        "cross_cycle_consistency": ("external_career", "orthogonal"),
        "style_discipline": ("external_career", "descriptive"),
        "career_track_record": ("external_career", "descriptive"),
        "workload_capacity": ("team_platform", "descriptive"),
        "research_platform_team": ("team_platform", "descriptive"),
        "compliance_integrity": ("external_career", "descriptive"),
    }
    return derive_manager_evidence_sources(
        document,
        "fund-1",
        [
            {
                "component": component,
                "evidence_id": f"e-manager-{component}",
                "lineage_id": f"lineage-manager-{component}",
                "series_id": f"series-manager-{component}",
                "source_scope": scope,
                "usage_mode": mode,
                "fund_strategy_id": None,
            }
            for component, (scope, mode) in contracts.items()
        ],
    )


def manager_handoff() -> ManagerResearchHandoff:
    return ManagerResearchHandoff(
        manager_research=manager_document(),
        as_of=datetime(2026, 8, 22, tzinfo=UTC),
        fund_strategy_id="fund-1",
        sources=manager_sources(),
        assertion_status="caller_provided",
    )


def category_inputs() -> dict[str, object]:
    profile_id = "active_equity_mixed"
    observations, peers = profile_fixture(profile_id)
    handoff = manager_handoff()
    ledger = deepcopy(evidence_ledger(profile_id, observations))
    ledger["usage"] = [
        item
        for item in ledger["usage"]
        if not item["target_component"].startswith("manager_")
    ]
    ledger["usage"].extend(recompute_manager_handoff(handoff)["component_evidence"])
    admission, _ = load_peer_admission_contract()
    return {
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
        "manager_handoff": handoff,
        "evidence_ledger": ledger,
    }


class ManagerHandoffTests(unittest.TestCase):
    def test_source_binding_is_derived_from_consumed_structured_facts(self) -> None:

        document = manager_document()
        performance = derive_manager_evidence_source_binding(
            document,
            component="cross_cycle_consistency",
            evidence_id="e-manager-cross_cycle_consistency",
            fund_strategy_id="fund-1",
        )
        compliance = derive_manager_evidence_source_binding(
            document,
            component="compliance_integrity",
            evidence_id="e-manager-compliance_integrity",
            fund_strategy_id="fund-1",
        )

        self.assertEqual(performance["observation_as_of"], "2020-12-31T00:00:00Z")
        self.assertEqual(performance["window_start"], "2020-07-01")
        self.assertEqual(performance["window_end"], "2020-12-31")
        self.assertEqual(compliance["observation_as_of"], "2020-01-01T00:00:00Z")
        self.assertRegex(performance["facts_sha256"], r"^[0-9a-f]{64}$")

    def test_public_source_deriver_fills_only_local_fact_binding_fields(self) -> None:
        sources = manager_sources()

        self.assertEqual(len(sources), 8)
        self.assertEqual(
            sources[0].lineage_id, "lineage-manager-tenure_attributed_performance"
        )
        self.assertEqual(sources[0].source_scope, "external_career")
        self.assertRegex(sources[0].facts_sha256, r"^[0-9a-f]{64}$")
        self.assertEqual(sources[0].window_start, date(2020, 1, 31))

        identity_rows = [
            {
                "component": source.component,
                "evidence_id": source.evidence_id,
                "lineage_id": source.lineage_id,
                "series_id": source.series_id,
                "source_scope": source.source_scope,
                "usage_mode": source.usage_mode,
                "fund_strategy_id": source.fund_strategy_id,
            }
            for source in sources
        ]
        del identity_rows[0]["lineage_id"]
        with self.assertRaises(ManagerResearchValidationError):
            derive_manager_evidence_sources(manager_document(), "fund-1", identity_rows)

    def test_public_source_deriver_normalizes_malformed_manager_documents(self) -> None:
        class HostileMapping(Mapping[str, object]):
            def __getitem__(self, key: str) -> object:
                raise RuntimeError("secret-hostile-payload")

            def __iter__(self) -> Iterator[str]:
                raise RuntimeError("secret-hostile-payload")

            def __len__(self) -> int:
                raise RuntimeError("secret-hostile-payload")

        cases: list[object] = []
        missing_tenure_id = manager_document()
        del missing_tenure_id["tenures"][0]["tenure_id"]  # type: ignore[index]
        cases.append(missing_tenure_id)

        non_sequence_tenures = manager_document()
        non_sequence_tenures["tenures"] = {"secret-hostile-payload": True}
        cases.append(non_sequence_tenures)

        missing_nested_field = manager_document()
        del missing_nested_field["style_fingerprint"]["factor_exposures"]["as_of"]  # type: ignore[index]
        cases.append(missing_nested_field)
        cases.append(HostileMapping())

        nested: object = "leaf"
        for _ in range(600):
            nested = [nested]
        recursive_depth = manager_document()
        recursive_depth["professional_profile"] = nested
        cases.append(recursive_depth)

        identities = [
            {
                "component": source.component,
                "evidence_id": source.evidence_id,
                "lineage_id": source.lineage_id,
                "series_id": source.series_id,
                "source_scope": source.source_scope,
                "usage_mode": source.usage_mode,
                "fund_strategy_id": source.fund_strategy_id,
            }
            for source in manager_sources()
        ]
        for document in cases:
            with self.subTest(document=type(document).__name__):
                with self.assertRaises(ManagerResearchValidationError) as raised:
                    derive_manager_evidence_sources(  # type: ignore[arg-type]
                        document, "fund-1", identities
                    )
                self.assertEqual(
                    str(raised.exception),
                    "manager evidence sources could not be safely derived",
                )
                self.assertNotIn("secret-hostile-payload", str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)

    def test_public_source_deriver_does_not_swallow_base_exception(self) -> None:
        identities = [
            {
                "component": source.component,
                "evidence_id": source.evidence_id,
                "lineage_id": source.lineage_id,
                "series_id": source.series_id,
                "source_scope": source.source_scope,
                "usage_mode": source.usage_mode,
                "fund_strategy_id": source.fund_strategy_id,
            }
            for source in manager_sources()
        ]
        with (
            patch(
                "openfundscore.validation.validate_record",
                side_effect=KeyboardInterrupt,
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            derive_manager_evidence_sources(manager_document(), "fund-1", identities)

    def test_caller_scores_recompute_total_but_cannot_claim_verified_confidence(
        self,
    ) -> None:
        handoff = replace(
            manager_handoff(),
            manager_research=manager_document(score=100),
        )

        result = recompute_manager_handoff(handoff)
        category = score_category_metrics(
            **{**category_inputs(), "manager_handoff": handoff}
        )

        self.assertEqual(result["score"], 100.0)
        self.assertEqual(result["manager_input_assertion_status"], "caller_provided")
        self.assertEqual(result["confidence"], "low")
        self.assertEqual(category.manager_score, 100.0)
        self.assertEqual(
            category.manager_audit.manager_input_assertion_status, "caller_provided"
        )
        self.assertEqual(category.manager_audit.confidence, "low")
        self.assertEqual(category.confidence, "low")

    def test_handoff_rejects_non_caller_assertion_status(self) -> None:
        for status in ("verified", "unknown", ""):
            with (
                self.subTest(status=status),
                self.assertRaises(ManagerResearchValidationError),
            ):
                replace(manager_handoff(), assertion_status=status)

    def test_handoff_target_must_exist_in_original_manager_tenures(self) -> None:
        with self.assertRaises(ManagerResearchValidationError):
            recompute_manager_handoff(
                replace(manager_handoff(), fund_strategy_id="fund-forged")
            )

    def test_source_builder_requires_all_caller_provenance_without_defaults(
        self,
    ) -> None:
        records = [
            {
                "component": source.component,
                "evidence_id": source.evidence_id,
                "lineage_id": source.lineage_id,
                "series_id": source.series_id,
                "facts_sha256": source.facts_sha256,
                "source_scope": source.source_scope,
                "usage_mode": source.usage_mode,
                "fund_strategy_id": source.fund_strategy_id,
                "observation_as_of": source.observation_as_of.isoformat(),
                "window_basis": source.window_basis,
                "window_months": source.window_months,
                "window_start": source.window_start.isoformat(),
                "window_end": source.window_end.isoformat(),
            }
            for source in manager_sources()
        ]
        rebuilt = build_manager_evidence_sources(records)
        self.assertEqual(rebuilt, manager_sources())

        for mutation in ("missing", "unknown", "bool-months"):
            with self.subTest(mutation=mutation):
                hostile = deepcopy(records)
                if mutation == "missing":
                    del hostile[0]["lineage_id"]
                elif mutation == "unknown":
                    hostile[0]["caller_provenance_default"] = "forbidden"
                else:
                    hostile[0]["window_months"] = True
                with self.assertRaises(ManagerResearchValidationError):
                    build_manager_evidence_sources(hostile)

    def test_real_sources_are_immutable_and_recomputed_without_synthetic_identity(
        self,
    ) -> None:
        handoff = manager_handoff()
        result = recompute_manager_handoff(handoff)

        self.assertEqual(result["score"], 80.0)
        self.assertEqual(len(result["component_evidence"]), 8)
        by_component = {
            item["target_component"].removeprefix("manager_"): item
            for item in result["component_evidence"]
        }
        for source in handoff.sources:
            with self.subTest(component=source.component):
                item = by_component[source.component]
                self.assertEqual(item["evidence_id"], source.evidence_id)
                self.assertEqual(item["lineage_id"], source.lineage_id)
                self.assertEqual(item["series_id"], source.series_id)
                self.assertEqual(item["source_facts_sha256"], source.facts_sha256)
                self.assertNotIn("facts_sha256", item)
        with self.assertRaises(FrozenInstanceError):
            handoff.fund_strategy_id = "forged"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            handoff.sources[0].lineage_id = "forged"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            handoff.manager_research["manager_id"] = "forged"  # type: ignore[index]

    def test_component_manifest_is_explicit_and_rejects_scope_mode_or_target_forgery(
        self,
    ) -> None:
        expected = {
            "tenure_attributed_performance": frozenset(
                {("external_career", "residualized"), ("current_fund", "raw")}
            ),
            "downside_control": frozenset(
                {("external_career", "orthogonal"), ("current_fund", "raw")}
            ),
            "cross_cycle_consistency": frozenset(
                {("external_career", "orthogonal"), ("current_fund", "raw")}
            ),
            "style_discipline": frozenset({("external_career", "descriptive")}),
            "career_track_record": frozenset({("external_career", "descriptive")}),
            "workload_capacity": frozenset({("team_platform", "descriptive")}),
            "research_platform_team": frozenset({("team_platform", "descriptive")}),
            "compliance_integrity": frozenset({("external_career", "descriptive")}),
        }
        self.assertEqual(dict(MANAGER_COMPONENT_SOURCE_MANIFEST), expected)

        base = manager_handoff()
        for index, source in enumerate(base.sources):
            for scope, mode in expected[source.component]:
                with self.subTest(component=source.component, scope=scope, mode=mode):
                    changed = list(base.sources)
                    changed[index] = replace(
                        source,
                        source_scope=scope,
                        usage_mode=mode,
                        fund_strategy_id="fund-1" if scope == "current_fund" else None,
                    )
                    recompute_manager_handoff(replace(base, sources=tuple(changed)))

        hostile = (
            replace(base.sources[0], source_scope="external_career", usage_mode="raw"),
            replace(
                base.sources[0],
                source_scope="current_fund",
                usage_mode="raw",
                fund_strategy_id="fund-forged",
            ),
            replace(base.sources[4], fund_strategy_id="fund-1"),
            replace(base.sources[7], source_scope="team_platform"),
        )
        for forged in hostile:
            changed = list(base.sources)
            changed[
                0
                if forged.component == base.sources[0].component
                else 4
                if forged.component == base.sources[4].component
                else 7
            ] = forged
            with (
                self.subTest(forged=forged),
                self.assertRaises(ManagerResearchValidationError),
            ):
                recompute_manager_handoff(replace(base, sources=tuple(changed)))

    def test_category_recomputes_handoff_and_rejects_forged_summary_or_target(
        self,
    ) -> None:
        inputs = category_inputs()
        result = score_category_metrics(**inputs)
        self.assertEqual(result.manager_score, 80.0)
        self.assertEqual(
            dict(result.manager_audit.component_raw_scores)["downside_control"], 80.0
        )
        self.assertEqual(
            result.manager_audit.component_evidence[0].source_facts_sha256,
            manager_sources()[0].facts_sha256,
        )

        forged = recompute_manager_handoff(manager_handoff())
        forged["component_raw_scores"]["downside_control"] = 100.0
        forged["component_contributions"]["downside_control"] = 15.0
        forged["score"] = 83.0
        legacy = dict(inputs)
        legacy.pop("manager_handoff")
        legacy["manager_audit"] = forged
        with self.assertRaises(CategoryMetricError) as summary_error:
            score_category_metrics(**legacy)
        self.assertEqual(summary_error.exception.code, "legacy_manager_audit_rejected")

        wrong_target = dict(inputs)
        wrong_target["manager_handoff"] = replace(
            manager_handoff(), fund_strategy_id="fund-forged"
        )
        with self.assertRaises(CategoryMetricError) as target_error:
            score_category_metrics(**wrong_target)
        self.assertEqual(target_error.exception.code, "manager_target_mismatch")


if __name__ == "__main__":
    unittest.main()
