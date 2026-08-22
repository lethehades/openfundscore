from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from pathlib import Path

from openfundscore.cli import main
from tests.test_category_metrics import evidence_ledger, manager_result, profile_fixture
from tests.test_manager_handoff import manager_document, manager_sources


def manager_handoff_document() -> dict:
    source_documents = [
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
    return {
        "manager_research": manager_document(),
        "as_of": "2026-08-22T00:00:00Z",
        "fund_strategy_id": "fund-1",
        "sources": source_documents,
        "assertion_status": "caller_provided",
    }


def cli_document() -> dict:
    observations, peers = profile_fixture("active_equity_mixed")
    observation_documents = []
    for item in observations:
        document = asdict(item)
        document["state"] = item.state.value
        for field in ("as_of", "published_at", "evaluation_timestamp"):
            document[field] = document[field].isoformat().replace("+00:00", "Z")
        observation_documents.append(document)
    peer_documents = []
    for item in peers:
        document = asdict(item)
        for field in ("as_of", "published_at", "evaluation_timestamp"):
            document[field] = document[field].isoformat().replace("+00:00", "Z")
        peer_documents.append(document)
    return {
        "profile_id": "active_equity_mixed",
        "peer_bucket": "active-equity-cn",
        "peer_bucket_version": "0.1.0",
        "peer_admission_version": "0.1.0",
        "history_months": 36,
        "adequate_regime_coverage": True,
        "applicability_context": {
            "declared_benchmark": True,
            "cross_border_or_currency_exposure": True,
            "derivative_or_commodity_exposure": True,
            "income_distributing_assets": True,
            "lookthrough_portfolio": True,
            "securities_lending_program": True,
        },
        "manager_handoff": manager_handoff_document(),
        "evidence_ledger": evidence_ledger("active_equity_mixed", observations),
        "config_version": "0.1.0",
        "metric_catalog_version": "0.1.0",
        "final_precision": 2,
        "observations": observation_documents,
        "peers": peer_documents,
    }


class CategoryMetricCliTests(unittest.TestCase):
    def test_public_package_exports_stable_category_api(self) -> None:
        from openfundscore import (
            MANAGER_COMPONENT_SOURCE_MANIFEST,
            ApplicabilityContext,
            CategoryMetricError,
            ManagerEvidenceSource,
            ManagerResearchHandoff,
            ManagerScoreAudit,
            MetricObservation,
            MetricState,
            PeerAuditRecord,
            PeerSetAudit,
            build_manager_evidence_sources,
            canonicalize_score_evidence_ledger_for_digest,
            derive_manager_evidence_sources,
            load_metric_catalog,
            normalize_metric,
            recompute_manager_handoff,
            score_category_metrics,
            validate_metric_catalog,
        )

        self.assertTrue(issubclass(CategoryMetricError, ValueError))
        self.assertTrue(callable(ApplicabilityContext))
        self.assertEqual(MetricState.MISSING.value, "missing")
        self.assertTrue(callable(ManagerScoreAudit))
        self.assertTrue(callable(ManagerEvidenceSource))
        self.assertTrue(callable(ManagerResearchHandoff))
        self.assertEqual(len(MANAGER_COMPONENT_SOURCE_MANIFEST), 8)
        self.assertTrue(callable(build_manager_evidence_sources))
        self.assertTrue(callable(canonicalize_score_evidence_ledger_for_digest))
        self.assertTrue(callable(derive_manager_evidence_sources))
        self.assertTrue(callable(recompute_manager_handoff))
        self.assertTrue(callable(MetricObservation))
        self.assertTrue(callable(PeerAuditRecord))
        self.assertTrue(callable(PeerSetAudit))
        self.assertTrue(callable(load_metric_catalog))
        self.assertTrue(callable(normalize_metric))
        self.assertTrue(callable(score_category_metrics))
        self.assertTrue(callable(validate_metric_catalog))

    def test_category_score_cli_reads_strict_json_and_emits_deterministic_json(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "score.json"
            path.write_text(json.dumps(cli_document()), encoding="utf-8")
            first = io.StringIO()
            second = io.StringIO()
            with redirect_stdout(first):
                first_code = main(["category-score", str(path)])
            with redirect_stdout(second):
                second_code = main(["category-score", str(path)])

        self.assertEqual((first_code, second_code), (0, 0))
        self.assertEqual(first.getvalue(), second.getvalue())
        result = json.loads(first.getvalue())
        self.assertEqual(result["open_score"], 57.2)
        self.assertEqual(result["catalog_version"], "0.1.0")
        self.assertEqual(len(result["metrics"]), 12)
        self.assertEqual(len(result["manager_audit"]["component_evidence"]), 8)
        self.assertEqual(
            result["manager_audit"]["manager_input_assertion_status"],
            "caller_provided",
        )
        self.assertTrue(
            all(
                len(row["source_facts_sha256"]) == 64
                for row in result["manager_audit"]["component_evidence"]
            )
        )
        self.assertNotIn("manager_handoff", result)
        self.assertNotIn("manager_research", result)

    def test_category_score_cli_rejects_legacy_summary_and_closed_handoff_violations(
        self,
    ) -> None:
        cases = []
        legacy = cli_document()
        legacy["manager_audit"] = manager_result()
        del legacy["manager_handoff"]
        cases.append(legacy)

        unknown_handoff = cli_document()
        unknown_handoff["manager_handoff"]["unknown"] = "secret-marker"
        cases.append(unknown_handoff)

        missing_source_field = cli_document()
        del missing_source_field["manager_handoff"]["sources"][0]["lineage_id"]
        cases.append(missing_source_field)

        forged_derived = cli_document()
        forged_derived["manager_handoff"]["sources"][0]["facts_sha256"] = "f" * 64
        cases.append(forged_derived)

        wrong_assertion = cli_document()
        wrong_assertion["manager_handoff"]["assertion_status"] = "verified"
        cases.append(wrong_assertion)

        oversized_sources = cli_document()
        oversized_sources["manager_handoff"]["sources"] *= 2
        cases.append(oversized_sources)

        with tempfile.TemporaryDirectory() as directory:
            for index, document in enumerate(cases):
                path = Path(directory) / f"closed-{index}.json"
                path.write_text(json.dumps(document), encoding="utf-8")
                stdout = io.StringIO()
                stderr = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main(["category-score", str(path)])
                self.assertEqual(code, 2)
                self.assertEqual(stdout.getvalue(), "")
                self.assertIn("openfundscore: error:", stderr.getvalue())
                self.assertNotIn("secret-marker", stderr.getvalue())

    def test_category_score_cli_closes_malformed_manager_documents(self) -> None:
        cases = []
        missing_tenure_id = cli_document()
        del missing_tenure_id["manager_handoff"]["manager_research"]["tenures"][0][
            "tenure_id"
        ]
        cases.append(missing_tenure_id)

        non_sequence_tenures = cli_document()
        non_sequence_tenures["manager_handoff"]["manager_research"]["tenures"] = {
            "secret-hostile-payload": True
        }
        cases.append(non_sequence_tenures)

        missing_nested_field = cli_document()
        del missing_nested_field["manager_handoff"]["manager_research"][
            "style_fingerprint"
        ]["factor_exposures"]["as_of"]
        cases.append(missing_nested_field)

        with tempfile.TemporaryDirectory() as directory:
            for index, document in enumerate(cases):
                with self.subTest(index=index):
                    path = Path(directory) / f"manager-{index}.json"
                    path.write_text(json.dumps(document), encoding="utf-8")
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        code = main(["category-score", str(path)])

                    self.assertEqual(code, 2)
                    self.assertEqual(stdout.getvalue(), "")
                    self.assertEqual(len(stderr.getvalue().splitlines()), 1)
                    self.assertIn("openfundscore: error:", stderr.getvalue())
                    self.assertNotIn("Traceback", stderr.getvalue())
                    self.assertNotIn("secret-hostile-payload", stderr.getvalue())

    def test_category_score_help_names_manager_handoff_not_caller_audit(self) -> None:
        output = io.StringIO()
        with self.assertRaises(SystemExit), redirect_stdout(output):
            main(["category-score", "--help"])
        self.assertIn("manager handoff", output.getvalue())
        self.assertNotIn("manager audit", output.getvalue())

    def test_category_score_cli_rejects_missing_or_unknown_prerequisite_facts(
        self,
    ) -> None:
        cases = []
        missing = cli_document()
        del missing["applicability_context"]["declared_benchmark"]
        cases.append(missing)
        unknown = cli_document()
        unknown["applicability_context"]["unknown_prerequisite"] = False
        cases.append(unknown)

        with tempfile.TemporaryDirectory() as directory:
            for index, document in enumerate(cases):
                path = Path(directory) / f"case-{index}.json"
                path.write_text(json.dumps(document), encoding="utf-8")
                output = io.StringIO()
                stderr = io.StringIO()
                with redirect_stdout(output), redirect_stderr(stderr):
                    code = main(["category-score", str(path)])
                self.assertEqual(code, 2)
                self.assertEqual(output.getvalue(), "")
                self.assertIn("openfundscore: error:", stderr.getvalue())

    def test_category_score_cli_rejects_duplicate_keys_nan_bad_utf8_and_semantics(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            valid = json.dumps(cli_document())
            cases = {
                "duplicate": valid[:-1] + ',"profile_id":"bond"}',
                "nan": valid.replace('"score": 80', '"score": NaN', 1),
                "bad-state": valid.replace(
                    '"state": "observed"', '"state": "broken"', 1
                ),
            }
            paths = []
            for name, payload in cases.items():
                path = root / f"{name}.json"
                path.write_text(payload, encoding="utf-8")
                paths.append(path)
            bad_utf8 = root / "bad-utf8.json"
            bad_utf8.write_bytes(b"\xff")
            paths.append(bad_utf8)

            for path in paths:
                with self.subTest(path=path.name):
                    output = io.StringIO()
                    stderr = io.StringIO()
                    with redirect_stdout(output), redirect_stderr(stderr):
                        code = main(["category-score", str(path)])
                    self.assertEqual(code, 2)
                    self.assertEqual(output.getvalue(), "")
                    self.assertIn("openfundscore: error:", stderr.getvalue())
                    self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
