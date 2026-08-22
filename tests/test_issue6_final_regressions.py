from __future__ import annotations

import unittest
from copy import deepcopy
from dataclasses import replace
from typing import Any, cast

from openfundscore.category_metrics import CategoryMetricError
from openfundscore.manager_research import (
    ManagerResearchHandoff,
    derive_manager_evidence_sources,
    recompute_manager_handoff,
)
from tests.test_category_metrics import (
    evidence_ledger,
    peer_set,
    profile_fixture,
    score,
)


class PeerAdmissionRegressionTests(unittest.TestCase):
    def test_packaged_contract_allowlists_one_profile_specific_bucket(self) -> None:
        from openfundscore.peer_admission import load_peer_admission_contract

        contract, digest = load_peer_admission_contract("0.1.0")
        self.assertEqual(
            set(contract["profiles"]),
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
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertNotIn(
            "active-equity-cn", contract["profiles"]["bond"]["allowed_peer_buckets"]
        )

    def test_score_rejects_equity_bucket_for_bond_even_when_all_peers_claim_it(
        self,
    ) -> None:
        with self.assertRaises(CategoryMetricError) as raised:
            score("bond", peer_bucket="active-equity-cn")
        self.assertEqual(raised.exception.code, "peer_admission_mismatch")

    def test_peer_profile_and_admission_digest_are_bound_into_audit(self) -> None:
        result = score()
        record = result.peer_sets[0].records[0]
        self.assertEqual(record.category_profile, "active_equity_mixed")
        self.assertEqual(record.admission_contract_version, "0.1.0")
        self.assertEqual(record.admission_contract_sha256, result.peer_admission_sha256)

        forged = tuple(
            replace(item, admission_contract_sha256="f" * 64)
            for item in peer_set("excess_return", peer_bucket="active-equity-cn")
        )
        with self.assertRaises(CategoryMetricError):
            score(peers=forged)


class CaptureDenominatorRegressionTests(unittest.TestCase):
    def test_observed_capture_requires_present_positive_benchmark_downside_sample(
        self,
    ) -> None:
        from openfundscore.category_metrics import (
            CaptureDenominatorAudit,
            CaptureDenominatorStatus,
        )

        observations, _ = profile_fixture("active_equity_mixed")
        changed = tuple(
            replace(
                item,
                capture_denominator=CaptureDenominatorAudit(
                    denominator_status=CaptureDenominatorStatus.ABSENT,
                    benchmark_downside_sample_count=0,
                    evidence_id="capture-denominator-evidence",
                    lineage_id="capture-denominator-lineage",
                    series_id="capture-denominator-series",
                ),
            )
            if item.metric_id == "downside_capture"
            else item
            for item in observations
        )
        with self.assertRaises(CategoryMetricError) as raised:
            score(observations=changed)
        self.assertEqual(raised.exception.code, "capture_denominator_mismatch")

    def test_missing_capture_records_absent_denominator_without_raw_zero(self) -> None:
        from openfundscore.category_metrics import (
            CaptureDenominatorAudit,
            CaptureDenominatorStatus,
            MetricState,
        )

        observations, peers = profile_fixture("active_equity_mixed")
        changed = tuple(
            replace(
                item,
                state=MetricState.MISSING,
                raw_value=None,
                sample_size=0,
                window_months=0,
                capture_denominator=CaptureDenominatorAudit(
                    denominator_status=CaptureDenominatorStatus.ABSENT,
                    benchmark_downside_sample_count=0,
                    evidence_id="capture-denominator-evidence",
                    lineage_id="capture-denominator-lineage",
                    series_id="capture-denominator-series",
                ),
            )
            if item.metric_id == "downside_capture"
            else item
            for item in observations
        )
        result = score(
            observations=changed,
            peers=tuple(item for item in peers if item.metric_id != "downside_capture"),
            evidence_ledger=evidence_ledger("active_equity_mixed", changed),
        )
        self.assertIn("downside_capture", result.missing_metric_ids)

    def test_capture_peer_uses_the_same_denominator_rule(self) -> None:
        from openfundscore.category_metrics import (
            CaptureDenominatorAudit,
            CaptureDenominatorStatus,
        )

        observations, peers = profile_fixture("active_equity_mixed")
        changed = tuple(
            replace(
                item,
                capture_denominator=CaptureDenominatorAudit(
                    denominator_status=CaptureDenominatorStatus.PRESENT,
                    benchmark_downside_sample_count=0,
                    evidence_id="peer-denominator-evidence",
                    lineage_id="peer-denominator-lineage",
                    series_id="peer-denominator-series",
                ),
            )
            if item.metric_id == "downside_capture"
            else item
            for item in peers
        )
        with self.assertRaises(CategoryMetricError) as raised:
            score(observations=observations, peers=changed)
        self.assertEqual(raised.exception.code, "capture_denominator_mismatch")


class ManagerAuditRegressionTests(unittest.TestCase):
    def test_manager_contributions_are_recomputed_from_raw_component_scores(
        self,
    ) -> None:
        from tests.test_manager_handoff import manager_document, manager_sources

        raw = cast(dict[str, Any], manager_document())
        raw["score_components"]["downside_control"]["score"] = 60
        raw["score_components"]["style_discipline"]["score"] = 100
        handoff = ManagerResearchHandoff(
            manager_research=raw,
            as_of=manager_document_as_of(),
            fund_strategy_id="fund-1",
            sources=manager_sources(),
            assertion_status="caller_provided",
        )
        recomputed = recompute_manager_handoff(handoff)
        result = score(manager_handoff=handoff)

        self.assertEqual(
            dict(result.manager_audit.component_raw_scores)["downside_control"], 60.0
        )
        self.assertEqual(
            dict(result.manager_audit.component_contributions)["downside_control"], 9.0
        )
        self.assertEqual(result.manager_score, recomputed["score"])

        forged_expected = deepcopy(recomputed)
        forged_expected["component_contributions"]["downside_control"] = 15.0
        forged_expected["score"] = 82.0
        with self.assertRaises(CategoryMetricError) as raised:
            score(manager_handoff=handoff, manager_audit=forged_expected)
        self.assertEqual(raised.exception.code, "legacy_manager_audit_rejected")

    def test_low_manager_confidence_caps_category_confidence_without_score_penalty(
        self,
    ) -> None:
        from tests.test_manager_handoff import manager_document, manager_sources

        raw = cast(dict[str, Any], manager_document())
        raw["score_components"]["research_platform_team"]["confidence"] = "low"
        handoff = ManagerResearchHandoff(
            manager_research=raw,
            as_of=manager_document_as_of(),
            fund_strategy_id="fund-1",
            sources=manager_sources(),
            assertion_status="caller_provided",
        )
        result = score(manager_handoff=handoff)
        self.assertEqual(result.manager_score, 80.0)
        self.assertEqual(result.confidence, "low")

    def test_tenure_contribution_reconciles_raw_score_factor_and_weight(self) -> None:
        from tests.test_manager_handoff import manager_document, manager_sources

        raw = cast(dict[str, Any], manager_document())
        raw["tenures"][0].update(
            {"attribution_mode": "team", "co_manager_ids": ["manager-2"]}
        )
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
            for source in manager_sources()
        ]
        handoff = ManagerResearchHandoff(
            manager_research=raw,
            as_of=manager_document_as_of(),
            fund_strategy_id="fund-1",
            sources=derive_manager_evidence_sources(raw, "fund-1", identity_rows),
            assertion_status="caller_provided",
        )
        observations, _ = profile_fixture("active_equity_mixed")
        ledger = cast(
            dict[str, Any],
            deepcopy(evidence_ledger("active_equity_mixed", observations)),
        )
        ledger["usage"] = [
            item
            for item in ledger["usage"]
            if not item["target_component"].startswith("manager_")
        ]
        ledger["usage"].extend(recompute_manager_handoff(handoff)["component_evidence"])
        result = score(manager_handoff=handoff, evidence_ledger=ledger)
        self.assertEqual(
            dict(result.manager_audit.component_raw_scores)[
                "tenure_attributed_performance"
            ],
            80.0,
        )
        self.assertEqual(result.manager_score, 70.0)

    def test_current_fund_raw_manager_source_cannot_overlap_same_fund_evidence(
        self,
    ) -> None:
        from tests.test_manager_handoff import manager_document, manager_sources

        observations, _ = profile_fixture("active_equity_mixed")
        fund = next(
            item
            for item in observations
            if item.metric_id == "annualized_benchmark_excess"
        )
        raw = cast(dict[str, Any], manager_document())
        component = "tenure_attributed_performance"
        old_evidence_id = raw["score_components"][component]["evidence_ids"][0]
        raw["score_components"][component]["evidence_ids"] = [fund.evidence_id]
        raw["tenures"][0]["evidence_ids"] = [fund.evidence_id]
        raw["tenures"][0]["end_date"] = "2026-08-20"
        raw["performance_evidence"][0]["evidence_ids"] = [fund.evidence_id]
        raw["performance_evidence"][0]["window_start"] = "2023-08-20"
        raw["performance_evidence"][0]["window_end"] = "2026-08-20"
        manager_evidence = next(
            item for item in raw["evidence"] if item["evidence_id"] == old_evidence_id
        )
        manager_evidence["evidence_id"] = fund.evidence_id

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
            for source in manager_sources()
        ]
        identity_rows[0].update(
            {
                "evidence_id": fund.evidence_id,
                "lineage_id": fund.lineage_id,
                "series_id": fund.series_id,
                "source_scope": "current_fund",
                "usage_mode": "raw",
                "fund_strategy_id": "fund-1",
            }
        )
        sources = derive_manager_evidence_sources(raw, "fund-1", identity_rows)
        handoff = ManagerResearchHandoff(
            manager_research=raw,
            as_of=manager_document_as_of(),
            fund_strategy_id="fund-1",
            sources=sources,
            assertion_status="caller_provided",
        )
        manager_rows = recompute_manager_handoff(handoff)["component_evidence"]
        ledger = cast(
            dict[str, Any],
            deepcopy(evidence_ledger("active_equity_mixed", observations)),
        )
        ledger["usage"] = [
            item
            for item in ledger["usage"]
            if not item["target_component"].startswith("manager_")
        ]
        ledger["usage"].extend(manager_rows)

        fund_row = next(
            item
            for item in ledger["usage"]
            if item["evidence_id"] == fund.evidence_id
            and item["target_component"].startswith("fund_")
        )
        manager_row = next(
            item
            for item in ledger["usage"]
            if item["evidence_id"] == fund.evidence_id
            and item["target_component"] == f"manager_{component}"
        )
        self.assertEqual(fund_row["evidence_id"], manager_row["evidence_id"])
        self.assertEqual(
            (manager_row["source_scope"], manager_row["usage_mode"]),
            ("current_fund", "raw"),
        )

        with self.assertRaises(CategoryMetricError) as raised:
            score(manager_handoff=handoff, evidence_ledger=ledger)
        self.assertEqual(raised.exception.code, "invalid_evidence_ledger")


def manager_document_as_of():
    from datetime import UTC, datetime

    return datetime(2026, 8, 22, tzinfo=UTC)


if __name__ == "__main__":
    unittest.main()
