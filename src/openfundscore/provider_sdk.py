"""Typed, local-only provider SDK and ingestion authorization boundary."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from ipaddress import ip_address
from typing import Any, Never, Protocol, runtime_checkable
from urllib.parse import urlsplit

from .provider_semantics import (
    ProviderRecordValidationError,
    parse_rfc3339_timestamp,
)
from .validation import (
    RecordType,
    RecordValidationError,
    _validate_json_data,
    validate_record,
)

__all__ = (
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
)


class ProviderCapability(StrEnum):
    """Operations a provider adapter can implement without implying entitlement."""

    LIST_FUNDS = "list_funds"
    GET_PROFILE = "get_profile"
    GET_SHARE_CLASSES = "get_share_classes"
    GET_NAV_SERIES = "get_nav_series"
    GET_BENCHMARK = "get_benchmark"
    GET_MANAGER_TENURES = "get_manager_tenures"
    GET_HOLDINGS = "get_holdings"
    GET_FEES = "get_fees"
    GET_PURCHASE_STATUS = "get_purchase_status"
    GET_DISCLOSURES = "get_disclosures"
    GET_EXTERNAL_RATINGS = "get_external_ratings"
    GET_ENTITLEMENTS = "get_entitlements"


class DataUse(StrEnum):
    """Post-fetch uses that require independent provider authorization."""

    CACHE = "cache"
    DERIVED_WORK = "derived_work"
    DISPLAY = "display"
    REDISTRIBUTION = "redistribution"


class AuthenticationMode(StrEnum):
    NONE = "none"
    API_KEY = "api_key"
    OAUTH = "oauth"
    USER_SESSION = "user_session"
    LOCAL_ENTITLEMENT = "local_entitlement"


class RightsMode(StrEnum):
    OPEN_REDISTRIBUTABLE = "open_redistributable"
    DERIVED_ONLY = "derived_only"
    LOCAL_ENTITLEMENT = "local_entitlement"
    DISPLAY_ONLY = "display_only"
    UNKNOWN_BLOCKED = "unknown_blocked"


class SourceType(StrEnum):
    REGULATOR = "regulator"
    EXCHANGE = "exchange"
    OFFICIAL_REGISTRY = "official_registry"
    FUND_COMPANY_OR_MANAGER = "fund_company_or_manager"
    CUSTODIAN = "custodian"
    INDEX_OR_MACRO_OFFICIAL_SOURCE = "index_or_macro_official_source"
    COMMERCIAL_VENDOR = "commercial_vendor"
    DISTRIBUTION_PLATFORM = "distribution_platform"
    USER_IMPORT = "user_import"


_JURISDICTION_RE = re.compile(r"^[A-Z]{2}$", re.ASCII)
_PUBLIC_DNS_RE = re.compile(
    r"(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z",
    re.ASCII,
)
_MAX_RATE_PERIOD_SECONDS = 365 * 24 * 60 * 60
_MAX_RATE_REQUESTS = 1_000_000_000
_MAX_REQUEST_COUNT = 1_000_000
_MAX_CACHE_TTL_SECONDS = 365 * 24 * 60 * 60
_MAX_RETENTION_DAYS = 36_500
_UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _is_aware(value: object) -> bool:
    if not isinstance(value, datetime) or value.tzinfo is None:
        return False
    try:
        return value.utcoffset() is not None
    except Exception:  # noqa: BLE001 - hostile tzinfo must fail closed
        return False


def _is_public_https_url(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except (UnicodeError, ValueError):
        return False
    if (
        host is None
        or host == "localhost"
        or host.endswith(".localhost")
        or _PUBLIC_DNS_RE.fullmatch(host) is None
    ):
        return False
    try:
        ip_address(host)
    except ValueError:
        pass
    else:
        return False
    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and (port is None or port > 0)
        and not parsed.fragment
    )


class ProviderContractError(ValueError):
    """Stable, redacted failure for an invalid typed provider contract."""

    def __init__(self, *, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        super().__init__(f"{path}: {code}: {message}")


def _contract_utc(value: datetime, *, path: str) -> datetime:
    normalized: datetime | None = None
    try:
        normalized = value.astimezone(UTC)
    except Exception:  # noqa: BLE001 - timezone implementations are untrusted
        normalized = None
    if normalized is None:
        raise ProviderContractError(
            code="invalid_timestamp",
            path=path,
            message="timestamp cannot be normalized to a supported UTC instant",
        ) from None
    return normalized


class IngestionDenied(ValueError):
    """Stable, redacted denial from the ingestion authorization boundary."""

    def __init__(self, *, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        super().__init__(f"{path}: {code}: {message}")


@dataclass(frozen=True, kw_only=True)
class RateLimit:
    requests_per_period: int
    period_seconds: int
    burst: int | None = None

    def __post_init__(self) -> None:
        for field in ("requests_per_period", "period_seconds", "burst"):
            value = getattr(self, field)
            if value is None and field == "burst":
                continue
            if type(value) is not int or value <= 0:
                raise ProviderContractError(
                    code="invalid_rate_limit",
                    path=f"$.{field}",
                    message="rate-limit values must be positive integers",
                )
        if self.period_seconds > _MAX_RATE_PERIOD_SECONDS:
            raise ProviderContractError(
                code="invalid_rate_limit",
                path="$.period_seconds",
                message="rate-limit period exceeds the supported bound",
            )
        if self.requests_per_period > _MAX_RATE_REQUESTS or (
            self.burst is not None and self.burst > _MAX_RATE_REQUESTS
        ):
            raise ProviderContractError(
                code="invalid_rate_limit",
                path="$.requests_per_period",
                message="rate-limit request counts exceed the supported bound",
            )


@dataclass(frozen=True, kw_only=True)
class ProviderEntitlements:
    """Redacted provider rights evaluated at one caller-selected instant."""

    provider_id: str
    evaluated_at: datetime
    valid_until: datetime | None
    source_type: SourceType
    jurisdictions: frozenset[str]
    authentication_mode: AuthenticationMode
    capabilities: frozenset[ProviderCapability]
    rights_mode: RightsMode
    cache_allowed: bool
    cache_ttl_seconds: int | None
    derived_works_allowed: bool
    public_display_allowed: bool
    redistribution_allowed: bool
    retention_days: int | None
    attribution_required: bool
    terms_url: str | None
    rights_reviewed_at: datetime | None
    rate_limit: RateLimit

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id.strip():
            raise ProviderContractError(
                code="invalid_contract",
                path="$.provider_id",
                message="provider identity must be a non-empty string",
            )
        enum_fields = (
            ("source_type", self.source_type, SourceType),
            ("authentication_mode", self.authentication_mode, AuthenticationMode),
            ("rights_mode", self.rights_mode, RightsMode),
        )
        for field, value, expected_type in enum_fields:
            if not isinstance(value, expected_type):
                raise ProviderContractError(
                    code="invalid_contract",
                    path=f"$.{field}",
                    message="contract enum value is invalid",
                )
        for field in (
            "cache_allowed",
            "derived_works_allowed",
            "public_display_allowed",
            "redistribution_allowed",
            "attribution_required",
        ):
            if type(getattr(self, field)) is not bool:
                raise ProviderContractError(
                    code="invalid_contract",
                    path=f"$.{field}",
                    message="rights flags must be booleans",
                )
        if not isinstance(self.rate_limit, RateLimit):
            raise ProviderContractError(
                code="invalid_contract",
                path="$.rate_limit",
                message="rate limit must use the typed contract",
            )
        if not _is_aware(self.evaluated_at):
            raise ProviderContractError(
                code="invalid_timestamp",
                path="$.evaluated_at",
                message="entitlement timestamps must be timezone-aware",
            )
        for field in ("valid_until", "rights_reviewed_at"):
            value = getattr(self, field)
            if value is not None and not _is_aware(value):
                raise ProviderContractError(
                    code="invalid_timestamp",
                    path=f"$.{field}",
                    message="entitlement timestamps must be timezone-aware",
                )
        evaluated_utc = _contract_utc(self.evaluated_at, path="$.evaluated_at")
        valid_until_utc = (
            None
            if self.valid_until is None
            else _contract_utc(self.valid_until, path="$.valid_until")
        )
        reviewed_utc = (
            None
            if self.rights_reviewed_at is None
            else _contract_utc(self.rights_reviewed_at, path="$.rights_reviewed_at")
        )
        if valid_until_utc is not None and valid_until_utc <= evaluated_utc:
            raise ProviderContractError(
                code="invalid_validity",
                path="$.valid_until",
                message="entitlements must expire after their evaluation instant",
            )
        if self.rights_reviewed_at is None:
            raise ProviderContractError(
                code="missing_rights_review",
                path="$.rights_reviewed_at",
                message="rights review timestamp is required",
            )
        if reviewed_utc is not None and reviewed_utc > evaluated_utc:
            raise ProviderContractError(
                code="future_rights_review",
                path="$.rights_reviewed_at",
                message="rights cannot be reviewed after their evaluation instant",
            )
        if not _is_public_https_url(self.terms_url):
            raise ProviderContractError(
                code="invalid_contract",
                path="$.terms_url",
                message="provider terms must be an absolute public HTTPS URL",
            )
        if (
            not isinstance(self.jurisdictions, frozenset)
            or not self.jurisdictions
            or any(
                not isinstance(item, str) or _JURISDICTION_RE.fullmatch(item) is None
                for item in self.jurisdictions
            )
        ):
            raise ProviderContractError(
                code="invalid_contract",
                path="$.jurisdictions",
                message="jurisdictions must be a non-empty frozen set",
            )
        if (
            not isinstance(self.capabilities, frozenset)
            or ProviderCapability.GET_ENTITLEMENTS not in self.capabilities
            or any(
                not isinstance(item, ProviderCapability) for item in self.capabilities
            )
        ):
            raise ProviderContractError(
                code="missing_entitlement_capability",
                path="$.capabilities",
                message="get_entitlements capability is mandatory",
            )
        if self.rights_mode is RightsMode.UNKNOWN_BLOCKED:
            requirements = (
                ("cache_allowed", self.cache_allowed, False),
                ("derived_works_allowed", self.derived_works_allowed, False),
                ("public_display_allowed", self.public_display_allowed, False),
                ("redistribution_allowed", self.redistribution_allowed, False),
                ("attribution_required", self.attribution_required, False),
            )
        elif self.rights_mode is RightsMode.DERIVED_ONLY:
            requirements = (
                ("derived_works_allowed", self.derived_works_allowed, True),
                ("public_display_allowed", self.public_display_allowed, False),
                ("redistribution_allowed", self.redistribution_allowed, False),
            )
        elif self.rights_mode is RightsMode.DISPLAY_ONLY:
            requirements = (
                ("public_display_allowed", self.public_display_allowed, True),
                ("cache_allowed", self.cache_allowed, False),
                ("derived_works_allowed", self.derived_works_allowed, False),
                ("redistribution_allowed", self.redistribution_allowed, False),
                ("attribution_required", self.attribution_required, True),
            )
        elif self.rights_mode is RightsMode.LOCAL_ENTITLEMENT:
            requirements = (
                ("public_display_allowed", self.public_display_allowed, False),
                ("redistribution_allowed", self.redistribution_allowed, False),
            )
        else:
            requirements = (
                ("redistribution_allowed", self.redistribution_allowed, True),
            )
        for field, actual, expected in requirements:
            if actual is not expected:
                raise ProviderContractError(
                    code="rights_mismatch",
                    path=f"$.{field}",
                    message="rights do not match their declared mode",
                )
        if self.cache_ttl_seconds is not None and (
            type(self.cache_ttl_seconds) is not int
            or self.cache_ttl_seconds <= 0
            or self.cache_ttl_seconds > _MAX_CACHE_TTL_SECONDS
        ):
            raise ProviderContractError(
                code="invalid_cache_policy",
                path="$.cache_ttl_seconds",
                message="cache TTL must be a positive bounded integer",
            )
        if self.retention_days is not None and (
            type(self.retention_days) is not int
            or self.retention_days < 0
            or self.retention_days > _MAX_RETENTION_DAYS
        ):
            raise ProviderContractError(
                code="invalid_retention",
                path="$.retention_days",
                message="retention must be a non-negative bounded integer",
            )
        if not self.cache_allowed and self.cache_ttl_seconds is not None:
            raise ProviderContractError(
                code="rights_mismatch",
                path="$.cache_ttl_seconds",
                message="cache TTL cannot authorize blocked caching",
            )
        if (
            self.cache_allowed
            and self.cache_ttl_seconds is None
            and self.retention_days is None
        ):
            raise ProviderContractError(
                code="ambiguous_cache_policy",
                path="$.cache_allowed",
                message="allowed caching requires a TTL or retention limit",
            )


@runtime_checkable
class ProviderAdapter(Protocol):
    """No-network contract implemented by provider-specific local adapters."""

    provider_id: str
    capabilities: frozenset[ProviderCapability]

    def get_entitlements(
        self,
        *,
        evaluation_timestamp: datetime,
    ) -> ProviderEntitlements:
        """Return redacted rights at exactly ``evaluation_timestamp``."""
        ...


@dataclass(frozen=True, kw_only=True)
class IngestionRequest:
    capability: ProviderCapability
    uses: frozenset[DataUse] = frozenset()
    request_count: int = 1
    cache_ttl_seconds: int | None = None
    attribution_ready: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.capability, ProviderCapability):
            raise ProviderContractError(
                code="invalid_request",
                path="$.capability",
                message="capability must use the typed provider enum",
            )
        if self.capability is ProviderCapability.GET_ENTITLEMENTS:
            raise ProviderContractError(
                code="invalid_request",
                path="$.capability",
                message="entitlement lookup is not a data-ingestion capability",
            )
        if not isinstance(self.uses, frozenset) or any(
            not isinstance(item, DataUse) for item in self.uses
        ):
            raise ProviderContractError(
                code="invalid_request",
                path="$.uses",
                message="uses must be a frozen set of typed data-use values",
            )
        if (
            type(self.request_count) is not int
            or self.request_count <= 0
            or self.request_count > _MAX_REQUEST_COUNT
        ):
            raise ProviderContractError(
                code="invalid_request",
                path="$.request_count",
                message="request count must be a positive integer",
            )
        if self.cache_ttl_seconds is not None and (
            type(self.cache_ttl_seconds) is not int
            or self.cache_ttl_seconds <= 0
            or self.cache_ttl_seconds > _MAX_CACHE_TTL_SECONDS
        ):
            raise ProviderContractError(
                code="invalid_request",
                path="$.cache_ttl_seconds",
                message="cache TTL must be a positive bounded integer",
            )
        if type(self.attribution_ready) is not bool:
            raise ProviderContractError(
                code="invalid_request",
                path="$.attribution_ready",
                message="attribution readiness must be a boolean",
            )
        if self.cache_ttl_seconds is not None and DataUse.CACHE not in self.uses:
            raise ProviderContractError(
                code="invalid_request",
                path="$.cache_ttl_seconds",
                message="cache TTL requires an explicit cache use",
            )


@dataclass(frozen=True, kw_only=True)
class RateLimitBudget:
    provider_id: str
    period_started_at: datetime
    requests_used: int

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id.strip():
            raise ProviderContractError(
                code="invalid_budget",
                path="$.provider_id",
                message="rate-limit budget must identify its provider",
            )
        if not _is_aware(self.period_started_at):
            raise ProviderContractError(
                code="invalid_budget",
                path="$.period_started_at",
                message="rate-limit period timestamp must be timezone-aware",
            )
        if (
            type(self.requests_used) is not int
            or self.requests_used < 0
            or self.requests_used > _MAX_RATE_REQUESTS
        ):
            raise ProviderContractError(
                code="invalid_budget",
                path="$.requests_used",
                message="used requests must be a non-negative integer",
            )


@dataclass(frozen=True, kw_only=True)
class IngestionAuthorization:
    provider_id: str
    evaluated_at: datetime
    capability: ProviderCapability
    uses: tuple[DataUse, ...]
    requests_remaining: int
    cache_expires_at: datetime | None
    retain_until: datetime | None
    attribution_required: bool


def _as_utc(value: datetime, *, path: str) -> datetime:
    normalized: datetime | None = None
    try:
        normalized = value.astimezone(UTC)
    except Exception:  # noqa: BLE001 - timezone implementations are untrusted
        normalized = None
    if normalized is None:
        raise IngestionDenied(
            code="temporal_policy_out_of_range",
            path=path,
            message="timestamp exceeds the supported UTC datetime range",
        )
    return normalized


def _rfc3339(value: datetime, *, path: str) -> str:
    return (
        _as_utc(value, path=path)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _contract_mismatch(path: str) -> Never:
    raise IngestionDenied(
        code="record_contract_mismatch",
        path=path,
        message="provider record does not match point-in-time entitlements",
    )


def _enforce_record_contract(
    record: Mapping[str, object],
    entitlements: ProviderEntitlements,
) -> None:
    for field, expected in (
        ("provider_id", entitlements.provider_id),
        ("source_type", entitlements.source_type.value),
    ):
        if record.get(field) != expected:
            _contract_mismatch(f"$.{field}")
    if record.get("jurisdiction") not in entitlements.jurisdictions:
        _contract_mismatch("$.jurisdiction")
    rights = record.get("rights")
    if not isinstance(rights, Mapping):
        _contract_mismatch("$.rights")
    expected_rights: tuple[tuple[str, object], ...] = (
        ("mode", entitlements.rights_mode.value),
        ("cache_allowed", entitlements.cache_allowed),
        ("derived_works_allowed", entitlements.derived_works_allowed),
        ("public_display_allowed", entitlements.public_display_allowed),
        ("redistribution_allowed", entitlements.redistribution_allowed),
        ("attribution_required", entitlements.attribution_required),
        ("retention_days", entitlements.retention_days),
        ("terms_url", entitlements.terms_url),
    )
    for field, expected in expected_rights:
        if rights.get(field) != expected:
            _contract_mismatch(f"$.rights.{field}")
    reviewed_at = rights.get("reviewed_at")
    if entitlements.rights_reviewed_at is None:
        if reviewed_at is not None:
            _contract_mismatch("$.rights.reviewed_at")
    else:
        try:
            parsed_reviewed_at = parse_rfc3339_timestamp(
                reviewed_at,
                path="$.rights.reviewed_at",
            )
        except ProviderRecordValidationError:
            _contract_mismatch("$.rights.reviewed_at")
        if parsed_reviewed_at != entitlements.rights_reviewed_at:
            _contract_mismatch("$.rights.reviewed_at")


def _deny(*, code: str, path: str, message: str) -> Never:
    raise IngestionDenied(code=code, path=path, message=message)


def _validate_record_boundary(
    record: Mapping[str, object],
    *,
    schema_version: str,
    evaluation_timestamp: datetime,
) -> dict[str, object]:
    error_path: str | None = None
    canonical_record: object | None = None
    try:
        canonical_record = _validate_json_data(
            RecordType.PROVIDER_RECORD,
            record,
            schema_version=schema_version,
        )
        validate_record(
            "provider_record",
            canonical_record,
            schema_version=schema_version,
            evaluation_timestamp=_rfc3339(
                evaluation_timestamp,
                path="$request.evaluation_timestamp",
            ),
        )
    except RecordValidationError as exc:
        error_path = exc.path
    if error_path is not None:
        _deny(
            code="invalid_provider_record",
            path=error_path,
            message="provider record failed the ingestion contract",
        )
    if not isinstance(canonical_record, dict):
        _deny(
            code="invalid_provider_record",
            path="$",
            message="provider record failed the ingestion contract",
        )
    return canonical_record


def _validated_entitlements_copy(value: ProviderEntitlements) -> ProviderEntitlements:
    if (
        not isinstance(value.provider_id, str)
        or not isinstance(value.jurisdictions, frozenset)
        or not isinstance(value.capabilities, frozenset)
        or not isinstance(value.rate_limit, RateLimit)
    ):
        raise TypeError("rate limit must use the typed contract")
    rate_limit = RateLimit(
        requests_per_period=value.rate_limit.requests_per_period,
        period_seconds=value.rate_limit.period_seconds,
        burst=value.rate_limit.burst,
    )
    return ProviderEntitlements(
        provider_id=str.__str__(value.provider_id),
        evaluated_at=_contract_utc(value.evaluated_at, path="$.evaluated_at"),
        valid_until=(
            None
            if value.valid_until is None
            else _contract_utc(value.valid_until, path="$.valid_until")
        ),
        source_type=value.source_type,
        jurisdictions=frozenset(
            str.__str__(item) if isinstance(item, str) else item
            for item in value.jurisdictions
        ),
        authentication_mode=value.authentication_mode,
        capabilities=frozenset(tuple(value.capabilities)),
        rights_mode=value.rights_mode,
        cache_allowed=value.cache_allowed,
        cache_ttl_seconds=value.cache_ttl_seconds,
        derived_works_allowed=value.derived_works_allowed,
        public_display_allowed=value.public_display_allowed,
        redistribution_allowed=value.redistribution_allowed,
        retention_days=value.retention_days,
        attribution_required=value.attribution_required,
        terms_url=(
            None
            if value.terms_url is None
            else str.__str__(value.terms_url)
        ),
        rights_reviewed_at=(
            None
            if value.rights_reviewed_at is None
            else _contract_utc(
                value.rights_reviewed_at,
                path="$.rights_reviewed_at",
            )
        ),
        rate_limit=rate_limit,
    )


def _validated_request_copy(value: IngestionRequest) -> IngestionRequest:
    if not isinstance(value.uses, frozenset):
        raise TypeError("request uses must use the typed contract")
    return IngestionRequest(
        capability=value.capability,
        uses=frozenset(tuple(value.uses)),
        request_count=value.request_count,
        cache_ttl_seconds=value.cache_ttl_seconds,
        attribution_ready=value.attribution_ready,
    )


def _validated_budget_copy(value: RateLimitBudget) -> RateLimitBudget:
    if not isinstance(value.provider_id, str):
        raise TypeError("budget provider id must use the typed contract")
    return RateLimitBudget(
        provider_id=str.__str__(value.provider_id),
        period_started_at=value.period_started_at,
        requests_used=value.requests_used,
    )


def _load_entitlements(
    provider: ProviderAdapter,
    *,
    evaluation_timestamp: datetime,
) -> tuple[str, frozenset[ProviderCapability], ProviderEntitlements]:
    failed = False
    provider_id: Any = None
    capabilities: Any = None
    entitlements: Any = None
    try:
        raw_provider_id = provider.provider_id
        raw_capabilities = provider.capabilities
        if not isinstance(raw_provider_id, str) or not isinstance(
            raw_capabilities, frozenset
        ):
            raise TypeError("provider identity contract is malformed")
        provider_id = str.__str__(raw_provider_id)
        capabilities = frozenset(tuple(raw_capabilities))
        entitlements = provider.get_entitlements(
            evaluation_timestamp=evaluation_timestamp,
        )
        if isinstance(entitlements, ProviderEntitlements):
            entitlements = _validated_entitlements_copy(entitlements)
    except Exception:  # noqa: BLE001 - external adapters may raise any Exception
        failed = True
    if (
        failed
        or not isinstance(provider_id, str)
        or not provider_id
        or not isinstance(capabilities, frozenset)
        or any(not isinstance(item, ProviderCapability) for item in capabilities)
        or ProviderCapability.GET_ENTITLEMENTS not in capabilities
        or not isinstance(entitlements, ProviderEntitlements)
    ):
        _deny(
            code="entitlement_lookup_failed",
            path="$provider.entitlements",
            message="provider entitlements are unavailable or malformed",
        )
    return provider_id, capabilities, entitlements


def _add_policy_delta(value: datetime, delta: timedelta, *, path: str) -> datetime:
    try:
        return value + delta
    except OverflowError:
        raise IngestionDenied(
            code="temporal_policy_out_of_range",
            path=path,
            message="temporal policy exceeds the supported datetime range",
        ) from None


def _enforce_rate_limit(
    entitlements: ProviderEntitlements,
    request: IngestionRequest,
    budget: RateLimitBudget,
    *,
    evaluation_timestamp: datetime,
) -> int:
    if budget.provider_id != entitlements.provider_id:
        _deny(
            code="rate_limit_budget_mismatch",
            path="$rate_limit_budget.provider_id",
            message="rate-limit budget belongs to a different provider",
        )
    period_started_utc = _as_utc(
        budget.period_started_at,
        path="$rate_limit_budget.period_started_at",
    )
    evaluation_utc = _as_utc(
        evaluation_timestamp,
        path="$request.evaluation_timestamp",
    )
    period_offset = period_started_utc - _UNIX_EPOCH
    offset_seconds = period_offset.days * 86400 + period_offset.seconds
    if (
        period_offset.microseconds != 0
        or offset_seconds % entitlements.rate_limit.period_seconds != 0
    ):
        _deny(
            code="rate_limit_period_mismatch",
            path="$rate_limit_budget.period_started_at",
            message="rate-limit budget is not aligned to its canonical UTC window",
        )
    window_end = _add_policy_delta(
        period_started_utc,
        timedelta(seconds=entitlements.rate_limit.period_seconds),
        path="$.entitlements.rate_limit.period_seconds",
    )
    if not (period_started_utc <= evaluation_utc < window_end):
        _deny(
            code="rate_limit_period_mismatch",
            path="$rate_limit_budget.period_started_at",
            message="rate-limit budget does not cover the evaluation instant",
        )
    if (
        entitlements.rate_limit.burst is not None
        and request.request_count > entitlements.rate_limit.burst
    ):
        _deny(
            code="rate_limit_burst_exceeded",
            path="$request.request_count",
            message="request exceeds the provider burst allowance",
        )
    remaining = (
        entitlements.rate_limit.requests_per_period
        - budget.requests_used
        - request.request_count
    )
    if remaining < 0:
        _deny(
            code="rate_limit_exceeded",
            path="$rate_limit_budget.requests_used",
            message="request exceeds the provider rate-limit budget",
        )
    return remaining


def _authorize_cache(
    entitlements: ProviderEntitlements,
    request: IngestionRequest,
    *,
    evaluation_timestamp: datetime,
) -> datetime | None:
    if DataUse.CACHE not in request.uses:
        return None
    if request.cache_ttl_seconds is None:
        _deny(
            code="cache_ttl_required",
            path="$request.cache_ttl_seconds",
            message="cache use requires an explicit bounded TTL",
        )
    limits: list[int] = []
    if entitlements.cache_ttl_seconds is not None:
        limits.append(entitlements.cache_ttl_seconds)
    if entitlements.retention_days is not None:
        limits.append(entitlements.retention_days * 86400)
    if not limits or request.cache_ttl_seconds > min(limits):
        _deny(
            code="cache_ttl_exceeded",
            path="$request.cache_ttl_seconds",
            message="requested cache TTL exceeds provider rights",
        )
    evaluation_utc = _as_utc(
        evaluation_timestamp,
        path="$request.evaluation_timestamp",
    )
    expires_at = _add_policy_delta(
        evaluation_utc,
        timedelta(seconds=request.cache_ttl_seconds),
        path="$request.cache_ttl_seconds",
    )
    if entitlements.valid_until is not None and expires_at > _as_utc(
        entitlements.valid_until,
        path="$.valid_until",
    ):
        _deny(
            code="cache_outlives_entitlement",
            path="$request.cache_ttl_seconds",
            message="requested cache TTL outlives the entitlement snapshot",
        )
    return expires_at


def authorize_ingestion(
    provider: ProviderAdapter,
    record: Mapping[str, object],
    *,
    schema_version: str,
    evaluation_timestamp: datetime,
    request: IngestionRequest,
    rate_limit_budget: RateLimitBudget,
) -> IngestionAuthorization:
    """Validate one provider record and return a deterministic authorization."""
    if not _is_aware(evaluation_timestamp):
        _deny(
            code="invalid_evaluation_timestamp",
            path="$request.evaluation_timestamp",
            message="evaluation timestamp must be timezone-aware",
        )
    evaluation_timestamp = _as_utc(
        evaluation_timestamp,
        path="$request.evaluation_timestamp",
    )
    if not isinstance(request, IngestionRequest):
        _deny(
            code="invalid_ingestion_request",
            path="$request",
            message="ingestion request must use the typed contract",
        )
    request_failed = False
    try:
        request = _validated_request_copy(request)
    except Exception:  # noqa: BLE001 - typed inputs remain untrusted
        request_failed = True
    if request_failed:
        _deny(
            code="invalid_ingestion_request",
            path="$request",
            message="ingestion request violates its typed contract",
        )
    if not isinstance(rate_limit_budget, RateLimitBudget):
        _deny(
            code="invalid_rate_limit_budget",
            path="$rate_limit_budget",
            message="rate-limit budget must use the typed contract",
        )
    budget_failed = False
    try:
        rate_limit_budget = _validated_budget_copy(rate_limit_budget)
    except Exception:  # noqa: BLE001 - typed inputs remain untrusted
        budget_failed = True
    if budget_failed:
        _deny(
            code="invalid_rate_limit_budget",
            path="$rate_limit_budget",
            message="rate-limit budget violates its typed contract",
        )
    record = _validate_record_boundary(
        record,
        schema_version=schema_version,
        evaluation_timestamp=evaluation_timestamp,
    )
    provider_id, provider_capabilities, entitlements = _load_entitlements(
        provider,
        evaluation_timestamp=evaluation_timestamp,
    )
    if provider_id != entitlements.provider_id:
        _deny(
            code="entitlement_contract_mismatch",
            path="$provider.provider_id",
            message="adapter identity does not match its entitlements",
        )
    if _as_utc(
        entitlements.evaluated_at,
        path="$.evaluated_at",
    ) != _as_utc(
        evaluation_timestamp,
        path="$request.evaluation_timestamp",
    ):
        _deny(
            code="entitlement_contract_mismatch",
            path="$.evaluated_at",
            message="entitlements do not match the requested evaluation instant",
        )
    if (
        request.capability not in provider_capabilities
        or request.capability not in entitlements.capabilities
    ):
        _deny(
            code="capability_not_authorized",
            path="$request.capability",
            message="provider capability is unavailable or not entitled",
        )
    _enforce_record_contract(record, entitlements)
    if entitlements.rights_mode is RightsMode.UNKNOWN_BLOCKED:
        _deny(
            code="rights_mode_blocked",
            path="$.rights.mode",
            message="provider rights do not authorize ingestion",
        )
    permissions = {
        DataUse.CACHE: entitlements.cache_allowed,
        DataUse.DERIVED_WORK: entitlements.derived_works_allowed,
        DataUse.DISPLAY: entitlements.public_display_allowed,
        DataUse.REDISTRIBUTION: entitlements.redistribution_allowed,
    }
    for use in sorted(request.uses, key=lambda item: item.value):
        if not permissions[use]:
            _deny(
                code="use_not_authorized",
                path=f"$request.uses.{use.value}",
                message="requested provider-data use is not authorized",
            )
    attributed_uses = request.uses - {DataUse.CACHE}
    if (
        entitlements.attribution_required
        and attributed_uses
        and not request.attribution_ready
    ):
        _deny(
            code="attribution_not_ready",
            path="$request.attribution_ready",
            message="requested provider-data use requires attribution readiness",
        )
    requests_remaining = _enforce_rate_limit(
        entitlements,
        request,
        rate_limit_budget,
        evaluation_timestamp=evaluation_timestamp,
    )
    cache_expires_at = _authorize_cache(
        entitlements,
        request,
        evaluation_timestamp=evaluation_timestamp,
    )
    retain_until = None
    if entitlements.retention_days is not None:
        retain_until = _add_policy_delta(
            _as_utc(
                evaluation_timestamp,
                path="$request.evaluation_timestamp",
            ),
            timedelta(days=entitlements.retention_days),
            path="$.entitlements.retention_days",
        )
    return IngestionAuthorization(
        provider_id=entitlements.provider_id,
        evaluated_at=entitlements.evaluated_at,
        capability=request.capability,
        uses=tuple(sorted(request.uses, key=lambda item: item.value)),
        requests_remaining=requests_remaining,
        cache_expires_at=cache_expires_at,
        retain_until=retain_until,
        attribution_required=entitlements.attribution_required,
    )
