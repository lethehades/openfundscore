from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv
from copy import deepcopy
from pathlib import Path

import jsonschema

from openfundscore.mainland_official import MainlandOfficialSnapshotAdapter
from tests.test_mainland_official_snapshot import (
    bundle,
    entitlement,
    entitlement_document,
)
from tests.test_record_validation import (
    external_rating,
    manager_record,
    provider_contract,
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
                    "--no-build-isolation",
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

            venv.EnvBuilder(with_pip=True, system_site_packages=True).create(
                environment
            )
            python = environment / "bin" / "python"
            dependency_layer = Path(jsonschema.__file__).resolve().parent.parent
            self.assertNotEqual(dependency_layer, ROOT.resolve())
            environment_site_packages = next(
                (environment / "lib").glob("python*/site-packages")
            )
            (environment_site_packages / "qa-dependencies.pth").write_text(
                str(dependency_layer) + "\n", encoding="utf-8"
            )
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
                    "--no-deps",
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
                        "assert len(items)==9;"
                        "import openfundscore;"
                        "from openfundscore import MainlandOfficialSnapshotAdapter,SnapshotValidationError,load_mainland_entitlements;"
                        "from openfundscore.fixtures import synthetic_mainland_snapshot_bundle;"
                        "assert {'MainlandOfficialSnapshotAdapter','SnapshotValidationError','load_mainland_entitlements'} <= set(openfundscore.__all__);"
                        "assert callable(MainlandOfficialSnapshotAdapter);"
                        "assert callable(load_mainland_entitlements);"
                        "assert synthetic_mainland_snapshot_bundle()['source_type']=='regulator';"
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
            mainland_snapshot_path = runtime / "mainland-snapshot.json"
            mainland_entitlement_path = runtime / "mainland-entitlements.json"
            mainland_source = bundle()
            mainland_source["rights"]["reviewed_at"] = "2026-08-19T19:00:00-05:00"  # type: ignore[index]
            mainland_source["rights"]["valid_until"] = "2026-08-31T19:00:00-05:00"  # type: ignore[index]
            installed_nav = mainland_source["items"][1]  # type: ignore[index]
            installed_original = installed_nav["observations"][1]
            installed_original["quality_state"] = "conflict"
            installed_original["conflict_group"] = "installed-nav-conflict"
            installed_alternative = deepcopy(installed_original)
            installed_alternative["observation_id"] = "nav-a-2-installed-alternative"
            installed_alternative["raw_value"] = 1.02
            installed_alternative["as_of"] = "2026-08-15T08:00:00+08:00"
            installed_alternative["valid_from"] = "2026-08-14T19:00:00-05:00"
            installed_nav["observations"].append(installed_alternative)
            mainland_snapshot_path.write_text(
                json.dumps(mainland_source, ensure_ascii=False), encoding="utf-8"
            )
            mainland_entitlement_path.write_text(
                json.dumps(entitlement_document()), encoding="utf-8"
            )
            installed_api_probe = subprocess.run(
                [
                    str(python),
                    "-c",
                    (
                        "import json,pathlib;from datetime import UTC,datetime;"
                        "from openfundscore import MainlandOfficialSnapshotAdapter,load_mainland_entitlements;"
                        "source=json.loads(pathlib.Path('mainland-snapshot.json').read_text());"
                        "rights=load_mainland_entitlements(pathlib.Path('mainland-entitlements.json'));"
                        "records=MainlandOfficialSnapshotAdapter(entitlements=rights).parse("
                        "source,evaluation_timestamp=datetime(2026,8,21,tzinfo=UTC));"
                        "assert len(records)==20;"
                        "assert all(r['rights']['reviewed_at']=='2026-08-19T19:00:00-05:00' "
                        "and r['rights']['valid_until']=='2026-08-31T19:00:00-05:00' for r in records);"
                        "nav=[r for r in records if r['field']=='nav'];"
                        "assert [r['value'] for r in nav]==[1.0,1.01,1.02];"
                        "assert [r['as_of'] for r in nav][-2:]==['2026-08-15T00:00:00Z','2026-08-15T08:00:00+08:00'];"
                        "print('mainland-api-ok')"
                    ),
                ],
                check=False,
                cwd=runtime,
                env=clean_environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                installed_api_probe.returncode,
                0,
                msg=(
                    f"stdout={installed_api_probe.stdout}\n"
                    f"stderr={installed_api_probe.stderr}"
                ),
            )
            self.assertEqual(installed_api_probe.stdout.strip(), "mainland-api-ok")
            mainland_probe = subprocess.run(
                [
                    str(executable),
                    "provider",
                    "mainland-parse",
                    str(mainland_snapshot_path),
                    "--entitlements",
                    str(mainland_entitlement_path),
                    "--evaluation-timestamp",
                    "2026-08-21T00:00:00Z",
                ],
                check=False,
                cwd=runtime,
                env=clean_environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                mainland_probe.returncode,
                0,
                msg=f"stdout={mainland_probe.stdout}\nstderr={mainland_probe.stderr}",
            )
            installed_cli_records = json.loads(mainland_probe.stdout)
            self.assertEqual(len(installed_cli_records), 20)
            self.assertTrue(
                all(
                    record["rights"]["reviewed_at"] == "2026-08-19T19:00:00-05:00"
                    and record["rights"]["valid_until"] == "2026-08-31T19:00:00-05:00"
                    for record in installed_cli_records
                )
            )
            self.assertEqual(
                [
                    record["value"]
                    for record in installed_cli_records
                    if record["field"] == "nav"
                ],
                [1.0, 1.01, 1.02],
            )

            list_probe = subprocess.run(
                [str(executable), "resources", "list"],
                check=True,
                cwd=runtime,
                env=clean_environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(len(json.loads(list_probe.stdout)), 9)

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
                "0.2.0",
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
                "openfundscore://schema/provider_record/0.2.0",
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

            current_provider_record = MainlandOfficialSnapshotAdapter(
                entitlements=entitlement()
            ).parse(bundle(), evaluation_timestamp=entitlement().evaluated_at)[0]
            records = {
                "manager_research": manager_record(),
                "provider_record": current_provider_record,
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
                        "[validate_record(kind,document,schema_version=("
                        "'0.2.0' if kind=='provider_record' else '0.1.0'),"
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
                        "'reviewed_at':'2026-08-21T00:00:00Z','valid_until':'2026-11-02T07:00:00Z'});"
                        "denied=False;"
                        "\ntry:\n authorize_ingestion(Adapter(),record,schema_version='0.2.0',"
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
                    schema_version = (
                        "0.2.0" if record_type == "provider_record" else "0.1.0"
                    )
                    record_path = runtime / f"{record_type}.json"
                    record_path.write_text(json.dumps(document), encoding="utf-8")
                    command = [
                        str(executable),
                        "validate-record",
                        "--type",
                        record_type,
                        "--schema-version",
                        schema_version,
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
                        f"valid: {record_type}@{schema_version} (schema+semantics)\n",
                    )


if __name__ == "__main__":
    unittest.main()
