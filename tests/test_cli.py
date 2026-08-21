from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from openfundscore.cli import main
from openfundscore.resources import resolve_resource


class CliTests(unittest.TestCase):
    def test_validate_config_reports_profiles_and_manager_total(self) -> None:
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.json"
            config_path.write_bytes(
                resolve_resource(
                    resource_type="scoring-config",
                    name="openfundscore-core",
                    version="0.1.0",
                ).read_bytes()
            )
            with redirect_stdout(output):
                exit_code = main(["validate-config", str(config_path)])

        self.assertEqual(0, exit_code)
        self.assertIn("10 category profiles", output.getvalue())
        self.assertIn("manager model: 100", output.getvalue())

    def test_resources_list_emits_deterministic_versioned_json(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(["resources", "list", "--type", "schema"])

        self.assertEqual(0, exit_code)
        document = json.loads(output.getvalue())
        self.assertEqual(len(document), 5)
        self.assertEqual(
            [item["name"] for item in document],
            sorted(item["name"] for item in document),
        )
        self.assertTrue(all(item["type"] == "schema" for item in document))
        self.assertTrue(all(item["version"] == "0.1.0" for item in document))

    def test_resources_resolve_returns_logical_metadata_not_a_path(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "resources",
                    "resolve",
                    "--type",
                    "schema",
                    "--name",
                    "provider_record",
                    "--version",
                    "0.1.0",
                ]
            )

        self.assertEqual(0, exit_code)
        document = json.loads(output.getvalue())
        self.assertEqual(
            document["uri"],
            "openfundscore://schema/provider_record/0.1.0",
        )
        self.assertEqual(document["type"], "schema")
        self.assertEqual(document["name"], "provider_record")
        self.assertEqual(document["version"], "0.1.0")
        self.assertNotIn("path", document)

    def test_resources_show_emits_the_exact_packaged_json_text(self) -> None:
        expected = resolve_resource(
            resource_type="schema",
            name="provider_record",
            version="0.1.0",
        ).read_text()
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "resources",
                    "show",
                    "--type",
                    "schema",
                    "--name",
                    "provider_record",
                    "--version",
                    "0.1.0",
                ]
            )

        self.assertEqual(0, exit_code)
        self.assertEqual(expected, output.getvalue())

    def test_resource_lookup_failures_return_2_without_traceback(self) -> None:
        output = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(output), redirect_stderr(stderr):
            exit_code = main(
                [
                    "resources",
                    "resolve",
                    "--type",
                    "schema",
                    "--name",
                    "provider_record",
                    "--version",
                    "9.9.9",
                ]
            )

        self.assertEqual(2, exit_code)
        self.assertEqual("", output.getvalue())
        self.assertIn("resource_not_found at $resource", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_all_config_load_failures_return_2_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            undecodable = root / "undecodable.json"
            undecodable.write_bytes(b"\xff")

            cases = (
                ("directory", str(root), None),
                ("unicode", str(undecodable), None),
                ("permission", "config.json", PermissionError("denied")),
                ("os-error", "config.json", OSError("device failure")),
            )
            for label, path, read_error in cases:
                with self.subTest(label=label):
                    stderr = io.StringIO()
                    context = (
                        patch(
                            "openfundscore.score_config.Path.read_text",
                            side_effect=read_error,
                        )
                        if read_error is not None
                        else nullcontext()
                    )
                    with context, redirect_stderr(stderr):
                        exit_code = main(["validate-config", path])

                    self.assertEqual(2, exit_code)
                    self.assertIn("openfundscore: error:", stderr.getvalue())
                    self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
