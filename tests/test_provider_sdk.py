from __future__ import annotations

import os
import time
import unittest
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import cast
from zoneinfo import ZoneInfo

from openfundscore import provider_sdk
from openfundscore.provider_sdk import (
    AuthenticationMode,
    DataUse,
    IngestionDenied,
    IngestionRequest,
    ProviderAdapter,
    ProviderCapability,
    ProviderContractError,
    ProviderEntitlements,
    RateLimit,
    RateLimitBudget,
    RightsMode,
    SourceType,
    authorize_ingestion,
)
from tests.test_record_validation import provider_record

EVALUATED_AT = datetime(2026, 8, 21, tzinfo=UTC)


class ExplodingTimezone(tzinfo):
    def utcoffset(self, dt):
        raise RuntimeError("PRIVATE-TZINFO-SENTINEL")

    def dst(self, dt):
        return None

    def tzname(self, dt):
        return "exploding"


class StatefulTimezone(tzinfo):
    def __init__(self) -> None:
        self.calls = 0

    def utcoffset(self, dt):
        self.calls += 1
        if self.calls == 1:
            return timedelta(0)
        raise RuntimeError("PRIVATE-STATEFUL-TZ-SENTINEL")

    def dst(self, dt):
        return None

    def tzname(self, dt):
        return "stateful"


class ExplodingWideList(list):
    def __getitem__(self, index):
        raise RuntimeError("PRIVATE-CONTAINER-ACCESS-SENTINEL")


class AllContainsFrozenSet(frozenset):
    def __contains__(self, item) -> bool:
        return True


class ForgedIterationFrozenSet(frozenset):
    forged: tuple[object, ...]

    def __new__(cls, actual, forged):
        instance = super().__new__(cls, actual)
        instance.forged = tuple(forged)
        return instance

    def __iter__(self):
        return iter(self.forged)


class AlwaysEqualStr(str):
    __hash__ = str.__hash__

    def __eq__(self, other) -> bool:
        return True

    def __ne__(self, other) -> bool:
        return False


class LyingStr(str):
    def __str__(self) -> str:
        return "provider-1"


class LyingInt(int):
    def __int__(self) -> int:
        return 7


class SplitRights(dict):
    def __init__(self, actual: dict, forged: dict) -> None:
        super().__init__(actual)
        self.forged = forged

    def get(self, key, default=None):
        return self.forged.get(key, default)


def entitlements(**changes: object) -> ProviderEntitlements:
    values: dict[str, object] = {
        "provider_id": "provider-1",
        "evaluated_at": EVALUATED_AT,
        "valid_until": datetime(2026, 8, 22, tzinfo=UTC),
        "source_type": SourceType.REGULATOR,
        "jurisdictions": frozenset({"CN"}),
        "authentication_mode": AuthenticationMode.NONE,
        "capabilities": frozenset(
            {
                ProviderCapability.GET_ENTITLEMENTS,
                ProviderCapability.GET_PROFILE,
            }
        ),
        "rights_mode": RightsMode.OPEN_REDISTRIBUTABLE,
        "cache_allowed": True,
        "cache_ttl_seconds": 3600,
        "derived_works_allowed": True,
        "public_display_allowed": True,
        "redistribution_allowed": True,
        "retention_days": 7,
        "attribution_required": True,
        "terms_url": "https://example.com/terms",
        "rights_reviewed_at": datetime(2026, 8, 20, tzinfo=UTC),
        "rate_limit": RateLimit(requests_per_period=10, period_seconds=60, burst=2),
    }
    values.update(changes)
    return ProviderEntitlements(**values)  # type: ignore[arg-type]


def record() -> dict:
    document = provider_record()
    document["rights"].update(
        {
            "terms_url": "https://example.com/terms",
            "retention_days": 7,
            "reviewed_at": "2026-08-20T00:00:00Z",
        }
    )
    return document


def record_for(value: ProviderEntitlements) -> dict:
    document = record()
    document["provider_id"] = value.provider_id
    document["source_type"] = value.source_type.value
    document["jurisdiction"] = min(value.jurisdictions)
    document["rights"] = {
        "mode": value.rights_mode.value,
        "terms_url": value.terms_url,
        "cache_allowed": value.cache_allowed,
        "derived_works_allowed": value.derived_works_allowed,
        "redistribution_allowed": value.redistribution_allowed,
        "attribution_required": value.attribution_required,
        "public_display_allowed": value.public_display_allowed,
        "retention_days": value.retention_days,
        "reviewed_at": (
            value.rights_reviewed_at.isoformat().replace("+00:00", "Z")
            if value.rights_reviewed_at is not None
            else None
        ),
    }
    return document


class LocalProvider:
    provider_id = "provider-1"
    capabilities = frozenset(
        {
            ProviderCapability.GET_ENTITLEMENTS,
            ProviderCapability.GET_PROFILE,
        }
    )

    def __init__(self, value: ProviderEntitlements | None = None) -> None:
        self.value = value or entitlements()
        self.calls: list[datetime] = []

    def get_entitlements(
        self,
        *,
        evaluation_timestamp: datetime,
    ) -> ProviderEntitlements:
        self.calls.append(evaluation_timestamp)
        return self.value


class FailingProvider(LocalProvider):
    def get_entitlements(
        self,
        *,
        evaluation_timestamp: datetime,
    ) -> ProviderEntitlements:
        raise RuntimeError("PRIVATE-ENTITLEMENT-SENTINEL")


class MalformedProvider(LocalProvider):
    def get_entitlements(  # type: ignore[override]
        self,
        *,
        evaluation_timestamp: datetime,
    ) -> object:
        return {"token": "PRIVATE-ENTITLEMENT-SENTINEL"}


class ProviderSdkTests(unittest.TestCase):
    def test_public_api_is_explicit(self) -> None:
        self.assertEqual(
            set(provider_sdk.__all__),
            {
                "AuthenticationMode",
                "DataUse",
                "IngestionAuthorization",
                "IngestionDenied",
                "IngestionRequest",
                "ProviderAdapter",
                "ProviderCapability",
                "ProviderContractError",
                "ProviderEntitlements",
                "RateLimit",
                "RateLimitBudget",
                "RightsMode",
                "SourceType",
                "authorize_ingestion",
            },
        )

    def _authorize(
        self,
        value: ProviderEntitlements,
        *,
        document: dict | None = None,
        provider: LocalProvider | None = None,
        schema_version: str = "0.1.0",
        evaluation_timestamp: datetime = EVALUATED_AT,
        request: IngestionRequest | None = None,
        budget: RateLimitBudget | None = None,
    ):
        selected_provider = provider or LocalProvider(value)
        return authorize_ingestion(
            selected_provider,
            document or record_for(value),
            schema_version=schema_version,
            evaluation_timestamp=evaluation_timestamp,
            request=request
            or IngestionRequest(capability=ProviderCapability.GET_PROFILE),
            rate_limit_budget=budget
            or RateLimitBudget(
                provider_id="provider-1",
                period_started_at=evaluation_timestamp,
                requests_used=0,
            ),
        )

    def _provider_record_v2(self, value: ProviderEntitlements) -> dict:
        document = record_for(value)
        document["exact_identifiers"] = [
            {
                "scheme": "official_entity_id",
                "value": "official:benchmark-1",
                "jurisdiction": "CN",
            }
        ]
        document["effective_status"] = "current"
        return document

    def test_typed_provider_contract_authorizes_valid_local_ingestion(self) -> None:
        provider = LocalProvider()
        self.assertIsInstance(provider, ProviderAdapter)

        document = record()
        snapshot = deepcopy(document)
        authorization = authorize_ingestion(
            provider,
            document,
            schema_version="0.1.0",
            evaluation_timestamp=EVALUATED_AT,
            request=IngestionRequest(
                capability=ProviderCapability.GET_PROFILE,
                uses=frozenset(
                    {
                        DataUse.CACHE,
                        DataUse.DERIVED_WORK,
                        DataUse.DISPLAY,
                        DataUse.REDISTRIBUTION,
                    }
                ),
                cache_ttl_seconds=1800,
                attribution_ready=True,
            ),
            rate_limit_budget=RateLimitBudget(
                provider_id="provider-1",
                period_started_at=EVALUATED_AT,
                requests_used=1,
            ),
        )

        self.assertEqual(provider.calls, [EVALUATED_AT])
        self.assertEqual(authorization.provider_id, "provider-1")
        self.assertEqual(authorization.evaluated_at, EVALUATED_AT)
        self.assertEqual(authorization.requests_remaining, 8)
        self.assertEqual(
            authorization.cache_expires_at,
            datetime(2026, 8, 21, 0, 30, tzinfo=UTC),
        )
        self.assertEqual(
            authorization.retain_until,
            datetime(2026, 8, 28, tzinfo=UTC),
        )
        self.assertTrue(authorization.attribution_required)
        self.assertEqual(document, snapshot)

    def test_unknown_rights_mode_is_blocked_by_typed_entitlements(self) -> None:
        with self.assertRaises(ProviderContractError) as raised:
            entitlements(
                rights_mode=RightsMode.UNKNOWN_BLOCKED,
                cache_allowed=True,
                cache_ttl_seconds=60,
                derived_works_allowed=False,
                public_display_allowed=False,
                redistribution_allowed=False,
                attribution_required=False,
            )

        self.assertEqual(raised.exception.code, "rights_mismatch")
        self.assertEqual(raised.exception.path, "$.cache_allowed")
        self.assertNotIn("provider-1", str(raised.exception))

    def test_rate_limit_requires_positive_non_boolean_integers(self) -> None:
        for changes, path in (
            ({"requests_per_period": 0, "period_seconds": 60}, "$.requests_per_period"),
            (
                {"requests_per_period": True, "period_seconds": 60},
                "$.requests_per_period",
            ),
            ({"requests_per_period": 10, "period_seconds": 0}, "$.period_seconds"),
            (
                {"requests_per_period": 10, "period_seconds": 60, "burst": False},
                "$.burst",
            ),
        ):
            with self.subTest(path=path):
                with self.assertRaises(ProviderContractError) as raised:
                    RateLimit(**changes)  # type: ignore[arg-type]
                self.assertEqual(raised.exception.code, "invalid_rate_limit")
                self.assertEqual(raised.exception.path, path)

    def test_entitlements_require_point_in_time_contract_identity(self) -> None:
        cases = (
            ({"provider_id": "   "}, "$.provider_id"),
            ({"evaluated_at": EVALUATED_AT.replace(tzinfo=None)}, "$.evaluated_at"),
            ({"valid_until": EVALUATED_AT}, "$.valid_until"),
            (
                {"rights_reviewed_at": datetime(2026, 8, 22, tzinfo=UTC)},
                "$.rights_reviewed_at",
            ),
            ({"jurisdictions": frozenset()}, "$.jurisdictions"),
            (
                {"capabilities": frozenset({ProviderCapability.GET_PROFILE})},
                "$.capabilities",
            ),
        )
        for changes, path in cases:
            with self.subTest(path=path):
                with self.assertRaises(ProviderContractError) as raised:
                    entitlements(**changes)
                self.assertEqual(raised.exception.path, path)

    def test_entitlement_modes_and_cache_limits_are_fail_closed(self) -> None:
        cases = (
            (
                {
                    "rights_mode": RightsMode.DERIVED_ONLY,
                    "derived_works_allowed": False,
                    "redistribution_allowed": False,
                },
                "$.derived_works_allowed",
            ),
            (
                {
                    "rights_mode": RightsMode.DISPLAY_ONLY,
                    "cache_allowed": False,
                    "cache_ttl_seconds": None,
                    "derived_works_allowed": True,
                    "public_display_allowed": True,
                    "redistribution_allowed": False,
                },
                "$.derived_works_allowed",
            ),
            (
                {
                    "rights_mode": RightsMode.LOCAL_ENTITLEMENT,
                    "public_display_allowed": False,
                    "redistribution_allowed": True,
                },
                "$.redistribution_allowed",
            ),
            (
                {
                    "rights_mode": RightsMode.OPEN_REDISTRIBUTABLE,
                    "redistribution_allowed": False,
                },
                "$.redistribution_allowed",
            ),
            (
                {"cache_allowed": False, "cache_ttl_seconds": 60},
                "$.cache_ttl_seconds",
            ),
            (
                {"cache_ttl_seconds": None, "retention_days": None},
                "$.cache_allowed",
            ),
            ({"cache_ttl_seconds": 0}, "$.cache_ttl_seconds"),
            ({"retention_days": -1}, "$.retention_days"),
        )
        for changes, path in cases:
            with self.subTest(path=path, changes=changes):
                with self.assertRaises(ProviderContractError) as raised:
                    entitlements(**changes)
                self.assertEqual(raised.exception.path, path)

    def test_ingestion_requires_record_to_match_point_in_time_entitlements(
        self,
    ) -> None:
        value = entitlements()
        cases = (
            ("provider_id", "provider-2", "$.provider_id"),
            ("source_type", "commercial_vendor", "$.source_type"),
            ("jurisdiction", "JP", "$.jurisdiction"),
            ("mode", "derived_only", "$.rights.mode"),
            ("cache_allowed", False, "$.rights.cache_allowed"),
            ("derived_works_allowed", False, "$.rights.derived_works_allowed"),
            ("public_display_allowed", False, "$.rights.public_display_allowed"),
            ("redistribution_allowed", False, "$.rights.redistribution_allowed"),
            ("attribution_required", False, "$.rights.attribution_required"),
            ("retention_days", 6, "$.rights.retention_days"),
            ("terms_url", "https://example.com/other", "$.rights.terms_url"),
            ("reviewed_at", "2026-08-19T00:00:00Z", "$.rights.reviewed_at"),
        )
        for field, replacement, path in cases:
            with self.subTest(path=path):
                document = record_for(value)
                if field in {"provider_id", "source_type", "jurisdiction"}:
                    document[field] = replacement
                else:
                    document["rights"][field] = replacement
                    if field == "mode":
                        document["rights"]["derived_works_allowed"] = True
                        document["rights"]["public_display_allowed"] = False
                        document["rights"]["redistribution_allowed"] = False
                with self.assertRaises(IngestionDenied) as raised:
                    self._authorize(value, document=document)
                expected_code = (
                    "invalid_provider_record"
                    if field == "redistribution_allowed"
                    else "record_contract_mismatch"
                )
                self.assertEqual(raised.exception.code, expected_code)
                self.assertEqual(raised.exception.path, path)

    def test_provider_record_v2_valid_until_must_match_entitlement_instant(
        self,
    ) -> None:
        value = entitlements()
        document = self._provider_record_v2(value)
        marker = "PRIVATE-RIGHTS-VALIDITY-MARKER"
        document["rights"]["valid_until"] = "2026-08-23T00:00:00Z"
        document["value"] = marker

        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(value, document=document, schema_version="0.2.0")

        self.assertEqual(raised.exception.code, "record_contract_mismatch")
        self.assertEqual(raised.exception.path, "$.rights.valid_until")
        self.assertNotIn(marker, str(raised.exception))
        self.assertNotIn("2026-08-23", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_provider_record_v2_accepts_equivalent_valid_until_offset_unchanged(
        self,
    ) -> None:
        value = entitlements()
        document = self._provider_record_v2(value)
        raw_valid_until = "2026-08-22T08:00:00+08:00"
        document["rights"]["valid_until"] = raw_valid_until
        snapshot = deepcopy(document)

        authorization = self._authorize(
            value,
            document=document,
            schema_version="0.2.0",
        )

        self.assertEqual(authorization.provider_id, value.provider_id)
        self.assertEqual(document, snapshot)
        self.assertEqual(document["rights"]["valid_until"], raw_valid_until)

    def test_provider_record_valid_until_remains_optional_in_v1_and_v2(self) -> None:
        value = entitlements()
        legacy = record_for(value)
        current = self._provider_record_v2(value)

        self.assertEqual(
            self._authorize(value, document=legacy).provider_id, "provider-1"
        )
        self.assertEqual(
            self._authorize(
                value,
                document=current,
                schema_version="0.2.0",
            ).provider_id,
            "provider-1",
        )

    def test_provider_record_v2_expired_valid_until_is_stably_redacted(self) -> None:
        value = entitlements()
        document = self._provider_record_v2(value)
        marker = "PRIVATE-EXPIRED-RIGHTS-MARKER"
        document["rights"]["valid_until"] = "2026-08-20T23:59:59.999999Z"
        document["value"] = marker

        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(value, document=document, schema_version="0.2.0")

        self.assertEqual(raised.exception.code, "invalid_provider_record")
        self.assertEqual(raised.exception.path, "$.rights.valid_until")
        self.assertNotIn(marker, str(raised.exception))
        self.assertNotIn("2026-08-20", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_provider_failures_and_malformed_entitlements_are_redacted(self) -> None:
        marker = "PRIVATE-ENTITLEMENT-SENTINEL"
        for provider in (FailingProvider(), MalformedProvider()):
            with self.subTest(provider=type(provider).__name__):
                with self.assertRaises(IngestionDenied) as raised:
                    authorize_ingestion(
                        cast(ProviderAdapter, provider),
                        record(),
                        schema_version="0.1.0",
                        evaluation_timestamp=EVALUATED_AT,
                        request=IngestionRequest(
                            capability=ProviderCapability.GET_PROFILE
                        ),
                        rate_limit_budget=RateLimitBudget(
                            provider_id="provider-1",
                            period_started_at=EVALUATED_AT,
                            requests_used=0,
                        ),
                    )
                self.assertEqual("entitlement_lookup_failed", raised.exception.code)
                self.assertEqual("$provider.entitlements", raised.exception.path)
                self.assertNotIn(marker, str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)

    def test_snapshot_must_match_adapter_and_exact_evaluation_instant(self) -> None:
        cases = (
            (
                LocalProvider(entitlements(provider_id="provider-other")),
                EVALUATED_AT,
                "$provider.provider_id",
            ),
            (
                LocalProvider(),
                EVALUATED_AT + timedelta(minutes=1),
                "$.evaluated_at",
            ),
        )
        for provider, evaluation_timestamp, path in cases:
            with self.subTest(path=path):
                with self.assertRaises(IngestionDenied) as raised:
                    authorize_ingestion(
                        provider,
                        record_for(provider.value),
                        schema_version="0.1.0",
                        evaluation_timestamp=evaluation_timestamp,
                        request=IngestionRequest(
                            capability=ProviderCapability.GET_PROFILE
                        ),
                        rate_limit_budget=RateLimitBudget(
                            provider_id="provider-1",
                            period_started_at=evaluation_timestamp,
                            requests_used=0,
                        ),
                    )
                self.assertEqual("entitlement_contract_mismatch", raised.exception.code)
                self.assertEqual(path, raised.exception.path)

    def test_requested_capability_must_be_supported_by_adapter_and_entitlements(
        self,
    ) -> None:
        value = entitlements()
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(
                value,
                request=IngestionRequest(capability=ProviderCapability.GET_NAV_SERIES),
            )
        self.assertEqual("capability_not_authorized", raised.exception.code)
        self.assertEqual("$request.capability", raised.exception.path)

    def test_request_and_budget_values_are_strict(self) -> None:
        constructors = (
            (
                lambda: IngestionRequest(
                    capability=ProviderCapability.GET_PROFILE,
                    request_count=0,
                ),
                ProviderContractError,
                "$.request_count",
            ),
            (
                lambda: IngestionRequest(
                    capability=ProviderCapability.GET_PROFILE,
                    request_count=True,
                ),
                ProviderContractError,
                "$.request_count",
            ),
            (
                lambda: IngestionRequest(
                    capability=ProviderCapability.GET_PROFILE,
                    cache_ttl_seconds=60,
                ),
                ProviderContractError,
                "$.cache_ttl_seconds",
            ),
            (
                lambda: RateLimitBudget(
                    provider_id="provider-1",
                    period_started_at=EVALUATED_AT,
                    requests_used=-1,
                ),
                ProviderContractError,
                "$.requests_used",
            ),
        )
        for constructor, error_type, path in constructors:
            with self.subTest(path=path):
                with self.assertRaises(error_type) as raised:
                    constructor()
                self.assertEqual(path, raised.exception.path)

    def test_rate_limit_period_burst_and_total_budget_are_enforced(self) -> None:
        cases = (
            (
                IngestionRequest(
                    capability=ProviderCapability.GET_PROFILE,
                    request_count=3,
                ),
                RateLimitBudget(
                    provider_id="provider-1",
                    period_started_at=EVALUATED_AT,
                    requests_used=0,
                ),
                "rate_limit_burst_exceeded",
                "$request.request_count",
            ),
            (
                IngestionRequest(
                    capability=ProviderCapability.GET_PROFILE,
                    request_count=2,
                ),
                RateLimitBudget(
                    provider_id="provider-1",
                    period_started_at=EVALUATED_AT,
                    requests_used=9,
                ),
                "rate_limit_exceeded",
                "$rate_limit_budget.requests_used",
            ),
            (
                IngestionRequest(capability=ProviderCapability.GET_PROFILE),
                RateLimitBudget(
                    provider_id="provider-1",
                    period_started_at=EVALUATED_AT - timedelta(seconds=60),
                    requests_used=0,
                ),
                "rate_limit_period_mismatch",
                "$rate_limit_budget.period_started_at",
            ),
            (
                IngestionRequest(capability=ProviderCapability.GET_PROFILE),
                RateLimitBudget(
                    provider_id="provider-1",
                    period_started_at=EVALUATED_AT + timedelta(seconds=1),
                    requests_used=0,
                ),
                "rate_limit_period_mismatch",
                "$rate_limit_budget.period_started_at",
            ),
        )
        for request, budget, code, path in cases:
            with self.subTest(code=code):
                with self.assertRaises(IngestionDenied) as raised:
                    self._authorize(
                        entitlements(),
                        request=request,
                        budget=budget,
                    )
                self.assertEqual(code, raised.exception.code)
                self.assertEqual(path, raised.exception.path)

    def test_cache_requests_are_explicit_and_cannot_exceed_contract_ttl(self) -> None:
        cases = (
            (None, "cache_ttl_required"),
            (3601, "cache_ttl_exceeded"),
        )
        for ttl, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(IngestionDenied) as raised:
                    self._authorize(
                        entitlements(),
                        request=IngestionRequest(
                            capability=ProviderCapability.GET_PROFILE,
                            uses=frozenset({DataUse.CACHE}),
                            cache_ttl_seconds=ttl,
                        ),
                    )
                self.assertEqual(code, raised.exception.code)
                self.assertEqual("$request.cache_ttl_seconds", raised.exception.path)

    def test_contract_requires_review_metadata_and_iso_jurisdictions(self) -> None:
        cases = (
            ({"terms_url": None}, "$.terms_url"),
            ({"rights_reviewed_at": None}, "$.rights_reviewed_at"),
            ({"jurisdictions": frozenset({"china"})}, "$.jurisdictions"),
        )
        for changes, path in cases:
            with self.subTest(path=path):
                with self.assertRaises(ProviderContractError) as raised:
                    entitlements(**changes)
                self.assertEqual(path, raised.exception.path)

    def test_rate_limit_budget_is_bound_to_provider_identity(self) -> None:
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(
                entitlements(),
                budget=RateLimitBudget(
                    provider_id="provider-other",
                    period_started_at=EVALUATED_AT,
                    requests_used=0,
                ),
            )
        self.assertEqual("rate_limit_budget_mismatch", raised.exception.code)
        self.assertEqual("$rate_limit_budget.provider_id", raised.exception.path)

        with self.assertRaises(ProviderContractError) as invalid:
            RateLimitBudget(
                provider_id=" ",
                period_started_at=EVALUATED_AT,
                requests_used=0,
            )
        self.assertEqual("$.provider_id", invalid.exception.path)

    def test_attribution_must_be_ready_before_authorized_use(self) -> None:
        request = IngestionRequest(
            capability=ProviderCapability.GET_PROFILE,
            uses=frozenset({DataUse.DERIVED_WORK}),
        )
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(entitlements(), request=request)
        self.assertEqual("attribution_not_ready", raised.exception.code)
        self.assertEqual("$request.attribution_ready", raised.exception.path)

        authorization = self._authorize(
            entitlements(),
            request=IngestionRequest(
                capability=ProviderCapability.GET_PROFILE,
                uses=frozenset({DataUse.DERIVED_WORK}),
                attribution_ready=True,
            ),
        )
        self.assertTrue(authorization.attribution_required)

    def test_ingestion_enforces_rights_mode_and_every_requested_use(self) -> None:
        blocked = entitlements(
            rights_mode=RightsMode.UNKNOWN_BLOCKED,
            cache_allowed=False,
            cache_ttl_seconds=None,
            derived_works_allowed=False,
            public_display_allowed=False,
            redistribution_allowed=False,
            attribution_required=False,
        )
        cases = (
            (blocked, frozenset(), "rights_mode_blocked", "$.rights.mode"),
            (
                entitlements(cache_allowed=False, cache_ttl_seconds=None),
                frozenset({DataUse.CACHE}),
                "use_not_authorized",
                "$request.uses.cache",
            ),
            (
                entitlements(
                    rights_mode=RightsMode.DISPLAY_ONLY,
                    cache_allowed=False,
                    cache_ttl_seconds=None,
                    derived_works_allowed=False,
                    public_display_allowed=True,
                    redistribution_allowed=False,
                ),
                frozenset({DataUse.DERIVED_WORK}),
                "use_not_authorized",
                "$request.uses.derived_work",
            ),
            (
                entitlements(
                    rights_mode=RightsMode.LOCAL_ENTITLEMENT,
                    public_display_allowed=False,
                    redistribution_allowed=False,
                ),
                frozenset({DataUse.DISPLAY}),
                "use_not_authorized",
                "$request.uses.display",
            ),
            (
                entitlements(
                    rights_mode=RightsMode.DERIVED_ONLY,
                    public_display_allowed=False,
                    redistribution_allowed=False,
                ),
                frozenset({DataUse.REDISTRIBUTION}),
                "use_not_authorized",
                "$request.uses.redistribution",
            ),
        )
        for value, uses, code, path in cases:
            with self.subTest(code=code, path=path):
                provider = LocalProvider(value)
                with self.assertRaises(IngestionDenied) as raised:
                    authorize_ingestion(
                        provider,
                        record_for(value),
                        schema_version="0.1.0",
                        evaluation_timestamp=EVALUATED_AT,
                        request=IngestionRequest(
                            capability=ProviderCapability.GET_PROFILE,
                            uses=uses,
                            cache_ttl_seconds=(60 if DataUse.CACHE in uses else None),
                        ),
                        rate_limit_budget=RateLimitBudget(
                            provider_id="provider-1",
                            period_started_at=EVALUATED_AT,
                            requests_used=0,
                        ),
                    )
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(raised.exception.path, path)

    def test_numeric_policies_are_bounded_before_datetime_arithmetic(self) -> None:
        cases = (
            (
                lambda: RateLimit(
                    requests_per_period=10,
                    period_seconds=10**13,
                ),
                "$.period_seconds",
            ),
            (
                lambda: entitlements(cache_ttl_seconds=10**13),
                "$.cache_ttl_seconds",
            ),
            (
                lambda: entitlements(retention_days=10**10),
                "$.retention_days",
            ),
            (
                lambda: IngestionRequest(
                    capability=ProviderCapability.GET_PROFILE,
                    uses=frozenset({DataUse.CACHE}),
                    cache_ttl_seconds=10**13,
                ),
                "$.cache_ttl_seconds",
            ),
        )
        for constructor, path in cases:
            with (
                self.subTest(path=path),
                self.assertRaises(ProviderContractError) as raised,
            ):
                constructor()
            self.assertEqual(path, raised.exception.path)
            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)

    def test_entitlement_lookup_is_not_an_ingestion_capability(self) -> None:
        with self.assertRaises(ProviderContractError) as raised:
            IngestionRequest(capability=ProviderCapability.GET_ENTITLEMENTS)
        self.assertEqual("$.capability", raised.exception.path)

    def test_terms_url_must_be_a_well_formed_public_dns_https_url(self) -> None:
        marker = "PRIVATE-TERMS-SENTINEL"
        for terms_url in (
            "https://[::1",
            "https://127.0.0.1/terms",
            "https://[::1]/terms",
            "https://localhost/terms",
            "https://ex ample.com/terms",
            f"https://{marker}.localhost/terms",
        ):
            with (
                self.subTest(terms_url=terms_url),
                self.assertRaises(ProviderContractError) as raised,
            ):
                entitlements(terms_url=terms_url)
            self.assertEqual("$.terms_url", raised.exception.path)
            self.assertNotIn(marker, str(raised.exception))
            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)

    def test_rate_limit_budget_uses_epoch_aligned_non_overlapping_windows(
        self,
    ) -> None:
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(
                entitlements(),
                budget=RateLimitBudget(
                    provider_id="provider-1",
                    period_started_at=EVALUATED_AT - timedelta(seconds=1),
                    requests_used=0,
                ),
            )
        self.assertEqual("rate_limit_period_mismatch", raised.exception.code)
        self.assertEqual("$rate_limit_budget.period_started_at", raised.exception.path)

    def test_datetime_arithmetic_overflow_is_a_stable_denial(self) -> None:
        edge = datetime(9999, 12, 30, 23, 59, tzinfo=UTC)
        value = entitlements(
            evaluated_at=edge,
            valid_until=None,
            rights_reviewed_at=edge,
            cache_ttl_seconds=3600,
            retention_days=7,
        )
        document = record_for(value)
        edge_text = edge.isoformat().replace("+00:00", "Z")
        document.update(
            {
                "as_of": edge_text,
                "published_at": edge_text,
                "fetched_at": edge_text,
            }
        )

        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(
                value,
                document=document,
                evaluation_timestamp=edge,
                request=IngestionRequest(
                    capability=ProviderCapability.GET_PROFILE,
                    uses=frozenset({DataUse.CACHE}),
                    cache_ttl_seconds=60,
                ),
            )
        self.assertEqual("temporal_policy_out_of_range", raised.exception.code)
        self.assertEqual("$.entitlements.retention_days", raised.exception.path)

    def test_cache_expiry_overflow_is_a_stable_denial(self) -> None:
        edge = datetime(9999, 12, 30, 23, 59, tzinfo=UTC)
        value = entitlements(
            evaluated_at=edge,
            valid_until=None,
            rights_reviewed_at=edge,
            cache_ttl_seconds=172800,
            retention_days=None,
        )
        document = record_for(value)
        edge_text = edge.isoformat().replace("+00:00", "Z")
        document.update(
            {
                "as_of": edge_text,
                "published_at": edge_text,
                "fetched_at": edge_text,
            }
        )

        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(
                value,
                document=document,
                evaluation_timestamp=edge,
                request=IngestionRequest(
                    capability=ProviderCapability.GET_PROFILE,
                    uses=frozenset({DataUse.CACHE}),
                    cache_ttl_seconds=172800,
                ),
            )
        self.assertEqual("temporal_policy_out_of_range", raised.exception.code)
        self.assertEqual("$request.cache_ttl_seconds", raised.exception.path)

    def test_rate_window_overflow_is_a_stable_denial(self) -> None:
        edge = datetime(9999, 12, 31, 23, 59, tzinfo=UTC)
        value = entitlements(
            evaluated_at=edge,
            valid_until=None,
            rights_reviewed_at=edge,
        )
        document = record_for(value)
        edge_text = edge.isoformat().replace("+00:00", "Z")
        document.update(
            {
                "as_of": edge_text,
                "published_at": edge_text,
                "fetched_at": edge_text,
            }
        )

        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(value, document=document, evaluation_timestamp=edge)
        self.assertEqual("temporal_policy_out_of_range", raised.exception.code)
        self.assertEqual(
            "$.entitlements.rate_limit.period_seconds", raised.exception.path
        )

    def test_evaluation_utc_normalization_overflow_is_a_stable_denial(self) -> None:
        edge = datetime(
            1,
            1,
            1,
            tzinfo=timezone(timedelta(hours=14)),
        )
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(entitlements(), evaluation_timestamp=edge)
        self.assertEqual("temporal_policy_out_of_range", raised.exception.code)
        self.assertEqual("$request.evaluation_timestamp", raised.exception.path)
        self.assertIsNone(raised.exception.__cause__)

    def test_budget_utc_normalization_overflow_is_a_stable_denial(self) -> None:
        edge = datetime(
            1,
            1,
            1,
            tzinfo=timezone(timedelta(hours=14)),
        )
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(
                entitlements(),
                budget=RateLimitBudget(
                    provider_id="provider-1",
                    period_started_at=edge,
                    requests_used=0,
                ),
            )
        self.assertEqual("temporal_policy_out_of_range", raised.exception.code)
        self.assertEqual("$rate_limit_budget.period_started_at", raised.exception.path)
        self.assertIsNone(raised.exception.__cause__)

    def test_mutated_typed_entitlements_are_revalidated_fail_closed(self) -> None:
        for field, replacement in (
            ("rights_reviewed_at", None),
            ("terms_url", "https://localhost/private"),
        ):
            with self.subTest(field=field):
                value = entitlements()
                object.__setattr__(value, field, replacement)
                with self.assertRaises(IngestionDenied) as raised:
                    self._authorize(value)
                self.assertEqual("entitlement_lookup_failed", raised.exception.code)
                self.assertNotIn("localhost", str(raised.exception))

        value = entitlements()
        object.__setattr__(value.rate_limit, "period_seconds", 0)
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(value)
        self.assertEqual("entitlement_lookup_failed", raised.exception.code)

    def test_mutated_naive_entitlement_timestamps_are_never_healed_by_host_timezone(
        self,
    ) -> None:
        if not hasattr(time, "tzset"):
            self.skipTest("host timezone switching requires time.tzset")
        original_timezone = os.environ.get("TZ")
        try:
            os.environ["TZ"] = "America/New_York"
            time.tzset()
            for field, naive_local_time in (
                ("evaluated_at", datetime(2026, 8, 20, 20, 0)),  # noqa: DTZ001
                ("valid_until", datetime(2026, 8, 21, 20, 0)),  # noqa: DTZ001
                (
                    "rights_reviewed_at",
                    datetime(2026, 8, 19, 20, 0),  # noqa: DTZ001
                ),
            ):
                with self.subTest(field=field):
                    value = entitlements()
                    object.__setattr__(value, field, naive_local_time)
                    with self.assertRaises(IngestionDenied) as raised:
                        self._authorize(value, document=record())
                    self.assertEqual(
                        "entitlement_lookup_failed",
                        raised.exception.code,
                    )
                    self.assertIsNone(raised.exception.__cause__)
        finally:
            if original_timezone is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = original_timezone
            time.tzset()

    def test_rate_window_coverage_uses_canonical_utc_across_dst_fold(self) -> None:
        eastern = ZoneInfo("America/New_York")
        period_start = datetime(2026, 11, 1, 1, 0, tzinfo=eastern, fold=0)
        evaluation = datetime(2026, 11, 1, 1, 30, tzinfo=eastern, fold=1)
        value = entitlements(
            evaluated_at=evaluation,
            valid_until=evaluation + timedelta(days=1),
        )
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(
                value,
                evaluation_timestamp=evaluation,
                budget=RateLimitBudget(
                    provider_id="provider-1",
                    period_started_at=period_start,
                    requests_used=0,
                ),
            )
        self.assertEqual("rate_limit_period_mismatch", raised.exception.code)

    def test_hostile_tzinfo_and_huge_rate_counts_fail_closed(self) -> None:
        hostile = datetime(2026, 1, 1, tzinfo=ExplodingTimezone())
        with self.assertRaises(ProviderContractError) as raised:
            RateLimitBudget(
                provider_id="provider-1",
                period_started_at=hostile,
                requests_used=0,
            )
        self.assertNotIn("PRIVATE-TZINFO-SENTINEL", str(raised.exception))

        for constructor in (
            lambda: RateLimit(requests_per_period=10**100, period_seconds=1),
            lambda: IngestionRequest(
                capability=ProviderCapability.GET_PROFILE,
                request_count=10**100,
            ),
            lambda: RateLimitBudget(
                provider_id="provider-1",
                period_started_at=EVALUATED_AT,
                requests_used=10**100,
            ),
        ):
            with (
                self.subTest(constructor=constructor),
                self.assertRaises(ProviderContractError),
            ):
                constructor()

    def test_provider_record_width_is_bounded_before_schema_validation(self) -> None:
        document = record()
        document["value"] = [0] * 10_001
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(entitlements(), document=document)
        self.assertEqual("invalid_provider_record", raised.exception.code)
        self.assertEqual("$.value", raised.exception.path)

        nested = record()
        nested["value"] = [[0] * 101 for _ in range(101)]
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(entitlements(), document=nested)
        self.assertEqual("invalid_provider_record", raised.exception.code)

        amplified = record()
        amplified["value"] = [ExplodingWideList(range(10_001))]
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(entitlements(), document=amplified)
        self.assertEqual("invalid_provider_record", raised.exception.code)
        self.assertNotIn("PRIVATE-CONTAINER-ACCESS-SENTINEL", str(raised.exception))

        deep_value: object = 0
        for _ in range(600):
            deep_value = [deep_value]
        deep = record()
        deep["value"] = deep_value
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(entitlements(), document=deep)
        self.assertEqual("invalid_provider_record", raised.exception.code)
        self.assertIsNone(raised.exception.__context__)

    def test_derived_only_forbids_public_display(self) -> None:
        with self.assertRaises(ProviderContractError) as raised:
            entitlements(
                rights_mode=RightsMode.DERIVED_ONLY,
                derived_works_allowed=True,
                public_display_allowed=True,
                redistribution_allowed=False,
            )
        self.assertEqual("$.public_display_allowed", raised.exception.path)

    def test_dst_fold_entitlement_binding_compares_utc_instants(self) -> None:
        eastern = ZoneInfo("America/New_York")
        snapshot_time = datetime(2026, 11, 1, 1, 30, tzinfo=eastern, fold=0)
        request_time = datetime(2026, 11, 1, 1, 30, tzinfo=eastern, fold=1)
        value = entitlements(
            evaluated_at=snapshot_time,
            valid_until=datetime(2026, 11, 2, 7, 0, tzinfo=UTC),
        )
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(
                value,
                evaluation_timestamp=request_time,
                budget=RateLimitBudget(
                    provider_id="provider-1",
                    period_started_at=request_time,
                    requests_used=0,
                ),
            )
        self.assertEqual("entitlement_contract_mismatch", raised.exception.code)

    def test_request_and_budget_are_revalidated_after_mutation(self) -> None:
        request = IngestionRequest(capability=ProviderCapability.GET_PROFILE)
        object.__setattr__(request, "request_count", -1)
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(entitlements(), request=request)
        self.assertEqual("invalid_ingestion_request", raised.exception.code)

        budget = RateLimitBudget(
            provider_id="provider-1",
            period_started_at=EVALUATED_AT,
            requests_used=0,
        )
        object.__setattr__(budget, "requests_used", -10)
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(entitlements(), budget=budget)
        self.assertEqual("invalid_rate_limit_budget", raised.exception.code)

    def test_stateful_tzinfo_exceptions_are_redacted(self) -> None:
        period_start = datetime(2026, 8, 21, tzinfo=StatefulTimezone())
        budget = RateLimitBudget(
            provider_id="provider-1",
            period_started_at=period_start,
            requests_used=0,
        )
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(entitlements(), budget=budget)
        self.assertNotIn("PRIVATE-STATEFUL-TZ-SENTINEL", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_dst_fold_cache_and_retention_use_elapsed_utc_time(self) -> None:
        eastern = ZoneInfo("America/New_York")
        evaluation = datetime(2026, 11, 1, 1, 30, tzinfo=eastern, fold=0)
        value = entitlements(
            evaluated_at=evaluation,
            valid_until=datetime(2026, 11, 4, 5, 30, tzinfo=UTC),
            retention_days=1,
        )
        authorization = self._authorize(
            value,
            evaluation_timestamp=evaluation,
            request=IngestionRequest(
                capability=ProviderCapability.GET_PROFILE,
                uses=frozenset({DataUse.CACHE}),
                cache_ttl_seconds=3600,
            ),
            budget=RateLimitBudget(
                provider_id="provider-1",
                period_started_at=evaluation,
                requests_used=0,
            ),
        )
        evaluated_utc = evaluation.astimezone(UTC)
        self.assertEqual(
            evaluated_utc + timedelta(hours=1), authorization.cache_expires_at
        )
        self.assertEqual(evaluated_utc + timedelta(days=1), authorization.retain_until)

    def test_entitlement_chronology_uses_utc_instants_across_dst_fold(self) -> None:
        eastern = ZoneInfo("America/New_York")
        with self.assertRaises(ProviderContractError):
            entitlements(
                evaluated_at=datetime(2026, 11, 1, 1, 30, tzinfo=eastern, fold=0),
                rights_reviewed_at=datetime(2026, 11, 1, 1, 15, tzinfo=eastern, fold=1),
                valid_until=datetime(2026, 11, 2, 7, 0, tzinfo=UTC),
            )
        with self.assertRaises(ProviderContractError):
            entitlements(
                evaluated_at=datetime(2026, 11, 1, 1, 30, tzinfo=eastern, fold=1),
                valid_until=datetime(2026, 11, 1, 1, 45, tzinfo=eastern, fold=0),
            )

    def test_builtin_subclasses_cannot_forge_membership_or_identity(self) -> None:
        value = entitlements()
        object.__setattr__(
            value,
            "jurisdictions",
            AllContainsFrozenSet({"CN"}),
        )
        document = record_for(value)
        document["jurisdiction"] = "JP"
        with self.assertRaises(IngestionDenied):
            self._authorize(value, document=document)

        value = entitlements()
        object.__setattr__(
            value,
            "capabilities",
            AllContainsFrozenSet({ProviderCapability.GET_ENTITLEMENTS}),
        )
        provider = LocalProvider(value)
        provider.capabilities = AllContainsFrozenSet(
            {ProviderCapability.GET_ENTITLEMENTS}
        )
        with self.assertRaises(IngestionDenied):
            self._authorize(
                value,
                provider=provider,
                request=IngestionRequest(capability=ProviderCapability.GET_NAV_SERIES),
            )

        value = entitlements()
        document = record_for(value)
        document["provider_id"] = AlwaysEqualStr("provider-2")
        with self.assertRaises(IngestionDenied):
            self._authorize(value, document=document)

        document = record_for(value)
        document["provider_id"] = LyingStr("provider-2")
        with self.assertRaises(IngestionDenied):
            self._authorize(value, document=document)

        document = record_for(value)
        document["rights"]["retention_days"] = LyingInt(30)
        with self.assertRaises(IngestionDenied):
            self._authorize(value, document=document)

        budget = RateLimitBudget(
            provider_id="provider-1",
            period_started_at=EVALUATED_AT,
            requests_used=0,
        )
        object.__setattr__(budget, "provider_id", AlwaysEqualStr("provider-2"))
        with self.assertRaises(IngestionDenied):
            self._authorize(value, budget=budget)

        provider = LocalProvider(value)
        provider.provider_id = AlwaysEqualStr("provider-2")
        with self.assertRaises(IngestionDenied):
            self._authorize(value, provider=provider)

    def test_mapping_subclasses_cannot_split_validated_and_authorized_rights(
        self,
    ) -> None:
        value = entitlements()
        document = record_for(value)
        actual = {
            "mode": "unknown_blocked",
            "terms_url": "https://example.com/terms",
            "cache_allowed": False,
            "derived_works_allowed": False,
            "redistribution_allowed": False,
            "attribution_required": False,
            "public_display_allowed": False,
            "retention_days": 7,
            "reviewed_at": "2026-08-20T00:00:00Z",
        }
        document["rights"] = SplitRights(actual, record_for(value)["rights"])
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(value, document=document)
        self.assertNotIn("KeyError", str(raised.exception))

    def test_frozenset_subclasses_cannot_forge_authorized_views(self) -> None:
        display_only = entitlements(
            rights_mode=RightsMode.DISPLAY_ONLY,
            cache_allowed=False,
            cache_ttl_seconds=None,
            derived_works_allowed=False,
            public_display_allowed=True,
            redistribution_allowed=False,
            retention_days=0,
        )
        hidden_use = IngestionRequest(
            capability=ProviderCapability.GET_PROFILE,
            attribution_ready=True,
        )
        object.__setattr__(
            hidden_use,
            "uses",
            ForgedIterationFrozenSet({DataUse.DERIVED_WORK}, ()),
        )
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(display_only, request=hidden_use)
        self.assertEqual("invalid_ingestion_request", raised.exception.code)

        forged_capabilities = entitlements()
        object.__setattr__(
            forged_capabilities,
            "capabilities",
            ForgedIterationFrozenSet(
                {ProviderCapability.GET_ENTITLEMENTS},
                {
                    ProviderCapability.GET_ENTITLEMENTS,
                    ProviderCapability.GET_PROFILE,
                },
            ),
        )
        provider = LocalProvider(forged_capabilities)
        provider.capabilities = forged_capabilities.capabilities
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(forged_capabilities, provider=provider)
        self.assertEqual("entitlement_lookup_failed", raised.exception.code)

        forged_jurisdiction = entitlements()
        object.__setattr__(
            forged_jurisdiction,
            "jurisdictions",
            ForgedIterationFrozenSet({"CN"}, {"JP"}),
        )
        document = record_for(entitlements())
        document["jurisdiction"] = "JP"
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(forged_jurisdiction, document=document)
        self.assertEqual("entitlement_lookup_failed", raised.exception.code)

    def test_schema_version_subclasses_cannot_forge_resource_identity(self) -> None:
        value = entitlements()
        with self.assertRaises(IngestionDenied) as raised:
            authorize_ingestion(
                LocalProvider(value),
                record_for(value),
                schema_version=AlwaysEqualStr("9.9.9"),
                evaluation_timestamp=EVALUATED_AT,
                request=IngestionRequest(
                    capability=ProviderCapability.GET_PROFILE,
                ),
                rate_limit_budget=RateLimitBudget(
                    provider_id="provider-1",
                    period_started_at=EVALUATED_AT,
                    requests_used=0,
                ),
            )
        self.assertEqual("invalid_provider_record", raised.exception.code)

    def test_capability_is_bound_to_the_provider_record_data_plane(self) -> None:
        capabilities = frozenset(
            {
                ProviderCapability.GET_ENTITLEMENTS,
                ProviderCapability.GET_PROFILE,
                ProviderCapability.GET_HOLDINGS,
            }
        )
        value = entitlements(capabilities=capabilities)
        provider = LocalProvider(value)
        provider.capabilities = capabilities
        document = record_for(value)
        document["entity_type"] = "holding"
        document["entity_id"] = "holding-1"
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(
                value,
                document=document,
                provider=provider,
                request=IngestionRequest(
                    capability=ProviderCapability.GET_PROFILE,
                ),
            )
        self.assertEqual("capability_record_mismatch", raised.exception.code)
        self.assertEqual("$.entity_type", raised.exception.path)

    def test_provider_record_scalar_bytes_are_bounded(self) -> None:
        document = record()
        document["value"] = "x" * 1_000_000
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(entitlements(), document=document)
        self.assertEqual("invalid_provider_record", raised.exception.code)
        self.assertEqual("$.value", raised.exception.path)

        aggregate = record()
        aggregate["value"] = ["x" * 60_000 for _ in range(20)]
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(entitlements(), document=aggregate)
        self.assertEqual("invalid_provider_record", raised.exception.code)

        huge_key = record()
        huge_key["value"] = {"k" * 70_000: 1}
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(entitlements(), document=huge_key)
        self.assertEqual("invalid_provider_record", raised.exception.code)

        surrogate = record()
        surrogate["value"] = "\ud800"
        with self.assertRaises(IngestionDenied) as raised:
            self._authorize(entitlements(), document=surrogate)
        self.assertEqual("invalid_provider_record", raised.exception.code)
        self.assertNotIn("surrogate", str(raised.exception).lower())

    def test_typed_provider_strings_match_packaged_schema_bounds(self) -> None:
        for changes, expected_path in (
            ({"provider_id": "p" * 257}, "$.provider_id"),
            (
                {"terms_url": "https://example.com/" + "a" * 2049},
                "$.terms_url",
            ),
        ):
            with self.subTest(expected_path=expected_path):
                with self.assertRaises(ProviderContractError) as raised:
                    entitlements(**changes)
                self.assertEqual(expected_path, raised.exception.path)

        with self.assertRaises(ProviderContractError) as raised:
            RateLimitBudget(
                provider_id="p" * 257,
                period_started_at=EVALUATED_AT,
                requests_used=0,
            )
        self.assertEqual("$.provider_id", raised.exception.path)

        with self.assertRaises(ProviderContractError) as raised:
            RateLimit(
                requests_per_period=1,
                period_seconds=1,
                burst=1_000_000_001,
            )
        self.assertEqual("$.burst", raised.exception.path)


if __name__ == "__main__":
    unittest.main()
