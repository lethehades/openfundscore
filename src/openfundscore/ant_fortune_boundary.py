"""Fail-closed Ant Fortune public-data boundary.

This module validates a packaged policy record.  It never performs network access,
authentication, scraping, reverse engineering, or platform-data collection.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from ipaddress import ip_address
from typing import Any, NoReturn, cast
from urllib.parse import urlsplit

from .resources import resolve_resource

_MAX_DEPTH = 64
_MAX_NODES = 10_000
_MAX_WIDTH = 1_000
_MAX_STRING = 65_536
_SUPPORTED_BOUNDARY_VERSION = "0.1.0"
_IDENTIFIER_RE = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*\Z", re.ASCII)
_VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z", re.ASCII)
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_TIMESTAMP_RE = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
    r"T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z\Z",
    re.ASCII,
)
_ALLOWED_OFFICIAL_HOSTS = frozenset({"www.antfortune.com", "open.alipay.com"})

_TOP_LEVEL_FIELDS = {
    "format_version",
    "boundary_id",
    "boundary_version",
    "provider_id",
    "reviewed_at",
    "as_of",
    "conclusion",
    "automated_adapter_available",
    "legal_permission_claimed",
    "per_fund_public_api_status",
    "collection_policy",
    "access_modes",
    "prohibited_collection",
    "sources",
    "fields",
    "reassessment_conditions",
    "unresolved_items",
}
_ACCESS_MODE_FIELDS = {
    "access_mode",
    "project_collection",
    "default_rights_mode",
    "public_by_default",
}
_SOURCE_FIELDS = {
    "source_id",
    "url",
    "host",
    "scope",
    "observation",
    "evidence_status",
    "retrieved_at",
    "reviewed_at",
    "terms_status",
    "terms_url",
    "robots_status",
    "robots_url",
    "robots_is_authorization",
    "rate_limit_status",
    "rate_limit_value",
    "rights_status",
}
_FIELD_FIELDS = {
    "field_id",
    "definition",
    "value_type",
    "unit",
    "grain",
    "public_observation",
    "access_mode_status",
    "authorization_status",
    "official_source_url",
    "official_evidence_status",
    "evidence_retrieved_at",
    "evidence_reviewed_at",
    "terms_status",
    "terms_url",
    "robots_status",
    "robots_url",
    "robots_is_authorization",
    "rate_limit_status",
    "rate_limit_value",
    "cache_status",
    "cache_ttl_seconds",
    "retention_status",
    "retention_value",
    "derived_status",
    "display_status",
    "redistribution_status",
    "attribution_status",
    "provenance",
    "review_status",
    "pending_evidence",
    "reevaluation_triggers",
    "namespace",
    "open_score_eligible",
    "automated_ingestion_allowed",
}

_FIELD_DEFINITIONS = {
    "fund_identifier": (
        "Platform-specific fund identifier candidate; not an ISIN or OpenFundScore identity unless independently mapped.",
        "ascii_string",
        "identifier",
    ),
    "share_class_identifier": (
        "Platform-specific identifier for one fund share class.",
        "ascii_string",
        "identifier",
    ),
    "share_class_name": (
        "Displayed name of one fund share class.",
        "unicode_string",
        "text",
    ),
    "subscription_fee": (
        "Displayed subscription or purchase fee rate candidate.",
        "decimal_string",
        "percent",
    ),
    "redemption_fee_tiers": (
        "Displayed redemption fee schedule by holding-period tier candidate.",
        "tier_array",
        "percent_by_holding_period",
    ),
    "sales_service_fee": (
        "Displayed recurring sales-service fee rate candidate.",
        "decimal_string",
        "percent_per_year",
    ),
    "ongoing_fee": (
        "Displayed ongoing-charge category candidate; presence on the platform has not been observed.",
        "decimal_string",
        "percent_per_year",
    ),
    "management_fee": (
        "Displayed management-fee category candidate; presence on the platform has not been observed.",
        "decimal_string",
        "percent_per_year",
    ),
    "custody_fee": (
        "Displayed custody-fee category candidate; presence on the platform has not been observed.",
        "decimal_string",
        "percent_per_year",
    ),
    "purchase_amount_limit": (
        "Displayed minimum, maximum, or remaining purchase amount limit candidate.",
        "money_limit_object",
        "currency_amount",
    ),
    "subscription_availability": (
        "Whether subscription or purchase is displayed as available.",
        "availability_enum",
        "status",
    ),
    "redemption_availability": (
        "Whether redemption is displayed as available.",
        "availability_enum",
        "status",
    ),
    "sale_availability": (
        "Whether the share class is displayed for sale on the platform.",
        "availability_enum",
        "status",
    ),
    "platform_rating": (
        "A proprietary platform rating, if ever authorized and observed; external only.",
        "external_rating_object",
        "provider_defined",
    ),
}
_PER_FUND_FIELDS = frozenset(_FIELD_DEFINITIONS)
_MARKETING_FIELD = "platform_brand_entry"

_PENDING_EVIDENCE = (
    "documented_public_per_fund_interface",
    "field_level_authorization",
    "official_terms",
    "robots_observation",
    "rate_limit",
    "cache_ttl",
    "retention",
    "derived_rights",
    "display_rights",
    "redistribution_rights",
    "attribution_terms",
)
_REEVALUATION_TRIGGERS = (
    "documented_public_api_published",
    "written_field_level_authorization",
    "official_terms_or_robots_change",
)
_REASSESSMENT_CONDITIONS = (
    "A documented public per-fund API and field-level terms are officially published.",
    "Written authorization defines exact fields, access modes, rate limits, caching, retention, derived work, display, redistribution, and attribution.",
    "Official terms or robots information changes; robots remains a collection signal, never authorization.",
    "A user supplies an authorized export; any review remains local_entitlement and does not enable public use.",
)
_UNRESOLVED_ITEMS = (
    "No confirmed public per-fund API or automated adapter.",
    "Per-fund field observation, terms, robots, rate limits, cache TTL, retention, derived work, display, redistribution, and attribution remain unverified.",
    "No login, cookie, session, CAPTCHA bypass, reverse engineering, or private-account collection is permitted.",
)
_MARKETING_PENDING_EVIDENCE = (
    "official_terms",
    "robots_policy",
    "rate_limit",
    "cache_ttl",
    "retention",
    "derived_rights",
    "display_rights",
    "redistribution_rights",
    "attribution_terms",
)
_MARKETING_REEVALUATION_TRIGGERS = (
    "official_terms_or_robots_change",
    "documented_public_api_published",
)


class BoundaryValidationError(ValueError):
    """Stable, redacted boundary validation failure."""

    def __init__(self, *, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        super().__init__(f"{code} at {path}: {message}")


class BoundaryConclusion(StrEnum):
    """Boundary and field authorization outcomes."""

    BLOCKED_PENDING_AUTHORIZATION = "blocked_pending_authorization"
    UNKNOWN_BLOCKED = "unknown_blocked"
    MARKETING_FACT_ONLY = "marketing_fact_only"


class AccessMode(StrEnum):
    """Recognized access selectors; recognition never grants entitlement."""

    UNAUTHENTICATED_OFFICIAL_PAGE = "unauthenticated_official_page"
    DOCUMENTED_PUBLIC_API = "documented_public_api"
    USER_AUTHORIZED_EXPORT = "user_authorized_export"
    LOGIN_SESSION = "login_session"
    PRIVATE_ACCOUNT = "private_account"
    LOGIN = "login"
    COOKIE = "cookie"
    SESSION = "session"
    AUTOMATED = "automated"


_ACCESS_POLICIES = {
    AccessMode.UNAUTHENTICATED_OFFICIAL_PAGE: (
        "boundary_review_only",
        "unknown_blocked",
        False,
    ),
    AccessMode.DOCUMENTED_PUBLIC_API: (
        "no_interface_identified",
        "unknown_blocked",
        False,
    ),
    AccessMode.USER_AUTHORIZED_EXPORT: (
        "local_import_only",
        "local_entitlement",
        False,
    ),
    AccessMode.LOGIN_SESSION: ("prohibited", "unknown_blocked", False),
    AccessMode.PRIVATE_ACCOUNT: ("prohibited", "unknown_blocked", False),
    AccessMode.LOGIN: ("prohibited", "unknown_blocked", False),
    AccessMode.COOKIE: ("prohibited", "unknown_blocked", False),
    AccessMode.SESSION: ("prohibited", "unknown_blocked", False),
    AccessMode.AUTOMATED: ("prohibited", "unknown_blocked", False),
}
_PROHIBITED_ACCESS = frozenset(
    {
        AccessMode.LOGIN_SESSION,
        AccessMode.PRIVATE_ACCOUNT,
        AccessMode.LOGIN,
        AccessMode.COOKIE,
        AccessMode.SESSION,
        AccessMode.AUTOMATED,
    }
)


class BoundaryUse(StrEnum):
    """Requested downstream purposes reviewed independently."""

    INGESTION = "ingestion"
    CACHE = "cache"
    DERIVED = "derived"
    DISPLAY = "display"
    REDISTRIBUTION = "redistribution"
    OPEN_SCORE = "open_score"
    AUTOMATED_ADAPTER = "automated_adapter"


class UseDecision(StrEnum):
    """Stable field-use outcome."""

    UNKNOWN_BLOCKED = "unknown_blocked"


@dataclass(frozen=True, slots=True)
class AccessModeDecision:
    access_mode: AccessMode
    project_collection: str
    default_rights_mode: str
    public_by_default: bool


@dataclass(frozen=True, slots=True)
class SourceBoundaryDecision:
    source_id: str
    url: str
    host: str
    scope: str
    observation: str
    evidence_status: str
    retrieved_at: str
    reviewed_at: str
    terms_status: str
    terms_url: str
    robots_status: str
    robots_url: str
    robots_is_authorization: bool
    rate_limit_status: str
    rate_limit_value: str
    rights_status: str


@dataclass(frozen=True, slots=True)
class FieldBoundaryDecision:
    field_id: str
    definition: str
    value_type: str
    unit: str
    grain: str
    public_observation: str
    access_mode_status: str
    authorization_status: BoundaryConclusion
    official_source_url: str
    official_evidence_status: str
    evidence_retrieved_at: str
    evidence_reviewed_at: str
    terms_status: str
    terms_url: str
    robots_status: str
    robots_url: str
    robots_is_authorization: bool
    rate_limit_status: str
    rate_limit_value: str
    cache_status: str
    cache_ttl_seconds: str
    retention_status: str
    retention_value: str
    derived_status: str
    display_status: str
    redistribution_status: str
    attribution_status: str
    provenance: tuple[str, ...]
    review_status: str
    pending_evidence: tuple[str, ...]
    reevaluation_triggers: tuple[str, ...]
    namespace: str
    open_score_eligible: bool
    automated_ingestion_allowed: bool


@dataclass(frozen=True, slots=True)
class AntFortuneBoundaryDecision:
    format_version: int
    boundary_id: str
    boundary_version: str
    provider_id: str
    reviewed_at: str
    as_of: str
    conclusion: BoundaryConclusion
    automated_adapter_available: bool
    legal_permission_claimed: bool
    per_fund_public_api_status: str
    collection_policy: str
    resource_sha256: str
    access_modes: tuple[AccessModeDecision, ...]
    prohibited_collection: tuple[str, ...]
    sources: tuple[SourceBoundaryDecision, ...]
    fields: tuple[FieldBoundaryDecision, ...]
    reassessment_conditions: tuple[str, ...]
    unresolved_items: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FieldDecision:
    """Immutable fail-closed purpose decision for one candidate field."""

    boundary_id: str
    boundary_version: str
    resource_sha256: str
    reviewed_at: str
    field_id: str
    namespace: str
    access_mode: AccessMode
    requested_uses: tuple[BoundaryUse, ...]
    authorization_status: BoundaryConclusion
    use_decisions: tuple[tuple[str, UseDecision], ...]
    allowed_uses: tuple[tuple[str, bool], ...]
    ingestion_allowed: bool
    cache_allowed: bool
    derived_allowed: bool
    display_allowed: bool
    redistribution_allowed: bool
    publication_allowed: bool
    open_score_allowed: bool
    automated_adapter_allowed: bool
    affects_open_score: bool
    reason_code: str


AntFortuneFieldAccessDecision = FieldDecision


def _fail(code: str, path: str, message: str) -> NoReturn:
    raise BoundaryValidationError(code=code, path=path, message=message) from None


def _copy_json_document(document: object) -> object:
    """Build one bounded snapshot without trusting caller container methods."""

    active: set[int] = set()
    nodes = 0

    def copy_value(value: object, *, path: str, depth: int) -> object:
        nonlocal nodes
        nodes += 1
        if depth > _MAX_DEPTH or nodes > _MAX_NODES:
            _fail("invalid_document", path, "boundary must be a bounded JSON object")
        if value is None or type(value) is bool:
            return value
        if isinstance(value, str):
            try:
                result = str.__str__(value)
            except Exception:  # noqa: BLE001 - hostile scalar boundary
                _fail("invalid_document", path, "boundary contains an invalid scalar")
            if len(result) > _MAX_STRING:
                _fail("invalid_document", path, "boundary contains an oversized string")
            return result
        if isinstance(value, int) and not isinstance(value, bool):
            try:
                return int(value)
            except Exception:  # noqa: BLE001 - hostile scalar boundary
                _fail("invalid_document", path, "boundary contains an invalid scalar")
        if isinstance(value, float):
            try:
                result_float = float(value)
            except Exception:  # noqa: BLE001 - hostile scalar boundary
                _fail("invalid_document", path, "boundary contains an invalid scalar")
            if not math.isfinite(result_float):
                _fail("invalid_document", path, "boundary numbers must be finite")
            return result_float
        if isinstance(value, Mapping):
            identity = id(value)
            if identity in active:
                _fail("invalid_document", path, "boundary cannot contain cycles")
            try:
                if isinstance(value, dict):
                    size = dict.__len__(value)
                    if size > _MAX_WIDTH:
                        _fail(
                            "invalid_document",
                            path,
                            "boundary mapping exceeds its limit",
                        )
                    raw_entries = tuple(dict.items(value))
                else:
                    size = len(value)
                    if size > _MAX_WIDTH:
                        _fail(
                            "invalid_document",
                            path,
                            "boundary mapping exceeds its limit",
                        )
                    iterator = iter(value.items())
                    bounded_entries: list[object] = []
                    for _ in range(size + 1):
                        try:
                            bounded_entries.append(next(iterator))
                        except StopIteration:
                            break
                    raw_entries = tuple(bounded_entries)
            except BoundaryValidationError:
                raise
            except Exception:  # noqa: BLE001 - hostile container boundary
                _fail("invalid_document", path, "boundary contains an invalid mapping")
            if len(raw_entries) != size:
                _fail("invalid_document", path, "boundary mapping exceeds its limit")
            pairs: list[tuple[object, object]] = []
            for entry in raw_entries:
                if type(entry) is tuple and tuple.__len__(entry) == 2:
                    raw_key = tuple.__getitem__(entry, 0)
                    child = tuple.__getitem__(entry, 1)
                elif type(entry) is list and list.__len__(entry) == 2:
                    raw_key = list.__getitem__(entry, 0)
                    child = list.__getitem__(entry, 1)
                else:
                    _fail(
                        "invalid_document", path, "boundary contains an invalid mapping"
                    )
                pairs.append((raw_key, child))
            active.add(identity)
            result: dict[str, object] = {}
            try:
                for raw_key, child in pairs:
                    if type(raw_key) is not str:
                        _fail("invalid_document", path, "boundary keys must be strings")
                    key = cast(str, raw_key)
                    if key in result:
                        _fail("duplicate_key", path, "boundary keys must be unique")
                    result[key] = copy_value(
                        child,
                        path=f"{path}.*",
                        depth=depth + 1,
                    )
            finally:
                active.discard(identity)
            return result
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            identity = id(value)
            if identity in active:
                _fail("invalid_document", path, "boundary cannot contain cycles")
            try:
                if isinstance(value, list):
                    size = list.__len__(value)
                    if size > _MAX_WIDTH:
                        _fail(
                            "invalid_document",
                            path,
                            "boundary sequence exceeds its limit",
                        )
                    children = tuple(
                        list.__getitem__(value, index) for index in range(size)
                    )
                elif isinstance(value, tuple):
                    size = tuple.__len__(value)
                    if size > _MAX_WIDTH:
                        _fail(
                            "invalid_document",
                            path,
                            "boundary sequence exceeds its limit",
                        )
                    children = tuple(
                        tuple.__getitem__(value, index) for index in range(size)
                    )
                else:
                    size = len(value)
                    if size > _MAX_WIDTH:
                        _fail(
                            "invalid_document",
                            path,
                            "boundary sequence exceeds its limit",
                        )
                    children = tuple(value[index] for index in range(size))
            except BoundaryValidationError:
                raise
            except Exception:  # noqa: BLE001 - hostile container boundary
                _fail("invalid_document", path, "boundary contains an invalid sequence")
            if len(children) != size:
                _fail("invalid_document", path, "boundary sequence exceeds its limit")
            active.add(identity)
            try:
                return [
                    copy_value(child, path=f"{path}[{index}]", depth=depth + 1)
                    for index, child in enumerate(children)
                ]
            finally:
                active.discard(identity)
        _fail("invalid_document", path, "boundary must contain JSON-compatible values")

    try:
        return copy_value(document, path="$", depth=0)
    except RecursionError:
        _fail("invalid_document", "$", "boundary exceeds its recursion limit")


def _closed_object(value: object, fields: set[str], path: str) -> dict[str, object]:
    if type(value) is not dict:
        _fail("invalid_shape", path, "boundary object has an invalid shape")
    item = cast(dict[str, object], value)
    unknown = set(item) - fields
    if unknown:
        _fail("unknown_field", path, "boundary object fields are closed")
    if set(item) != fields:
        _fail("invalid_shape", path, "boundary object is missing required fields")
    return item


def _identifier(value: object, path: str) -> str:
    if (
        type(value) is not str
        or len(value) > 128
        or _IDENTIFIER_RE.fullmatch(value) is None
    ):
        _fail("invalid_identifier", path, "identifier must be bounded lowercase ASCII")
    return cast(str, value)


def _text(value: object, path: str) -> str:
    if type(value) is not str or not value or len(value) > _MAX_STRING:
        _fail("invalid_string", path, "value must be a non-empty bounded string")
    return cast(str, value)


def _audit_text(value: object, path: str) -> str:
    text = _text(value, path)
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in text):
        _fail("invalid_string", path, "audit text must not contain control characters")
    return text


def _strict_boolean(value: object, path: str) -> bool:
    if type(value) is not bool:
        _fail("invalid_boolean", path, "value must be a JSON boolean")
    return cast(bool, value)


def _string_list(value: object, path: str) -> tuple[str, ...]:
    if type(value) is not list:
        _fail("invalid_shape", path, "value must be an array")
    result = tuple(_text(item, f"{path}[{index}]") for index, item in enumerate(value))
    if len(set(result)) != len(result):
        _fail("policy_violation", path, "array entries must be unique")
    return result


def _timestamp(value: object, path: str) -> str:
    text = _text(value, path)
    if _TIMESTAMP_RE.fullmatch(text) is None:
        _fail("invalid_timestamp", path, "timestamp must use the reviewed UTC profile")
    try:
        date.fromisoformat(text[:10])
    except ValueError:
        _fail("invalid_timestamp", path, "timestamp must be a valid UTC instant")
    return text


def _official_url(value: object, path: str) -> tuple[str, str]:
    text = _text(value, path)
    try:
        parsed = urlsplit(text)
        host = parsed.hostname
        port = parsed.port
    except (UnicodeError, ValueError):
        _fail("invalid_url", path, "source URL must be an allowlisted public HTTPS URL")
    if host is not None:
        try:
            ip_address(host)
        except ValueError:
            pass
        else:
            _fail("invalid_url", path, "source URL must not use an IP literal")
    if (
        parsed.scheme != "https"
        or host not in _ALLOWED_OFFICIAL_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.fragment
    ):
        _fail("invalid_url", path, "source URL must be an allowlisted public HTTPS URL")
    return text, cast(str, host)


def _optional_official_url(value: object, path: str) -> str:
    if value == "not_identified":
        return "not_identified"
    return _official_url(value, path)[0]


def load_ant_fortune_boundary(*, boundary_version: str) -> dict[str, Any]:
    """Load the exact digest-verified policy resource; performs no network access."""
    return resolve_resource(
        resource_type="platform-boundary",
        name="ant_fortune",
        version=boundary_version,
    ).load_json()


def _validate_sources(
    document: dict[str, object], reviewed_at: str
) -> tuple[SourceBoundaryDecision, ...]:
    sources = document["sources"]
    if type(sources) is not list or len(sources) != 2:
        _fail("policy_violation", "$.sources", "official entry inventory must be exact")
    expected = {
        "ant_fortune_official_entry": (
            "https://www.antfortune.com/",
            "www.antfortune.com",
            "brand_and_entry_only",
            "https://www.antfortune.com/robots.txt",
            "Official public entry; not evidence for any per-fund field or API.",
        ),
        "alipay_open_platform_entry": (
            "https://open.alipay.com/",
            "open.alipay.com",
            "open_platform_entry_only",
            "not_identified",
            "Official open-platform entry; no confirmed public Ant Fortune per-fund API.",
        ),
    }
    seen: set[str] = set()
    decisions: list[SourceBoundaryDecision] = []
    for index, raw in enumerate(sources):
        path = f"$.sources[{index}]"
        item = _closed_object(raw, _SOURCE_FIELDS, path)
        source_id = _identifier(item["source_id"], f"{path}.source_id")
        if source_id in seen:
            _fail("policy_violation", "$.sources", "source identifiers must be unique")
        seen.add(source_id)
        if source_id not in expected:
            _fail(
                "policy_violation", f"{path}.source_id", "source is outside inventory"
            )
        url, host = _official_url(item["url"], f"{path}.url")
        (
            expected_url,
            expected_host,
            expected_scope,
            expected_robots,
            expected_observation,
        ) = expected[source_id]
        robots_url = _optional_official_url(item["robots_url"], f"{path}.robots_url")
        observation = _audit_text(item["observation"], f"{path}.observation")
        if (
            url != expected_url
            or host != expected_host
            or item["host"] != host
            or item["scope"] != expected_scope
            or robots_url != expected_robots
            or item["evidence_status"] != "entry_only"
            or item["retrieved_at"] != "provided_verified_design_input"
            or item["reviewed_at"] != reviewed_at
            or item["terms_status"] != "unverified"
            or item["terms_url"] != "not_identified"
            or item["robots_status"] != "unverified_unavailable"
            or item["robots_is_authorization"] is not False
            or item["rate_limit_status"] != "unverified"
            or item["rate_limit_value"] != "not_established"
            or item["rights_status"] != "unknown_blocked"
            or observation != expected_observation
        ):
            _fail(
                "policy_violation",
                path,
                "source evidence exceeds the reviewed boundary",
            )
        decisions.append(
            SourceBoundaryDecision(
                source_id=source_id,
                url=url,
                host=host,
                scope=cast(str, item["scope"]),
                observation=observation,
                evidence_status="entry_only",
                retrieved_at="provided_verified_design_input",
                reviewed_at=reviewed_at,
                terms_status="unverified",
                terms_url="not_identified",
                robots_status="unverified_unavailable",
                robots_url=robots_url,
                robots_is_authorization=False,
                rate_limit_status="unverified",
                rate_limit_value="not_established",
                rights_status="unknown_blocked",
            )
        )
    if seen != set(expected):
        _fail(
            "policy_violation", "$.sources", "official entry inventory must be complete"
        )
    return tuple(decisions)


def _validate_access_modes(
    document: dict[str, object],
) -> tuple[AccessModeDecision, ...]:
    raw_modes = document["access_modes"]
    if type(raw_modes) is not list:
        _fail("invalid_shape", "$.access_modes", "access modes must be an array")
    decisions: list[AccessModeDecision] = []
    seen: set[AccessMode] = set()
    for index, raw in enumerate(raw_modes):
        path = f"$.access_modes[{index}]"
        item = _closed_object(raw, _ACCESS_MODE_FIELDS, path)
        try:
            mode = AccessMode(item["access_mode"])
        except (TypeError, ValueError):
            _fail("invalid_enum", f"{path}.access_mode", "access mode is unsupported")
        if mode in seen:
            _fail("policy_violation", "$.access_modes", "access modes must be unique")
        seen.add(mode)
        actual = (
            item["project_collection"],
            item["default_rights_mode"],
            _strict_boolean(item["public_by_default"], f"{path}.public_by_default"),
        )
        if actual != _ACCESS_POLICIES[mode]:
            _fail("policy_violation", path, "access mode exceeds the reviewed boundary")
        decisions.append(
            AccessModeDecision(
                access_mode=mode,
                project_collection=cast(str, item["project_collection"]),
                default_rights_mode=cast(str, item["default_rights_mode"]),
                public_by_default=cast(bool, item["public_by_default"]),
            )
        )
    if seen != set(AccessMode):
        _fail(
            "policy_violation", "$.access_modes", "every access mode must be explicit"
        )
    return tuple(decisions)


def _validate_per_fund_field(
    item: dict[str, object],
    *,
    path: str,
    field_id: str,
    reviewed_at: str,
) -> FieldBoundaryDecision:
    for boolean_field in (
        "robots_is_authorization",
        "open_score_eligible",
        "automated_ingestion_allowed",
    ):
        _strict_boolean(item[boolean_field], f"{path}.{boolean_field}")
    definition, value_type, unit = _FIELD_DEFINITIONS[field_id]
    expected_namespace = (
        "external_ratings" if field_id == "platform_rating" else "provider_observation"
    )
    enum_values = {
        "authorization_status": {"unknown_blocked", "authorized"},
        "cache_status": {"unknown_blocked", "allowed"},
        "retention_status": {"unknown_blocked", "allowed"},
        "derived_status": {"unknown_blocked", "allowed"},
        "display_status": {"unknown_blocked", "allowed"},
        "redistribution_status": {"unknown_blocked", "allowed"},
        "attribution_status": {
            "unverified_unknown_blocked",
            "required",
            "not_required",
        },
    }
    for key, allowed_values in enum_values.items():
        if item[key] not in allowed_values:
            _fail("invalid_enum", f"{path}.{key}", "field status is unsupported")
    policy_values = {
        "definition": definition,
        "value_type": value_type,
        "unit": unit,
        "grain": "per_fund_share_class",
        "public_observation": "not_observed",
        "access_mode_status": "no_authorized_access_mode",
        "authorization_status": "unknown_blocked",
        "official_source_url": "not_identified",
        "official_evidence_status": "not_identified",
        "evidence_retrieved_at": "not_retrieved",
        "evidence_reviewed_at": reviewed_at,
        "terms_status": "unverified_unknown_blocked",
        "terms_url": "not_identified",
        "robots_status": "unverified_unavailable",
        "robots_url": "not_identified",
        "robots_is_authorization": False,
        "rate_limit_status": "unverified_unknown_blocked",
        "rate_limit_value": "not_established",
        "cache_status": "unknown_blocked",
        "cache_ttl_seconds": "not_established",
        "retention_status": "unknown_blocked",
        "retention_value": "not_established",
        "derived_status": "unknown_blocked",
        "display_status": "unknown_blocked",
        "redistribution_status": "unknown_blocked",
        "attribution_status": "unverified_unknown_blocked",
        "review_status": "pending_evidence",
        "namespace": expected_namespace,
        "open_score_eligible": False,
        "automated_ingestion_allowed": False,
    }
    if any(item[key] != value for key, value in policy_values.items()):
        _fail("policy_violation", path, "field policy exceeds the reviewed boundary")
    provenance = _string_list(item["provenance"], f"{path}.provenance")
    pending = _string_list(item["pending_evidence"], f"{path}.pending_evidence")
    triggers = _string_list(
        item["reevaluation_triggers"], f"{path}.reevaluation_triggers"
    )
    if (
        provenance != ("boundary_review:no_per_fund_source_identified",)
        or pending != _PENDING_EVIDENCE
        or triggers != _REEVALUATION_TRIGGERS
    ):
        _fail(
            "policy_violation", path, "field evidence inventory must remain fail closed"
        )
    return FieldBoundaryDecision(
        field_id=field_id,
        definition=definition,
        value_type=value_type,
        unit=unit,
        grain="per_fund_share_class",
        public_observation="not_observed",
        access_mode_status="no_authorized_access_mode",
        authorization_status=BoundaryConclusion.UNKNOWN_BLOCKED,
        official_source_url="not_identified",
        official_evidence_status="not_identified",
        evidence_retrieved_at="not_retrieved",
        evidence_reviewed_at=reviewed_at,
        terms_status="unverified_unknown_blocked",
        terms_url="not_identified",
        robots_status="unverified_unavailable",
        robots_url="not_identified",
        robots_is_authorization=False,
        rate_limit_status="unverified_unknown_blocked",
        rate_limit_value="not_established",
        cache_status="unknown_blocked",
        cache_ttl_seconds="not_established",
        retention_status="unknown_blocked",
        retention_value="not_established",
        derived_status="unknown_blocked",
        display_status="unknown_blocked",
        redistribution_status="unknown_blocked",
        attribution_status="unverified_unknown_blocked",
        provenance=provenance,
        review_status="pending_evidence",
        pending_evidence=pending,
        reevaluation_triggers=triggers,
        namespace=expected_namespace,
        open_score_eligible=False,
        automated_ingestion_allowed=False,
    )


def _validate_marketing_field(
    item: dict[str, object], *, path: str, reviewed_at: str
) -> FieldBoundaryDecision:
    for boolean_field in (
        "robots_is_authorization",
        "open_score_eligible",
        "automated_ingestion_allowed",
    ):
        _strict_boolean(item[boolean_field], f"{path}.{boolean_field}")
    expected = {
        "definition": "Official public homepage/open-platform entry and brand-presence fact only.",
        "value_type": "official_entry_fact",
        "unit": "not_applicable",
        "grain": "platform_marketing",
        "public_observation": "observed_official_entry_only",
        "access_mode_status": "boundary_review_only",
        "authorization_status": "marketing_fact_only",
        "official_source_url": "https://www.antfortune.com/",
        "official_evidence_status": "entry_fact_only_not_per_fund_evidence",
        "evidence_retrieved_at": "provided_verified_design_input",
        "evidence_reviewed_at": reviewed_at,
        "terms_status": "unverified_unknown_blocked",
        "terms_url": "not_identified",
        "robots_status": "unverified_unavailable",
        "robots_url": "https://www.antfortune.com/robots.txt",
        "robots_is_authorization": False,
        "rate_limit_status": "unverified_unknown_blocked",
        "rate_limit_value": "not_established",
        "cache_status": "unknown_blocked",
        "cache_ttl_seconds": "not_established",
        "retention_status": "unknown_blocked",
        "retention_value": "not_established",
        "derived_status": "unknown_blocked",
        "display_status": "unknown_blocked",
        "redistribution_status": "unknown_blocked",
        "attribution_status": "unverified_unknown_blocked",
        "review_status": "entry_fact_only",
        "namespace": "platform_marketing",
        "open_score_eligible": False,
        "automated_ingestion_allowed": False,
    }
    _official_url(item["official_source_url"], f"{path}.official_source_url")
    _official_url(item["robots_url"], f"{path}.robots_url")
    if any(item[key] != value for key, value in expected.items()):
        _fail("policy_violation", path, "marketing fact exceeds entry-only evidence")
    provenance = _string_list(item["provenance"], f"{path}.provenance")
    pending = _string_list(item["pending_evidence"], f"{path}.pending_evidence")
    triggers = _string_list(
        item["reevaluation_triggers"], f"{path}.reevaluation_triggers"
    )
    expected_provenance = (
        "official_entry:https://www.antfortune.com/",
        "official_entry:https://open.alipay.com/",
    )
    if (
        provenance != expected_provenance
        or pending != _MARKETING_PENDING_EVIDENCE
        or triggers != _MARKETING_REEVALUATION_TRIGGERS
    ):
        _fail("policy_violation", path, "marketing evidence inventory is invalid")
    return FieldBoundaryDecision(
        field_id=_MARKETING_FIELD,
        definition=cast(str, item["definition"]),
        value_type=cast(str, item["value_type"]),
        unit=cast(str, item["unit"]),
        grain=cast(str, item["grain"]),
        public_observation=cast(str, item["public_observation"]),
        access_mode_status=cast(str, item["access_mode_status"]),
        authorization_status=BoundaryConclusion.MARKETING_FACT_ONLY,
        official_source_url=cast(str, item["official_source_url"]),
        official_evidence_status=cast(str, item["official_evidence_status"]),
        evidence_retrieved_at=cast(str, item["evidence_retrieved_at"]),
        evidence_reviewed_at=reviewed_at,
        terms_status=cast(str, item["terms_status"]),
        terms_url=cast(str, item["terms_url"]),
        robots_status=cast(str, item["robots_status"]),
        robots_url=cast(str, item["robots_url"]),
        robots_is_authorization=False,
        rate_limit_status=cast(str, item["rate_limit_status"]),
        rate_limit_value=cast(str, item["rate_limit_value"]),
        cache_status=cast(str, item["cache_status"]),
        cache_ttl_seconds=cast(str, item["cache_ttl_seconds"]),
        retention_status=cast(str, item["retention_status"]),
        retention_value=cast(str, item["retention_value"]),
        derived_status=cast(str, item["derived_status"]),
        display_status=cast(str, item["display_status"]),
        redistribution_status=cast(str, item["redistribution_status"]),
        attribution_status=cast(str, item["attribution_status"]),
        provenance=provenance,
        review_status=cast(str, item["review_status"]),
        pending_evidence=pending,
        reevaluation_triggers=triggers,
        namespace="platform_marketing",
        open_score_eligible=False,
        automated_ingestion_allowed=False,
    )


def _validate_fields(
    document: dict[str, object], reviewed_at: str
) -> tuple[FieldBoundaryDecision, ...]:
    raw_fields = document["fields"]
    if type(raw_fields) is not list:
        _fail("invalid_shape", "$.fields", "fields must be an array")
    seen: set[str] = set()
    decisions: list[FieldBoundaryDecision] = []
    for index, raw in enumerate(raw_fields):
        path = f"$.fields[{index}]"
        item = _closed_object(raw, _FIELD_FIELDS, path)
        field_id = _identifier(item["field_id"], f"{path}.field_id")
        if field_id in seen:
            _fail("duplicate_field", "$.fields", "field identifiers must be unique")
        seen.add(field_id)
        if field_id in _PER_FUND_FIELDS:
            decisions.append(
                _validate_per_fund_field(
                    item,
                    path=path,
                    field_id=field_id,
                    reviewed_at=reviewed_at,
                )
            )
        elif field_id == _MARKETING_FIELD:
            decisions.append(
                _validate_marketing_field(item, path=path, reviewed_at=reviewed_at)
            )
        else:
            _fail("policy_violation", f"{path}.field_id", "field is outside inventory")
    if seen != _PER_FUND_FIELDS | {_MARKETING_FIELD}:
        _fail("policy_violation", "$.fields", "field matrix must be complete")
    return tuple(decisions)


def validate_ant_fortune_boundary(
    document: object,
    *,
    expected_version: str,
    resource_sha256: str,
) -> AntFortuneBoundaryDecision:
    """Validate one untrusted policy record and return an immutable snapshot."""
    if (
        type(expected_version) is not str
        or _VERSION_RE.fullmatch(expected_version) is None
        or expected_version != _SUPPORTED_BOUNDARY_VERSION
    ):
        _fail("invalid_selector", "$expected_version", "version selector is invalid")
    if (
        type(resource_sha256) is not str
        or _SHA256_RE.fullmatch(resource_sha256) is None
    ):
        _fail("invalid_digest", "$resource_sha256", "resource digest must be SHA-256")
    snapshot = _copy_json_document(document)
    root = _closed_object(snapshot, _TOP_LEVEL_FIELDS, "$")
    if type(root["format_version"]) is not int or root["format_version"] != 1:
        _fail("invalid_integer", "$.format_version", "format version must be integer 1")
    boundary_id = _identifier(root["boundary_id"], "$.boundary_id")
    provider_id = _identifier(root["provider_id"], "$.provider_id")
    boundary_version = _text(root["boundary_version"], "$.boundary_version")
    if (
        _VERSION_RE.fullmatch(boundary_version) is None
        or boundary_version != expected_version
    ):
        _fail(
            "invalid_version",
            "$.boundary_version",
            "boundary version must match selector",
        )
    reviewed_at = _timestamp(root["reviewed_at"], "$.reviewed_at")
    as_of = _timestamp(root["as_of"], "$.as_of")
    if (
        boundary_id != "ant_fortune_public_data_boundary"
        or provider_id != "ant_fortune"
        or as_of != reviewed_at
        or root["conclusion"] != "blocked_pending_authorization"
        or root["automated_adapter_available"] is not False
        or root["legal_permission_claimed"] is not False
        or root["per_fund_public_api_status"] != "not_identified"
        or root["collection_policy"] != "no_ingestion"
    ):
        _fail(
            "policy_violation", "$", "boundary cannot claim collection or authorization"
        )
    access_modes = _validate_access_modes(root)
    prohibited = _string_list(root["prohibited_collection"], "$.prohibited_collection")
    expected_prohibited = (
        "account_password",
        "automated_adapter",
        "captcha_bypass",
        "private_holdings",
        "reverse_engineering",
        "session_cookie",
        "sms_code",
    )
    if prohibited != expected_prohibited:
        _fail(
            "policy_violation",
            "$.prohibited_collection",
            "prohibitions must be complete",
        )
    sources = _validate_sources(root, reviewed_at)
    fields = _validate_fields(root, reviewed_at)
    reassessment_conditions = _string_list(
        root["reassessment_conditions"], "$.reassessment_conditions"
    )
    if reassessment_conditions != _REASSESSMENT_CONDITIONS:
        _fail("policy_violation", "$.reassessment_conditions", "triggers are required")
    unresolved_items = _string_list(root["unresolved_items"], "$.unresolved_items")
    if unresolved_items != _UNRESOLVED_ITEMS:
        _fail("policy_violation", "$.unresolved_items", "unknowns must remain explicit")
    return AntFortuneBoundaryDecision(
        format_version=1,
        boundary_id=boundary_id,
        boundary_version=boundary_version,
        provider_id=provider_id,
        reviewed_at=reviewed_at,
        as_of=as_of,
        conclusion=BoundaryConclusion.BLOCKED_PENDING_AUTHORIZATION,
        automated_adapter_available=False,
        legal_permission_claimed=False,
        per_fund_public_api_status="not_identified",
        collection_policy="no_ingestion",
        resource_sha256=resource_sha256,
        access_modes=access_modes,
        prohibited_collection=prohibited,
        sources=sources,
        fields=fields,
        reassessment_conditions=reassessment_conditions,
        unresolved_items=unresolved_items,
    )


def decide_ant_fortune_field(
    field_id: str,
    *,
    access_mode: AccessMode | str,
    requested_uses: frozenset[BoundaryUse],
    boundary_version: str,
) -> FieldDecision:
    """Return a fail-closed decision without collecting or opening any platform URL."""
    selected_field = _identifier(field_id, "$field_id")
    try:
        selected_access = AccessMode(access_mode)
    except Exception:  # noqa: BLE001 - hostile public selector boundary
        _fail("invalid_selector", "$access_mode", "access mode selector is unsupported")
    if type(requested_uses) is not frozenset or any(
        type(item) is not BoundaryUse for item in requested_uses
    ):
        _fail("invalid_selector", "$requested_uses", "uses must be typed frozen values")
    resource = resolve_resource(
        resource_type="platform-boundary",
        name="ant_fortune",
        version=boundary_version,
    )
    boundary = validate_ant_fortune_boundary(
        resource.load_json(),
        expected_version=boundary_version,
        resource_sha256=resource.info.sha256,
    )
    field = next(
        (item for item in boundary.fields if item.field_id == selected_field), None
    )
    if field is None:
        _fail(
            "invalid_selector", "$field_id", "field is outside the reviewed inventory"
        )
    uses = tuple(sorted(requested_uses, key=lambda item: item.value))
    if selected_access in _PROHIBITED_ACCESS:
        reason = "access_mode_prohibited"
    elif (
        field.field_id == "platform_rating" and BoundaryUse.OPEN_SCORE in requested_uses
    ):
        reason = "external_rating_core_score_prohibited"
    elif BoundaryUse.AUTOMATED_ADAPTER in requested_uses:
        reason = "automated_adapter_prohibited"
    elif selected_access is AccessMode.USER_AUTHORIZED_EXPORT:
        reason = "local_authorization_required"
    elif field.authorization_status is BoundaryConclusion.MARKETING_FACT_ONLY:
        reason = "marketing_use_rights_unverified"
    else:
        reason = "field_authorization_missing"
    use_decisions = tuple((use.value, UseDecision.UNKNOWN_BLOCKED) for use in uses)
    allowed_uses = tuple((use.value, False) for use in uses)
    return FieldDecision(
        boundary_id=boundary.boundary_id,
        boundary_version=boundary.boundary_version,
        resource_sha256=boundary.resource_sha256,
        reviewed_at=boundary.reviewed_at,
        field_id=field.field_id,
        namespace=field.namespace,
        access_mode=selected_access,
        requested_uses=uses,
        authorization_status=field.authorization_status,
        use_decisions=use_decisions,
        allowed_uses=allowed_uses,
        ingestion_allowed=False,
        cache_allowed=False,
        derived_allowed=False,
        display_allowed=False,
        redistribution_allowed=False,
        publication_allowed=False,
        open_score_allowed=False,
        automated_adapter_allowed=False,
        affects_open_score=False,
        reason_code=reason,
    )
