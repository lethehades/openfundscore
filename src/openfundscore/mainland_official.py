"""Offline parser for locally frozen Mainland official disclosure snapshots.

The adapter has deliberately no transport.  It accepts caller-supplied bytes, a
local Path, or a Mapping and authorizes every mapped provider record against an
explicit point-in-time entitlement.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from ipaddress import ip_address
from itertools import islice
from pathlib import Path
from typing import NoReturn
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator

from .provider_sdk import (
    AuthenticationMode,
    IngestionRequest,
    ProviderCapability,
    ProviderContractError,
    ProviderEntitlements,
    RateLimit,
    RateLimitBudget,
    RightsMode,
    SourceType,
    authorize_ingestion,
)
from .provider_semantics import (
    ProviderRecordValidationError,
    parse_rfc3339_timestamp,
)
from .resources import resolve_resource
from .validation import RecordValidationError, validate_record

__all__ = (
    "MainlandOfficialSnapshotAdapter",
    "SnapshotValidationError",
    "load_mainland_entitlements",
)

_MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
_MAX_NODES = 25_000
_MAX_DEPTH = 64
_MAX_CONTAINER_ITEMS = 10_000
_MAX_STRING_BYTES = 65_536
_MAX_TOTAL_STRING_BYTES = 2_000_000
_CONCRETE_PATH_TYPE = type(Path())
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$", re.ASCII)
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)
_DNS = re.compile(
    r"(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z",
    re.ASCII,
)
_DEFAULT_HOSTS: dict[str, tuple[str, ...]] = {
    "regulator": ("csrc.gov.cn",),
    "exchange": ("sse.com.cn", "szse.cn"),
}
_SOURCE_TYPES = {
    "regulator": SourceType.REGULATOR,
    "exchange": SourceType.EXCHANGE,
    "fund_company": SourceType.FUND_COMPANY_OR_MANAGER,
}
_CAPABILITIES = {
    "identity": ProviderCapability.GET_PROFILE,
    "nav": ProviderCapability.GET_NAV_SERIES,
    "report": ProviderCapability.GET_DISCLOSURES,
    "manager_tenure": ProviderCapability.GET_MANAGER_TENURES,
    "benchmark": ProviderCapability.GET_BENCHMARK,
    "holding": ProviderCapability.GET_HOLDINGS,
    "corporate_action": ProviderCapability.GET_CORPORATE_ACTIONS,
}
_ENTITY_TYPES = {
    "nav": frozenset({"share_class"}),
    "report": frozenset({"report"}),
    "manager_tenure": frozenset({"manager_tenure"}),
    "benchmark": frozenset({"benchmark"}),
    "holding": frozenset({"holding"}),
    "corporate_action": frozenset({"corporate_action"}),
    "identity": frozenset({"fund_strategy", "share_class", "manager", "benchmark"}),
}
_PROFILE_FIELDS: dict[tuple[str, str], frozenset[str]] = {
    ("identity", "fund_strategy"): frozenset({"canonical_name"}),
    ("identity", "share_class"): frozenset({"canonical_name", "class_code"}),
    ("identity", "manager"): frozenset({"canonical_name"}),
    ("identity", "benchmark"): frozenset({"canonical_name"}),
    ("nav", "share_class"): frozenset({"nav"}),
    ("report", "report"): frozenset({"report_url", "report_document_hash"}),
    ("manager_tenure", "manager_tenure"): frozenset(
        {"manager_id", "fund_strategy_id", "tenure_start", "tenure_end"}
    ),
    ("benchmark", "benchmark"): frozenset({"canonical_name"}),
    ("holding", "holding"): frozenset(
        {"fund_strategy_id", "instrument_id", "weight", "coverage"}
    ),
    ("corporate_action", "corporate_action"): frozenset(
        {"action_type", "effective_at", "before_id", "after_id"}
    ),
}
_TEXT_FIELDS = frozenset({"canonical_name", "class_code"})
_RELATION_FIELDS = frozenset(
    {"manager_id", "fund_strategy_id", "instrument_id", "before_id", "after_id"}
)
_NULL_QUALIFIER_FIELDS = frozenset(
    {
        "canonical_name",
        "class_code",
        "manager_id",
        "fund_strategy_id",
        "instrument_id",
        "before_id",
        "after_id",
        "report_url",
        "report_document_hash",
        "tenure_start",
        "tenure_end",
        "action_type",
        "effective_at",
    }
)
_KNOWN_ERROR_FIELDS = frozenset(
    {
        "schema_version",
        "provider_id",
        "snapshot_id",
        "source_type",
        "jurisdiction",
        "official_source_url",
        "retrieved_at",
        "published_at",
        "as_of",
        "effective_at",
        "evaluated_at",
        "document_sha256",
        "timezone",
        "currency",
        "units",
        "rights",
        "items",
        "item_id",
        "item_type",
        "entity_type",
        "entity_id",
        "exact_identifiers",
        "scheme",
        "value",
        "observations",
        "observation_id",
        "field",
        "raw_value",
        "fetched_at",
        "valid_from",
        "valid_to",
        "unit",
        "source_url",
        "source_document_hash",
        "point_in_time_status",
        "methodology",
        "quality_state",
        "conflict_group",
        "mode",
        "terms_url",
        "reviewed_at",
        "valid_until",
        "cache_allowed",
        "derived_works_allowed",
        "redistribution_allowed",
        "attribution_required",
        "public_display_allowed",
        "retention_days",
        "source_evidence_url",
        "nav",
        "weight",
        "coverage",
    }
)


def _safe_error_path(path: object) -> str:
    if path == "$document":
        return "$document"
    if not isinstance(path, str) or not path.startswith("$"):
        return "$document"
    safe = "$"
    position = 1
    while position < len(path):
        index = re.match(r"\[([0-9]+)\]", path[position:])
        if index is not None:
            safe += index.group(0)
            position += len(index.group(0))
            continue
        field = re.match(r"\.([A-Za-z_][A-Za-z0-9_]*)", path[position:])
        if field is None or field.group(1) not in _KNOWN_ERROR_FIELDS:
            break
        safe += field.group(0)
        position += len(field.group(0))
    return safe


class SnapshotValidationError(ValueError):
    """Stable redacted error at the frozen-snapshot trust boundary."""

    def __init__(self, *, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = _safe_error_path(path)
        super().__init__(f"{self.path}: {code}: {message}")


def _reject(*, code: str, path: str, message: str) -> NoReturn:
    raise SnapshotValidationError(code=code, path=path, message=message)


def _require_schema(condition: bool, path: str) -> None:
    if not condition:
        _reject(
            code="snapshot_schema",
            path=path,
            message="snapshot violates the closed versioned bundle schema",
        )


def _safe_copy(document: object) -> object:
    active: set[int] = set()
    nodes = 0
    total_string_bytes = 0

    def fail(path: str, code: str = "invalid_document") -> NoReturn:
        _reject(
            code=code,
            path=path,
            message=(
                "snapshot exceeds the supported complexity bound"
                if code == "snapshot_too_complex"
                else "snapshot must be finite JSON data"
            ),
        )

    def string(value: str, path: str) -> str:
        nonlocal total_string_bytes
        try:
            normalized = str.__str__(value)
            size = len(normalized.encode("utf-8"))
        except (TypeError, UnicodeEncodeError):
            fail(path)
        total_string_bytes += size
        if size > _MAX_STRING_BYTES or total_string_bytes > _MAX_TOTAL_STRING_BYTES:
            fail(path, "snapshot_too_complex")
        return normalized

    def copy(value: object, path: str, depth: int) -> object:
        nonlocal nodes
        nodes += 1
        if nodes > _MAX_NODES or depth > _MAX_DEPTH:
            fail(path, "snapshot_too_complex")
        if value is None:
            return None
        if isinstance(value, str):
            return string(value, path)
        if type(value) is bool:
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            return int.__int__(value)
        if isinstance(value, float):
            result = float.__float__(value)
            if not math.isfinite(result):
                fail(path)
            return result
        if isinstance(value, Mapping):
            identity = id(value)
            if identity in active:
                fail(path)
            pairs: tuple[tuple[object, object], ...] | None = None
            size = -1
            try:
                if type(value) is dict:
                    size = dict.__len__(value)
                    if size <= _MAX_CONTAINER_ITEMS:
                        pairs = tuple(dict.items(value))
                else:
                    size = len(value)
                    if size <= _MAX_CONTAINER_ITEMS:
                        entries = tuple(islice(value.items(), size + 1))
                        unpacked: list[tuple[object, object]] = []
                        for entry in entries:
                            raw_key, child = entry
                            unpacked.append((raw_key, child))
                        pairs = tuple(unpacked)
            except Exception:  # noqa: BLE001 - hostile Mapping may raise anything
                pairs = None
            if pairs is None or len(pairs) > _MAX_CONTAINER_ITEMS or len(pairs) != size:
                fail(path, "snapshot_too_complex")
            active.add(identity)
            result: dict[str, object] = {}
            try:
                for raw_key, child in pairs:
                    if not isinstance(raw_key, str):
                        fail(path)
                    key = string(raw_key, path)
                    if key in result:
                        fail(path)
                    result[key] = copy(child, f"{path}.{key}", depth + 1)
            finally:
                active.discard(identity)
            return result
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray, memoryview)
        ):
            identity = id(value)
            if identity in active:
                fail(path)
            children: tuple[object, ...] | None = None
            try:
                if type(value) is list:
                    size = list.__len__(value)
                    if size <= _MAX_CONTAINER_ITEMS:
                        children = tuple(
                            list.__getitem__(value, index) for index in range(size)
                        )
                else:
                    size = len(value)
                    if size <= _MAX_CONTAINER_ITEMS:
                        children = tuple(value[index] for index in range(size))
            except Exception:  # noqa: BLE001 - hostile Sequence may raise anything
                children = None
            if children is None:
                fail(path, "snapshot_too_complex")
            active.add(identity)
            try:
                return [
                    copy(child, f"{path}[{index}]", depth + 1)
                    for index, child in enumerate(children)
                ]
            finally:
                active.discard(identity)
        fail(path)

    try:
        return copy(document, "$", 0)
    except RecursionError:
        _reject(
            code="snapshot_too_complex",
            path="$",
            message="snapshot exceeds the supported complexity bound",
        )


def _load_source(source: bytes | Path | Mapping[str, object]) -> dict[str, object]:
    if type(source) is _CONCRETE_PATH_TYPE:
        payload: bytes | None = None
        try:
            with source.open("rb") as stream:
                payload = stream.read(_MAX_SNAPSHOT_BYTES + 1)
        except OSError:
            payload = None
        if payload is None:
            _reject(
                code="snapshot_io",
                path="$document",
                message="snapshot document could not be read",
            )
        source = payload
    if type(source) is bytes:
        if bytes.__len__(source) > _MAX_SNAPSHOT_BYTES:
            _reject(
                code="snapshot_too_large",
                path="$document",
                message="snapshot exceeds the supported byte limit",
            )
        text: str | None = None
        try:
            text = bytes.decode(source, "utf-8", errors="strict")
        except UnicodeDecodeError:
            pass
        if text is None:
            _reject(
                code="snapshot_format",
                path="$document",
                message="snapshot must be strict UTF-8 JSON",
            )
        parsed: object | None = None
        failed = False
        try:
            parsed = json.loads(
                text,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            )
        except (ValueError, RecursionError):
            failed = True
        if failed:
            _reject(
                code="snapshot_format",
                path="$document",
                message="snapshot must be strict UTF-8 JSON",
            )
        source = parsed  # type: ignore[assignment]
    if not isinstance(source, Mapping):
        _reject(
            code="invalid_document",
            path="$",
            message="snapshot root must be an object",
        )
    copied = _safe_copy(source)
    if not isinstance(copied, dict):
        _reject(
            code="invalid_document",
            path="$",
            message="snapshot root must be an object",
        )
    return copied


def _reject_constant(_: str) -> object:
    raise ValueError("non-finite JSON constant")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _timestamp(value: object, path: str) -> datetime:
    parsed: datetime | None = None
    try:
        parsed = parse_rfc3339_timestamp(value, path=path)
    except ProviderRecordValidationError:
        pass
    normalized: datetime | None = None
    if parsed is not None:
        try:
            normalized = parsed.astimezone(UTC)
        except (OverflowError, ValueError, OSError):
            pass
    if normalized is None:
        _reject(
            code="invalid_timestamp",
            path=path,
            message="timestamp must use the supported RFC3339 profile",
        )
    return normalized


def _public_https_host(value: object, path: str) -> str:
    host: str | None = None
    valid = False
    if isinstance(value, str):
        try:
            parsed = urlsplit(value)
            host = parsed.hostname
            port = parsed.port
            valid = (
                parsed.scheme == "https"
                and host is not None
                and parsed.username is None
                and parsed.password is None
                and not parsed.fragment
                and (port is None or port > 0)
                and _DNS.fullmatch(host) is not None
                and host != "localhost"
                and not host.endswith(".localhost")
            )
        except (UnicodeError, ValueError):
            valid = False
    if valid and host is not None:
        try:
            ip_address(host)
        except ValueError:
            return host.lower()
    _reject(
        code="unapproved_source",
        path=path,
        message="source must be an approved public HTTPS hostname",
    )


def _host_matches(host: str, approved: str, *, exact: bool) -> bool:
    return (
        host == approved if exact else host == approved or host.endswith("." + approved)
    )


def _date_value(value: object, path: str) -> date | None:
    if value is None:
        return None
    parsed: date | None = None
    if isinstance(value, str) and _DATE.fullmatch(value) is not None:
        try:
            parsed = date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
        except ValueError:
            pass
    if parsed is None:
        _reject(code="invalid_item", path=path, message="date field is invalid")
    return parsed


def _decimal_value(value: object, path: str) -> Decimal:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        _reject(code="invalid_holding", path=path, message="holding value is invalid")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _reject(code="invalid_holding", path=path, message="holding value is invalid")
    if not result.is_finite():
        _reject(code="invalid_holding", path=path, message="holding value is invalid")
    return result


def _has_visible_text(value: object) -> bool:
    return (
        type(value) is str
        and 0 < len(value) <= 512
        and any(
            unicodedata.category(character)[:1] in {"L", "N"} for character in value
        )
        and not any(character in {"\u200b", "\u2060", "\ufeff"} for character in value)
    )


def _is_default_ignorable(character: str) -> bool:
    codepoint = ord(character)
    return (
        unicodedata.category(character) == "Cf"
        or codepoint in {0x034F, 0x3164, 0xFFA0}
        or 0x115F <= codepoint <= 0x1160
        or 0x17B4 <= codepoint <= 0x17B5
        or 0x180B <= codepoint <= 0x180D
        or 0xFE00 <= codepoint <= 0xFE0F
        or 0xE0100 <= codepoint <= 0xE01EF
    )


def _has_substantive_identifier(value: object) -> bool:
    return (
        type(value) is str
        and 0 < len(value) <= 512
        and any(
            not character.isspace() and not _is_default_ignorable(character)
            for character in value
        )
    )


def load_mainland_entitlements(
    source: bytes | Path | Mapping[str, object],
) -> ProviderEntitlements:
    """Load a closed, local-only entitlement declaration for the CLI boundary."""
    document = _load_source(source)
    required = {
        "schema_version",
        "provider_id",
        "evaluated_at",
        "valid_until",
        "source_type",
        "jurisdictions",
        "authentication_mode",
        "capabilities",
        "rights",
        "rate_limit",
    }
    if set(document) != required or document.get("schema_version") != "0.1.0":
        _reject(
            code="invalid_entitlements",
            path="$entitlements",
            message="entitlement declaration fields are closed and versioned",
        )
    rights = document.get("rights")
    rate_limit = document.get("rate_limit")
    rights_fields = {
        "mode",
        "cache_allowed",
        "cache_ttl_seconds",
        "derived_works_allowed",
        "public_display_allowed",
        "redistribution_allowed",
        "retention_days",
        "attribution_required",
        "terms_url",
        "reviewed_at",
    }
    rate_fields = {"requests_per_period", "period_seconds", "burst"}
    if (
        not isinstance(rights, dict)
        or set(rights) != rights_fields
        or not isinstance(rate_limit, dict)
        or set(rate_limit) != rate_fields
        or document.get("jurisdictions") != ["CN"]
        or document.get("authentication_mode") != "local_entitlement"
    ):
        _reject(
            code="invalid_entitlements",
            path="$entitlements",
            message="entitlement declaration is malformed",
        )
    source_type = document.get("source_type")
    capabilities = document.get("capabilities")
    if (
        not isinstance(source_type, str)
        or source_type not in _SOURCE_TYPES
        or not isinstance(capabilities, list)
    ):
        _reject(
            code="invalid_entitlements",
            path="$entitlements",
            message="entitlement source or capabilities are unsupported",
        )
    converted_capabilities: frozenset[ProviderCapability] | None = None
    mode: RightsMode | None = None
    try:
        converted = tuple(ProviderCapability(value) for value in capabilities)
        if len(converted) != len(set(converted)):
            raise ValueError
        converted_capabilities = frozenset(converted)
        mode = RightsMode(rights["mode"])
    except (TypeError, ValueError):
        pass
    if converted_capabilities is None or mode is None:
        _reject(
            code="invalid_entitlements",
            path="$entitlements",
            message="entitlement enums are invalid",
        )
    try:
        return ProviderEntitlements(
            provider_id=document["provider_id"],  # type: ignore[arg-type]
            evaluated_at=_timestamp(document["evaluated_at"], "$.evaluated_at"),
            valid_until=_timestamp(document["valid_until"], "$.valid_until"),
            source_type=_SOURCE_TYPES[source_type],
            jurisdictions=frozenset({"CN"}),
            authentication_mode=AuthenticationMode.LOCAL_ENTITLEMENT,
            capabilities=converted_capabilities,
            rights_mode=mode,
            cache_allowed=rights["cache_allowed"],  # type: ignore[arg-type]
            cache_ttl_seconds=rights["cache_ttl_seconds"],  # type: ignore[arg-type]
            derived_works_allowed=rights["derived_works_allowed"],  # type: ignore[arg-type]
            public_display_allowed=rights["public_display_allowed"],  # type: ignore[arg-type]
            redistribution_allowed=rights["redistribution_allowed"],  # type: ignore[arg-type]
            retention_days=rights["retention_days"],  # type: ignore[arg-type]
            attribution_required=rights["attribution_required"],  # type: ignore[arg-type]
            terms_url=rights["terms_url"],  # type: ignore[arg-type]
            rights_reviewed_at=_timestamp(
                rights["reviewed_at"], "$.rights.reviewed_at"
            ),
            rate_limit=RateLimit(
                requests_per_period=rate_limit["requests_per_period"],  # type: ignore[arg-type]
                period_seconds=rate_limit["period_seconds"],  # type: ignore[arg-type]
                burst=rate_limit["burst"],  # type: ignore[arg-type]
            ),
        )
    except ProviderContractError:
        _reject(
            code="invalid_entitlements",
            path="$entitlements",
            message="typed entitlement contract is invalid",
        )


def _freeze_entitlement_timestamp(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("entitlement timestamp must be a datetime")
    if datetime.tzinfo.__get__(value) is None or datetime.utcoffset(value) is None:
        raise ValueError("entitlement timestamp must be timezone-aware")
    normalized = datetime.astimezone(value, UTC)
    frozen = datetime(
        datetime.year.__get__(normalized),
        datetime.month.__get__(normalized),
        datetime.day.__get__(normalized),
        datetime.hour.__get__(normalized),
        datetime.minute.__get__(normalized),
        datetime.second.__get__(normalized),
        datetime.microsecond.__get__(normalized),
        tzinfo=UTC,
        fold=datetime.fold.__get__(normalized),
    )
    if type(frozen) is not datetime or frozen.tzinfo is not UTC:
        raise ValueError("entitlement timestamp could not be frozen")
    return frozen


def _trusted_entitlements(value: ProviderEntitlements) -> ProviderEntitlements:
    """Rebuild a typed contract so mutated caller state is never retained."""
    trusted: ProviderEntitlements | None = None
    try:
        rate_limit = value.rate_limit
        trusted_rate_limit = RateLimit(
            requests_per_period=rate_limit.requests_per_period,
            period_seconds=rate_limit.period_seconds,
            burst=rate_limit.burst,
        )
        trusted = ProviderEntitlements(
            provider_id=value.provider_id,
            evaluated_at=_freeze_entitlement_timestamp(value.evaluated_at),
            valid_until=(
                None
                if value.valid_until is None
                else _freeze_entitlement_timestamp(value.valid_until)
            ),
            source_type=value.source_type,
            jurisdictions=value.jurisdictions,
            authentication_mode=value.authentication_mode,
            capabilities=value.capabilities,
            rights_mode=value.rights_mode,
            cache_allowed=value.cache_allowed,
            cache_ttl_seconds=value.cache_ttl_seconds,
            derived_works_allowed=value.derived_works_allowed,
            public_display_allowed=value.public_display_allowed,
            redistribution_allowed=value.redistribution_allowed,
            retention_days=value.retention_days,
            attribution_required=value.attribution_required,
            terms_url=value.terms_url,
            rights_reviewed_at=(
                None
                if value.rights_reviewed_at is None
                else _freeze_entitlement_timestamp(value.rights_reviewed_at)
            ),
            rate_limit=trusted_rate_limit,
        )
    except Exception:  # noqa: BLE001, S110 - supplied typed object is untrusted
        pass
    if trusted is None:
        _reject(
            code="invalid_entitlements",
            path="$entitlements",
            message="typed entitlement contract is invalid",
        )
    return trusted


class MainlandOfficialSnapshotAdapter:
    """Validate, map, and authorize an offline official snapshot bundle."""

    def __init__(
        self,
        *,
        entitlements: ProviderEntitlements,
        fund_company_hosts: Mapping[str, str] | None = None,
    ) -> None:
        if not isinstance(entitlements, ProviderEntitlements):
            _reject(
                code="missing_entitlements",
                path="$entitlements",
                message="explicit typed entitlements are required",
            )
        trusted_entitlements = _trusted_entitlements(entitlements)
        if trusted_entitlements.valid_until is None:
            _reject(
                code="invalid_entitlements",
                path="$entitlements",
                message="Mainland snapshots require an explicit entitlement expiry",
            )
        if trusted_entitlements.rights_reviewed_at is None:
            _reject(
                code="invalid_entitlements",
                path="$entitlements",
                message="Mainland snapshots require an explicit rights review",
            )
        self._entitlements = trusted_entitlements
        self.provider_id = self._entitlements.provider_id
        self.capabilities = self._entitlements.capabilities
        approvals = {} if fund_company_hosts is None else _safe_copy(fund_company_hosts)
        if not isinstance(approvals, dict):
            _reject(
                code="invalid_host_approval",
                path="$fund_company_hosts",
                message="fund-company approvals must be exact-host evidence mappings",
            )
        checked: dict[str, str] = {}
        for raw_host, evidence_url in approvals.items():
            if type(raw_host) is not str:
                _reject(
                    code="invalid_host_approval",
                    path="$fund_company_hosts",
                    message="fund-company approvals must use exact public hostnames",
                )
            host = raw_host.lower()
            if _DNS.fullmatch(host) is None or host.startswith("."):
                _reject(
                    code="invalid_host_approval",
                    path="$fund_company_hosts",
                    message="fund-company approvals must use exact public hostnames",
                )
            evidence_host = _public_https_host(evidence_url, "$fund_company_hosts")
            if host in checked or evidence_host != host:
                _reject(
                    code="invalid_host_approval",
                    path="$fund_company_hosts",
                    message="fund-company approvals must be unique exact-host evidence mappings",
                )
            checked[host] = evidence_url
        self._fund_company_hosts = checked

    def get_entitlements(
        self, *, evaluation_timestamp: datetime
    ) -> ProviderEntitlements:
        del evaluation_timestamp
        return _trusted_entitlements(self._entitlements)

    def _approve_url(
        self,
        value: object,
        source_type: str,
        path: str,
        *,
        required_host: str | None = None,
    ) -> str:
        host = _public_https_host(value, path)
        if source_type == "fund_company":
            approved = host in self._fund_company_hosts and (
                required_host is None or host == required_host
            )
        else:
            approved = any(
                _host_matches(host, candidate, exact=False)
                for candidate in _DEFAULT_HOSTS[source_type]
            )
        if not approved:
            _reject(
                code="unapproved_source",
                path=path,
                message="source hostname is outside the reviewed official allowlist",
            )
        return host

    def _validate_schema(self, document: dict[str, object]) -> None:
        schema = resolve_resource(
            resource_type="schema",
            name="mainland_official_snapshot",
            version="0.1.0",
        ).load_json()
        error = next(Draft202012Validator(schema).iter_errors(document), None)
        if error is not None:
            absolute_path = list(error.absolute_path)
            code = "snapshot_schema"
            if (
                len(absolute_path) >= 5
                and absolute_path[0] == "items"
                and isinstance(absolute_path[1], int)
            ):
                items = document.get("items")
                item_index = absolute_path[1]
                item = (
                    items[item_index]
                    if isinstance(items, list) and 0 <= item_index < len(items)
                    else None
                )
                item_type = item.get("item_type") if isinstance(item, dict) else None
                if absolute_path[-1] == "raw_value" and item_type in {
                    "nav",
                    "report",
                    "holding",
                }:
                    code = {
                        "nav": "invalid_nav",
                        "report": "invalid_report",
                        "holding": "invalid_holding",
                    }[item_type]
                elif absolute_path[-1] == "field" and item_type == "holding":
                    code = "missing_item_field"
            path = "$"
            for part in absolute_path:
                path += f"[{part}]" if isinstance(part, int) else f".{part}"
            _reject(
                code=code,
                path=path,
                message="snapshot violates the closed versioned bundle schema",
            )

    def _validate_contract(
        self, document: dict[str, object], *, evaluation_timestamp: datetime
    ) -> tuple[datetime, str, datetime]:
        evaluation: datetime | None = None
        if (
            isinstance(evaluation_timestamp, datetime)
            and evaluation_timestamp.tzinfo is not None
        ):
            try:
                if evaluation_timestamp.utcoffset() is not None:
                    evaluation = evaluation_timestamp.astimezone(UTC)
            except Exception:  # noqa: BLE001 - hostile tzinfo must fail closed
                evaluation = None
        if evaluation is None:
            _reject(
                code="invalid_evaluation_timestamp",
                path="$evaluation_timestamp",
                message="evaluation timestamp must be timezone-aware",
            )
        source_type = document["source_type"]
        _require_schema(isinstance(source_type, str), "$.source_type")
        official_host = self._approve_url(
            document["official_source_url"], source_type, "$.official_source_url"
        )
        expected_source = _SOURCE_TYPES[source_type]
        if (
            document["provider_id"] != self.provider_id
            or self._entitlements.evaluated_at.astimezone(UTC) != evaluation
            or self._entitlements.source_type is not expected_source
            or "CN" not in self._entitlements.jurisdictions
        ):
            _reject(
                code="entitlement_mismatch",
                path="$entitlements",
                message="entitlements do not match the snapshot identity and source",
            )
        rights = document["rights"]
        _require_schema(isinstance(rights, dict), "$.rights")
        expected_rights = {
            "mode": self._entitlements.rights_mode.value,
            "terms_url": self._entitlements.terms_url,
            "cache_allowed": self._entitlements.cache_allowed,
            "derived_works_allowed": self._entitlements.derived_works_allowed,
            "redistribution_allowed": self._entitlements.redistribution_allowed,
            "attribution_required": self._entitlements.attribution_required,
            "public_display_allowed": self._entitlements.public_display_allowed,
            "retention_days": self._entitlements.retention_days,
        }
        reviewed = _timestamp(rights["reviewed_at"], "$.rights.reviewed_at")
        valid_until = _timestamp(rights["valid_until"], "$.rights.valid_until")
        entitlement_reviewed = self._entitlements.rights_reviewed_at
        entitlement_valid_until = self._entitlements.valid_until
        if not isinstance(entitlement_reviewed, datetime) or not isinstance(
            entitlement_valid_until, datetime
        ):
            _reject(
                code="invalid_entitlements",
                path="$entitlements",
                message="Mainland snapshots require reviewed, expiring entitlements",
            )
        if (
            any(rights.get(key) != value for key, value in expected_rights.items())
            or reviewed != entitlement_reviewed.astimezone(UTC)
            or valid_until != entitlement_valid_until.astimezone(UTC)
        ):
            _reject(
                code="rights_mismatch",
                path="$.rights",
                message="snapshot rights do not match explicit entitlements",
            )
        if rights["mode"] == "unknown_blocked":
            _reject(
                code="rights_blocked",
                path="$.rights.mode",
                message="unknown rights fail closed",
            )
        if reviewed > evaluation:
            _reject(
                code="future_rights_review",
                path="$.rights.reviewed_at",
                message="rights review cannot occur after evaluation",
            )
        if valid_until <= evaluation:
            _reject(
                code="expired_entitlements",
                path="$.rights.valid_until",
                message="snapshot rights are expired",
            )
        self._approve_url(
            rights["terms_url"],
            source_type,
            "$.rights.terms_url",
            required_host=official_host if source_type == "fund_company" else None,
        )
        evidence_host = self._approve_url(
            rights["source_evidence_url"],
            source_type,
            "$.rights.source_evidence_url",
            required_host=official_host if source_type == "fund_company" else None,
        )
        if source_type == "fund_company" and (
            evidence_host not in self._fund_company_hosts
            or self._fund_company_hosts[evidence_host] != rights["source_evidence_url"]
        ):
            _reject(
                code="unapproved_source",
                path="$.rights.source_evidence_url",
                message="fund-company host requires matching exact-host source evidence",
            )
        published = _timestamp(document["published_at"], "$.published_at")
        retrieved = _timestamp(document["retrieved_at"], "$.retrieved_at")
        as_of = _timestamp(document["as_of"], "$.as_of")
        _timestamp(document["effective_at"], "$.effective_at")
        if published > retrieved or retrieved > evaluation or as_of > retrieved:
            _reject(
                code="chronology_violation",
                path="$",
                message="snapshot chronology violates point-in-time evaluation",
            )
        return evaluation, official_host, retrieved

    @staticmethod
    def _rfc3339(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _effective_status(
        valid_from: object,
        valid_to: object,
        evaluation: datetime,
    ) -> str:
        starts = _timestamp(valid_from, "$.items.observations.valid_from")
        ends = (
            None
            if valid_to is None
            else _timestamp(valid_to, "$.items.observations.valid_to")
        )
        if starts > evaluation:
            return "future"
        if ends is not None and ends < evaluation:
            return "expired"
        return "current"

    def _validate_item(
        self,
        item: dict[str, object],
        source_type: str,
        document_sha256: object,
        official_host: str,
        retrieved: datetime,
    ) -> None:
        item_type = item["item_type"]
        entity_type = item["entity_type"]
        _require_schema(
            isinstance(item_type, str) and isinstance(entity_type, str),
            "$.items",
        )
        if entity_type not in _ENTITY_TYPES[item_type]:
            _reject(
                code="invalid_item",
                path="$.items.entity_type",
                message="entity type does not match disclosure item type",
            )
        allowed_fields = _PROFILE_FIELDS[(item_type, entity_type)]
        identifiers = item["exact_identifiers"]
        _require_schema(isinstance(identifiers, list), "$.items.exact_identifiers")
        exact_keys: list[tuple[object, object, object]] = []
        for entry in identifiers:
            _require_schema(isinstance(entry, dict), "$.items.exact_identifiers")
            exact_keys.append(
                (entry["scheme"], entry["value"], entry["jurisdiction"])
            )
        if len(exact_keys) != len(set(exact_keys)):
            _reject(
                code="duplicate_identifier",
                path="$.items.exact_identifiers",
                message="exact identifiers must be unique",
            )

        observations = item["observations"]
        _require_schema(isinstance(observations, list), "$.items.observations")
        ids: set[str] = set()
        observation_signatures: set[tuple[object, ...]] = set()
        field_values: dict[str, object] = {}
        field_counts: dict[str, int] = {}
        nav_revisions: list[tuple[datetime, str]] = []
        conflict_keys: dict[tuple[str, datetime], list[dict[str, object]]] = {}
        snapshot_fields: dict[datetime, dict[str, list[dict[str, object]]]] = {}
        for observation in observations:
            _require_schema(isinstance(observation, dict), "$.items.observations")
            observation_id = observation["observation_id"]
            _require_schema(
                isinstance(observation_id, str),
                "$.items.observations.observation_id",
            )
            if observation_id in ids:
                _reject(
                    code="duplicate_observation",
                    path="$.items.observations.observation_id",
                    message="observation identifiers must be unique",
                )
            ids.add(observation_id)
            field = observation["field"]
            _require_schema(isinstance(field, str), "$.items.observations.field")
            if field not in allowed_fields:
                _reject(
                    code="invalid_item_field",
                    path="$.items.observations.field",
                    message="field is outside the closed item profile",
                )
            raw_value = observation["raw_value"]
            if field in _TEXT_FIELDS and not _has_visible_text(raw_value):
                _reject(
                    code="invalid_item_value",
                    path="$.items.observations.raw_value",
                    message="text fields require substantive visible text",
                )
            if (
                field in _RELATION_FIELDS
                and not (field == "after_id" and raw_value is None)
                and not _has_visible_text(raw_value)
            ):
                _reject(
                    code="invalid_item_value",
                    path="$.items.observations.raw_value",
                    message="relationship identifiers require substantive text",
                )
            if field in _NULL_QUALIFIER_FIELDS and (
                observation["unit"] is not None or observation["currency"] is not None
            ):
                _reject(
                    code="invalid_item_value",
                    path="$.items.observations.unit",
                    message="non-numeric fields cannot carry numeric qualifiers",
                )
            if observation["point_in_time_status"] in {
                "reconstructed",
                "not_point_in_time",
            } and not _has_visible_text(observation["methodology"]):
                _reject(
                    code="invalid_item_value",
                    path="$.items.observations.methodology",
                    message="non-PIT observations require substantive methodology",
                )
            field_counts[field] = field_counts.get(field, 0) + 1
            field_values[field] = raw_value
            as_of = _timestamp(observation["as_of"], "$.items.observations.as_of")
            snapshot_fields.setdefault(as_of, {}).setdefault(field, []).append(
                observation
            )
            published = _timestamp(
                observation["published_at"], "$.items.observations.published_at"
            )
            fetched = _timestamp(
                observation["fetched_at"], "$.items.observations.fetched_at"
            )
            valid_from = _timestamp(
                observation["valid_from"], "$.items.observations.valid_from"
            )
            valid_to = (
                None
                if observation["valid_to"] is None
                else _timestamp(
                    observation["valid_to"], "$.items.observations.valid_to"
                )
            )
            signature = (
                field,
                json.dumps(
                    raw_value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
                as_of,
                published,
                fetched,
                valid_from,
                valid_to,
                observation["source_url"],
                observation["source_document_hash"],
            )
            if signature in observation_signatures:
                _reject(
                    code="duplicate_observation_snapshot",
                    path="$.items.observations",
                    message="duplicate observation snapshots fail closed",
                )
            observation_signatures.add(signature)
            if (
                as_of > published
                or published > fetched
                or fetched > retrieved
                or (valid_to is not None and valid_from > valid_to)
            ):
                _reject(
                    code="chronology_violation",
                    path="$.items.observations",
                    message="observation chronology is invalid",
                )
            self._approve_url(
                observation["source_url"],
                source_type,
                "$.items.observations.source_url",
                required_host=official_host if source_type == "fund_company" else None,
            )
            if _SHA256.fullmatch(str(observation["source_document_hash"])) is None:
                _reject(
                    code="invalid_hash",
                    path="$.items.observations.source_document_hash",
                    message="document hash must be lowercase SHA-256",
                )
            if observation["source_document_hash"] != document_sha256:
                _reject(
                    code="document_hash_mismatch",
                    path="$.items.observations.source_document_hash",
                    message="observation provenance must bind to the bundle document",
                )
            quality = observation["quality_state"]
            conflict_group = observation["conflict_group"]
            if (quality == "conflict") != (
                isinstance(conflict_group, str) and bool(conflict_group)
            ):
                _reject(
                    code="invalid_conflict",
                    path="$.items.observations.conflict_group",
                    message="conflicts require an explicit conflict group",
                )
            key = (field, as_of)
            conflict_keys.setdefault(key, []).append(observation)
            if item_type == "nav" and field == "nav":
                value = observation["raw_value"]
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(float(value))
                    or value < 0
                    or observation["currency"] != "CNY"
                    or observation["unit"] != "CNY_per_share"
                ):
                    _reject(
                        code="invalid_nav",
                        path="$.items.observations.raw_value",
                        message="NAV must be finite, non-negative, and unit-qualified",
                    )
                nav_revisions.append((as_of, observation_id))
            elif item_type == "report" and field == "report_url":
                self._approve_url(
                    raw_value,
                    source_type,
                    "$.items.observations.raw_value",
                    required_host=(
                        official_host if source_type == "fund_company" else None
                    ),
                )
            elif item_type == "report" and field == "report_document_hash":
                if (
                    not isinstance(raw_value, str)
                    or _SHA256.fullmatch(raw_value) is None
                ):
                    _reject(
                        code="invalid_report",
                        path="$.items.observations.raw_value",
                        message="report hash is invalid",
                    )
        for values in conflict_keys.values():
            if len(values) > 1 and not all(
                value["quality_state"] == "conflict"
                and value["conflict_group"] == values[0]["conflict_group"]
                for value in values
            ):
                _reject(
                    code="silent_conflict",
                    path="$.items.observations",
                    message="duplicate field knowledge must be preserved as a conflict",
                )
        if any(
            set(fields) != set(allowed_fields) for fields in snapshot_fields.values()
        ):
            _reject(
                code=(
                    "invalid_holding"
                    if item_type == "holding"
                    else "missing_item_field"
                ),
                path="$.items.observations",
                message="each observation snapshot must contain its closed profile fields",
            )
        if set(field_values) != set(allowed_fields):
            _reject(
                code="missing_item_field",
                path="$.items.observations",
                message="item must contain exactly its closed profile fields",
            )
        if item_type == "nav":
            if not nav_revisions or nav_revisions != sorted(nav_revisions):
                _reject(
                    code="invalid_nav_order",
                    path="$.items.observations",
                    message=(
                        "NAV observations must have non-decreasing revision instants "
                        "and deterministic observation-id order within a conflict group"
                    ),
                )
        elif item_type == "report":
            self._approve_url(
                field_values["report_url"],
                source_type,
                "$.items.report_url",
                required_host=official_host if source_type == "fund_company" else None,
            )
            if _SHA256.fullmatch(str(field_values["report_document_hash"])) is None:
                _reject(
                    code="invalid_report",
                    path="$.items",
                    message="report hash is invalid",
                )
        elif item_type == "manager_tenure":
            for fields in snapshot_fields.values():
                starts = [
                    _date_value(
                        observation["raw_value"],
                        "$.items.observations.raw_value",
                    )
                    for observation in fields["tenure_start"]
                ]
                ends = [
                    _date_value(
                        observation["raw_value"],
                        "$.items.observations.raw_value",
                    )
                    for observation in fields["tenure_end"]
                ]
                finite_ends = [end for end in ends if end is not None]
                if finite_ends and max(starts) > min(finite_ends):
                    _reject(
                        code="invalid_tenure",
                        path="$.items",
                        message="tenure interval is reversed",
                    )
        elif item_type == "holding":
            maximums = {
                "bps": Decimal(10000),
                "percent": Decimal(100),
                "fraction": Decimal(1),
            }
            snapshots: dict[datetime, dict[str, list[dict[str, object]]]] = {}
            for observation in observations:
                field = observation["field"]
                _require_schema(
                    isinstance(field, str), "$.items.observations.field"
                )
                as_of = _timestamp(observation["as_of"], "$.items.observations.as_of")
                snapshot = snapshots.setdefault(as_of, {})
                snapshot.setdefault(field, []).append(observation)
                if field not in {"weight", "coverage"}:
                    continue
                unit = observation["unit"]
                value = observation["raw_value"]
                if unit not in maximums or (unit == "bps" and type(value) is not int):
                    _reject(
                        code="invalid_holding",
                        path="$.items.observations",
                        message="holding weights or coverage are invalid",
                    )
                decimal_value = _decimal_value(value, "$.items.observations.raw_value")
                if not Decimal(0) <= decimal_value <= maximums[unit]:
                    _reject(
                        code="invalid_holding",
                        path="$.items.observations.raw_value",
                        message="holding weights or coverage are invalid",
                    )
            for snapshot in snapshots.values():
                if set(snapshot) != set(allowed_fields):
                    _reject(
                        code="invalid_holding",
                        path="$.items.observations",
                        message="holding snapshot fields are incomplete",
                    )
                numeric = snapshot["weight"] + snapshot["coverage"]
                numeric_units = {observation["unit"] for observation in numeric}
                strategy_ids = {
                    observation["raw_value"]
                    for observation in snapshot["fund_strategy_id"]
                }
                instruments = {
                    observation["raw_value"]
                    for observation in snapshot["instrument_id"]
                }
                weights = [
                    _decimal_value(
                        observation["raw_value"],
                        "$.items.observations.raw_value",
                    )
                    for observation in snapshot["weight"]
                ]
                coverages = [
                    _decimal_value(
                        observation["raw_value"],
                        "$.items.observations.raw_value",
                    )
                    for observation in snapshot["coverage"]
                ]
                if (
                    len(numeric_units) != 1
                    or len(strategy_ids) != 1
                    or len(instruments) != 1
                    or max(weights) > min(coverages)
                ):
                    _reject(
                        code="invalid_holding",
                        path="$.items",
                        message="holding weights or coverage are invalid",
                    )
        elif item_type == "corporate_action":
            for fields in snapshot_fields.values():
                effective_times = {
                    _timestamp(
                        observation["raw_value"],
                        "$.items.observations.raw_value",
                    )
                    for observation in fields["effective_at"]
                }
                valid_from_times = {
                    _timestamp(
                        observation["valid_from"],
                        "$.items.observations.valid_from",
                    )
                    for observations_for_field in fields.values()
                    for observation in observations_for_field
                }
                if len(effective_times) != 1 or valid_from_times != effective_times:
                    _reject(
                        code="invalid_corporate_action",
                        path="$.items.observations.valid_from",
                        message="corporate action validity must bind to its effective time",
                    )
            for fields in snapshot_fields.values():
                actions = {
                    observation["raw_value"] for observation in fields["action_type"]
                }
                before_ids = {
                    observation["raw_value"] for observation in fields["before_id"]
                }
                after_ids = {
                    observation["raw_value"] for observation in fields["after_id"]
                }
                for action in actions:
                    if action == "closed":
                        valid_ids = after_ids == {None}
                    else:
                        valid_ids = (
                            action in {"merged", "transformed"}
                            and all(
                                _has_substantive_identifier(after)
                                for after in after_ids
                            )
                            and before_ids.isdisjoint(after_ids)
                        )
                    if not valid_ids:
                        _reject(
                            code="invalid_corporate_action",
                            path="$.items",
                            message="corporate action identifiers are invalid",
                        )

    def _validate_holding_totals(
        self,
        items: list[object],
        units: object,
    ) -> None:
        _require_schema(isinstance(units, dict), "$.units")
        expected_weight_unit = units["weight"]
        expected_coverage_unit = units["coverage"]
        groups: dict[tuple[str, object], dict[str, object]] = {}
        for item in items:
            _require_schema(isinstance(item, dict), "$.items")
            if item["item_type"] != "holding":
                continue
            observations = item["observations"]
            _require_schema(isinstance(observations, list), "$.items.observations")
            snapshots: dict[object, dict[str, list[dict[str, object]]]] = {}
            for observation in observations:
                _require_schema(
                    isinstance(observation, dict), "$.items.observations"
                )
                field = observation["field"]
                _require_schema(
                    isinstance(field, str), "$.items.observations.field"
                )
                as_of = _timestamp(observation["as_of"], "$.items.observations.as_of")
                snapshots.setdefault(as_of, {}).setdefault(field, []).append(
                    observation
                )
            for as_of, fields in snapshots.items():
                fund_values = {
                    observation["raw_value"]
                    for observation in fields["fund_strategy_id"]
                }
                instrument_values = {
                    observation["raw_value"] for observation in fields["instrument_id"]
                }
                weight_observations = fields["weight"]
                coverage_observations = fields["coverage"]
                if (
                    len(fund_values) != 1
                    or len(instrument_values) != 1
                    or any(
                        observation["unit"] != expected_weight_unit
                        for observation in weight_observations
                    )
                    or any(
                        observation["unit"] != expected_coverage_unit
                        for observation in coverage_observations
                    )
                    or expected_weight_unit != expected_coverage_unit
                ):
                    _reject(
                        code="invalid_holding",
                        path="$.items.observations.unit",
                        message="holding units must match the bundle declaration",
                    )
                fund_strategy_id = next(iter(fund_values))
                instrument = next(iter(instrument_values))
                _require_schema(
                    isinstance(fund_strategy_id, str) and isinstance(instrument, str),
                    "$.items.observations.raw_value",
                )
                weights = [
                    _decimal_value(
                        observation["raw_value"],
                        "$.items.observations.raw_value",
                    )
                    for observation in weight_observations
                ]
                coverages = {
                    _decimal_value(
                        observation["raw_value"],
                        "$.items.observations.raw_value",
                    )
                    for observation in coverage_observations
                }
                if len(coverages) != 1:
                    _reject(
                        code="invalid_holding",
                        path="$.items",
                        message="holding coverage and exact instruments must reconcile",
                    )
                coverage = next(iter(coverages))
                key = (fund_strategy_id, as_of)
                group = groups.setdefault(
                    key,
                    {
                        "coverage": coverage,
                        "weight": Decimal(0),
                        "instruments": set(),
                    },
                )
                instruments = group["instruments"]
                if not isinstance(instruments, set):
                    _reject(
                        code="invalid_holding",
                        path="$.items",
                        message="holding reconciliation state is invalid",
                    )
                if group["coverage"] != coverage or instrument in instruments:
                    _reject(
                        code="invalid_holding",
                        path="$.items",
                        message="holding coverage and exact instruments must reconcile",
                    )
                instruments.add(instrument)
                group["weight"] = group["weight"] + max(weights)  # type: ignore[operator]
        for group in groups.values():
            if group["weight"] > group["coverage"]:  # type: ignore[operator]
                _reject(
                    code="invalid_holding",
                    path="$.items",
                    message="holding weights exceed disclosed snapshot coverage",
                )

    def parse(
        self,
        source: bytes | Path | Mapping[str, object],
        *,
        evaluation_timestamp: datetime,
    ) -> tuple[dict[str, object], ...]:
        """Parse one frozen snapshot without network I/O and authorize every record."""
        document = _load_source(source)
        self._validate_schema(document)
        evaluation, official_host, retrieved = self._validate_contract(
            document, evaluation_timestamp=evaluation_timestamp
        )
        source_type = document["source_type"]
        _require_schema(isinstance(source_type, str), "$.source_type")
        items = document["items"]
        _require_schema(isinstance(items, list), "$.items")
        item_ids: set[str] = set()
        resolved_identifiers: dict[
            tuple[object, object, object], tuple[object, object]
        ] = {}
        for item_value in items:
            _require_schema(isinstance(item_value, dict), "$.items")
            item_id = item_value["item_id"]
            _require_schema(isinstance(item_id, str), "$.items.item_id")
            if item_id in item_ids:
                _reject(
                    code="duplicate_item",
                    path="$.items.item_id",
                    message="item identifiers must be unique",
                )
            item_ids.add(item_id)
            if not _has_substantive_identifier(item_value["entity_id"]):
                _reject(
                    code="invalid_identifier",
                    path="$.items.entity_id",
                    message="entity identifiers require substantive codepoints",
                )
            exact_identifiers = item_value["exact_identifiers"]
            _require_schema(
                isinstance(exact_identifiers, list), "$.items.exact_identifiers"
            )
            for identifier in exact_identifiers:
                _require_schema(
                    isinstance(identifier, dict), "$.items.exact_identifiers"
                )
                if not _has_substantive_identifier(identifier["value"]):
                    _reject(
                        code="invalid_identifier",
                        path="$.items.exact_identifiers.value",
                        message="exact identifiers require substantive codepoints",
                    )
                key = (
                    identifier["scheme"],
                    identifier["value"],
                    identifier["jurisdiction"],
                )
                identity = (item_value["entity_type"], item_value["entity_id"])
                resolved = resolved_identifiers.setdefault(key, identity)
                if resolved != identity:
                    _reject(
                        code="identifier_resolution_conflict",
                        path="$.items.exact_identifiers",
                        message=(
                            "one exact identifier cannot resolve to multiple "
                            "canonical entities"
                        ),
                    )
            self._validate_item(
                item_value,
                source_type,
                document["document_sha256"],
                official_host,
                retrieved,
            )
        self._validate_holding_totals(items, document["units"])

        record_ids: set[str] = set()
        records: list[dict[str, object]] = []
        for item_value in items:
            _require_schema(isinstance(item_value, dict), "$.items")
            item_id = item_value["item_id"]
            _require_schema(isinstance(item_id, str), "$.items.item_id")
            item_type = item_value["item_type"]
            entity_type = item_value["entity_type"]
            entity_id = item_value["entity_id"]
            observations = item_value["observations"]
            _require_schema(
                isinstance(item_type, str) and isinstance(entity_type, str),
                "$.items",
            )
            _require_schema(
                isinstance(entity_id, str) and isinstance(observations, list),
                "$.items",
            )
            for observation_value in observations:
                _require_schema(
                    isinstance(observation_value, dict), "$.items.observations"
                )
                record_id = f"{document['snapshot_id']}:{item_id}:{observation_value['observation_id']}"
                if record_id in record_ids or len(record_id) > 256:
                    _reject(
                        code="duplicate_record",
                        path="$.items",
                        message="mapped provider-record identifiers must be unique and bounded",
                    )
                record_ids.add(record_id)
                rights = document["rights"]
                _require_schema(isinstance(rights, dict), "$.rights")
                record: dict[str, object] = {
                    "provider_id": document["provider_id"],
                    "provider_record_id": record_id,
                    "namespace": "canonical_observation",
                    "source_type": _SOURCE_TYPES[source_type].value,
                    "jurisdiction": "CN",
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "exact_identifiers": [
                        dict(identifier)
                        for identifier in item_value["exact_identifiers"]
                    ],
                    "field": observation_value["field"],
                    "value": observation_value["raw_value"],
                    "unit": observation_value["unit"],
                    "currency": observation_value["currency"],
                    "as_of": observation_value["as_of"],
                    "published_at": observation_value["published_at"],
                    "fetched_at": observation_value["fetched_at"],
                    "valid_from": observation_value["valid_from"],
                    "valid_to": observation_value["valid_to"],
                    "effective_status": self._effective_status(
                        observation_value["valid_from"],
                        observation_value["valid_to"],
                        evaluation,
                    ),
                    "source_url": observation_value["source_url"],
                    "source_document_hash": observation_value["source_document_hash"],
                    "point_in_time_status": observation_value["point_in_time_status"],
                    "methodology": observation_value["methodology"],
                    "quality_state": observation_value["quality_state"],
                    "conflict_group": observation_value["conflict_group"],
                    "rights": {
                        key: rights[key]
                        for key in (
                            "mode",
                            "terms_url",
                            "cache_allowed",
                            "derived_works_allowed",
                            "redistribution_allowed",
                            "attribution_required",
                            "public_display_allowed",
                            "retention_days",
                            "reviewed_at",
                            "valid_until",
                        )
                    },
                }
                try:
                    validate_record(
                        "provider_record",
                        record,
                        schema_version="0.2.0",
                        evaluation_timestamp=self._rfc3339(evaluation),
                    )
                except RecordValidationError as exc:
                    _reject(
                        code="invalid_mapped_record",
                        path=exc.path,
                        message="mapped provider record failed validation",
                    )
                period = self._entitlements.rate_limit.period_seconds
                epoch_seconds = int(evaluation.timestamp())
                period_start = datetime.fromtimestamp(
                    epoch_seconds - epoch_seconds % period, tz=UTC
                )
                authorize_ingestion(
                    self,
                    record,
                    schema_version="0.2.0",
                    evaluation_timestamp=evaluation,
                    request=IngestionRequest(capability=_CAPABILITIES[item_type]),
                    rate_limit_budget=RateLimitBudget(
                        provider_id=self.provider_id,
                        period_started_at=period_start,
                        requests_used=len(records),
                    ),
                )
                records.append(record)
        return tuple(records)
