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

from openfundscore.walk_forward_io import synthetic_fixture_document
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
                    "--no-deps",
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
            uv = shutil.which("uv")
            if uv is not None:
                subprocess.run(
                    [
                        uv,
                        "pip",
                        "install",
                        "--offline",
                        "--python",
                        str(python),
                        "jsonschema[format-nongpl]>=4.18,<5",
                    ],
                    check=True,
                    env=clean_environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            else:
                subprocess.run(
                    [
                        str(python),
                        "-m",
                        "pip",
                        "install",
                        "jsonschema[format-nongpl]>=4.18,<5",
                    ],
                    check=True,
                    env=clean_environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            subprocess.run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--force-reinstall",
                    "--no-deps",
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

            manager_payload = json.dumps(manager_record())
            api_probe = subprocess.run(
                [
                    str(python),
                    "-c",
                    (
                        "from openfundscore.resources import list_resources, resolve_resource;"
                        "items=list_resources();"
                        "assert len(items)==7;"
                        "[resolve_resource(resource_type=i.key.resource_type,"
                        "name=i.key.name,version=i.key.version).load_json() for i in items];"
                        "from openfundscore.strategy_mapping import map_strategy_family;"
                        "d=map_strategy_family('market_neutral',mapping_version='0.1.0');"
                        "assert d.peer_bucket=='market_neutral';"
                        "assert d.score_profile=='unrated' and not d.is_rated;"
                        "assert d.unrated_reason=='insufficient_comparable_sample';"
                        "from openfundscore import score_manager_research;"
                        "import json;"
                        f"m=score_manager_research(json.loads({manager_payload!r}));"
                        "assert m['manager_id']=='manager-1';"
                        "assert m['model_version']=='0.1.0';"
                        "assert m['status']=='insufficient' and m['score'] is None;"
                        "assert len(m['component_weights'])==8;"
                        "assert m['tenure_attribution']['aggregate_factor'] is None;"
                        "from openfundscore.validation import validate_record;"
                        f"bad=json.loads({manager_payload!r});"
                        "bad['evidence']=[{'evidence_id':'e-url','tier':'A',"
                        "'source_url':'https://example.com/source',"
                        "'published_at':'2026-08-20T00:00:00Z',"
                        "'fetched_at':'2026-08-21T00:00:00Z',"
                        "'fact_excerpt':'Public professional fact',"
                        f"'supports_components':{['tenure_attributed_performance', 'downside_control', 'cross_cycle_consistency', 'style_discipline', 'career_track_record', 'workload_capacity', 'research_platform_team', 'compliance_integrity']!r}}}];"
                        "urls=('https://example.com/2125550198',"
                        "'https://example.com/212%252D555%252D0198',"
                        "'https://example.com/person%2540example.com');"
                        "apis=(lambda d: score_manager_research(d),"
                        "lambda d: validate_record('manager_research',d,schema_version='0.1.0'));"
                        "\ndef _expect_value_error(api, document):\n"
                        "    try:\n"
                        "        api(document)\n"
                        "    except ValueError:\n"
                        "        return\n"
                        "    raise AssertionError('private source URL accepted')\n"
                        "[(lambda u,a: (bad['evidence'][0].__setitem__('source_url',u),"
                        "_expect_value_error(a,bad)))(u,a) for u in urls for a in apis];"
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
            walk_forward_path = runtime / "walk-forward.json"
            walk_forward_path.write_text(
                json.dumps(synthetic_fixture_document(), allow_nan=False),
                encoding="utf-8",
            )
            walk_forward_probe = subprocess.run(
                [str(executable), "walk-forward", str(walk_forward_path)],
                check=False,
                cwd=runtime,
                env=clean_environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                walk_forward_probe.returncode,
                0,
                msg=(
                    f"stdout={walk_forward_probe.stdout}\n"
                    f"stderr={walk_forward_probe.stderr}"
                ),
            )
            walk_forward_report = json.loads(walk_forward_probe.stdout)
            self.assertEqual(walk_forward_report["report"]["summary"]["fold_count"], 2)
            self.assertIn(
                "component_diagnostics",
                walk_forward_report["report"]["summary"],
            )
            first_fold = walk_forward_report["report"]["folds"][0]
            self.assertEqual(len(first_fold["audit_score_ids"][0]), 3)
            self.assertIn("strategy_id", first_fold["score_audit_trail"][0])
            self.assertIn("revision_id", first_fold["score_audit_trail"][0])
            self.assertIn(
                "supersedes_revision_id",
                first_fold["score_audit_trail"][0],
            )

            list_probe = subprocess.run(
                [str(executable), "resources", "list"],
                check=True,
                cwd=runtime,
                env=clean_environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(len(json.loads(list_probe.stdout)), 7)

            strategy_map_probe = subprocess.run(
                [
                    str(executable),
                    "strategy-map",
                    "long_short_equity",
                    "--mapping-version",
                    "0.1.0",
                ],
                check=True,
                cwd=runtime,
                env=clean_environment,
                capture_output=True,
                text=True,
            )
            strategy_decision = json.loads(strategy_map_probe.stdout)
            self.assertEqual(strategy_decision["peer_bucket"], "long_short_equity")
            self.assertEqual(strategy_decision["score_profile"], "unrated")
            self.assertFalse(strategy_decision["is_rated"])

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

            provider_sdk_probe = subprocess.run(
                [
                    str(python),
                    "-c",
                    (
                        "import json,pathlib;"
                        "from datetime import UTC,datetime;"
                        "from zoneinfo import ZoneInfo;"
                        "from openfundscore.provider_sdk import *;"
                        "e=ZoneInfo('America/New_York');"
                        "snapshot_time=datetime(2026,11,1,1,30,tzinfo=e,fold=0);"
                        "request_time=datetime(2026,11,1,1,30,tzinfo=e,fold=1);"
                        "caps=frozenset({ProviderCapability.GET_ENTITLEMENTS,ProviderCapability.GET_PROFILE});"
                        "snapshot=ProviderEntitlements(provider_id='provider-1',evaluated_at=snapshot_time,"
                        "valid_until=datetime(2026,11,2,7,tzinfo=UTC),source_type=SourceType.REGULATOR,"
                        "jurisdictions=frozenset({'CN'}),authentication_mode=AuthenticationMode.NONE,"
                        "capabilities=caps,rights_mode=RightsMode.OPEN_REDISTRIBUTABLE,cache_allowed=True,"
                        "cache_ttl_seconds=3600,derived_works_allowed=True,public_display_allowed=True,"
                        "redistribution_allowed=True,retention_days=30,attribution_required=True,"
                        "terms_url='https://example.com/terms',rights_reviewed_at=datetime(2026,8,21,tzinfo=UTC),"
                        "rate_limit=RateLimit(requests_per_period=10,period_seconds=60));"
                        "Adapter=type('Adapter',(),{'provider_id':'provider-1','capabilities':caps,"
                        "'get_entitlements':lambda self,*,evaluation_timestamp:snapshot});"
                        "record=json.loads(pathlib.Path('records.json').read_text())['provider_record'];"
                        "record['rights'].update({'mode':'open_redistributable','cache_allowed':True,"
                        "'derived_works_allowed':True,'public_display_allowed':True,'redistribution_allowed':True,"
                        "'attribution_required':True,'retention_days':30,'terms_url':'https://example.com/terms',"
                        "'reviewed_at':'2026-08-21T00:00:00Z'});"
                        "denied=False;"
                        "\ntry:\n authorize_ingestion(Adapter(),record,schema_version='0.1.0',"
                        "evaluation_timestamp=request_time,request=IngestionRequest(capability=ProviderCapability.GET_PROFILE),"
                        "rate_limit_budget=RateLimitBudget(provider_id='provider-1',period_started_at=request_time,requests_used=0))"
                        "\nexcept IngestionDenied as exc:\n denied=exc.code=='entitlement_contract_mismatch'"
                        "\nassert denied\nprint('provider-sdk-ok')"
                    ),
                ],
                check=False,
                cwd=runtime,
                env=clean_environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                provider_sdk_probe.returncode,
                0,
                msg=(
                    f"stdout={provider_sdk_probe.stdout}\n"
                    f"stderr={provider_sdk_probe.stderr}"
                ),
            )
            self.assertEqual(provider_sdk_probe.stdout.strip(), "provider-sdk-ok")

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
