from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from openfundscore.cli import main
from tests.test_official_provider_adapters import SEC_FIXTURE, WORLD_BANK_PAGE_1


class OfficialProviderCliTests(unittest.TestCase):
    def test_non_provider_cli_runs_when_sec_timezone_database_is_unavailable(
        self,
    ) -> None:
        root = Path(__file__).parents[1]
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(
                None,
                (str(root / "src"), environment.get("PYTHONPATH")),
            )
        )
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import zoneinfo\n"
                    "def missing(*args,**kwargs):\n"
                    "    raise zoneinfo.ZoneInfoNotFoundError('PRIVATE-TZDB-SENTINEL')\n"
                    "zoneinfo.ZoneInfo=missing\n"
                    "from openfundscore.cli import main\n"
                    "raise SystemExit(main(['resources','list','--type','schema']))\n"
                ),
            ],
            check=False,
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            probe.returncode,
            0,
            msg=f"stdout={probe.stdout}\nstderr={probe.stderr}",
        )
        resources = json.loads(probe.stdout)
        self.assertGreaterEqual(len(resources), 1)
        self.assertNotIn("PRIVATE-TZDB-SENTINEL", probe.stderr)

    def test_cli_parses_sec_and_world_bank_fixtures_without_network_access(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            sec_path = root / "sec.json"
            sec_path.write_bytes(SEC_FIXTURE)
            world_bank = json.loads(json.dumps(WORLD_BANK_PAGE_1))
            world_bank[0]["pages"] = 1
            world_bank[0]["total"] = 1
            world_bank_path = root / "world-bank.json"
            world_bank_path.write_text(json.dumps(world_bank), encoding="utf-8")

            commands = (
                (
                    [
                        "provider-fixture",
                        "sec",
                        "--schema-version",
                        "0.2.0",
                        "--cik",
                        "0000320193",
                        "--user-agent",
                        "OpenFundScore security@openfundscore.org",
                        "--fetched-at",
                        "2026-08-21T12:30:00Z",
                        "--evaluation-timestamp",
                        "2026-08-21T12:30:00Z",
                        str(sec_path),
                    ],
                    2,
                    "sec-edgar-submissions",
                ),
                (
                    [
                        "provider-fixture",
                        "world-bank",
                        "--schema-version",
                        "0.2.0",
                        "--country",
                        "US",
                        "--indicator",
                        "NY.GDP.MKTP.CD",
                        "--source",
                        "2",
                        "--page",
                        "1",
                        "--per-page",
                        "1",
                        "--fetched-at",
                        "2026-08-21T12:30:00Z",
                        "--evaluation-timestamp",
                        "2026-08-21T12:30:00Z",
                        str(world_bank_path),
                    ],
                    1,
                    "world-bank-indicators-v2",
                ),
            )
            for command, expected_count, provider_id in commands:
                with self.subTest(provider_id=provider_id):
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        exit_code = main(command)
                    self.assertEqual(exit_code, 0, msg=stderr.getvalue())
                    records = json.loads(stdout.getvalue())
                    self.assertEqual(len(records), expected_count)
                    self.assertTrue(
                        all(record["provider_id"] == provider_id for record in records)
                    )
                    self.assertEqual(stderr.getvalue(), "")
                    self.assertNotIn("security@openfundscore.org", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
