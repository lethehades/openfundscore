from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from unittest.mock import patch

from openfundscore.cli import main
from openfundscore.mainland_official import (
    MainlandOfficialSnapshotAdapter,
    SnapshotValidationError,
)
from openfundscore.provider_sdk import (
    AuthenticationMode,
    ProviderCapability,
    ProviderEntitlements,
    RateLimit,
    RightsMode,
    SourceType,
)
from openfundscore.resources import resolve_resource

EVALUATION = datetime(2026, 8, 21, tzinfo=UTC)
HASH = "sha256:" + "a" * 64
SOURCE = "https://www.csrc.gov.cn/synthetic/disclosure.json"
TERMS = "https://www.csrc.gov.cn/synthetic/terms"


class MutableEntitlementTimezone(tzinfo):
    def __init__(self) -> None:
        self.explode = False
        self.interrupt = False
        self.calls = 0

    def utcoffset(self, dt):
        self.calls += 1
        if self.interrupt:
            raise KeyboardInterrupt
        if self.explode:
            raise RuntimeError("PRIVATE-ENTITLEMENT-TZ-MARKER")
        return timedelta(hours=8)

    def dst(self, dt):
        return timedelta(0)

    def tzname(self, dt):
        return "mutable-entitlement-timezone"


class NonFiniteEntitlementTimezone(tzinfo):
    def utcoffset(self, dt):  # type: ignore[override]
        return float("nan")

    def dst(self, dt):
        return None


class DatetimeSubclass(datetime):
    pass


def entitlement() -> ProviderEntitlements:
    return ProviderEntitlements(
        provider_id="mainland-official-pilot",
        evaluated_at=EVALUATION,
        valid_until=datetime(2026, 9, 1, tzinfo=UTC),
        source_type=SourceType.REGULATOR,
        jurisdictions=frozenset({"CN"}),
        authentication_mode=AuthenticationMode.LOCAL_ENTITLEMENT,
        capabilities=frozenset(
            {
                ProviderCapability.GET_ENTITLEMENTS,
                ProviderCapability.GET_PROFILE,
                ProviderCapability.GET_NAV_SERIES,
                ProviderCapability.GET_DISCLOSURES,
                ProviderCapability.GET_MANAGER_TENURES,
                ProviderCapability.GET_BENCHMARK,
                ProviderCapability.GET_HOLDINGS,
                ProviderCapability.GET_CORPORATE_ACTIONS,
            }
        ),
        rights_mode=RightsMode.LOCAL_ENTITLEMENT,
        cache_allowed=True,
        cache_ttl_seconds=86400,
        derived_works_allowed=True,
        public_display_allowed=False,
        redistribution_allowed=False,
        retention_days=30,
        attribution_required=True,
        terms_url=TERMS,
        rights_reviewed_at=datetime(2026, 8, 20, tzinfo=UTC),
        rate_limit=RateLimit(requests_per_period=1000, period_seconds=86400),
    )


def observation(
    observation_id: str,
    field: str,
    raw_value: object,
    *,
    as_of: str = "2026-08-15T00:00:00Z",
    published_at: str = "2026-08-16T00:00:00Z",
    unit: str | None = None,
    currency: str | None = None,
    quality_state: str = "verified",
    conflict_group: str | None = None,
) -> dict[str, object]:
    return {
        "observation_id": observation_id,
        "field": field,
        "raw_value": raw_value,
        "as_of": as_of,
        "published_at": published_at,
        "fetched_at": "2026-08-17T00:00:00Z",
        "valid_from": as_of,
        "valid_to": None,
        "currency": currency,
        "unit": unit,
        "source_url": SOURCE,
        "source_document_hash": HASH,
        "point_in_time_status": "verified",
        "methodology": None,
        "quality_state": quality_state,
        "conflict_group": conflict_group,
    }


def item(
    item_id: str,
    item_type: str,
    entity_type: str,
    entity_id: str,
    observations: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "item_id": item_id,
        "item_type": item_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "exact_identifiers": [
            {
                "scheme": "official_entity_id",
                "value": f"official:{entity_id}",
                "jurisdiction": "CN",
            }
        ],
        "observations": observations,
    }


def bundle() -> dict[str, object]:
    rights = {
        "mode": "local_entitlement",
        "terms_url": TERMS,
        "reviewed_at": "2026-08-20T00:00:00Z",
        "valid_until": "2026-09-01T00:00:00Z",
        "cache_allowed": True,
        "derived_works_allowed": True,
        "redistribution_allowed": False,
        "attribution_required": True,
        "public_display_allowed": False,
        "retention_days": 30,
        "source_evidence_url": TERMS,
    }
    return {
        "schema_version": "0.1.0",
        "provider_id": "mainland-official-pilot",
        "snapshot_id": "synthetic-snapshot-2026-08-17",
        "source_type": "regulator",
        "jurisdiction": "CN",
        "official_source_url": SOURCE,
        "retrieved_at": "2026-08-17T00:00:00Z",
        "published_at": "2026-08-16T00:00:00Z",
        "as_of": "2026-08-15T00:00:00Z",
        "effective_at": "2026-08-15T00:00:00Z",
        "document_sha256": HASH,
        "timezone": "Asia/Shanghai",
        "currency": "CNY",
        "units": {"nav": "CNY_per_share", "weight": "bps", "coverage": "bps"},
        "rights": rights,
        "items": [
            item(
                "01-identity-a",
                "identity",
                "share_class",
                "share-a",
                [
                    observation("id-a-name", "canonical_name", "合成基金A"),
                    observation("id-a-class", "class_code", "A"),
                ],
            ),
            item(
                "02-nav-a",
                "nav",
                "share_class",
                "share-a",
                [
                    observation(
                        "nav-a-1",
                        "nav",
                        1.0,
                        as_of="2026-08-14T00:00:00Z",
                        currency="CNY",
                        unit="CNY_per_share",
                    ),
                    observation(
                        "nav-a-2",
                        "nav",
                        1.01,
                        currency="CNY",
                        unit="CNY_per_share",
                    ),
                ],
            ),
            item(
                "03-report",
                "report",
                "report",
                "report-2026q2",
                [
                    observation("report-url", "report_url", SOURCE),
                    observation("report-hash", "report_document_hash", HASH),
                ],
            ),
            item(
                "04-manager-tenure",
                "manager_tenure",
                "manager_tenure",
                "tenure-1",
                [
                    observation("tenure-manager", "manager_id", "manager-1"),
                    observation("tenure-fund", "fund_strategy_id", "strategy-1"),
                    observation("tenure-start", "tenure_start", "2024-01-01"),
                    observation("tenure-end", "tenure_end", None),
                ],
            ),
            item(
                "05-benchmark",
                "benchmark",
                "benchmark",
                "benchmark-1",
                [observation("benchmark-name", "canonical_name", "合成基准")],
            ),
            item(
                "06-holding",
                "holding",
                "holding",
                "holding-1",
                [
                    observation("holding-fund", "fund_strategy_id", "strategy-1"),
                    observation("holding-instrument", "instrument_id", "CN-SYN-1"),
                    observation("holding-weight", "weight", 6000, unit="bps"),
                    observation("holding-coverage", "coverage", 8000, unit="bps"),
                ],
            ),
            item(
                "07-action",
                "corporate_action",
                "corporate_action",
                "action-transform-1",
                [
                    observation("action-type", "action_type", "transformed"),
                    observation(
                        "action-effective",
                        "effective_at",
                        "2026-08-15T00:00:00Z",
                    ),
                    observation("action-before", "before_id", "strategy-old"),
                    observation("action-after", "after_id", "strategy-1"),
                ],
            ),
        ],
    }


def entitlement_document() -> dict[str, object]:
    value = entitlement()
    return {
        "schema_version": "0.1.0",
        "provider_id": value.provider_id,
        "evaluated_at": "2026-08-21T00:00:00Z",
        "valid_until": "2026-09-01T08:00:00+08:00",
        "source_type": "regulator",
        "jurisdictions": ["CN"],
        "authentication_mode": "local_entitlement",
        "capabilities": sorted(capability.value for capability in value.capabilities),
        "rights": {
            "mode": value.rights_mode.value,
            "cache_allowed": value.cache_allowed,
            "cache_ttl_seconds": value.cache_ttl_seconds,
            "derived_works_allowed": value.derived_works_allowed,
            "public_display_allowed": value.public_display_allowed,
            "redistribution_allowed": value.redistribution_allowed,
            "retention_days": value.retention_days,
            "attribution_required": value.attribution_required,
            "terms_url": value.terms_url,
            "reviewed_at": "2026-08-20T08:00:00+08:00",
        },
        "rate_limit": {
            "requests_per_period": value.rate_limit.requests_per_period,
            "period_seconds": value.rate_limit.period_seconds,
            "burst": value.rate_limit.burst,
        },
    }


class MainlandOfficialSnapshotTests(unittest.TestCase):
    def adapter(self) -> MainlandOfficialSnapshotAdapter:
        return MainlandOfficialSnapshotAdapter(entitlements=entitlement())

    def test_versioned_schema_and_all_seven_item_types_map_to_auditable_records(
        self,
    ) -> None:
        schema = resolve_resource(
            resource_type="schema",
            name="mainland_official_snapshot",
            version="0.1.0",
        ).load_json()
        self.assertFalse(schema["additionalProperties"])

        source = bundle()
        before = deepcopy(source)
        records = self.adapter().parse(source, evaluation_timestamp=EVALUATION)

        self.assertEqual(source, before)
        self.assertEqual(
            {record["entity_type"] for record in records},
            {
                "share_class",
                "report",
                "manager_tenure",
                "benchmark",
                "holding",
                "corporate_action",
            },
        )
        self.assertEqual(len(records), 19)
        nav = [record for record in records if record["field"] == "nav"]
        self.assertEqual([record["value"] for record in nav], [1.0, 1.01])
        self.assertTrue(all(record["entity_id"] == "share-a" for record in nav))
        for record in records:
            self.assertEqual(record["namespace"], "canonical_observation")
            self.assertEqual(record["source_type"], "regulator")
            self.assertEqual(record["jurisdiction"], "CN")
            self.assertIn("source_document_hash", record)
            self.assertIn("rights", record)
            self.assertEqual(record["exact_identifiers"][0]["jurisdiction"], "CN")

    def test_schema_enforces_ascii_extended_date_shape_without_format_checker(
        self,
    ) -> None:
        from jsonschema import Draft202012Validator

        schema = resolve_resource(
            resource_type="schema",
            name="mainland_official_snapshot",
            version="0.1.0",
        ).load_json()
        validator = Draft202012Validator(schema)
        invalid_dates = (
            "20240101",
            "2024-W01-1",
            "2024-01-01T00:00:00Z",
            "２０２４-０１-０１",
        )
        for field_index in (2, 3):
            for invalid_date in invalid_dates:
                document = bundle()
                document["items"][3]["observations"][field_index][  # type: ignore[index]
                    "raw_value"
                ] = invalid_date

                with self.subTest(field_index=field_index, invalid_date=invalid_date):
                    self.assertTrue(tuple(validator.iter_errors(document)))

    def test_tenure_semantics_enforce_ascii_calendar_dates_without_format_checker(
        self,
    ) -> None:
        invalid_dates = (
            "20240101",
            "2024-W01-1",
            "2024-01-01T00:00:00Z",
            "２０２４-０１-０１",
            "2023-02-29",
        )
        with patch.object(
            MainlandOfficialSnapshotAdapter, "_validate_schema", return_value=None
        ):
            for field_index in (2, 3):
                for invalid_date in invalid_dates:
                    document = bundle()
                    document["items"][3]["observations"][field_index][  # type: ignore[index]
                        "raw_value"
                    ] = invalid_date

                    with self.subTest(
                        field_index=field_index, invalid_date=invalid_date
                    ):
                        with self.assertRaises(SnapshotValidationError) as raised:
                            self.adapter().parse(
                                document, evaluation_timestamp=EVALUATION
                            )
                        self.assertEqual(raised.exception.code, "invalid_item")
                        self.assertNotIn(invalid_date, str(raised.exception))

            for field_index in (2, 3):
                document = bundle()
                document["items"][3]["observations"][field_index][  # type: ignore[index]
                    "raw_value"
                ] = "2024-02-29"
                records = self.adapter().parse(
                    document, evaluation_timestamp=EVALUATION
                )
                self.assertTrue(
                    any(record["value"] == "2024-02-29" for record in records)
                )

    def test_api_rejects_invalid_tenure_dates_with_stable_redacted_errors(
        self,
    ) -> None:
        cases = (
            ("20240101", "snapshot_schema"),
            ("2024-W01-1", "snapshot_schema"),
            ("2024-01-01T00:00:00Z", "snapshot_schema"),
            ("２０２４-０１-０１", "snapshot_schema"),
            ("2023-02-29", "invalid_item"),
        )
        for field_index in (2, 3):
            for invalid_date, code in cases:
                document = bundle()
                document["items"][3]["observations"][field_index][  # type: ignore[index]
                    "raw_value"
                ] = invalid_date

                with self.subTest(field_index=field_index, invalid_date=invalid_date):
                    with self.assertRaises(SnapshotValidationError) as raised:
                        self.adapter().parse(document, evaluation_timestamp=EVALUATION)
                    self.assertEqual(raised.exception.code, code)
                    self.assertNotIn(invalid_date, str(raised.exception))
                    self.assertIsNone(raised.exception.__cause__)
                    self.assertIsNone(raised.exception.__context__)

        leap = bundle()
        leap["items"][3]["observations"][2]["raw_value"] = "2024-02-29"  # type: ignore[index]
        leap["items"][3]["observations"][3]["raw_value"] = "2024-02-29"  # type: ignore[index]
        records = self.adapter().parse(leap, evaluation_timestamp=EVALUATION)
        self.assertEqual(
            sum(record["value"] == "2024-02-29" for record in records),
            2,
        )

    def test_provider_record_version_is_immutable_and_adapter_uses_new_contract(
        self,
    ) -> None:
        import hashlib

        legacy = resolve_resource(
            resource_type="schema", name="provider_record", version="0.1.0"
        )
        published = resolve_resource(
            resource_type="schema", name="provider_record", version="0.2.0"
        )
        current = resolve_resource(
            resource_type="schema", name="provider_record", version="0.3.0"
        )
        self.assertEqual(
            hashlib.sha256(legacy.read_bytes()).hexdigest(),
            "baf590e637dc0e0bdf01eddf9d51ccbe5e9d3c16057910a9cf7b9b58ccec65bf",
        )
        self.assertEqual(
            hashlib.sha256(published.read_bytes()).hexdigest(),
            "36a25071c7622a6252a51c559c3adae49855a3b2e1bf954ce62c5a8b71c47f5f",
        )
        self.assertNotEqual(published.read_bytes(), current.read_bytes())
        current_schema = current.load_json()
        self.assertIn("exact_identifiers", current_schema["required"])
        self.assertIn(
            "valid_until", current_schema["properties"]["rights"]["properties"]
        )
        self.assertNotIn(
            "valid_until", current_schema["properties"]["rights"]["required"]
        )
        records = self.adapter().parse(bundle(), evaluation_timestamp=EVALUATION)
        self.assertTrue(all("exact_identifiers" in record for record in records))
        self.assertTrue(
            all(
                record["rights"]["valid_until"] == "2026-09-01T00:00:00Z"  # type: ignore[index]
                for record in records
            )
        )

    def test_provider_record_valid_until_uses_strict_rfc3339_profile(self) -> None:
        from openfundscore.validation import RecordValidationError, validate_record

        record = self.adapter().parse(bundle(), evaluation_timestamp=EVALUATION)[0]
        record["rights"]["valid_until"] = "2026-09-01t00:00:00z"  # type: ignore[index]

        with self.assertRaises(RecordValidationError) as raised:
            validate_record(
                "provider_record",
                record,
                schema_version="0.3.0",
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )

        self.assertEqual(raised.exception.path, "$.rights.valid_until")

    def test_exact_identifier_tuple_resolves_independently_from_canonical_entity_id(
        self,
    ) -> None:
        document = bundle()
        document["items"][0]["exact_identifiers"].append(  # type: ignore[index]
            {
                "scheme": "cn_fund_code",
                "value": "000001",
                "jurisdiction": "CN",
            }
        )
        records = self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        identity = [
            record
            for record in records
            if record["provider_record_id"].startswith(
                f"{document['snapshot_id']}:01-identity-a:"
            )
        ]
        self.assertTrue(identity)
        self.assertTrue(all(record["entity_id"] == "share-a" for record in identity))
        self.assertTrue(
            all(
                record["exact_identifiers"]
                == [
                    {
                        "scheme": "official_entity_id",
                        "value": "official:share-a",
                        "jurisdiction": "CN",
                    },
                    {
                        "scheme": "cn_fund_code",
                        "value": "000001",
                        "jurisdiction": "CN",
                    },
                ]
                for record in identity
            )
        )

    def test_exact_identifier_binds_full_canonical_identity_in_api_and_cli(
        self,
    ) -> None:
        import io
        from contextlib import redirect_stderr, redirect_stdout

        marker = "PRIVATE-EXACT-IDENTIFIER-MARKER"
        document = bundle()
        first_identity = document["items"][0]  # type: ignore[index]
        benchmark = document["items"][4]  # type: ignore[index]
        benchmark["entity_id"] = first_identity["entity_id"]
        benchmark["exact_identifiers"] = [
            {
                "scheme": "official_entity_id",
                "value": marker,
                "jurisdiction": "CN",
            }
        ]
        first_identity["exact_identifiers"] = deepcopy(benchmark["exact_identifiers"])

        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "identifier_resolution_conflict")
        self.assertEqual(raised.exception.path, "$.items.exact_identifiers")
        self.assertNotIn(marker, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            snapshot_path = root / "snapshot.json"
            entitlement_path = root / "entitlements.json"
            snapshot_path.write_text(
                json.dumps(document, ensure_ascii=False), encoding="utf-8"
            )
            entitlement_path.write_text(
                json.dumps(entitlement_document()), encoding="utf-8"
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(
                    [
                        "provider",
                        "mainland-parse",
                        str(snapshot_path),
                        "--entitlements",
                        str(entitlement_path),
                        "--evaluation-timestamp",
                        "2026-08-21T00:00:00Z",
                    ]
                )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(len(stderr.getvalue().splitlines()), 1)
        self.assertIn("identifier_resolution_conflict", stderr.getvalue())
        self.assertNotIn(marker, stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_synthetic_identifier_scheme_is_absent_from_public_contract(self) -> None:
        schema = resolve_resource(
            resource_type="schema",
            name="mainland_official_snapshot",
            version="0.1.0",
        ).load_json()
        schemes = schema["$defs"]["identifier"]["properties"]["scheme"]["enum"]
        self.assertNotIn("synthetic_official_id", schemes)

        document = bundle()
        document["items"][0]["exact_identifiers"][0]["scheme"] = (  # type: ignore[index]
            "synthetic_official_id"
        )
        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "snapshot_schema")

    def test_bytes_and_path_are_strict_utf8_json_and_mapping_is_deep_copied(
        self,
    ) -> None:
        payload = json.dumps(bundle(), ensure_ascii=False).encode("utf-8")
        expected = self.adapter().parse(payload, evaluation_timestamp=EVALUATION)
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "synthetic.json"
            path.write_bytes(payload)
            self.assertEqual(
                self.adapter().parse(path, evaluation_timestamp=EVALUATION),
                expected,
            )

        hostile = bundle()
        records = self.adapter().parse(hostile, evaluation_timestamp=EVALUATION)
        hostile["items"][0]["observations"][0]["raw_value"] = "mutated"  # type: ignore[index]
        self.assertEqual(records[0]["value"], "合成基金A")

    def test_errors_are_stable_and_redact_paths_payloads_and_personal_markers(
        self,
    ) -> None:
        marker = "PRIVATE-PERSON-MARKER"
        cases: list[object] = [
            b"\xff" + marker.encode(),
            json.dumps({"marker": marker, "items": []}).encode(),
            Path("/private/" + marker + ".json"),
        ]
        for source in cases:
            with self.subTest(source_type=type(source).__name__):
                with self.assertRaises(SnapshotValidationError) as raised:
                    self.adapter().parse(source, evaluation_timestamp=EVALUATION)
                self.assertNotIn(marker, str(raised.exception))
                self.assertNotIn("/private/", str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)

    def test_official_host_policy_rejects_sales_platforms_and_network_style_urls(
        self,
    ) -> None:
        blocked = (
            "http://www.csrc.gov.cn/file",
            "https://user@www.csrc.gov.cn/file",
            "https://www.csrc.gov.cn/file#fragment",
            "https://127.0.0.1/file",
            "https://localhost/file",
            "https://fund.eastmoney.com/file",
            "https://csrc.gov.cn.evil.example/file",
        )
        for url in blocked:
            document = bundle()
            document["official_source_url"] = url
            with (
                self.subTest(url=url),
                self.assertRaises(SnapshotValidationError) as raised,
            ):
                self.adapter().parse(document, evaluation_timestamp=EVALUATION)
            self.assertEqual(raised.exception.code, "unapproved_source")
            self.assertNotIn(url, str(raised.exception))

        sales = bundle()
        sales["source_type"] = "distribution_platform"
        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(sales, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "snapshot_schema")

        rating = bundle()
        rating["items"][0]["item_type"] = "external_rating"  # type: ignore[index]
        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(rating, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "snapshot_schema")

    def test_exchange_defaults_and_fund_company_exact_host_evidence_are_enforced(
        self,
    ) -> None:
        exchange_entitlement = replace(
            entitlement(),
            source_type=SourceType.EXCHANGE,
            terms_url="https://www.sse.com.cn/synthetic/terms",
        )
        exchange = bundle()
        exchange["source_type"] = "exchange"
        exchange["official_source_url"] = "https://www.sse.com.cn/synthetic/file"
        exchange["rights"]["terms_url"] = exchange_entitlement.terms_url  # type: ignore[index]
        exchange["rights"]["source_evidence_url"] = exchange_entitlement.terms_url  # type: ignore[index]
        for disclosure_item in exchange["items"]:  # type: ignore[union-attr]
            for field in disclosure_item["observations"]:
                field["source_url"] = "https://www.sse.com.cn/synthetic/file"
                if field["field"] == "report_url":
                    field["raw_value"] = "https://www.sse.com.cn/synthetic/report"
        records = MainlandOfficialSnapshotAdapter(
            entitlements=exchange_entitlement
        ).parse(exchange, evaluation_timestamp=EVALUATION)
        self.assertEqual(records[0]["source_type"], "exchange")

        fund_host = "fund.synthetic.example"
        evidence = f"https://{fund_host}/terms-review"
        fund_entitlement = replace(
            entitlement(),
            source_type=SourceType.FUND_COMPANY_OR_MANAGER,
            terms_url=evidence,
        )
        fund = bundle()
        fund["source_type"] = "fund_company"
        fund["official_source_url"] = f"https://{fund_host}/snapshot"
        fund["rights"]["terms_url"] = evidence  # type: ignore[index]
        fund["rights"]["source_evidence_url"] = evidence  # type: ignore[index]
        for disclosure_item in fund["items"]:  # type: ignore[union-attr]
            for field in disclosure_item["observations"]:
                field["source_url"] = f"https://{fund_host}/disclosure"
                if field["field"] == "report_url":
                    field["raw_value"] = f"https://{fund_host}/report"

        with self.assertRaises(SnapshotValidationError):
            MainlandOfficialSnapshotAdapter(entitlements=fund_entitlement).parse(
                fund, evaluation_timestamp=EVALUATION
            )
        adapter = MainlandOfficialSnapshotAdapter(
            entitlements=fund_entitlement,
            fund_company_hosts={fund_host: evidence},
        )
        self.assertEqual(len(adapter.parse(fund, evaluation_timestamp=EVALUATION)), 19)

        subdomain = deepcopy(fund)
        subdomain["official_source_url"] = f"https://sub.{fund_host}/snapshot"
        with self.assertRaises(SnapshotValidationError) as raised:
            adapter.parse(subdomain, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "unapproved_source")

    def test_fund_company_bundle_is_bound_to_one_exact_root_host(self) -> None:
        root_host = "fund-a.synthetic.example"
        other_host = "fund-b.synthetic.example"
        root_evidence = f"https://{root_host}/terms-review"
        other_evidence = f"https://{other_host}/terms-review"
        fund_entitlement = replace(
            entitlement(),
            source_type=SourceType.FUND_COMPANY_OR_MANAGER,
            terms_url=root_evidence,
        )
        adapter = MainlandOfficialSnapshotAdapter(
            entitlements=fund_entitlement,
            fund_company_hosts={
                root_host: root_evidence,
                other_host: other_evidence,
            },
        )

        fund = bundle()
        fund["source_type"] = "fund_company"
        fund["official_source_url"] = f"https://{root_host}/snapshot"
        fund["rights"]["terms_url"] = root_evidence  # type: ignore[index]
        fund["rights"]["source_evidence_url"] = root_evidence  # type: ignore[index]
        for disclosure_item in fund["items"]:  # type: ignore[union-attr]
            for field in disclosure_item["observations"]:
                field["source_url"] = f"https://{root_host}/snapshot"
                if field["field"] == "report_url":
                    field["raw_value"] = f"https://{root_host}/report"
        self.assertEqual(len(adapter.parse(fund, evaluation_timestamp=EVALUATION)), 19)

        for target in ("observation", "report"):
            cross_host = deepcopy(fund)
            if target == "observation":
                cross_host["items"][0]["observations"][0]["source_url"] = (  # type: ignore[index]
                    f"https://{other_host}/snapshot"
                )
            else:
                cross_host["items"][2]["observations"][0]["raw_value"] = (  # type: ignore[index]
                    f"https://{other_host}/report"
                )
            with (
                self.subTest(target=target),
                self.assertRaises(SnapshotValidationError) as raised,
            ):
                adapter.parse(cross_host, evaluation_timestamp=EVALUATION)
            self.assertEqual(raised.exception.code, "unapproved_source")

    def test_normalized_duplicate_fund_host_approvals_fail_closed(self) -> None:
        evidence = "https://fund.synthetic.example/terms"
        with self.assertRaises(SnapshotValidationError) as raised:
            MainlandOfficialSnapshotAdapter(
                entitlements=entitlement(),
                fund_company_hosts={
                    "Fund.Synthetic.Example": evidence,
                    "fund.synthetic.example": evidence,
                },
            )
        self.assertEqual(raised.exception.code, "invalid_host_approval")

    def test_adapter_rebuilds_entitlements_and_does_not_retain_caller_state(
        self,
    ) -> None:
        supplied = entitlement()
        adapter = MainlandOfficialSnapshotAdapter(entitlements=supplied)
        object.__setattr__(supplied, "rights_mode", "mutated")
        object.__setattr__(supplied, "capabilities", frozenset())
        self.assertEqual(
            len(adapter.parse(bundle(), evaluation_timestamp=EVALUATION)), 19
        )

        malformed = entitlement()
        object.__setattr__(malformed, "rights_mode", "mutated")
        with self.assertRaises(SnapshotValidationError) as raised:
            MainlandOfficialSnapshotAdapter(entitlements=malformed)
        self.assertEqual(raised.exception.code, "invalid_entitlements")
        self.assertIsNone(raised.exception.__context__)

    def test_adapter_freezes_entitlement_datetimes_before_caller_tzinfo_mutation(
        self,
    ) -> None:
        timezone_state = MutableEntitlementTimezone()
        supplied = replace(
            entitlement(),
            evaluated_at=datetime(2026, 8, 21, 8, tzinfo=timezone_state),
            valid_until=datetime(2026, 9, 1, 8, tzinfo=timezone_state),
            rights_reviewed_at=datetime(2026, 8, 20, 8, tzinfo=timezone_state),
        )
        adapter = MainlandOfficialSnapshotAdapter(entitlements=supplied)
        calls_after_construction = timezone_state.calls
        timezone_state.explode = True

        records = adapter.parse(bundle(), evaluation_timestamp=EVALUATION)
        frozen = adapter.get_entitlements(evaluation_timestamp=EVALUATION)

        self.assertEqual(len(records), 19)
        self.assertEqual(timezone_state.calls, calls_after_construction)
        for field in ("evaluated_at", "valid_until", "rights_reviewed_at"):
            timestamp = getattr(frozen, field)
            self.assertIs(type(timestamp), datetime)
            self.assertIs(timestamp.tzinfo, UTC)

    def test_entitlement_datetime_subclasses_are_rebuilt_as_builtin_utc_values(
        self,
    ) -> None:
        supplied = replace(
            entitlement(),
            evaluated_at=DatetimeSubclass(2026, 8, 21, tzinfo=UTC),
            valid_until=DatetimeSubclass(2026, 9, 1, tzinfo=UTC),
            rights_reviewed_at=DatetimeSubclass(2026, 8, 20, tzinfo=UTC),
        )

        frozen = MainlandOfficialSnapshotAdapter(
            entitlements=supplied
        ).get_entitlements(evaluation_timestamp=EVALUATION)

        for field in ("evaluated_at", "valid_until", "rights_reviewed_at"):
            timestamp = getattr(frozen, field)
            self.assertIs(type(timestamp), datetime)
            self.assertIs(timestamp.tzinfo, UTC)

    def test_hostile_entitlement_datetime_failure_is_stable_and_redacted(self) -> None:
        timezone_state = MutableEntitlementTimezone()
        supplied = replace(
            entitlement(),
            evaluated_at=datetime(2026, 8, 21, 8, tzinfo=timezone_state),
            valid_until=datetime(2026, 9, 1, 8, tzinfo=timezone_state),
            rights_reviewed_at=datetime(2026, 8, 20, 8, tzinfo=timezone_state),
        )
        timezone_state.explode = True

        with self.assertRaises(SnapshotValidationError) as raised:
            MainlandOfficialSnapshotAdapter(entitlements=supplied)

        self.assertEqual(raised.exception.code, "invalid_entitlements")
        self.assertEqual(raised.exception.path, "$")
        self.assertNotIn("PRIVATE-ENTITLEMENT-TZ-MARKER", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_entitlement_datetime_base_exceptions_propagate(self) -> None:
        timezone_state = MutableEntitlementTimezone()
        supplied = replace(
            entitlement(),
            evaluated_at=datetime(2026, 8, 21, 8, tzinfo=timezone_state),
            valid_until=datetime(2026, 9, 1, 8, tzinfo=timezone_state),
            rights_reviewed_at=datetime(2026, 8, 20, 8, tzinfo=timezone_state),
        )
        timezone_state.interrupt = True

        with self.assertRaises(KeyboardInterrupt):
            MainlandOfficialSnapshotAdapter(entitlements=supplied)

    def test_entitlement_datetime_type_and_utc_range_fail_closed(self) -> None:
        invalid_type = entitlement()
        object.__setattr__(invalid_type, "evaluated_at", "2026-08-21T00:00:00Z")
        out_of_range = entitlement()
        object.__setattr__(
            out_of_range,
            "evaluated_at",
            datetime(1, 1, 1, tzinfo=MutableEntitlementTimezone()),
        )
        non_finite_offset = entitlement()
        object.__setattr__(
            non_finite_offset,
            "evaluated_at",
            datetime(2026, 8, 21, tzinfo=NonFiniteEntitlementTimezone()),
        )

        for index, supplied in enumerate(
            (invalid_type, out_of_range, non_finite_offset)
        ):
            with (
                self.subTest(index=index),
                self.assertRaises(SnapshotValidationError) as raised,
            ):
                MainlandOfficialSnapshotAdapter(entitlements=supplied)
            self.assertEqual(raised.exception.code, "invalid_entitlements")
            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)

    def test_entitlements_rights_validity_source_and_capability_fail_closed(
        self,
    ) -> None:
        cases: list[tuple[ProviderEntitlements, dict[str, object], str]] = []
        provider_mismatch = bundle()
        provider_mismatch["provider_id"] = "other-provider"
        cases.append((entitlement(), provider_mismatch, "entitlement_mismatch"))

        rights_mismatch = bundle()
        rights_mismatch["rights"]["redistribution_allowed"] = True  # type: ignore[index]
        cases.append((entitlement(), rights_mismatch, "rights_mismatch"))

        expired_entitlement = entitlement()
        object.__setattr__(
            expired_entitlement,
            "valid_until",
            datetime(2026, 8, 20, tzinfo=UTC),
        )
        expired = bundle()
        expired["rights"]["valid_until"] = "2026-08-20T00:00:00Z"  # type: ignore[index]
        cases.append((expired_entitlement, expired, "invalid_entitlements"))

        for value, document, code in cases:
            with (
                self.subTest(code=code),
                self.assertRaises(SnapshotValidationError) as raised,
            ):
                MainlandOfficialSnapshotAdapter(entitlements=value).parse(
                    document, evaluation_timestamp=EVALUATION
                )
            self.assertEqual(raised.exception.code, code)

        missing_capability = replace(
            entitlement(),
            capabilities=frozenset(
                capability
                for capability in entitlement().capabilities
                if capability is not ProviderCapability.GET_CORPORATE_ACTIONS
            ),
        )
        with self.assertRaises(Exception) as raised:
            MainlandOfficialSnapshotAdapter(entitlements=missing_capability).parse(
                bundle(), evaluation_timestamp=EVALUATION
            )
        self.assertEqual(
            getattr(raised.exception, "code", None), "capability_not_authorized"
        )

    def test_mainland_typed_entitlements_require_expiry_in_api_and_cli(self) -> None:
        import io
        from contextlib import redirect_stderr, redirect_stdout

        supplied = replace(entitlement(), valid_until=None)
        with self.assertRaises(SnapshotValidationError) as raised:
            MainlandOfficialSnapshotAdapter(entitlements=supplied)
        self.assertEqual(raised.exception.code, "invalid_entitlements")
        self.assertEqual(raised.exception.path, "$")
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

        marker = "PRIVATE-NONE-ENTITLEMENT-MARKER"
        with tempfile.TemporaryDirectory() as temporary_directory:
            snapshot_path = Path(temporary_directory) / f"{marker}.json"
            snapshot_path.write_text(json.dumps(bundle()), encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch(
                    "openfundscore.cli.load_mainland_entitlements",
                    return_value=supplied,
                ),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                exit_code = main(
                    [
                        "provider",
                        "mainland-parse",
                        str(snapshot_path),
                        "--entitlements",
                        str(snapshot_path),
                        "--evaluation-timestamp",
                        "2026-08-21T00:00:00Z",
                    ]
                )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(
            stderr.getvalue(),
            "openfundscore: error: $: invalid_entitlements: "
            "Mainland snapshots require an explicit entitlement expiry\n",
        )
        self.assertNotIn(marker, stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_equivalent_entitlement_rights_instants_accept_mixed_offsets(self) -> None:
        cases = (
            (
                "2026-08-20T08:00:00+08:00",
                "2026-09-01T00:00:00Z",
                "2026-08-20T00:00:00Z",
                "2026-08-31T19:00:00-05:00",
            ),
            (
                "2026-08-19T19:00:00-05:00",
                "2026-09-01T08:00:00+08:00",
                "2026-08-20T08:00:00+08:00",
                "2026-09-01T00:00:00Z",
            ),
        )
        for (
            entitlement_reviewed,
            entitlement_valid_until,
            snapshot_reviewed,
            snapshot_valid_until,
        ) in cases:
            document = bundle()
            document["rights"]["reviewed_at"] = snapshot_reviewed  # type: ignore[index]
            document["rights"]["valid_until"] = snapshot_valid_until  # type: ignore[index]
            before = deepcopy(document)
            value = replace(
                entitlement(),
                rights_reviewed_at=datetime.fromisoformat(entitlement_reviewed),
                valid_until=datetime.fromisoformat(entitlement_valid_until),
            )

            records = MainlandOfficialSnapshotAdapter(entitlements=value).parse(
                document, evaluation_timestamp=EVALUATION
            )

            self.assertEqual(document, before)
            self.assertTrue(records)
            self.assertTrue(
                all(
                    record["rights"]["reviewed_at"] == snapshot_reviewed  # type: ignore[index]
                    for record in records
                )
            )
            self.assertTrue(
                all(
                    record["rights"]["valid_until"] == snapshot_valid_until  # type: ignore[index]
                    for record in records
                )
            )

    def test_distinct_entitlement_rights_instants_fail_closed(self) -> None:
        cases = (
            ("reviewed_at", "2026-08-20T00:00:01Z"),
            ("valid_until", "2026-09-01T00:00:01Z"),
        )
        for field, distinct_instant in cases:
            document = bundle()
            document["rights"][field] = distinct_instant  # type: ignore[index]

            with (
                self.subTest(field=field),
                self.assertRaises(SnapshotValidationError) as raised,
            ):
                self.adapter().parse(document, evaluation_timestamp=EVALUATION)

            self.assertEqual(raised.exception.code, "rights_mismatch")
            self.assertEqual(raised.exception.path, "$.rights")

    def test_all_seven_profiles_have_closed_typed_fields_in_schema_and_semantics(
        self,
    ) -> None:
        from jsonschema import Draft202012Validator

        schema = resolve_resource(
            resource_type="schema",
            name="mainland_official_snapshot",
            version="0.1.0",
        ).load_json()
        mutations: list[dict[str, object]] = []

        unrelated_identity = bundle()
        unrelated_identity["items"][0]["observations"] = [  # type: ignore[index]
            observation("identity-unrelated", "unrelated_field", None)
        ]
        mutations.append(unrelated_identity)

        null_benchmark = bundle()
        null_benchmark["items"][4]["observations"][0]["raw_value"] = None  # type: ignore[index]
        mutations.append(null_benchmark)

        cross_capability = bundle()
        cross_capability["items"][1]["observations"][0]["field"] = "manager_id"  # type: ignore[index]
        mutations.append(cross_capability)

        boolean_holding = bundle()
        boolean_holding["items"][5]["observations"][2]["raw_value"] = True  # type: ignore[index]
        mutations.append(boolean_holding)

        invalid_relation = bundle()
        invalid_relation["items"][3]["observations"][0]["raw_value"] = "\u200b"  # type: ignore[index]
        mutations.append(invalid_relation)

        invisible_name = bundle()
        invisible_name["items"][0]["observations"][0]["raw_value"] = (
            "\u200b\u2060\ufeff"  # type: ignore[index]
        )
        mutations.append(invisible_name)

        for document in mutations:
            with self.subTest(case=id(document)):
                self.assertFalse(Draft202012Validator(schema).is_valid(document))
                with self.assertRaises(SnapshotValidationError) as raised:
                    self.adapter().parse(document, evaluation_timestamp=EVALUATION)
                self.assertIn(
                    raised.exception.code,
                    {
                        "snapshot_schema",
                        "invalid_item_field",
                        "invalid_item_value",
                        "invalid_nav",
                        "invalid_holding",
                    },
                )

    def test_identity_entity_profiles_are_distinct_and_complete(self) -> None:
        profiles = {
            "fund_strategy": {"canonical_name"},
            "share_class": {"canonical_name", "class_code"},
            "manager": {"canonical_name"},
            "benchmark": {"canonical_name"},
        }
        for entity_type, required in profiles.items():
            document = bundle()
            identity = document["items"][0]  # type: ignore[index]
            identity["entity_type"] = entity_type
            identity["exact_identifiers"][0]["value"] = (  # type: ignore[index]
                f"official:{entity_type}:share-a"
            )
            identity["observations"] = [
                observation(
                    f"identity-{field}",
                    field,
                    "合成名称" if field == "canonical_name" else "A",
                )
                for field in required
            ]
            records = self.adapter().parse(document, evaluation_timestamp=EVALUATION)
            fields = {
                record["field"]
                for record in records
                if record["provider_record_id"].startswith(
                    f"{document['snapshot_id']}:01-identity-a:"
                )
            }
            self.assertEqual(fields, required)

    def test_reconstructed_observation_requires_and_preserves_methodology(self) -> None:
        missing = bundle()
        reconstructed = missing["items"][0]["observations"][0]  # type: ignore[index]
        reconstructed["point_in_time_status"] = "reconstructed"
        reconstructed["quality_state"] = "unverified"
        with self.assertRaises(SnapshotValidationError):
            self.adapter().parse(missing, evaluation_timestamp=EVALUATION)

        documented = bundle()
        reconstructed = documented["items"][0]["observations"][0]  # type: ignore[index]
        reconstructed["point_in_time_status"] = "reconstructed"
        reconstructed["quality_state"] = "unverified"
        reconstructed["methodology"] = "Reconstructed from dated official filings."
        records = self.adapter().parse(documented, evaluation_timestamp=EVALUATION)
        mapped = next(
            record
            for record in records
            if record["provider_record_id"].endswith(":id-a-name")
        )
        self.assertEqual(
            mapped["methodology"],
            "Reconstructed from dated official filings.",
        )

    def test_holding_units_are_exact_and_key_fields_share_one_snapshot_time(
        self,
    ) -> None:
        floating_bps = bundle()
        floating_bps["items"][5]["observations"][2]["raw_value"] = 6000.0  # type: ignore[index]
        inconsistent_time = bundle()
        inconsistent_time["items"][5]["observations"][0]["as_of"] = (
            "2026-08-14T00:00:00Z"  # type: ignore[index]
        )
        for document in (floating_bps, inconsistent_time):
            with (
                self.subTest(case=id(document)),
                self.assertRaises(SnapshotValidationError) as raised,
            ):
                self.adapter().parse(document, evaluation_timestamp=EVALUATION)
            self.assertEqual(raised.exception.code, "invalid_holding")

    def test_every_conflicting_holding_value_is_checked_before_grouping(self) -> None:
        document = bundle()
        holding = document["items"][5]  # type: ignore[index]
        first = holding["observations"][2]
        first["quality_state"] = "conflict"
        first["conflict_group"] = "weight-conflict"
        first["raw_value"] = 9000
        valid = deepcopy(first)
        valid["observation_id"] = "holding-weight-valid"
        valid["raw_value"] = 6000
        holding["observations"].append(valid)

        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "invalid_holding")

    def test_equivalent_rfc3339_instants_share_holding_coverage(self) -> None:
        document = bundle()
        second = deepcopy(document["items"][5])  # type: ignore[index]
        second["item_id"] = "06-holding-second"
        second["entity_id"] = "holding-2"
        second["exact_identifiers"][0]["value"] = "official:holding-2"
        for disclosed_field in second["observations"]:
            disclosed_field["observation_id"] += "-second"
            disclosed_field["as_of"] = "2026-08-15T08:00:00+08:00"
            disclosed_field["valid_from"] = "2026-08-14T19:00:00-05:00"
            if disclosed_field["field"] == "instrument_id":
                disclosed_field["raw_value"] = "CN-SYN-2"
        document["items"].append(second)  # type: ignore[union-attr]

        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "invalid_holding")

    def test_fraction_holding_totals_use_exact_decimal_comparison(self) -> None:
        document = bundle()
        document["units"]["weight"] = "fraction"  # type: ignore[index]
        document["units"]["coverage"] = "fraction"  # type: ignore[index]
        first = document["items"][5]  # type: ignore[index]
        first["observations"][2]["raw_value"] = 0.1
        first["observations"][2]["unit"] = "fraction"
        first["observations"][3]["raw_value"] = 0.3
        first["observations"][3]["unit"] = "fraction"
        second = deepcopy(first)
        second["item_id"] = "06-holding-second"
        second["entity_id"] = "holding-2"
        second["exact_identifiers"][0]["value"] = "official:holding-2"
        for disclosed_field in second["observations"]:
            disclosed_field["observation_id"] += "-second"
            if disclosed_field["field"] == "instrument_id":
                disclosed_field["raw_value"] = "CN-SYN-2"
            elif disclosed_field["field"] == "weight":
                disclosed_field["raw_value"] = 0.2
        document["items"].append(second)  # type: ignore[union-attr]

        records = self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        weights = [record["value"] for record in records if record["field"] == "weight"]
        self.assertEqual(weights, [0.1, 0.2])

    def test_fraction_holding_totals_do_not_tolerate_true_overcoverage(self) -> None:
        document = bundle()
        document["units"]["weight"] = "fraction"  # type: ignore[index]
        document["units"]["coverage"] = "fraction"  # type: ignore[index]
        first = document["items"][5]  # type: ignore[index]
        first["observations"][2]["raw_value"] = 0.1
        first["observations"][2]["unit"] = "fraction"
        first["observations"][3]["raw_value"] = 0.3
        first["observations"][3]["unit"] = "fraction"
        second = deepcopy(first)
        second["item_id"] = "06-holding-second"
        second["entity_id"] = "holding-2"
        second["exact_identifiers"][0]["value"] = "official:holding-2"
        for disclosed_field in second["observations"]:
            disclosed_field["observation_id"] += "-second"
            if disclosed_field["field"] == "instrument_id":
                disclosed_field["raw_value"] = "CN-SYN-2"
            elif disclosed_field["field"] == "weight":
                disclosed_field["raw_value"] = 0.20000000000000004
        document["items"].append(second)  # type: ignore[union-attr]

        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "invalid_holding")

    def test_type_specific_semantics_reject_invalid_financial_disclosures(self) -> None:
        mutations = []

        negative_nav = bundle()
        negative_nav["items"][1]["observations"][0]["raw_value"] = -0.01  # type: ignore[index]
        mutations.append((negative_nav, "invalid_nav"))

        boolean_nav = bundle()
        boolean_nav["items"][1]["observations"][0]["raw_value"] = True  # type: ignore[index]
        mutations.append((boolean_nav, "invalid_nav"))

        reversed_nav = bundle()
        reversed_nav["items"][1]["observations"].reverse()  # type: ignore[index]
        mutations.append((reversed_nav, "invalid_nav_order"))

        overweight = bundle()
        overweight["items"][5]["observations"][2]["raw_value"] = 9000  # type: ignore[index]
        mutations.append((overweight, "invalid_holding"))

        reversed_tenure = bundle()
        reversed_tenure["items"][3]["observations"][2]["raw_value"] = "2027-01-01"  # type: ignore[index]
        reversed_tenure["items"][3]["observations"][3]["raw_value"] = "2026-01-01"  # type: ignore[index]
        mutations.append((reversed_tenure, "invalid_tenure"))

        malformed_action = bundle()
        malformed_action["items"][6]["observations"][3]["raw_value"] = "strategy-old"  # type: ignore[index]
        mutations.append((malformed_action, "invalid_corporate_action"))

        bad_report = bundle()
        bad_report["items"][2]["observations"][1]["raw_value"] = "not-a-hash"  # type: ignore[index]
        mutations.append((bad_report, "invalid_report"))

        for document, code in mutations:
            with (
                self.subTest(code=code),
                self.assertRaises(SnapshotValidationError) as raised,
            ):
                self.adapter().parse(document, evaluation_timestamp=EVALUATION)
            self.assertEqual(raised.exception.code, code)

    def test_conflicting_tenure_dates_cannot_hide_a_reversed_interval(self) -> None:
        document = bundle()
        tenure = document["items"][3]  # type: ignore[index]
        first = tenure["observations"][2]
        first["quality_state"] = "conflict"
        first["conflict_group"] = "tenure-start-conflict"
        first["raw_value"] = "2027-01-01"
        valid = deepcopy(first)
        valid["observation_id"] = "tenure-start-valid"
        valid["raw_value"] = "2024-01-01"
        tenure["observations"].append(valid)
        tenure["observations"][3]["raw_value"] = "2026-01-01"

        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "invalid_tenure")

    def test_conflicting_action_types_cannot_hide_an_invalid_closed_shape(self) -> None:
        document = bundle()
        action = document["items"][6]  # type: ignore[index]
        first = action["observations"][0]
        first["quality_state"] = "conflict"
        first["conflict_group"] = "action-type-conflict"
        first["raw_value"] = "closed"
        valid = deepcopy(first)
        valid["observation_id"] = "action-type-transformed"
        valid["raw_value"] = "transformed"
        action["observations"].append(valid)

        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "invalid_corporate_action")

    def test_revision_snapshot_groups_must_each_contain_the_closed_profile(
        self,
    ) -> None:
        document = bundle()
        report = document["items"][2]  # type: ignore[index]
        revision = deepcopy(report["observations"][0])
        revision["observation_id"] = "report-url-revision-only"
        revision["as_of"] = "2026-08-16T00:00:00Z"
        revision["published_at"] = "2026-08-17T00:00:00Z"
        revision["valid_from"] = revision["as_of"]
        report["observations"].append(revision)

        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "missing_item_field")

    def test_conflicts_and_publication_lag_are_preserved_without_last_write_wins(
        self,
    ) -> None:
        document = bundle()
        identity = document["items"][0]  # type: ignore[index]
        first = identity["observations"][0]
        first["quality_state"] = "conflict"
        first["conflict_group"] = "name-conflict-1"
        alternative = deepcopy(first)
        alternative["observation_id"] = "id-a-name-alternative"
        alternative["raw_value"] = "合成基金A（冲突披露）"
        identity["observations"].append(alternative)

        records = self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        names = [
            record
            for record in records
            if record["field"] == "canonical_name" and record["entity_id"] == "share-a"
        ]
        self.assertEqual(len(names), 2)
        self.assertEqual({record["quality_state"] for record in names}, {"conflict"})
        self.assertEqual(
            {record["conflict_group"] for record in names}, {"name-conflict-1"}
        )
        self.assertTrue(
            all(record["as_of"] < record["published_at"] for record in names)
        )

    def test_nav_equivalent_offset_conflict_is_preserved_in_deterministic_order(
        self,
    ) -> None:
        document = bundle()
        nav = document["items"][1]  # type: ignore[index]
        original = nav["observations"][1]
        original["quality_state"] = "conflict"
        original["conflict_group"] = "nav-close-conflict"
        alternative = deepcopy(original)
        alternative["observation_id"] = "nav-a-2-alternative"
        alternative["raw_value"] = 1.02
        alternative["as_of"] = "2026-08-15T08:00:00+08:00"
        alternative["valid_from"] = "2026-08-14T19:00:00-05:00"
        nav["observations"].append(alternative)

        records = self.adapter().parse(document, evaluation_timestamp=EVALUATION)

        nav_records = [record for record in records if record["field"] == "nav"]
        self.assertEqual([record["value"] for record in nav_records], [1.0, 1.01, 1.02])
        self.assertEqual(
            [record["as_of"] for record in nav_records],
            [
                "2026-08-14T00:00:00Z",
                "2026-08-15T00:00:00Z",
                "2026-08-15T08:00:00+08:00",
            ],
        )
        self.assertEqual(
            [record["conflict_group"] for record in nav_records[1:]],
            ["nav-close-conflict", "nav-close-conflict"],
        )

    def test_nav_conflict_group_must_be_uniform_and_non_mixed(self) -> None:
        cases = ("silent", "mixed", "different-group")
        for case in cases:
            document = bundle()
            nav = document["items"][1]  # type: ignore[index]
            original = nav["observations"][1]
            alternative = deepcopy(original)
            alternative["observation_id"] = f"nav-a-2-{case}"
            alternative["raw_value"] = 1.02
            alternative["as_of"] = "2026-08-15T08:00:00+08:00"
            alternative["valid_from"] = "2026-08-14T19:00:00-05:00"
            if case != "silent":
                alternative["quality_state"] = "conflict"
                alternative["conflict_group"] = "nav-conflict-b"
            if case == "different-group":
                original["quality_state"] = "conflict"
                original["conflict_group"] = "nav-conflict-a"
            nav["observations"].append(alternative)

            with (
                self.subTest(case=case),
                self.assertRaises(SnapshotValidationError) as raised,
            ):
                self.adapter().parse(document, evaluation_timestamp=EVALUATION)

            self.assertEqual(raised.exception.code, "silent_conflict")

    def test_nav_same_instant_conflict_group_order_is_deterministic(self) -> None:
        document = bundle()
        nav = document["items"][1]  # type: ignore[index]
        original = nav["observations"][1]
        original["quality_state"] = "conflict"
        original["conflict_group"] = "nav-conflict"
        alternative = deepcopy(original)
        alternative["observation_id"] = "nav-a-2-alternative"
        alternative["raw_value"] = 1.02
        alternative["as_of"] = "2026-08-15T08:00:00+08:00"
        alternative["valid_from"] = "2026-08-14T19:00:00-05:00"
        nav["observations"].insert(1, alternative)

        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)

        self.assertEqual(raised.exception.code, "invalid_nav_order")

    def test_exact_duplicate_nav_still_fails_closed(self) -> None:
        document = bundle()
        nav = document["items"][1]  # type: ignore[index]
        original = nav["observations"][1]
        original["quality_state"] = "conflict"
        original["conflict_group"] = "nav-duplicate"
        duplicate = deepcopy(original)
        duplicate["observation_id"] = "nav-a-2-duplicate"
        nav["observations"].append(duplicate)

        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)

        self.assertEqual(raised.exception.code, "duplicate_observation_snapshot")

    def test_equivalent_rfc3339_spellings_form_one_profile_snapshot_and_stay_raw(
        self,
    ) -> None:
        document = bundle()
        expected_record_ids = {
            record["provider_record_id"]
            for record in self.adapter().parse(
                deepcopy(document), evaluation_timestamp=EVALUATION
            )
        }
        equivalent_instants = (
            "2026-08-15T00:00:00Z",
            "2026-08-15T08:00:00+08:00",
            "2026-08-14T19:00:00-05:00",
        )
        expected_as_of_by_id: dict[str, str] = {}
        for disclosure_item in document["items"]:  # type: ignore[union-attr]
            for index, disclosed_field in enumerate(disclosure_item["observations"]):
                if disclosed_field["as_of"] == "2026-08-15T00:00:00Z":
                    spelling = equivalent_instants[index % len(equivalent_instants)]
                    disclosed_field["as_of"] = spelling
                    disclosed_field["valid_from"] = spelling
                expected_as_of_by_id[
                    f"{document['snapshot_id']}:{disclosure_item['item_id']}:{disclosed_field['observation_id']}"
                ] = disclosed_field["as_of"]

        records = self.adapter().parse(document, evaluation_timestamp=EVALUATION)

        self.assertEqual(
            {record["provider_record_id"] for record in records}, expected_record_ids
        )
        self.assertEqual(
            {record["provider_record_id"]: record["as_of"] for record in records},
            expected_as_of_by_id,
        )
        self.assertIn(
            "2026-08-15T08:00:00+08:00",
            {record["as_of"] for record in records},
        )
        self.assertIn(
            "2026-08-14T19:00:00-05:00",
            {record["as_of"] for record in records},
        )

    def test_equivalent_rfc3339_report_revision_is_a_silent_conflict(self) -> None:
        document = bundle()
        report = document["items"][2]  # type: ignore[index]
        revision = deepcopy(report["observations"])
        for disclosed_field in revision:
            disclosed_field["observation_id"] += "-equivalent-offset"
            disclosed_field["as_of"] = "2026-08-15T08:00:00+08:00"
            disclosed_field["valid_from"] = "2026-08-14T19:00:00-05:00"
            if disclosed_field["field"] == "report_url":
                disclosed_field["raw_value"] = (
                    "https://www.csrc.gov.cn/synthetic/revised-report.json"
                )
            else:
                disclosed_field["raw_value"] = "sha256:" + "b" * 64
        report["observations"].extend(revision)

        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "silent_conflict")

    def test_equivalent_rfc3339_verified_conflicts_fail_for_all_seven_profiles(
        self,
    ) -> None:
        cases = (
            (0, 0, "合成基金A（另一披露）", "identity"),
            (1, 1, 1.02, "nav"),
            (
                2,
                0,
                "https://www.csrc.gov.cn/synthetic/revised-report.json",
                "report",
            ),
            (3, 0, "manager-2", "manager_tenure"),
            (4, 0, "另一合成基准", "benchmark"),
            (5, 2, 5000, "holding"),
            (6, 0, "merged", "corporate_action"),
        )
        for item_index, observation_index, alternative_value, item_type in cases:
            document = bundle()
            disclosure_item = document["items"][item_index]  # type: ignore[index]
            duplicate = deepcopy(disclosure_item["observations"][observation_index])
            duplicate["observation_id"] += "-equivalent-conflict"
            duplicate["raw_value"] = alternative_value
            duplicate["as_of"] = "2026-08-15T08:00:00+08:00"
            duplicate["valid_from"] = "2026-08-14T19:00:00-05:00"
            disclosure_item["observations"].append(duplicate)

            with (
                self.subTest(item_type=item_type),
                self.assertRaises(SnapshotValidationError) as raised,
            ):
                self.adapter().parse(document, evaluation_timestamp=EVALUATION)
            self.assertEqual(raised.exception.code, "silent_conflict")

    def test_distinct_real_instant_remains_an_allowed_complete_revision(self) -> None:
        document = bundle()
        report = document["items"][2]  # type: ignore[index]
        revision = deepcopy(report["observations"])
        for disclosed_field in revision:
            disclosed_field["observation_id"] += "-next-instant"
            disclosed_field["as_of"] = "2026-08-16T00:00:00Z"
            disclosed_field["published_at"] = "2026-08-17T00:00:00Z"
            disclosed_field["fetched_at"] = "2026-08-17T00:00:00Z"
            disclosed_field["valid_from"] = disclosed_field["as_of"]
            if disclosed_field["field"] == "report_url":
                disclosed_field["raw_value"] = (
                    "https://www.csrc.gov.cn/synthetic/next-report.json"
                )
            else:
                disclosed_field["raw_value"] = "sha256:" + "c" * 64
        report["observations"].extend(revision)

        records = self.adapter().parse(document, evaluation_timestamp=EVALUATION)

        revised = [
            record
            for record in records
            if str(record["provider_record_id"]).endswith("-next-instant")
        ]
        self.assertEqual(len(revised), 2)
        self.assertEqual(
            {record["as_of"] for record in revised}, {"2026-08-16T00:00:00Z"}
        )

    def test_every_conflicting_report_url_is_independently_approved(self) -> None:
        document = bundle()
        report = document["items"][2]  # type: ignore[index]
        first = report["observations"][0]
        first["quality_state"] = "conflict"
        first["conflict_group"] = "report-url-conflict"
        first["raw_value"] = "https://fund.eastmoney.com/private"
        approved = deepcopy(first)
        approved["observation_id"] = "report-url-approved"
        approved["raw_value"] = SOURCE
        report["observations"].append(approved)

        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "unapproved_source")

    def test_every_report_revision_is_independently_approved(self) -> None:
        document = bundle()
        report = document["items"][2]  # type: ignore[index]
        first = report["observations"][0]
        first["raw_value"] = "https://fund.eastmoney.com/private"
        approved = deepcopy(first)
        approved["observation_id"] = "report-url-revision"
        approved["raw_value"] = SOURCE
        approved["as_of"] = "2026-08-16T00:00:00Z"
        approved["published_at"] = "2026-08-17T00:00:00Z"
        approved["fetched_at"] = "2026-08-17T00:00:00Z"
        approved["valid_from"] = approved["as_of"]
        report["observations"].append(approved)

        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "unapproved_source")

    def test_each_record_is_validated_before_it_is_authorized(self) -> None:
        events: list[str] = []
        from openfundscore import mainland_official as module

        real_validate = module.validate_record
        real_authorize = module.authorize_ingestion

        def validating(*args, **kwargs):
            events.append("validate")
            return real_validate(*args, **kwargs)

        def authorizing(*args, **kwargs):
            events.append("authorize")
            return real_authorize(*args, **kwargs)

        with (
            patch.object(module, "validate_record", side_effect=validating),
            patch.object(module, "authorize_ingestion", side_effect=authorizing),
        ):
            self.adapter().parse(bundle(), evaluation_timestamp=EVALUATION)
        self.assertEqual(events, ["validate", "authorize"] * 19)

    def test_every_observation_is_bound_to_the_bundle_document_digest(self) -> None:
        document = bundle()
        document["items"][0]["observations"][0]["source_document_hash"] = (  # type: ignore[index]
            "sha256:" + "b" * 64
        )
        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "document_hash_mismatch")
        self.assertEqual(
            raised.exception.path,
            "$.items.observations.source_document_hash",
        )

    def test_hostile_mapping_keys_never_enter_api_or_cli_errors(self) -> None:
        import io
        from contextlib import redirect_stderr, redirect_stdout

        marker = "PRIVATE-KEY-MARKER"
        nested: object = None
        for _ in range(70):
            nested = [nested]
        document = bundle()
        document["items"][0]["observations"][0]["raw_value"] = {marker: nested}  # type: ignore[index]
        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertNotIn(marker, raised.exception.path)
        self.assertNotIn(marker, str(raised.exception))

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            snapshot_path = root / "snapshot.json"
            entitlement_path = root / "entitlements.json"
            snapshot_path.write_text(json.dumps(document), encoding="utf-8")
            entitlement_path.write_text(
                json.dumps(entitlement_document()), encoding="utf-8"
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(
                    [
                        "provider",
                        "mainland-parse",
                        str(snapshot_path),
                        "--entitlements",
                        str(entitlement_path),
                        "--evaluation-timestamp",
                        "2026-08-21T00:00:00Z",
                    ]
                )
        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertNotIn(marker, stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_hostile_cycles_nonfinite_values_depth_and_timestamp_errors_are_redacted(
        self,
    ) -> None:
        cyclic = bundle()
        cyclic["cycle"] = cyclic
        too_deep: object = "leaf"
        for _ in range(70):
            too_deep = [too_deep]
        deep = bundle()
        deep["items"][0]["observations"][0]["raw_value"] = too_deep  # type: ignore[index]
        nonfinite = bundle()
        nonfinite["items"][0]["observations"][0]["raw_value"] = float("nan")  # type: ignore[index]
        bad_timestamp = bundle()
        bad_timestamp["retrieved_at"] = "PRIVATE-TIMESTAMP-MARKER"

        for document in (cyclic, deep, nonfinite, bad_timestamp):
            with (
                self.subTest(case=id(document)),
                self.assertRaises(SnapshotValidationError) as raised,
            ):
                self.adapter().parse(document, evaluation_timestamp=EVALUATION)
            self.assertNotIn("PRIVATE-TIMESTAMP-MARKER", str(raised.exception))
            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)

    def test_utc_unrepresentable_rfc3339_fails_closed_across_all_snapshot_paths(
        self,
    ) -> None:
        import io
        from contextlib import redirect_stderr, redirect_stdout

        from openfundscore.mainland_official import load_mainland_entitlements

        lower = "0001-01-01T00:00:00+23:59"
        upper = "9999-12-31T23:59:59-23:59"
        api_cases: list[tuple[str, dict[str, object], str]] = []

        root = bundle()
        root["retrieved_at"] = lower
        api_cases.append(("root", root, "$.retrieved_at"))

        rights = bundle()
        rights["rights"]["valid_until"] = upper  # type: ignore[index]
        api_cases.append(("rights", rights, "$.rights.valid_until"))

        disclosed = bundle()
        disclosed["items"][0]["observations"][0]["as_of"] = lower  # type: ignore[index]
        api_cases.append(("observation", disclosed, "$.items.observations.as_of"))

        for label, document, expected_path in api_cases:
            with (
                self.subTest(label=label),
                self.assertRaises(SnapshotValidationError) as raised,
            ):
                self.adapter().parse(document, evaluation_timestamp=EVALUATION)
            self.assertEqual(raised.exception.code, "invalid_timestamp")
            self.assertEqual(raised.exception.path, expected_path)
            self.assertNotIn(lower, str(raised.exception))
            self.assertNotIn(upper, str(raised.exception))
            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)

        entitlements = entitlement_document()
        entitlements["evaluated_at"] = upper
        with self.assertRaises(SnapshotValidationError) as raised:
            load_mainland_entitlements(entitlements)
        self.assertEqual(raised.exception.code, "invalid_timestamp")
        self.assertEqual(raised.exception.path, "$.evaluated_at")
        self.assertNotIn(upper, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

        with tempfile.TemporaryDirectory() as temporary_directory:
            root_path = Path(temporary_directory)
            snapshot_path = root_path / "snapshot.json"
            entitlement_path = root_path / "entitlements.json"
            snapshot = bundle()
            snapshot["published_at"] = upper
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
            entitlement_path.write_text(
                json.dumps(entitlement_document()), encoding="utf-8"
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(
                    [
                        "provider",
                        "mainland-parse",
                        str(snapshot_path),
                        "--entitlements",
                        str(entitlement_path),
                        "--evaluation-timestamp",
                        "2026-08-21T00:00:00Z",
                    ]
                )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(len(stderr.getvalue().splitlines()), 1)
        self.assertIn("invalid_timestamp", stderr.getvalue())
        self.assertNotIn(upper, stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_timestamp_utc_normalization_wraps_os_errors_but_not_base_exceptions(
        self,
    ) -> None:
        from openfundscore import mainland_official as module

        class NormalizationDatetime(datetime):
            failure: BaseException = ValueError()

            def astimezone(self, tz=None):
                raise self.failure

        parsed = NormalizationDatetime(2026, 8, 21, tzinfo=UTC)
        marker = "PRIVATE-UTC-NORMALIZATION-MARKER"
        for failure_type in (ValueError, OSError):
            parsed.failure = failure_type(marker)
            with (
                self.subTest(failure_type=failure_type.__name__),
                patch.object(module, "parse_rfc3339_timestamp", return_value=parsed),
                self.assertRaises(SnapshotValidationError) as raised,
            ):
                module._timestamp("valid-profile-placeholder", "$.as_of")
            self.assertEqual(raised.exception.code, "invalid_timestamp")
            self.assertNotIn(marker, str(raised.exception))
            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)

        parsed.failure = KeyboardInterrupt(marker)
        with (
            patch.object(module, "parse_rfc3339_timestamp", return_value=parsed),
            self.assertRaises(KeyboardInterrupt),
        ):
            module._timestamp("valid-profile-placeholder", "$.as_of")

    def test_json_duplicate_keys_nonfinite_constants_and_oversize_input_fail_closed(
        self,
    ) -> None:
        marker = b"PRIVATE-JSON-MARKER"
        cases = (
            (
                b'{"schema_version":"0.1.0","schema_version":"0.1.0"}' + marker,
                "snapshot_format",
            ),
            (b'{"value":NaN}' + marker, "snapshot_format"),
            (b'{"value":Infinity}' + marker, "snapshot_format"),
            (b" " * (8 * 1024 * 1024 + 1) + marker, "snapshot_too_large"),
        )
        for payload, code in cases:
            with (
                self.subTest(code=code),
                self.assertRaises(SnapshotValidationError) as raised,
            ):
                self.adapter().parse(payload, evaluation_timestamp=EVALUATION)
            self.assertEqual(raised.exception.code, code)
            self.assertNotIn(marker.decode(), str(raised.exception))
            self.assertIsNone(raised.exception.__context__)

    def test_mapping_width_string_budget_and_both_infinities_are_bounded(self) -> None:
        documents: list[dict[str, object]] = []
        wide = bundle()
        wide["items"][0]["observations"][0]["raw_value"] = {  # type: ignore[index]
            f"key-{index}": None for index in range(10_001)
        }
        documents.append(wide)
        long_string = bundle()
        long_string["items"][0]["observations"][0]["raw_value"] = "x" * 65_537  # type: ignore[index]
        documents.append(long_string)
        for value in (float("inf"), float("-inf")):
            nonfinite = bundle()
            nonfinite["items"][0]["observations"][0]["raw_value"] = value  # type: ignore[index]
            documents.append(nonfinite)

        for document in documents:
            with (
                self.subTest(case=id(document)),
                self.assertRaises(SnapshotValidationError) as raised,
            ):
                self.adapter().parse(document, evaluation_timestamp=EVALUATION)
            self.assertEqual(
                raised.exception.code,
                "snapshot_too_complex"
                if document in (wide, long_string)
                else "invalid_document",
            )
            self.assertIsNone(raised.exception.__context__)

    def test_future_effective_fact_is_known_but_never_marked_current(self) -> None:
        document = bundle()
        document["effective_at"] = "2026-09-15T00:00:00Z"
        action = document["items"][6]  # type: ignore[index]
        action["observations"][1]["raw_value"] = "2026-09-15T00:00:00Z"
        for disclosed_field in action["observations"]:
            disclosed_field["valid_from"] = "2026-09-15T00:00:00Z"
        records = self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        action_records = [
            record for record in records if record["entity_type"] == "corporate_action"
        ]
        self.assertTrue(action_records)
        self.assertTrue(
            all(record["effective_status"] == "future" for record in action_records)
        )

    def test_root_as_of_must_not_follow_retrieval_even_before_evaluation(self) -> None:
        document = bundle()
        document["as_of"] = "2026-08-18T00:00:00Z"
        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "chronology_violation")

    def test_equivalent_rfc3339_duplicate_snapshot_is_not_distinct(self) -> None:
        document = bundle()
        identity = document["items"][0]  # type: ignore[index]
        original = identity["observations"][0]
        original["quality_state"] = "conflict"
        original["conflict_group"] = "equivalent-duplicate"
        duplicate = deepcopy(original)
        duplicate["observation_id"] = "id-a-name-equivalent-duplicate"
        duplicate["as_of"] = "2026-08-15T08:00:00+08:00"
        duplicate["published_at"] = "2026-08-15T19:00:00-05:00"
        duplicate["fetched_at"] = "2026-08-17T08:00:00+08:00"
        duplicate["valid_from"] = "2026-08-14T19:00:00-05:00"
        identity["observations"].append(duplicate)

        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "duplicate_observation_snapshot")

    def test_duplicate_snapshot_and_revision_shapes_fail_closed(self) -> None:
        document = bundle()
        identity = document["items"][0]  # type: ignore[index]
        first = identity["observations"][0]
        first["quality_state"] = "conflict"
        first["conflict_group"] = "duplicate-group"
        duplicate = deepcopy(first)
        duplicate["observation_id"] = "identity-duplicate"
        identity["observations"].append(duplicate)
        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "duplicate_observation_snapshot")

    def test_root_and_observation_point_in_time_chronology_fail_closed(self) -> None:
        cases: list[dict[str, object]] = []
        for field in ("retrieved_at", "as_of"):
            document = bundle()
            document[field] = "2026-08-22T00:00:00Z"
            cases.append(document)
        root_publication = bundle()
        root_publication["published_at"] = "2026-08-18T00:00:00Z"
        cases.append(root_publication)
        for field in ("published_at", "as_of"):
            document = bundle()
            document["items"][0]["observations"][0][field] = "2026-08-18T00:00:00Z"  # type: ignore[index]
            cases.append(document)
        reversed_validity = bundle()
        reversed_validity["items"][0]["observations"][0]["valid_from"] = (
            "2026-08-19T00:00:00Z"  # type: ignore[index]
        )
        reversed_validity["items"][0]["observations"][0]["valid_to"] = (
            "2026-08-18T00:00:00Z"  # type: ignore[index]
        )
        cases.append(reversed_validity)

        for document in cases:
            with (
                self.subTest(case=id(document)),
                self.assertRaises(SnapshotValidationError) as raised,
            ):
                self.adapter().parse(document, evaluation_timestamp=EVALUATION)
            self.assertEqual(raised.exception.code, "chronology_violation")

    def test_observation_knowledge_time_is_bounded_by_root_retrieval(self) -> None:
        document = bundle()
        document["items"][0]["observations"][0]["fetched_at"] = (  # type: ignore[index]
            "2026-08-18T00:00:00Z"
        )
        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "chronology_violation")

    def test_observation_as_of_cannot_follow_its_publication(self) -> None:
        document = bundle()
        disclosed = document["items"][0]["observations"][0]  # type: ignore[index]
        disclosed["as_of"] = "2026-08-16T12:00:00Z"
        disclosed["valid_from"] = disclosed["as_of"]
        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "chronology_violation")

    def test_complete_corporate_action_revision_may_correct_effective_at(self) -> None:
        document = bundle()
        action = document["items"][6]  # type: ignore[index]
        old_effective = "2026-08-15T00:00:00Z"
        corrected_effective = "2026-08-25T08:00:00+08:00"
        for disclosed_field in action["observations"]:
            disclosed_field["valid_to"] = "2026-08-20T00:00:00Z"

        revision = deepcopy(action["observations"])
        for disclosed_field in revision:
            disclosed_field["observation_id"] += "-corrected"
            disclosed_field["as_of"] = "2026-08-16T08:00:00+08:00"
            disclosed_field["published_at"] = "2026-08-16T01:00:00Z"
            disclosed_field["valid_from"] = corrected_effective
            disclosed_field["valid_to"] = None
            if disclosed_field["field"] == "effective_at":
                disclosed_field["raw_value"] = "2026-08-24T19:00:00-05:00"
        action["observations"].extend(revision)

        records = self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        action_records = [
            record for record in records if record["entity_type"] == "corporate_action"
        ]

        self.assertEqual(len(action_records), 8)
        self.assertEqual(
            {
                record["effective_status"]
                for record in action_records
                if record["valid_from"] == old_effective
            },
            {"expired"},
        )
        self.assertEqual(
            {
                record["effective_status"]
                for record in action_records
                if record["valid_from"] == corrected_effective
            },
            {"future"},
        )

    def test_corporate_action_revision_must_be_complete(self) -> None:
        document = bundle()
        action = document["items"][6]  # type: ignore[index]
        revision = deepcopy(action["observations"][:-1])
        for disclosed_field in revision:
            disclosed_field["observation_id"] += "-incomplete-revision"
            disclosed_field["as_of"] = "2026-08-16T00:00:00Z"
            disclosed_field["published_at"] = "2026-08-16T01:00:00Z"
            disclosed_field["valid_from"] = "2026-08-25T00:00:00Z"
            if disclosed_field["field"] == "effective_at":
                disclosed_field["raw_value"] = "2026-08-25T00:00:00Z"
        action["observations"].extend(revision)

        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)

        self.assertEqual(raised.exception.code, "missing_item_field")

    def test_corporate_action_equivalent_as_of_offset_conflict_fails_closed(
        self,
    ) -> None:
        document = bundle()
        action = document["items"][6]  # type: ignore[index]
        conflicting_effective = deepcopy(action["observations"][1])
        conflicting_effective["observation_id"] += "-equivalent-offset-conflict"
        conflicting_effective["as_of"] = "2026-08-15T08:00:00+08:00"
        conflicting_effective["raw_value"] = "2026-08-25T00:00:00Z"
        conflicting_effective["valid_from"] = "2026-08-25T00:00:00Z"
        action["observations"].append(conflicting_effective)

        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)

        self.assertEqual(raised.exception.code, "silent_conflict")

    def test_corporate_action_effective_at_binds_every_observation_valid_from(
        self,
    ) -> None:
        document = bundle()
        action = document["items"][6]  # type: ignore[index]
        action["observations"][1]["raw_value"] = "2026-09-15T00:00:00Z"
        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "invalid_corporate_action")

    def test_hostile_evaluation_timezone_fails_with_stable_redacted_error(self) -> None:
        from datetime import timedelta, tzinfo

        marker = "PRIVATE-TIMEZONE-MARKER"

        class HostileTimezone(tzinfo):
            def utcoffset(self, value: datetime | None) -> timedelta:
                raise RuntimeError(marker)

            def dst(self, value: datetime | None) -> timedelta:
                return timedelta(0)

        evaluation = datetime(2026, 8, 21, tzinfo=HostileTimezone())
        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(bundle(), evaluation_timestamp=evaluation)
        self.assertEqual(raised.exception.code, "invalid_evaluation_timestamp")
        self.assertNotIn(marker, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_hostile_mapping_iteration_is_bounded_before_materialization(self) -> None:
        from collections.abc import Iterator, Mapping

        class OversupplyingMapping(Mapping[str, object]):
            def __init__(self) -> None:
                self.items_requested = 0

            def __getitem__(self, key: str) -> object:
                raise KeyError(key)

            def __iter__(self) -> Iterator[str]:
                return iter(())

            def __len__(self) -> int:
                return 1

            def items(self) -> Iterator[tuple[str, object]]:  # type: ignore[override]
                while True:
                    self.items_requested += 1
                    if self.items_requested > 2:
                        raise AssertionError(
                            "mapping iterator consumed past declared bound"
                        )
                    yield (f"key-{self.items_requested}", None)

        document = OversupplyingMapping()
        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "snapshot_too_complex")
        self.assertLessEqual(document.items_requested, 2)
        self.assertNotIn("mapping iterator", str(raised.exception))

    def test_hostile_mapping_entries_are_safely_unpacked_and_redacted(self) -> None:
        from collections.abc import Iterator, Mapping

        marker = "PRIVATE-ENTRY-MARKER"

        class ExplodingEntry:
            def __iter__(self) -> Iterator[object]:
                raise RuntimeError(marker)

        class EntryMapping(Mapping[str, object]):
            def __init__(self, entry: object) -> None:
                self.entry = entry

            def __getitem__(self, key: str) -> object:
                raise KeyError(key)

            def __iter__(self) -> Iterator[str]:
                return iter(())

            def __len__(self) -> int:
                return 1

            def items(self) -> Iterator[object]:  # type: ignore[override]
                yield self.entry

        for entry in (ExplodingEntry(), ("a", None, marker)):
            with self.subTest(entry_type=type(entry).__name__):
                with self.assertRaises(SnapshotValidationError) as raised:
                    self.adapter().parse(
                        EntryMapping(entry), evaluation_timestamp=EVALUATION
                    )
                self.assertEqual(raised.exception.code, "snapshot_too_complex")
                self.assertNotIn(marker, str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)

    def test_bytes_and_path_subclasses_cannot_execute_overridden_io_methods(
        self,
    ) -> None:
        marker = "PRIVATE-BOUNDARY-MARKER"

        class HostileBytes(bytes):
            def decode(self, *args: object, **kwargs: object) -> str:
                raise RuntimeError(marker)

        class HostilePath(type(Path())):
            def open(self, *args: object, **kwargs: object) -> object:
                raise RuntimeError(marker)

        cases = (
            HostileBytes(json.dumps(bundle()).encode()),
            HostilePath(f"/{marker}.json"),
        )
        for source in cases:
            with self.subTest(source_type=type(source).__name__):
                with self.assertRaises(SnapshotValidationError) as raised:
                    self.adapter().parse(source, evaluation_timestamp=EVALUATION)
                self.assertNotIn(marker, str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)

    def test_hostile_mapping_base_exceptions_are_not_swallowed(self) -> None:
        from collections.abc import Iterator, Mapping

        class InterruptingMapping(Mapping[str, object]):
            def __getitem__(self, key: str) -> object:
                raise KeyError(key)

            def __iter__(self) -> Iterator[str]:
                return iter(())

            def __len__(self) -> int:
                return 1

            def items(self) -> Iterator[tuple[str, object]]:  # type: ignore[override]
                raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            self.adapter().parse(InterruptingMapping(), evaluation_timestamp=EVALUATION)

    def test_offline_cli_emits_only_canonical_json_and_never_uses_network(self) -> None:
        import io
        from contextlib import redirect_stderr, redirect_stdout

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            snapshot_path = root / "snapshot.json"
            entitlement_path = root / "entitlements.json"
            source = bundle()
            source["rights"]["reviewed_at"] = "2026-08-19T19:00:00-05:00"  # type: ignore[index]
            source["rights"]["valid_until"] = "2026-08-31T19:00:00-05:00"  # type: ignore[index]
            nav = source["items"][1]  # type: ignore[index]
            original = nav["observations"][1]
            original["quality_state"] = "conflict"
            original["conflict_group"] = "cli-nav-conflict"
            alternative = deepcopy(original)
            alternative["observation_id"] = "nav-a-2-cli-alternative"
            alternative["raw_value"] = 1.02
            alternative["as_of"] = "2026-08-15T08:00:00+08:00"
            alternative["valid_from"] = "2026-08-14T19:00:00-05:00"
            nav["observations"].append(alternative)
            snapshot_path.write_text(
                json.dumps(source, ensure_ascii=False), encoding="utf-8"
            )
            entitlement_path.write_text(
                json.dumps(entitlement_document()), encoding="utf-8"
            )
            output = io.StringIO()
            stderr = io.StringIO()
            with (
                patch(
                    "socket.create_connection", side_effect=AssertionError("network")
                ),
                redirect_stdout(output),
                redirect_stderr(stderr),
            ):
                exit_code = main(
                    [
                        "provider",
                        "mainland-parse",
                        str(snapshot_path),
                        "--entitlements",
                        str(entitlement_path),
                        "--evaluation-timestamp",
                        "2026-08-21T00:00:00Z",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        document = json.loads(output.getvalue())
        self.assertIsInstance(document, list)
        self.assertEqual(len(document), 20)
        self.assertTrue(
            all(
                record["rights"]["reviewed_at"] == "2026-08-19T19:00:00-05:00"
                and record["rights"]["valid_until"] == "2026-08-31T19:00:00-05:00"
                for record in document
            )
        )
        nav_records = [record for record in document if record["field"] == "nav"]
        self.assertEqual([record["value"] for record in nav_records], [1.0, 1.01, 1.02])
        self.assertEqual(
            output.getvalue(),
            json.dumps(
                document,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
        )

    def test_cli_rejects_invalid_tenure_dates_with_redacted_stderr(self) -> None:
        import io
        from contextlib import redirect_stderr, redirect_stdout

        marker = "PRIVATE-DATE-PATH-MARKER"
        cases = (
            ("2024-W01-1", "snapshot_schema"),
            ("2023-02-29", "invalid_item"),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            snapshot_path = root / f"{marker}.json"
            entitlement_path = root / "entitlements.json"
            entitlement_path.write_text(
                json.dumps(entitlement_document()), encoding="utf-8"
            )
            for invalid_date, code in cases:
                document = bundle()
                document["items"][3]["observations"][2][  # type: ignore[index]
                    "raw_value"
                ] = invalid_date
                snapshot_path.write_text(
                    json.dumps(document, ensure_ascii=False), encoding="utf-8"
                )
                errors: list[str] = []
                for _ in range(2):
                    output = io.StringIO()
                    stderr = io.StringIO()
                    with redirect_stdout(output), redirect_stderr(stderr):
                        exit_code = main(
                            [
                                "provider",
                                "mainland-parse",
                                str(snapshot_path),
                                "--entitlements",
                                str(entitlement_path),
                                "--evaluation-timestamp",
                                "2026-08-21T00:00:00Z",
                            ]
                        )
                    self.assertEqual(exit_code, 2)
                    self.assertEqual(output.getvalue(), "")
                    self.assertIn(f": {code}: ", stderr.getvalue())
                    self.assertNotIn(invalid_date, stderr.getvalue())
                    self.assertNotIn(marker, stderr.getvalue())
                    self.assertNotIn(temporary_directory, stderr.getvalue())
                    errors.append(stderr.getvalue())
                self.assertEqual(errors[0], errors[1])

    def test_cli_rejects_non_utf8_with_deterministic_redacted_stderr(self) -> None:
        import io
        from contextlib import redirect_stderr, redirect_stdout

        marker = "PRIVATE-CLI-BYTES-MARKER"
        errors: list[str] = []
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            snapshot_path = root / f"{marker}.json"
            entitlement_path = root / "entitlements.json"
            snapshot_path.write_bytes(b"\xff" + marker.encode())
            entitlement_path.write_text(
                json.dumps(entitlement_document()), encoding="utf-8"
            )
            for _ in range(2):
                output = io.StringIO()
                stderr = io.StringIO()
                with (
                    patch(
                        "socket.create_connection",
                        side_effect=AssertionError("network"),
                    ),
                    redirect_stdout(output),
                    redirect_stderr(stderr),
                ):
                    exit_code = main(
                        [
                            "provider",
                            "mainland-parse",
                            str(snapshot_path),
                            "--entitlements",
                            str(entitlement_path),
                            "--evaluation-timestamp",
                            "2026-08-21T00:00:00Z",
                        ]
                    )
                self.assertEqual(exit_code, 2)
                self.assertEqual(output.getvalue(), "")
                self.assertNotIn(marker, stderr.getvalue())
                errors.append(stderr.getvalue())
        self.assertEqual(errors[0], errors[1])
        self.assertEqual(
            errors[0],
            "openfundscore: error: $document: snapshot_format: "
            "snapshot must be strict UTF-8 JSON\n",
        )

    def test_cli_entitlements_are_required_and_failures_do_not_echo_paths(self) -> None:
        import io
        from contextlib import redirect_stderr, redirect_stdout

        marker = "PRIVATE-PATH-MARKER"
        output = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(output), redirect_stderr(stderr):
            exit_code = main(
                [
                    "provider",
                    "mainland-parse",
                    f"/private/{marker}.json",
                    "--entitlements",
                    f"/private/{marker}-rights.json",
                    "--evaluation-timestamp",
                    "2026-08-21T00:00:00Z",
                ]
            )
        self.assertEqual(exit_code, 2)
        self.assertEqual(output.getvalue(), "")
        self.assertNotIn(marker, stderr.getvalue())
        self.assertNotIn("/private/", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_external_identifier_values_are_not_compared_to_entity_ids(self) -> None:
        document = bundle()
        document["items"][0]["exact_identifiers"][0]["value"] = "similar display name"  # type: ignore[index]
        records = self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertEqual(records[0]["entity_id"], "share-a")
        self.assertEqual(
            records[0]["exact_identifiers"][0]["value"],  # type: ignore[index]
            "similar display name",
        )

    def test_identifier_values_are_preserved_codepoint_exactly(self) -> None:
        variants = (
            "share-a display name",
            "SHARE-A",
            "ｓｈａｒｅ－ａ",
            "shаre-a",  # Cyrillic small a at index 2.
        )
        for value in variants:
            document = bundle()
            document["items"][0]["exact_identifiers"][0]["value"] = value  # type: ignore[index]
            records = self.adapter().parse(document, evaluation_timestamp=EVALUATION)
            with self.subTest(value=value):
                self.assertEqual(
                    records[0]["exact_identifiers"][0]["value"],  # type: ignore[index]
                    value,
                )

    def test_entity_and_exact_identifier_values_require_substantive_codepoints(
        self,
    ) -> None:
        for value in (" ", "\t\n", "\u200b", "\u2060", "\ufeff"):
            for target in ("entity_id", "identifier"):
                document = bundle()
                if target == "entity_id":
                    document["items"][0]["entity_id"] = value  # type: ignore[index]
                else:
                    document["items"][0]["exact_identifiers"][0]["value"] = value  # type: ignore[index]
                with self.subTest(value=repr(value), target=target):
                    with self.assertRaises(SnapshotValidationError) as raised:
                        self.adapter().parse(document, evaluation_timestamp=EVALUATION)
                    self.assertEqual(raised.exception.code, "invalid_identifier")

    def test_duplicate_exact_identifier_is_rejected_deterministically(self) -> None:
        document = bundle()
        duplicate = deepcopy(document["items"][0]["exact_identifiers"][0])  # type: ignore[index]
        document["items"][0]["exact_identifiers"].append(duplicate)  # type: ignore[index]
        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "duplicate_identifier")
        self.assertEqual(raised.exception.path, "$.items.exact_identifiers")

    def test_identifier_schemes_are_closed_to_reliable_official_schemes(self) -> None:
        document = bundle()
        document["items"][0]["exact_identifiers"][0]["scheme"] = "display_name"  # type: ignore[index]
        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "snapshot_schema")

    def test_multiple_reliable_identifier_schemes_may_have_distinct_values(
        self,
    ) -> None:
        document = bundle()
        document["items"][0]["exact_identifiers"].append(  # type: ignore[index]
            {
                "scheme": "cn_fund_code",
                "value": "different-exact-id",
                "jurisdiction": "CN",
            }
        )
        records = self.adapter().parse(document, evaluation_timestamp=EVALUATION)
        self.assertEqual(len(records[0]["exact_identifiers"]), 2)  # type: ignore[arg-type]

    def test_missing_holding_fields_and_malformed_entitlement_enums_are_stable(
        self,
    ) -> None:
        missing = bundle()
        missing["items"][5]["observations"][0]["field"] = "unexpected"  # type: ignore[index]
        with self.assertRaises(SnapshotValidationError) as holding_error:
            self.adapter().parse(missing, evaluation_timestamp=EVALUATION)
        self.assertEqual(holding_error.exception.code, "missing_item_field")
        self.assertIsNone(holding_error.exception.__context__)

        malformed_entitlements = entitlement_document()
        malformed_entitlements["source_type"] = []
        from openfundscore.mainland_official import load_mainland_entitlements

        with self.assertRaises(SnapshotValidationError) as entitlement_error:
            load_mainland_entitlements(malformed_entitlements)
        self.assertEqual(entitlement_error.exception.code, "invalid_entitlements")
        self.assertIsNone(entitlement_error.exception.__context__)

    def test_adapter_structural_guards_never_depend_on_python_assertions(self) -> None:
        cases: list[tuple[str, dict[str, object]]] = []

        bad_source = bundle()
        bad_source["source_type"] = []
        cases.append(("source", bad_source))

        bad_rights = bundle()
        bad_rights["rights"] = []
        cases.append(("rights", bad_rights))

        bad_items = bundle()
        bad_items["items"] = {}
        cases.append(("items", bad_items))

        bad_item = bundle()
        bad_item["items"][0] = []  # type: ignore[index]
        cases.append(("item", bad_item))

        bad_observations = bundle()
        bad_observations["items"][0]["observations"] = {}  # type: ignore[index]
        cases.append(("observations", bad_observations))

        bad_units = bundle()
        bad_units["units"] = []
        cases.append(("units", bad_units))

        with patch.object(
            MainlandOfficialSnapshotAdapter, "_validate_schema", return_value=None
        ):
            for label, document in cases:
                with (
                    self.subTest(label=label),
                    self.assertRaises(SnapshotValidationError) as raised,
                ):
                    self.adapter().parse(document, evaluation_timestamp=EVALUATION)
                self.assertEqual(raised.exception.code, "snapshot_schema")
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)

    def test_malformed_structural_values_fail_closed_without_python_type_errors(
        self,
    ) -> None:
        malformed = bundle()
        malformed["items"][5]["observations"][0]["raw_value"] = []  # type: ignore[index]
        with self.assertRaises(SnapshotValidationError) as raised:
            self.adapter().parse(malformed, evaluation_timestamp=EVALUATION)
        self.assertEqual(raised.exception.code, "invalid_holding")
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_holding_snapshot_totals_and_declared_bundle_units_are_reconciled(
        self,
    ) -> None:
        second_position = bundle()
        second = deepcopy(second_position["items"][5])  # type: ignore[index]
        second["item_id"] = "06-holding-second"
        second["entity_id"] = "holding-2"
        second["exact_identifiers"][0]["value"] = "holding-2"
        for field in second["observations"]:
            field["observation_id"] += "-second"
            if field["field"] == "instrument_id":
                field["raw_value"] = "CN-SYN-2"
            if field["field"] == "weight":
                field["raw_value"] = 5000
        second_position["items"].append(second)  # type: ignore[union-attr]

        mismatched_unit = bundle()
        mismatched_unit["units"]["weight"] = "percent"  # type: ignore[index]
        mismatched_unit["units"]["coverage"] = "percent"  # type: ignore[index]

        for document in (second_position, mismatched_unit):
            with self.subTest(case=id(document)):
                with self.assertRaises(SnapshotValidationError) as raised:
                    self.adapter().parse(document, evaluation_timestamp=EVALUATION)
                self.assertEqual(raised.exception.code, "invalid_holding")

    def test_mainland_adapter_api_is_exported_from_package_top_level(self) -> None:
        import openfundscore

        self.assertIn("MainlandOfficialSnapshotAdapter", openfundscore.__all__)
        self.assertIn("SnapshotValidationError", openfundscore.__all__)
        self.assertIn("load_mainland_entitlements", openfundscore.__all__)
        self.assertIs(
            openfundscore.MainlandOfficialSnapshotAdapter,
            MainlandOfficialSnapshotAdapter,
        )
        self.assertIs(openfundscore.SnapshotValidationError, SnapshotValidationError)
        self.assertTrue(callable(openfundscore.load_mainland_entitlements))

    def test_packaged_synthetic_snapshot_fixture_covers_share_classes_lifecycle_and_conflicts(
        self,
    ) -> None:
        from openfundscore.fixtures import synthetic_mainland_snapshot_bundle

        first = synthetic_mainland_snapshot_bundle()
        second = synthetic_mainland_snapshot_bundle()
        self.assertEqual(first, second)
        first["snapshot_id"] = "mutated"
        self.assertNotEqual(first, second)

        records = self.adapter().parse(second, evaluation_timestamp=EVALUATION)
        class_codes = {
            record["value"] for record in records if record["field"] == "class_code"
        }
        action_types = {
            record["value"] for record in records if record["field"] == "action_type"
        }
        conflicts = [
            record for record in records if record["quality_state"] == "conflict"
        ]
        self.assertEqual(class_codes, {"A", "C"})
        self.assertEqual(action_types, {"closed", "merged", "transformed"})
        self.assertEqual(len(conflicts), 2)
        self.assertTrue(
            all(record["as_of"] < record["published_at"] for record in records)
        )


if __name__ == "__main__":
    unittest.main()
