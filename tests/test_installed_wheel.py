from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path

from tests.test_record_validation import (
    external_rating,
    manager_record,
    provider_contract,
    provider_record,
    score_evidence_usage,
)

ROOT = Path(__file__).parents[1]


class InstalledWheelResourceTests(unittest.TestCase):
    def test_installed_wheel_exposes_resources_without_a_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            wheelhouse = root / "wheelhouse"
            environment = root / "venv"
            runtime = root / "runtime"
            wheelhouse.mkdir()
            runtime.mkdir()
            shutil.copytree(
                ROOT,
                source,
                ignore=shutil.ignore_patterns(
                    ".git",
                    ".venv",
                    "__pycache__",
                    "build",
                    "dist",
                    "*.egg-info",
                ),
            )

            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "wheel",
                    str(source),
                    "--wheel-dir",
                    str(wheelhouse),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            wheels = tuple(wheelhouse.glob("openfundscore-*.whl"))
            self.assertEqual(len(wheels), 1)

            venv.EnvBuilder(with_pip=True).create(environment)
            python = environment / "bin" / "python"
            clean_environment = os.environ.copy()
            clean_environment.pop("PYTHONPATH", None)
            clean_environment["PYTHONNOUSERSITE"] = "1"
            subprocess.run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--force-reinstall",
                    "--no-index",
                    "--find-links",
                    str(wheelhouse),
                    str(wheels[0]),
                ],
                check=True,
                env=clean_environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            shutil.rmtree(source)

            api_probe = subprocess.run(
                [
                    str(python),
                    "-c",
                    (
                        "from openfundscore.resources import list_resources, resolve_resource;"
                        "items=list_resources();"
                        "assert len(items)==6;"
                        "[resolve_resource(resource_type=i.key.resource_type,"
                        "name=i.key.name,version=i.key.version).load_json() for i in items];"
                        "print('api-ok')"
                    ),
                ],
                check=False,
                cwd=runtime,
                env=clean_environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                api_probe.returncode,
                0,
                msg=f"stdout={api_probe.stdout}\nstderr={api_probe.stderr}",
            )
            self.assertEqual(api_probe.stdout.strip(), "api-ok")

            executable = environment / "bin" / "openfundscore"
            list_probe = subprocess.run(
                [str(executable), "resources", "list"],
                check=True,
                cwd=runtime,
                env=clean_environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(len(json.loads(list_probe.stdout)), 6)

            selector = [
                "--type",
                "schema",
                "--name",
                "provider_record",
                "--version",
                "0.1.0",
            ]
            resolve_probe = subprocess.run(
                [str(executable), "resources", "resolve", *selector],
                check=True,
                cwd=runtime,
                env=clean_environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                json.loads(resolve_probe.stdout)["uri"],
                "openfundscore://schema/provider_record/0.1.0",
            )

            show_probe = subprocess.run(
                [str(executable), "resources", "show", *selector],
                check=True,
                cwd=runtime,
                env=clean_environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                json.loads(show_probe.stdout)["$schema"],
                "https://json-schema.org/draft/2020-12/schema",
            )

            records = {
                "manager_research": manager_record(),
                "provider_record": provider_record(),
                "provider_contract": provider_contract(),
                "external_rating": external_rating(),
                "score_evidence_usage": score_evidence_usage(),
            }
            bundle_path = runtime / "records.json"
            bundle_path.write_text(json.dumps(records), encoding="utf-8")
            validation_api_probe = subprocess.run(
                [
                    str(python),
                    "-c",
                    (
                        "import json,pathlib;"
                        "from openfundscore.validation import validate_record;"
                        "records=json.loads(pathlib.Path('records.json').read_text());"
                        "[validate_record(kind,document,schema_version='0.1.0',"
                        "evaluation_timestamp=('2026-08-21T00:00:00Z' if kind in "
                        "{'provider_record','external_rating'} else None)) "
                        "for kind,document in records.items()];"
                        "print('validation-api-ok')"
                    ),
                ],
                check=False,
                cwd=runtime,
                env=clean_environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                validation_api_probe.returncode,
                0,
                msg=(
                    f"stdout={validation_api_probe.stdout}\n"
                    f"stderr={validation_api_probe.stderr}"
                ),
            )
            self.assertEqual(
                validation_api_probe.stdout.strip(),
                "validation-api-ok",
            )

            publication_gate_probe = subprocess.run(
                [
                    str(python),
                    "-c",
                    (
                        "from openfundscore import PublicationDecision,"
                        "evaluate_publication_gate;"
                        "result=evaluate_publication_gate("
                        "{'request_id':'local-1','publication_mode':"
                        "'local_private_research','jurisdictions':[]},"
                        "evaluation_timestamp='2026-08-21T00:00:00Z');"
                        "assert result.decision is PublicationDecision.LOCAL_ONLY;"
                        "print('publication-gate-api-ok')"
                    ),
                ],
                check=False,
                cwd=runtime,
                env=clean_environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                publication_gate_probe.returncode,
                0,
                msg=(
                    f"stdout={publication_gate_probe.stdout}\n"
                    f"stderr={publication_gate_probe.stderr}"
                ),
            )
            self.assertEqual(
                publication_gate_probe.stdout.strip(),
                "publication-gate-api-ok",
            )

            for record_type, document in records.items():
                with self.subTest(installed_record_type=record_type):
                    record_path = runtime / f"{record_type}.json"
                    record_path.write_text(json.dumps(document), encoding="utf-8")
                    command = [
                        str(executable),
                        "validate-record",
                        "--type",
                        record_type,
                        "--schema-version",
                        "0.1.0",
                    ]
                    if record_type in {"provider_record", "external_rating"}:
                        command.extend(
                            [
                                "--evaluation-timestamp",
                                "2026-08-21T00:00:00Z",
                            ]
                        )
                    command.append(str(record_path))
                    validation_cli_probe = subprocess.run(
                        command,
                        check=False,
                        cwd=runtime,
                        env=clean_environment,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(
                        validation_cli_probe.returncode,
                        0,
                        msg=(
                            f"stdout={validation_cli_probe.stdout}\n"
                            f"stderr={validation_cli_probe.stderr}"
                        ),
                    )
                    self.assertEqual(
                        validation_cli_probe.stdout,
                        f"valid: {record_type}@0.1.0 (schema+semantics)\n",
                    )


if __name__ == "__main__":
    unittest.main()
