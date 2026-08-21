from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from openfundscore.cli import main


CONFIG_PATH = Path(__file__).parents[1] / "configs" / "scoring" / "v0.1.0.json"


class CliTests(unittest.TestCase):
    def test_validate_config_reports_profiles_and_manager_total(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(["validate-config", str(CONFIG_PATH)])

        self.assertEqual(0, exit_code)
        self.assertIn("10 category profiles", output.getvalue())
        self.assertIn("manager model: 100", output.getvalue())

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
