from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import cast

from openfundscore.cli import main
from openfundscore.walk_forward_io import synthetic_fixture_document


class WalkForwardCliTests(unittest.TestCase):
    def test_cli_runs_strict_json_and_emits_reproducible_auditable_report(self) -> None:
        payload = json.dumps(
            synthetic_fixture_document(),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "walk-forward.json"
            path.write_bytes(payload)
            outputs = []
            for _ in range(2):
                output = io.StringIO()
                with redirect_stdout(output):
                    exit_code = main(["walk-forward", str(path)])
                self.assertEqual(exit_code, 0)
                outputs.append(output.getvalue())

        self.assertEqual(outputs[0], outputs[1])
        document = json.loads(outputs[0])
        self.assertEqual(document["schema_version"], "0.1.0")
        self.assertEqual(
            document["methodology"]["score_stability"],
            "Spearman rank correlation on scores for overlapping eligible strategies",
        )
        self.assertEqual(
            document["methodology"]["selection_turnover"], "Jaccard distance"
        )
        self.assertEqual(
            document["methodology"]["component_correlation"],
            "Pearson correlation using pairwise-complete component contributions",
        )
        self.assertEqual(
            document["methodology"]["sensitivity"],
            "leave one additive component out without refitting or using outcomes",
        )
        self.assertEqual(
            document["methodology"]["score_audit_identity"],
            "(strategy_id, audit_id, revision_id)",
        )
        self.assertEqual(document["report"]["summary"]["fold_count"], 2)
        self.assertEqual(
            document["report"]["summary"]["disclaimer"],
            "research_only_not_a_return_guarantee",
        )
        self.assertIn("provider_snapshot_id", outputs[0])
        first_fold = document["report"]["folds"][0]
        self.assertEqual(len(first_fold["audit_score_ids"][0]), 3)
        self.assertIn("strategy_id", first_fold["score_audit_trail"][0])
        self.assertIn("revision_id", first_fold["score_audit_trail"][0])
        self.assertIn("supersedes_revision_id", first_fold["score_audit_trail"][0])

    def test_cli_rejects_non_strict_or_oversized_json_without_echoing_content(
        self,
    ) -> None:
        cases = (
            b"\xffprivate-marker",
            b'{"schema_version":"0.1.0","schema_version":"private-marker"}',
            b'{"schema_version":"0.1.0","private-marker":NaN}',
            json.dumps({"private-marker": "\ud800"}).encode("utf-8"),
            b" " * (8 * 1024 * 1024 + 1),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "bad.json"
            for payload in cases:
                with self.subTest(payload=payload[:1]):
                    path.write_bytes(payload)
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        exit_code = main(["walk-forward", str(path)])
                    self.assertEqual(exit_code, 2)
                    self.assertEqual(stdout.getvalue(), "")
                    self.assertIn("walk_forward_document", stderr.getvalue())
                    self.assertNotIn("private-marker", stderr.getvalue())
                    self.assertNotIn("Traceback", stderr.getvalue())

    def test_cli_rejects_huge_integer_score_with_code_2_and_no_traceback(self) -> None:
        document = synthetic_fixture_document()
        scores = cast(list[dict[str, object]], document["precomputed_scores"])
        self.assertIsInstance(scores, list)
        score = scores[0]
        self.assertIsInstance(score, dict)
        score["total_score"] = 10**400
        components = cast(list[dict[str, object]], score["components"])
        self.assertIsInstance(components, list)
        components[0]["contribution"] = 10**400

        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "huge-score.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(["walk-forward", str(path)])

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("walk_forward_document", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
