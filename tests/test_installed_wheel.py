from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
import venv
from pathlib import Path

from tests.test_category_metrics_cli import cli_document, manager_handoff_document
from tests.test_official_provider_adapters import SEC_FIXTURE, WORLD_BANK_PAGE_1
from tests.test_record_validation import (
    external_rating,
    manager_record,
    provider_contract,
    provider_record,
    score_evidence_usage,
)

ROOT = Path(__file__).parents[1]
_EXPECTED_RESOURCE_SELECTORS = frozenset(
    {
        ("metric-catalog", "openfundscore-category-metrics", "0.1.0"),
        ("peer-admission", "category-profile-buckets", "0.1.0"),
        ("schema", "external_rating", "0.1.0"),
        ("schema", "manager_research", "0.1.0"),
        ("schema", "provider_contract", "0.1.0"),
        ("schema", "provider_contract", "0.2.0"),
        ("schema", "provider_record", "0.1.0"),
        ("schema", "provider_record", "0.2.0"),
        ("schema", "score_evidence_usage", "0.1.0"),
        ("schema", "score_evidence_usage", "0.2.0"),
        ("scoring-config", "openfundscore-core", "0.1.0"),
        ("strategy-mapping", "complex_alternatives", "0.1.0"),
    }
)


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

            builder_python = shutil.which("python3")
            self.assertIsNotNone(builder_python)
            clean_environment = os.environ.copy()
            clean_environment.pop("PYTHONPATH", None)
            clean_environment["PYTHONNOUSERSITE"] = "1"
            build_probe = subprocess.run(
                [
                    str(builder_python),
                    "-m",
                    "pip",
                    "wheel",
                    str(source),
                    "--no-index",
                    "--no-deps",
                    "--no-build-isolation",
                    "--wheel-dir",
                    str(wheelhouse),
                ],
                check=False,
                env=clean_environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                build_probe.returncode,
                0,
                msg=(f"stdout={build_probe.stdout}\nstderr={build_probe.stderr}"),
            )
            wheels = tuple(wheelhouse.glob("openfundscore-*.whl"))
            self.assertEqual(len(wheels), 1)

            venv.EnvBuilder(with_pip=True).create(environment)
            python = environment / "bin" / "python"
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

            manager_payload = json.dumps(manager_handoff_document())
            validation_manager_payload = json.dumps(manager_record())
            category_path = runtime / "category-score.json"
            category_document = cli_document()
            category_document["observations"][0].pop("uncertainty")
            category_path.write_text(json.dumps(category_document), encoding="utf-8")
            ledger_v020_path = runtime / "score-evidence-usage-0.2.0.json"
            ledger_v020_path.write_text(
                json.dumps(category_document["evidence_ledger"]), encoding="utf-8"
            )
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
            api_probe = subprocess.run(
                [
                    str(python),
                    "-c",
                    (
                        "from openfundscore.resources import list_resources, resolve_resource;"
                        "items=list_resources();"
                        "selectors={(i.key.resource_type.value,i.key.name,i.key.version)"
                        " for i in items};"
                        f"assert selectors=={_EXPECTED_RESOURCE_SELECTORS!r};"
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
                        "from openfundscore import ManagerResearchHandoff,"
                        "derive_manager_evidence_sources,score_manager_research;"
                        "from datetime import datetime;import json,pathlib;"
                        f"h=json.loads({manager_payload!r});"
                        "dt=lambda v:datetime.fromisoformat(v.replace('Z','+00:00'));"
                        "sources=derive_manager_evidence_sources(h['manager_research'],"
                        "h['fund_strategy_id'],h['sources']);"
                        "handoff=ManagerResearchHandoff(manager_research=h['manager_research'],"
                        "as_of=dt(h['as_of']),fund_strategy_id=h['fund_strategy_id'],"
                        "sources=sources,assertion_status=h['assertion_status']);"
                        "m=score_manager_research(h['manager_research'],"
                        "fund_strategy_id=handoff.fund_strategy_id,sources=handoff.sources,"
                        "assertion_status=handoff.assertion_status);"
                        "assert m['manager_id']=='manager-1';"
                        "assert m['model_version']=='0.1.0';"
                        "assert m['status']=='scored' and m['score']==80.0;"
                        "assert len(m['component_weights'])==8;"
                        "assert m['tenure_attribution']['aggregate_factor']==1.0;"
                        "assert len(m['component_evidence'])==8;"
                        "assert {x['evidence_role'] for x in m['component_evidence']}=={'primary'};"
                        "from openfundscore.validation import validate_record;"
                        f"bad=json.loads({validation_manager_payload!r});"
                        "bad['evidence']=[{'evidence_id':'e-url','tier':'A',"
                        "'source_url':'https://example.com/source',"
                        "'published_at':'2026-08-20T00:00:00Z',"
                        "'fetched_at':'2026-08-21T00:00:00Z',"
                        "'fact_excerpt':'Public professional fact',"
                        f"'supports_components':{['tenure_attributed_performance', 'downside_control', 'cross_cycle_consistency', 'style_discipline', 'career_track_record', 'workload_capacity', 'research_platform_team', 'compliance_integrity']!r}}}];"
                        "urls=('https://example.com/2125550198',"
                        "'https://example.com/212%252D555%252D0198',"
                        "'https://example.com/person%2540example.com');"
                        "apis=(lambda d: score_manager_research(d,"
                        "fund_strategy_id=handoff.fund_strategy_id,sources=handoff.sources,"
                        "assertion_status=handoff.assertion_status),"
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

            category_api_probe = subprocess.run(
                [
                    str(python),
                    "-c",
                    (
                        "import json,pathlib;from datetime import datetime;"
                        "from openfundscore import ApplicabilityContext,"
                        "CaptureDenominatorAudit,CaptureDenominatorStatus,"
                        "ManagerResearchHandoff,MetricObservation,MetricState,PeerObservation,"
                        "derive_manager_evidence_sources,"
                        "score_category_metrics;"
                        "d=json.loads(pathlib.Path('category-score.json').read_text());"
                        "dt=lambda v:datetime.fromisoformat(v.replace('Z','+00:00'));"
                        "cd=lambda v:None if v is None else CaptureDenominatorAudit("
                        "denominator_status=CaptureDenominatorStatus(v['denominator_status']),"
                        "benchmark_downside_sample_count=v['benchmark_downside_sample_count'],"
                        "evidence_id=v['evidence_id'],lineage_id=v['lineage_id'],"
                        "series_id=v['series_id']);"
                        "obs=tuple(MetricObservation(metric_id=o['metric_id'],"
                        "state=MetricState(o['state']),raw_value=o['raw_value'],"
                        "fund_id=o['fund_id'],series_id=o['series_id'],"
                        "evidence_id=o['evidence_id'],lineage_id=o['lineage_id'],"
                        "as_of=dt(o['as_of']),published_at=dt(o['published_at']),"
                        "evaluation_timestamp=dt(o['evaluation_timestamp']),"
                        "sample_size=o['sample_size'],window_months=o['window_months'],"
                        "uncertainty=o.get('uncertainty'),"
                        "capture_denominator=cd(o['capture_denominator']))"
                        " for o in d['observations']);"
                        "ps=tuple(PeerObservation(**{**p,"
                        "'as_of':dt(p['as_of']),'published_at':dt(p['published_at']),"
                        "'evaluation_timestamp':dt(p['evaluation_timestamp']),"
                        "'capture_denominator':cd(p['capture_denominator'])})"
                        " for p in d['peers']);"
                        "h=d['manager_handoff'];"
                        "mh=ManagerResearchHandoff(manager_research=h['manager_research'],"
                        "as_of=dt(h['as_of']),fund_strategy_id=h['fund_strategy_id'],"
                        "sources=derive_manager_evidence_sources(h['manager_research'],"
                        "h['fund_strategy_id'],h['sources']),"
                        "assertion_status=h['assertion_status']);"
                        "r=score_category_metrics(profile_id=d['profile_id'],"
                        "peer_bucket=d['peer_bucket'],"
                        "peer_bucket_version=d['peer_bucket_version'],"
                        "history_months=d['history_months'],"
                        "adequate_regime_coverage=d['adequate_regime_coverage'],"
                        "applicability_context=ApplicabilityContext(**d['applicability_context']),"
                        "observations=obs,peers=ps,manager_handoff=mh,"
                        "evidence_ledger=d['evidence_ledger'],"
                        "config_version=d['config_version'],"
                        "metric_catalog_version=d['metric_catalog_version'],"
                        "final_precision=d['final_precision']);"
                        "assert r.open_score==57.2 and r.catalog_version=='0.1.0';"
                        "assert r.evidence_ledger_record_id==d['evidence_ledger']['score_record_id'];"
                        "assert len(r.evidence_ledger_sha256)==64;"
                        "assert r.manager_audit.manager_id=='manager-1';"
                        "assert len(r.manager_audit.component_evidence)==8;"
                        "assert r.manager_audit.manager_input_assertion_status=='caller_provided';"
                        "assert all(len(x.source_facts_sha256)==64"
                        " for x in r.manager_audit.component_evidence);"
                        "assert {x.evidence_role for x in r.manager_audit.component_evidence}=={'primary'};"
                        "assert len(r.peer_sets)==12 and len(r.peer_sets[0].records)==5;"
                        "assert all(x.window_start and x.window_end and len(x.snapshot_hash)==64"
                        " and len(x.document_hash)==64 for s in r.peer_sets for x in s.records);"
                        "den=[x for x in d['evidence_ledger']['usage']"
                        " if x['evidence_role']=='capture_denominator'];"
                        "assert len(den)==1 and den[0]['target_component']=='fund_d2_downside_risk';"
                        "assert all(x['evidence_role']=='primary' for x in d['evidence_ledger']['usage']"
                        " if x['target_component'].startswith('manager_'));"
                        "assert any(m.applicability=='requires_declared_benchmark' for m in r.metrics);"
                        "assert r.not_applicable_metric_ids==();"
                        "print('category-api-ok')"
                    ),
                ],
                check=False,
                cwd=runtime,
                env=clean_environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                category_api_probe.returncode,
                0,
                msg=(
                    f"stdout={category_api_probe.stdout}\n"
                    f"stderr={category_api_probe.stderr}"
                ),
            )
            self.assertEqual(category_api_probe.stdout.strip(), "category-api-ok")

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
                    assert len(json.loads(stdout.getvalue())) == 8
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
                _EXPECTED_RESOURCE_SELECTORS,
            )

            category_cli_probe = subprocess.run(
                [str(executable), "category-score", str(category_path)],
                check=False,
                cwd=runtime,
                env=clean_environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                category_cli_probe.returncode,
                0,
                msg=(
                    f"stdout={category_cli_probe.stdout}\n"
                    f"stderr={category_cli_probe.stderr}"
                ),
            )
            self.assertEqual(
                json.loads(category_cli_probe.stdout)["open_score"],
                57.2,
            )
            category_output = json.loads(category_cli_probe.stdout)
            self.assertEqual(category_output["manager_audit"]["status"], "scored")
            self.assertEqual(len(category_output["peer_sets"][0]["records"]), 5)

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
                        "ledger=json.loads(pathlib.Path("
                        "'score-evidence-usage-0.2.0.json').read_text());"
                        "validate_record('score_evidence_usage',ledger,"
                        "schema_version='0.2.0');"
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

            ledger_v020_cli_probe = subprocess.run(
                [
                    str(executable),
                    "validate-record",
                    "--type",
                    "score_evidence_usage",
                    "--schema-version",
                    "0.2.0",
                    str(ledger_v020_path),
                ],
                check=False,
                cwd=runtime,
                env=clean_environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                ledger_v020_cli_probe.returncode,
                0,
                msg=(
                    f"stdout={ledger_v020_cli_probe.stdout}\n"
                    f"stderr={ledger_v020_cli_probe.stderr}"
                ),
            )
            self.assertEqual(
                ledger_v020_cli_probe.stdout,
                "valid: score_evidence_usage@0.2.0 (schema+semantics)\n",
            )


if __name__ == "__main__":
    unittest.main()
