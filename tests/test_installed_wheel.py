from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import venv
from pathlib import Path

from tests.test_distribution_resources import _EXPECTED_SELECTORS
from tests.test_official_provider_adapters import SEC_FIXTURE, WORLD_BANK_PAGE_1
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

            sec_fixture_path = runtime / "sec-fixture.json"
            sec_fixture_path.write_bytes(SEC_FIXTURE)
            world_bank_fixture = json.loads(json.dumps(WORLD_BANK_PAGE_1))
            world_bank_fixture[0]["pages"] = 1
            world_bank_fixture[0]["total"] = 1
            world_bank_fixture_path = runtime / "world-bank-fixture.json"
            world_bank_fixture_path.write_text(
                json.dumps(world_bank_fixture),
                encoding="utf-8",
            )

            manager_payload = json.dumps(manager_record())
            api_probe = subprocess.run(
                [
                    str(python),
                    "-c",
                    (
                        "from openfundscore.resources import list_resources, resolve_resource;"
                        "items=list_resources();"
                        "selectors={(i.key.resource_type.value,i.key.name,i.key.version) for i in items};"
                        f"assert selectors=={set(_EXPECTED_SELECTORS)!r};"
                        "legacy=resolve_resource(resource_type='schema',name='provider_record',version='0.1.0');"
                        "current=resolve_resource(resource_type='schema',name='provider_record',version='0.2.0');"
                        "assert 'macro_observation' not in legacy.load_json()['properties']['entity_type']['enum'];"
                        "assert 'macro_observation' in current.load_json()['properties']['entity_type']['enum'];"
                        "[resolve_resource(resource_type=i.key.resource_type,"
                        "name=i.key.name,version=i.key.version).load_json() for i in items];"
                        "from openfundscore.strategy_mapping import map_strategy_family;"
                        "d=map_strategy_family('market_neutral',mapping_version='0.1.0');"
                        "assert d.peer_bucket=='market_neutral';"
                        "assert d.score_profile=='unrated' and not d.is_rated;"
                        "assert d.unrated_reason=='insufficient_comparable_sample';"
                        "from openfundscore import score_manager_research;"
                        "import json,pathlib;"
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
                        "from datetime import UTC,datetime;"
                        "from openfundscore import SecEdgarSubmissionsAdapter,WorldBankIndicatorsAdapter;"
                        "cutoff=datetime(2026,8,21,12,30,tzinfo=UTC);"
                        "sec=SecEdgarSubmissionsAdapter(user_agent='OpenFundScore security@openfundscore.org')"
                        ".parse_submissions_fixture(pathlib.Path('sec-fixture.json').read_bytes(),"
                        "cik='0000320193',fetched_at=cutoff,evaluation_timestamp=cutoff);"
                        "wb=WorldBankIndicatorsAdapter(countries=frozenset({'US'}))"
                        ".parse_page_fixture(pathlib.Path('world-bank-fixture.json').read_bytes(),"
                        "country='US',indicator='NY.GDP.MKTP.CD',source=2,page=1,per_page=1,"
                        "fetched_at=cutoff,evaluation_timestamp=cutoff);"
                        "assert len(sec)==2 and sec[0]['entity_type']=='issuer';"
                        "assert len(wb)==1 and wb[0]['entity_type']=='macro_observation';"
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

            hostile_probe_path = runtime / "installed-hostile-probe.py"
            hostile_probe_path.write_text(
                textwrap.dedent(
                    """
                    import contextlib
                    import io
                    import json
                    import pathlib
                    import zoneinfo
                    from datetime import UTC, datetime

                    marker = "PRIVATE-TZDB-SENTINEL"

                    def missing_zone(*args, **kwargs):
                        raise zoneinfo.ZoneInfoNotFoundError(marker)

                    zoneinfo.ZoneInfo = missing_zone

                    import openfundscore.official_providers as official
                    from openfundscore.cli import main
                    from openfundscore.official_providers import (
                        FixedHostHttpClient,
                        LocalRateLimiter,
                        ProviderHttpError,
                        SecEdgarSubmissionsAdapter,
                        WorldBankIndicatorsAdapter,
                    )

                    transport_calls = []

                    def zero_transport(request):
                        transport_calls.append(request)
                        raise AssertionError("transport must not run")

                    try:
                        FixedHostHttpClient(
                            host="data.sec.gov",
                            transport=zero_transport,
                            connect_timeout=60.000001,
                        )
                    except ProviderHttpError as exc:
                        assert exc.code == "invalid_client_config"
                    else:
                        raise AssertionError("timeout above 60 seconds accepted")
                    assert transport_calls == []

                    client = FixedHostHttpClient(
                        host="data.sec.gov",
                        transport=zero_transport,
                    )
                    invalid_requests = (
                        {"path": "/safe", "query": {"q": "\\ud800"}, "headers": {}},
                        {"path": "/safe", "query": {}, "headers": {"Accept": "Ā"}},
                        {"path": "/safe", "query": {}, "headers": {"Accept": "x\\x7f"}},
                    )
                    for request in invalid_requests:
                        try:
                            client.get_json(**request)
                        except ProviderHttpError as exc:
                            assert exc.code == "invalid_request"
                        else:
                            raise AssertionError("hostile query/header accepted")
                    assert transport_calls == []

                    world_bank = WorldBankIndicatorsAdapter(
                        countries=frozenset({"US"}),
                        transport=zero_transport,
                    )
                    try:
                        world_bank.fetch_series(
                            country="US",
                            indicator="NY.GDP.MKTP.CD",
                            source=1,
                        )
                    except ProviderHttpError as exc:
                        assert exc.code == "unreviewed_world_bank_source"
                    else:
                        raise AssertionError("unreviewed World Bank source accepted")
                    assert transport_calls == []

                    current = [0.0]
                    sleeps = []

                    def monotonic():
                        return current[0]

                    def sleep(seconds):
                        sleeps.append(seconds)
                        current[0] += seconds

                    injected = LocalRateLimiter(
                        requests_per_second=1,
                        monotonic=monotonic,
                        sleep=sleep,
                    )
                    sec = SecEdgarSubmissionsAdapter(
                        user_agent="OpenFundScore security@openfundscore.org",
                        transport=zero_transport,
                        requests_per_second=1,
                        limiter=injected,
                    )
                    assert sec._limiter is not injected
                    injected.requests_per_second = 10
                    injected._interval = 0.001
                    injected._next_allowed = -100.0
                    sec._limiter.acquire()
                    sec._limiter.acquire()
                    assert sleeps == [1.0]
                    assert sec.get_entitlements(
                        evaluation_timestamp=datetime(2026, 8, 21, tzinfo=UTC)
                    ).rate_limit.requests_per_period == 1

                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        exit_code = main(["resources", "list", "--type", "schema"])
                    assert exit_code == 0
                    assert len(json.loads(stdout.getvalue())) == 7
                    assert marker not in stderr.getvalue()

                    cutoff = datetime(2026, 8, 21, 12, 30, tzinfo=UTC)
                    try:
                        sec.parse_submissions_fixture(
                            pathlib.Path("sec-fixture.json").read_bytes(),
                            cik="0000320193",
                            fetched_at=cutoff,
                            evaluation_timestamp=cutoff,
                        )
                    except ProviderHttpError as exc:
                        assert exc.code == "invalid_sec_payload"
                        assert marker not in str(exc)
                        assert exc.__cause__ is None
                        assert exc.__context__ is None
                    else:
                        raise AssertionError("SEC parse did not fail without timezone data")
                    assert transport_calls == []
                    print("installed-hostile-ok")
                    """
                ).lstrip(),
                encoding="utf-8",
            )
            hostile_probe = subprocess.run(
                [str(python), str(hostile_probe_path)],
                check=False,
                cwd=runtime,
                env=clean_environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                hostile_probe.returncode,
                0,
                msg=(f"stdout={hostile_probe.stdout}\nstderr={hostile_probe.stderr}"),
            )
            self.assertEqual(
                hostile_probe.stdout.strip(),
                "installed-hostile-ok",
            )

            executable = environment / "bin" / "openfundscore"
            fixture_commands = (
                (
                    [
                        str(executable),
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
                        str(sec_fixture_path),
                    ],
                    2,
                    "sec-edgar-submissions",
                ),
                (
                    [
                        str(executable),
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
                        str(world_bank_fixture_path),
                    ],
                    1,
                    "world-bank-indicators-v2",
                ),
            )
            for command, expected_count, provider_id in fixture_commands:
                fixture_probe = subprocess.run(
                    command,
                    check=False,
                    cwd=runtime,
                    env=clean_environment,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(
                    fixture_probe.returncode,
                    0,
                    msg=(
                        f"stdout={fixture_probe.stdout}\nstderr={fixture_probe.stderr}"
                    ),
                )
                fixture_records = json.loads(fixture_probe.stdout)
                self.assertEqual(len(fixture_records), expected_count)
                self.assertTrue(
                    all(
                        record["provider_id"] == provider_id
                        for record in fixture_records
                    )
                )

            list_probe = subprocess.run(
                [str(executable), "resources", "list"],
                check=True,
                cwd=runtime,
                env=clean_environment,
                capture_output=True,
                text=True,
            )
            listed_resources = json.loads(list_probe.stdout)
            self.assertEqual(
                {
                    (item["type"], item["name"], item["version"])
                    for item in listed_resources
                },
                _EXPECTED_SELECTORS,
            )

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
