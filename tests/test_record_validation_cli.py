from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from openfundscore.cli import main
from tests.test_record_validation import provider_record


class RecordValidationCliTests(unittest.TestCase):
    def _run(self, path: Path, *extra: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(
                [
                    "validate-record",
                    "--type",
                    "provider_record",
                    "--schema-version",
                    "0.1.0",
                    *extra,
                    str(path),
                ]
            )
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_validate_record_cli_runs_schema_and_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "provider-record.json"
            path.write_text(json.dumps(provider_record()), encoding="utf-8")
            exit_code, stdout, stderr = self._run(
                path,
                "--evaluation-timestamp",
                "2026-08-21T00:00:00Z",
            )

            self.assertEqual(0, exit_code)
            self.assertEqual(
                "valid: provider_record@0.1.0 (schema+semantics)\n",
                stdout,
            )
            self.assertEqual("", stderr)

            invalid = provider_record()
            invalid["value"] = "private-marker"
            invalid["published_at"] = "2026-08-22T00:00:00Z"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            exit_code, stdout, stderr = self._run(
                path,
                "--evaluation-timestamp",
                "2026-08-21T00:00:00Z",
            )

            self.assertEqual(2, exit_code)
            self.assertEqual("", stdout)
            self.assertIn("chronology_violation at $.published_at", stderr)
            self.assertNotIn("private-marker", stderr)
            self.assertNotIn(str(path), stderr)
            self.assertNotIn("Traceback", stderr)

    def test_validate_record_cli_fails_closed_on_input_and_context_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "provider-record.json"
            path.write_text('{"private-marker":', encoding="utf-8")
            exit_code, stdout, stderr = self._run(
                path,
                "--evaluation-timestamp",
                "2026-08-21T00:00:00Z",
            )
            self.assertEqual(2, exit_code)
            self.assertEqual("", stdout)
            self.assertIn("document_format at $document", stderr)
            self.assertNotIn("private-marker", stderr)
            self.assertNotIn(str(path), stderr)
            self.assertNotIn("Traceback", stderr)

            path.write_text(json.dumps(provider_record()), encoding="utf-8")
            exit_code, stdout, stderr = self._run(path)
            self.assertEqual(2, exit_code)
            self.assertEqual("", stdout)
            self.assertIn(
                "missing_evaluation_timestamp at $evaluation_timestamp",
                stderr,
            )
            self.assertNotIn("Traceback", stderr)

    def test_validate_record_cli_rejects_io_encoding_size_and_recursion_errors(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            missing = root / "missing-private-marker.json"
            for label, path, expected_code in (
                ("missing", missing, "document_io"),
                ("encoding", root / "encoding.json", "document_format"),
                ("large", root / "large.json", "document_too_large"),
            ):
                if label == "encoding":
                    path.write_bytes(b"\xffprivate-marker")
                elif label == "large":
                    path.write_text(
                        '"' + "x" * (8 * 1024 * 1024) + '"',
                        encoding="utf-8",
                    )
                with self.subTest(label=label):
                    try:
                        exit_code, stdout, stderr = self._run(
                            path,
                            "--evaluation-timestamp",
                            "2026-08-21T00:00:00Z",
                        )
                    except (OSError, UnicodeError) as exc:
                        self.fail(f"raw input exception escaped: {type(exc).__name__}")
                    self.assertEqual(2, exit_code)
                    self.assertEqual("", stdout)
                    self.assertIn(f"{expected_code} at $document", stderr)
                    self.assertNotIn("private-marker", stderr)
                    self.assertNotIn(str(path), stderr)
                    self.assertNotIn("Traceback", stderr)

            valid = root / "valid.json"
            valid.write_text(json.dumps(provider_record()), encoding="utf-8")
            with patch(
                "openfundscore.cli.json.loads",
                side_effect=RecursionError("private-marker"),
            ):
                try:
                    exit_code, stdout, stderr = self._run(
                        valid,
                        "--evaluation-timestamp",
                        "2026-08-21T00:00:00Z",
                    )
                except RecursionError:
                    self.fail("raw parser recursion escaped")
            self.assertEqual(2, exit_code)
            self.assertEqual("", stdout)
            self.assertIn("document_format at $document", stderr)
            self.assertNotIn("private-marker", stderr)
            self.assertNotIn("Traceback", stderr)

    def test_validate_record_cli_rejects_duplicate_keys_and_non_finite_numbers(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "record.json"
            base = json.dumps(provider_record())
            duplicate = base.replace(
                '{"provider_id": "provider-1",',
                '{"provider_id": "private-marker", "provider_id": "provider-1",',
                1,
            )
            non_finite = provider_record()
            non_finite["value"] = float("nan")
            for label, payload in (
                ("duplicate", duplicate),
                ("non-finite", json.dumps(non_finite)),
            ):
                with self.subTest(label=label):
                    path.write_text(payload, encoding="utf-8")
                    exit_code, stdout, stderr = self._run(
                        path,
                        "--evaluation-timestamp",
                        "2026-08-21T00:00:00Z",
                    )
                    self.assertEqual(2, exit_code)
                    self.assertEqual("", stdout)
                    self.assertIn("document_format at $document", stderr)
                    self.assertNotIn("private-marker", stderr)
                    self.assertNotIn("Traceback", stderr)

    def test_validate_record_cli_wraps_parser_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "valid.json"
            path.write_text(json.dumps(provider_record()), encoding="utf-8")
            with patch(
                "openfundscore.cli.json.loads",
                side_effect=ValueError("private-marker"),
            ):
                try:
                    exit_code, stdout, stderr = self._run(
                        path,
                        "--evaluation-timestamp",
                        "2026-08-21T00:00:00Z",
                    )
                except ValueError:
                    self.fail("raw parser value error escaped")
            self.assertEqual(2, exit_code)
            self.assertEqual("", stdout)
            self.assertNotIn("private-marker", stderr)
            self.assertNotIn(str(path), stderr)
            self.assertNotIn("Traceback", stderr)


if __name__ == "__main__":
    unittest.main()
