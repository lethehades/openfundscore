"""Fixed-host HTTP primitives for official provider pilots."""

from __future__ import annotations

import hashlib
import http.client
import json
import math
import re
import ssl
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from types import MappingProxyType
from typing import Any, NoReturn, cast
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from .provider_sdk import (
    AuthenticationMode,
    DataUse,
    IngestionRequest,
    ProviderCapability,
    ProviderEntitlements,
    RateLimit,
    RateLimitBudget,
    RightsMode,
    SourceType,
    authorize_ingestion,
)
from .validation import validate_record

_OFFICIAL_HOSTS = frozenset({"api.worldbank.org", "data.sec.gov"})
_ALLOWED_REQUEST_HEADERS = MappingProxyType(
    {"accept": "Accept", "user-agent": "User-Agent"}
)
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$", re.ASCII)
_HTTP_TOKEN_CHARACTERS = frozenset(
    "!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
)
_SAFE_PATH = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*$", re.ASCII)
_MAX_QUERY_ITEMS = 64
_MAX_QUERY_COMPONENT_CHARACTERS = 1_024
_MAX_QUERY_COMPONENT_UTF8_BYTES = 4_096
_MAX_REQUEST_TARGET_BYTES = 8_192
_MAX_RAW_PATH_CHARACTERS = 8_192
_MAX_RAW_PATH_UTF8_BYTES = 8_192
_MAX_PATH_DECODE_ROUNDS = 8
_MAX_REQUEST_HEADER_VALUE_CHARACTERS = 1_024
_MAX_TIMEOUT_SECONDS = 60.0
_CIK = re.compile(r"^[0-9]{10}$", re.ASCII)
_ACCESSION = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$", re.ASCII)
_DOCUMENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$", re.ASCII)
_CONTACT_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+)"
    r"(?![A-Za-z0-9.-])",
    re.ASCII,
)
_DNS_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$", re.ASCII)
_DNS_TLD = re.compile(r"^[A-Za-z]{2,63}$", re.ASCII)
_EXAMPLE_EMAIL_DOMAINS = frozenset({"example.com", "example.org", "example.net"})
_SPECIAL_USE_EMAIL_TLDS = frozenset({"example", "invalid", "localhost", "test"})
_IGNORED_SEC_IDENTITIES = frozenset(
    {"app", "client", "default", "n a", "none", "test", "tool", "unknown"}
)
_DEFAULT_HTTP_USER_AGENT_PREFIXES = (
    "aiohttp/",
    "curl/",
    "go-http-client/",
    "httpx/",
    "java/",
    "libwww-perl/",
    "mozilla/",
    "okhttp/",
    "postmanruntime/",
    "python-requests/",
    "python-urllib/",
    "wget/",
)
_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", re.ASCII)
_SEC_ACCEPTANCE_DATETIME = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?Z$",
    re.ASCII,
)
_SEC_TERMS_URL = "https://www.sec.gov/os/accessing-edgar-data"
_SEC_REVIEWED_AT = datetime(2026, 8, 21, tzinfo=UTC)
_WB_COUNTRY = re.compile(r"^[A-Z]{2}$", re.ASCII)
# ISO 3166-1 alpha-2/alpha-3 pairs from Debian iso-codes. The tuple form and
# cardinality check prevent an incomplete duplicate-key last-write.
_ISO2_TO_ISO3_PAIRS = (
    ("AD", "AND"),
    ("AE", "ARE"),
    ("AF", "AFG"),
    ("AG", "ATG"),
    ("AI", "AIA"),
    ("AL", "ALB"),
    ("AM", "ARM"),
    ("AO", "AGO"),
    ("AQ", "ATA"),
    ("AR", "ARG"),
    ("AS", "ASM"),
    ("AT", "AUT"),
    ("AU", "AUS"),
    ("AW", "ABW"),
    ("AX", "ALA"),
    ("AZ", "AZE"),
    ("BA", "BIH"),
    ("BB", "BRB"),
    ("BD", "BGD"),
    ("BE", "BEL"),
    ("BF", "BFA"),
    ("BG", "BGR"),
    ("BH", "BHR"),
    ("BI", "BDI"),
    ("BJ", "BEN"),
    ("BL", "BLM"),
    ("BM", "BMU"),
    ("BN", "BRN"),
    ("BO", "BOL"),
    ("BQ", "BES"),
    ("BR", "BRA"),
    ("BS", "BHS"),
    ("BT", "BTN"),
    ("BV", "BVT"),
    ("BW", "BWA"),
    ("BY", "BLR"),
    ("BZ", "BLZ"),
    ("CA", "CAN"),
    ("CC", "CCK"),
    ("CD", "COD"),
    ("CF", "CAF"),
    ("CG", "COG"),
    ("CH", "CHE"),
    ("CI", "CIV"),
    ("CK", "COK"),
    ("CL", "CHL"),
    ("CM", "CMR"),
    ("CN", "CHN"),
    ("CO", "COL"),
    ("CR", "CRI"),
    ("CU", "CUB"),
    ("CV", "CPV"),
    ("CW", "CUW"),
    ("CX", "CXR"),
    ("CY", "CYP"),
    ("CZ", "CZE"),
    ("DE", "DEU"),
    ("DJ", "DJI"),
    ("DK", "DNK"),
    ("DM", "DMA"),
    ("DO", "DOM"),
    ("DZ", "DZA"),
    ("EC", "ECU"),
    ("EE", "EST"),
    ("EG", "EGY"),
    ("EH", "ESH"),
    ("ER", "ERI"),
    ("ES", "ESP"),
    ("ET", "ETH"),
    ("FI", "FIN"),
    ("FJ", "FJI"),
    ("FK", "FLK"),
    ("FM", "FSM"),
    ("FO", "FRO"),
    ("FR", "FRA"),
    ("GA", "GAB"),
    ("GB", "GBR"),
    ("GD", "GRD"),
    ("GE", "GEO"),
    ("GF", "GUF"),
    ("GG", "GGY"),
    ("GH", "GHA"),
    ("GI", "GIB"),
    ("GL", "GRL"),
    ("GM", "GMB"),
    ("GN", "GIN"),
    ("GP", "GLP"),
    ("GQ", "GNQ"),
    ("GR", "GRC"),
    ("GS", "SGS"),
    ("GT", "GTM"),
    ("GU", "GUM"),
    ("GW", "GNB"),
    ("GY", "GUY"),
    ("HK", "HKG"),
    ("HM", "HMD"),
    ("HN", "HND"),
    ("HR", "HRV"),
    ("HT", "HTI"),
    ("HU", "HUN"),
    ("ID", "IDN"),
    ("IE", "IRL"),
    ("IL", "ISR"),
    ("IM", "IMN"),
    ("IN", "IND"),
    ("IO", "IOT"),
    ("IQ", "IRQ"),
    ("IR", "IRN"),
    ("IS", "ISL"),
    ("IT", "ITA"),
    ("JE", "JEY"),
    ("JM", "JAM"),
    ("JO", "JOR"),
    ("JP", "JPN"),
    ("KE", "KEN"),
    ("KG", "KGZ"),
    ("KH", "KHM"),
    ("KI", "KIR"),
    ("KM", "COM"),
    ("KN", "KNA"),
    ("KP", "PRK"),
    ("KR", "KOR"),
    ("KW", "KWT"),
    ("KY", "CYM"),
    ("KZ", "KAZ"),
    ("LA", "LAO"),
    ("LB", "LBN"),
    ("LC", "LCA"),
    ("LI", "LIE"),
    ("LK", "LKA"),
    ("LR", "LBR"),
    ("LS", "LSO"),
    ("LT", "LTU"),
    ("LU", "LUX"),
    ("LV", "LVA"),
    ("LY", "LBY"),
    ("MA", "MAR"),
    ("MC", "MCO"),
    ("MD", "MDA"),
    ("ME", "MNE"),
    ("MF", "MAF"),
    ("MG", "MDG"),
    ("MH", "MHL"),
    ("MK", "MKD"),
    ("ML", "MLI"),
    ("MM", "MMR"),
    ("MN", "MNG"),
    ("MO", "MAC"),
    ("MP", "MNP"),
    ("MQ", "MTQ"),
    ("MR", "MRT"),
    ("MS", "MSR"),
    ("MT", "MLT"),
    ("MU", "MUS"),
    ("MV", "MDV"),
    ("MW", "MWI"),
    ("MX", "MEX"),
    ("MY", "MYS"),
    ("MZ", "MOZ"),
    ("NA", "NAM"),
    ("NC", "NCL"),
    ("NE", "NER"),
    ("NF", "NFK"),
    ("NG", "NGA"),
    ("NI", "NIC"),
    ("NL", "NLD"),
    ("NO", "NOR"),
    ("NP", "NPL"),
    ("NR", "NRU"),
    ("NU", "NIU"),
    ("NZ", "NZL"),
    ("OM", "OMN"),
    ("PA", "PAN"),
    ("PE", "PER"),
    ("PF", "PYF"),
    ("PG", "PNG"),
    ("PH", "PHL"),
    ("PK", "PAK"),
    ("PL", "POL"),
    ("PM", "SPM"),
    ("PN", "PCN"),
    ("PR", "PRI"),
    ("PS", "PSE"),
    ("PT", "PRT"),
    ("PW", "PLW"),
    ("PY", "PRY"),
    ("QA", "QAT"),
    ("RE", "REU"),
    ("RO", "ROU"),
    ("RS", "SRB"),
    ("RU", "RUS"),
    ("RW", "RWA"),
    ("SA", "SAU"),
    ("SB", "SLB"),
    ("SC", "SYC"),
    ("SD", "SDN"),
    ("SE", "SWE"),
    ("SG", "SGP"),
    ("SH", "SHN"),
    ("SI", "SVN"),
    ("SJ", "SJM"),
    ("SK", "SVK"),
    ("SL", "SLE"),
    ("SM", "SMR"),
    ("SN", "SEN"),
    ("SO", "SOM"),
    ("SR", "SUR"),
    ("SS", "SSD"),
    ("ST", "STP"),
    ("SV", "SLV"),
    ("SX", "SXM"),
    ("SY", "SYR"),
    ("SZ", "SWZ"),
    ("TC", "TCA"),
    ("TD", "TCD"),
    ("TF", "ATF"),
    ("TG", "TGO"),
    ("TH", "THA"),
    ("TJ", "TJK"),
    ("TK", "TKL"),
    ("TL", "TLS"),
    ("TM", "TKM"),
    ("TN", "TUN"),
    ("TO", "TON"),
    ("TR", "TUR"),
    ("TT", "TTO"),
    ("TV", "TUV"),
    ("TW", "TWN"),
    ("TZ", "TZA"),
    ("UA", "UKR"),
    ("UG", "UGA"),
    ("UM", "UMI"),
    ("US", "USA"),
    ("UY", "URY"),
    ("UZ", "UZB"),
    ("VA", "VAT"),
    ("VC", "VCT"),
    ("VE", "VEN"),
    ("VG", "VGB"),
    ("VI", "VIR"),
    ("VN", "VNM"),
    ("VU", "VUT"),
    ("WF", "WLF"),
    ("WS", "WSM"),
    ("YE", "YEM"),
    ("YT", "MYT"),
    ("ZA", "ZAF"),
    ("ZM", "ZMB"),
    ("ZW", "ZWE"),
)
if len(_ISO2_TO_ISO3_PAIRS) != 249 or len(dict(_ISO2_TO_ISO3_PAIRS)) != 249:
    raise RuntimeError("ISO 3166-1 country mapping is incomplete")
_ISO2_TO_ISO3 = MappingProxyType(dict(_ISO2_TO_ISO3_PAIRS))
_WB_INDICATOR = re.compile(r"^[A-Z0-9][A-Z0-9._]{0,63}$", re.ASCII)
_WB_YEAR = re.compile(r"^[0-9]{4}$", re.ASCII)
_MAX_WB_ABS_VALUE = 10**308


def _consume_http_token(value: str, start: int) -> int:
    end = start
    while end < len(value) and value[end] in _HTTP_TOKEN_CHARACTERS:
        end += 1
    return end


def _content_type_is_utf8_json(value: str | None) -> bool:
    if value is None or not value.isascii():
        return False

    length = len(value)
    index = 0

    while index < length and value[index] == " ":
        index += 1
    type_end = _consume_http_token(value, index)
    if type_end == index or type_end >= length or value[type_end] != "/":
        return False
    media_type = value[index:type_end].lower()
    index = type_end + 1

    subtype_end = _consume_http_token(value, index)
    if subtype_end == index:
        return False
    subtype = value[index:subtype_end].lower()
    index = subtype_end
    while index < length and value[index] == " ":
        index += 1

    parameters: dict[str, str] = {}
    while index < length:
        if value[index] != ";":
            return False
        index += 1
        while index < length and value[index] == " ":
            index += 1

        name_end = _consume_http_token(value, index)
        if name_end == index:
            return False
        name = value[index:name_end].lower()
        index = name_end
        while index < length and value[index] == " ":
            index += 1
        if index >= length or value[index] != "=":
            return False
        index += 1
        while index < length and value[index] == " ":
            index += 1

        if index < length and value[index] == '"':
            index += 1
            decoded: list[str] = []
            quoted_closed = False
            while index < length:
                character = value[index]
                if character == '"':
                    index += 1
                    quoted_closed = True
                    break
                if character == "\\":
                    index += 1
                    if index >= length or not " " <= value[index] <= "~":
                        return False
                    decoded.append(value[index])
                    index += 1
                    continue
                if not (
                    character in {" ", "!"}
                    or "#" <= character <= "["
                    or "]" <= character <= "~"
                ):
                    return False
                decoded.append(character)
                index += 1
            if not quoted_closed:
                return False
            parameter_value = "".join(decoded)
        else:
            value_end = _consume_http_token(value, index)
            if value_end == index:
                return False
            parameter_value = value[index:value_end]
            index = value_end

        while index < length and value[index] == " ":
            index += 1
        if name in parameters:
            return False
        parameters[name] = parameter_value

    is_json = (media_type == "application" and subtype == "json") or (
        len(subtype) > len("+json") and subtype.endswith("+json")
    )
    charset = parameters.get("charset")
    return (
        is_json
        and not set(parameters) - {"charset"}
        and (charset is None or charset.lower() == "utf-8")
    )


_WB_TERMS_URL = "https://www.worldbank.org/en/about/legal/terms-of-use-for-datasets"
_WB_REVIEWED_AT = datetime(2026, 8, 21, tzinfo=UTC)
_WB_REVIEWED_SOURCE = 2
_WB_REVIEWED_DATASET = "World Development Indicators"
OFFICIAL_PROVIDER_SCHEMA_VERSION = "0.2.0"

__all__ = (
    "OFFICIAL_PROVIDER_SCHEMA_VERSION",
    "FixedHostHttpClient",
    "HttpRequest",
    "HttpResponse",
    "JsonResponse",
    "LocalRateLimiter",
    "ProviderHttpError",
    "SecEdgarSubmissionsAdapter",
    "WorldBankIndicatorsAdapter",
)


class ProviderHttpError(ValueError):
    """Stable failure that never includes provider payloads or private headers."""

    def __init__(self, *, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        super().__init__(f"{path}: {code}: {message}")


@dataclass(frozen=True, slots=True)
class HttpRequest:
    scheme: str
    host: str
    target: str
    headers: Mapping[str, str]
    connect_timeout: float
    read_timeout: float
    max_response_bytes: int


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class JsonResponse:
    document: Any
    body: bytes
    sha256: str


Transport = Callable[[HttpRequest], HttpResponse]


def _stdlib_https_transport(request: HttpRequest) -> HttpResponse:
    connection = http.client.HTTPSConnection(
        request.host,
        timeout=request.connect_timeout,
        context=ssl.create_default_context(),
    )
    try:
        connection.request("GET", request.target, headers=dict(request.headers))
        if connection.sock is None:
            raise OSError("connection socket unavailable")
        connection.sock.settimeout(request.read_timeout)
        response = connection.getresponse()
        status = response.status
        if type(status) is not int:
            raise OSError("invalid response status")
        if not 200 <= status < 300:
            return HttpResponse(status=status, headers={}, body=b"")
        headers: dict[str, str] = {}
        for name, value in response.getheaders():
            lowered = name.lower()
            if lowered in {key.lower() for key in headers}:
                raise OSError("duplicate response header")
            headers[name] = value
        body = response.read(request.max_response_bytes + 1)
        return HttpResponse(status=status, headers=headers, body=body)
    finally:
        connection.close()


def _fail(*, code: str, path: str, message: str) -> NoReturn:
    raise ProviderHttpError(code=code, path=path, message=message)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(_: str) -> NoReturn:
    raise ValueError("non-finite JSON number")


def _valid_contact_email(match: re.Match[str] | None) -> bool:
    if match is None:
        return False
    local = match.group(1)
    domain = match.group(2).lower()
    labels = domain.split(".")
    return (
        1 <= len(local) <= 64
        and not local.startswith(".")
        and not local.endswith(".")
        and ".." not in local
        and len(domain) <= 253
        and len(labels) >= 2
        and all(_DNS_LABEL.fullmatch(label) is not None for label in labels)
        and _DNS_TLD.fullmatch(labels[-1]) is not None
        and labels[-1] not in _SPECIAL_USE_EMAIL_TLDS
        and domain not in _EXAMPLE_EMAIL_DOMAINS
        and not any(domain.endswith(f".{item}") for item in _EXAMPLE_EMAIL_DOMAINS)
    )


def _safe_request_path(path: object) -> str | None:
    if type(path) is not str or len(path) > _MAX_RAW_PATH_CHARACTERS:
        return None
    try:
        raw_path_size = len(path.encode("utf-8", errors="strict"))
    except Exception:  # noqa: BLE001 - exact-string encoding failures are redacted
        return None
    if (
        raw_path_size > _MAX_RAW_PATH_UTF8_BYTES
        or _SAFE_PATH.fullmatch(path) is None
        or path.startswith("//")
    ):
        return None
    current = path
    for decode_round in range(_MAX_PATH_DECODE_ROUNDS + 1):
        if (
            current.startswith("//")
            or any(part in {".", ".."} for part in current.split("/"))
            or any(
                character in "\\?#" or ord(character) < 32 or ord(character) >= 127
                for character in current
            )
        ):
            return None
        decoded: list[str] = []
        index = 0
        found_escape = False
        while index < len(current):
            character = current[index]
            if character != "%":
                decoded.append(character)
                index += 1
                continue
            if (
                index + 2 >= len(current)
                or current[index + 1] not in "0123456789abcdefABCDEF"
                or current[index + 2] not in "0123456789abcdefABCDEF"
            ):
                return None
            found_escape = True
            if decode_round == _MAX_PATH_DECODE_ROUNDS:
                return None
            decoded_character = chr(int(current[index + 1 : index + 3], 16))
            if (
                decoded_character in "/\\?#"
                or ord(decoded_character) < 32
                or ord(decoded_character) >= 127
            ):
                return None
            decoded.append(decoded_character)
            index += 3
        if not found_escape:
            return path
        current = "".join(decoded)
    return None


def _valid_sec_identity(identity: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", identity.lower()).strip()
    return (
        3 <= len(identity) <= 128
        and all(32 <= ord(character) <= 126 for character in identity)
        and any(character.isascii() and character.isalnum() for character in identity)
        and normalized not in _IGNORED_SEC_IDENTITIES
        and not identity.lower().startswith(_DEFAULT_HTTP_USER_AGENT_PREFIXES)
    )


def _sec_eastern_timezone() -> ZoneInfo:
    eastern: ZoneInfo | None = None
    try:
        eastern = ZoneInfo("America/New_York")
    except Exception:  # noqa: BLE001 - local tzdb details are redacted below
        eastern = None
    if eastern is None:
        _fail(
            code="invalid_sec_payload",
            path="$.filings.recent.acceptanceDateTime",
            message="SEC filing timezone is unavailable",
        )
    return eastern


class FixedHostHttpClient:
    """HTTPS-only client whose host is fixed before any request is made."""

    def __init__(
        self,
        *,
        host: str,
        transport: Transport | None = None,
        allowed_hosts: frozenset[str] = _OFFICIAL_HOSTS,
        connect_timeout: float = 5.0,
        read_timeout: float = 10.0,
        max_response_bytes: int = 1_048_576,
        max_json_depth: int = 64,
        max_container_items: int = 10_000,
        max_json_nodes: int = 20_000,
    ) -> None:
        config_valid = (
            type(host) is str
            and type(allowed_hosts) is frozenset
            and allowed_hosts <= _OFFICIAL_HOSTS
            and host in allowed_hosts
            and host in _OFFICIAL_HOSTS
            and all(type(item) is str for item in allowed_hosts)
            and (transport is None or callable(transport))
            and type(connect_timeout) in {int, float}
            and math.isfinite(connect_timeout)
            and 0 < connect_timeout <= _MAX_TIMEOUT_SECONDS
            and type(read_timeout) in {int, float}
            and math.isfinite(read_timeout)
            and 0 < read_timeout <= _MAX_TIMEOUT_SECONDS
            and type(max_response_bytes) is int
            and 0 < max_response_bytes <= 64 * 1024 * 1024
            and type(max_json_depth) is int
            and 0 < max_json_depth <= 512
            and type(max_container_items) is int
            and 0 < max_container_items <= 100_000
            and type(max_json_nodes) is int
            and 0 < max_json_nodes <= 1_000_000
        )
        if not config_valid:
            _fail(
                code="invalid_client_config",
                path="$client",
                message="fixed-host HTTP client configuration is invalid",
            )
        self._host = host
        self._transport = transport or _stdlib_https_transport
        self._connect_timeout = float(connect_timeout)
        self._read_timeout = float(read_timeout)
        self._max_response_bytes = max_response_bytes
        self._max_json_depth = max_json_depth
        self._max_container_items = max_container_items
        self._max_json_nodes = max_json_nodes

    def _validate_request(
        self,
        *,
        path: object,
        query: object,
        headers: object,
    ) -> tuple[str, dict[str, str], dict[str, str]]:
        safe_path = _safe_request_path(path)
        if safe_path is None:
            _fail(
                code="invalid_request",
                path="$request.path",
                message="request path is invalid",
            )
        copied_query: dict[str, str] | None = None
        try:
            if isinstance(query, Mapping):
                candidate: dict[str, str] = {}
                for item_count, (key, value) in enumerate(query.items(), start=1):
                    if (
                        item_count > _MAX_QUERY_ITEMS
                        or type(key) is not str
                        or type(value) is not str
                        or key in candidate
                        or len(key) > _MAX_QUERY_COMPONENT_CHARACTERS
                        or len(value) > _MAX_QUERY_COMPONENT_CHARACTERS
                        or len(key.encode("utf-8", errors="strict"))
                        > _MAX_QUERY_COMPONENT_UTF8_BYTES
                        or len(value.encode("utf-8", errors="strict"))
                        > _MAX_QUERY_COMPONENT_UTF8_BYTES
                    ):
                        break
                    candidate[key] = value
                else:
                    copied_query = candidate
        except Exception:  # noqa: BLE001 - hostile mappings are redacted below
            copied_query = None
        if copied_query is None:
            _fail(
                code="invalid_request",
                path="$request.query",
                message="request query is invalid",
            )
        if type(headers) is not dict:
            _fail(
                code="invalid_request",
                path="$request.headers",
                message="request headers are invalid",
            )
        copied_headers: dict[str, str] = {"Host": self._host}
        seen_names: set[str] = set()
        for name, value in headers.items():
            lowered = name.lower() if type(name) is str else ""
            if (
                type(name) is not str
                or _HEADER_NAME.fullmatch(name) is None
                or lowered in seen_names
                or lowered not in _ALLOWED_REQUEST_HEADERS
                or type(value) is not str
                or not value
                or len(value) > _MAX_REQUEST_HEADER_VALUE_CHARACTERS
                or any(not 32 <= ord(character) <= 126 for character in value)
            ):
                _fail(
                    code="invalid_request",
                    path="$request.headers",
                    message="request headers are invalid",
                )
            seen_names.add(lowered)
            copied_headers[_ALLOWED_REQUEST_HEADERS[lowered]] = value
        return safe_path, copied_query, copied_headers

    @staticmethod
    def _header(headers: Mapping[str, str], name: str) -> str | None:
        lowered = name.lower()
        for key, value in headers.items():
            if type(key) is str and key.lower() == lowered and type(value) is str:
                return value
        return None

    def _decode_json(self, response: HttpResponse) -> JsonResponse:
        if (
            type(response) is not HttpResponse
            or type(response.status) is not int
            or type(response.headers) is not dict
            or any(
                type(key) is not str
                or _HEADER_NAME.fullmatch(key) is None
                or type(value) is not str
                or any(
                    ord(character) < 32 or ord(character) == 127 for character in value
                )
                for key, value in response.headers.items()
            )
            or len({key.lower() for key in response.headers}) != len(response.headers)
            or type(response.body) is not bytes
        ):
            _fail(
                code="transport_failure",
                path="$response",
                message="provider response is unavailable",
            )
        if not 200 <= response.status < 300:
            _fail(
                code="http_status",
                path="$response.status",
                message="provider returned an unsuccessful status",
            )
        content_length = self._header(response.headers, "Content-Length")
        declared_size: int | None = None
        if content_length is not None:
            if (
                len(content_length) > 20
                or re.fullmatch(r"[0-9]+", content_length, re.ASCII) is None
            ):
                _fail(
                    code="invalid_content_length",
                    path="$response.headers.content_length",
                    message="provider response Content-Length is invalid",
                )
            try:
                declared_size = int(content_length)
            except (ValueError, OverflowError):
                _fail(
                    code="invalid_content_length",
                    path="$response.headers.content_length",
                    message="provider response Content-Length is invalid",
                )
        if declared_size is not None and declared_size != len(response.body):
            _fail(
                code="invalid_content_length",
                path="$response.headers.content_length",
                message="provider response Content-Length does not match its body",
            )
        if declared_size is not None and declared_size > self._max_response_bytes:
            _fail(
                code="response_too_large",
                path="$response.body",
                message="provider response exceeds the size limit",
            )
        if (
            type(response.body) is not bytes
            or len(response.body) > self._max_response_bytes
        ):
            _fail(
                code="response_too_large",
                path="$response.body",
                message="provider response exceeds the size limit",
            )
        content_type = self._header(response.headers, "Content-Type")
        if not _content_type_is_utf8_json(content_type):
            _fail(
                code="invalid_content_type",
                path="$response.headers.content_type",
                message="provider response must be UTF-8 JSON",
            )

        text: str | None = None
        try:
            text = response.body.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            pass
        if text is None:
            _fail(
                code="invalid_utf8",
                path="$response.body",
                message="provider response must use strict UTF-8",
            )

        document: object | None = None
        parsed = False
        try:
            document = json.loads(
                text,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            )
            parsed = True
        except (ValueError, RecursionError):
            pass
        if not parsed:
            _fail(
                code="invalid_json",
                path="$response.body",
                message="provider response must be strict JSON with unique keys",
            )

        nodes = 0
        stack: list[tuple[object, int]] = [(document, 1)]
        while stack:
            value, depth = stack.pop()
            nodes += 1
            if depth > self._max_json_depth or nodes > self._max_json_nodes:
                _fail(
                    code="json_too_complex",
                    path="$response.body",
                    message="provider JSON exceeds complexity limits",
                )
            if isinstance(value, dict):
                if len(value) > self._max_container_items:
                    _fail(
                        code="json_too_complex",
                        path="$response.body",
                        message="provider JSON exceeds complexity limits",
                    )
                stack.extend((child, depth + 1) for child in value.values())
            elif isinstance(value, list):
                if len(value) > self._max_container_items:
                    _fail(
                        code="json_too_complex",
                        path="$response.body",
                        message="provider JSON exceeds complexity limits",
                    )
                stack.extend((child, depth + 1) for child in value)
            elif type(value) is float and not math.isfinite(value):
                _fail(
                    code="invalid_json",
                    path="$response.body",
                    message="provider response must contain only finite JSON numbers",
                )
        return JsonResponse(
            document=document,
            body=response.body,
            sha256=f"sha256:{hashlib.sha256(response.body).hexdigest()}",
        )

    def get_json(
        self,
        *,
        path: str,
        query: Mapping[str, str],
        headers: Mapping[str, str],
    ) -> JsonResponse:
        safe_path, safe_query, safe_headers = self._validate_request(
            path=path,
            query=query,
            headers=headers,
        )
        encoded_query: str | None = None
        try:
            encoded_query = urlencode(sorted(safe_query.items()))
        except Exception:  # noqa: BLE001 - URL encoding failures are redacted below
            encoded_query = None
        if encoded_query is None:
            _fail(
                code="invalid_request",
                path="$request.query",
                message="request query is invalid",
            )
        target = safe_path if not encoded_query else f"{safe_path}?{encoded_query}"
        target_valid = False
        try:
            target_valid = (
                len(target.encode("utf-8", errors="strict"))
                <= _MAX_REQUEST_TARGET_BYTES
            )
        except Exception:  # noqa: BLE001 - target encoding failures are redacted below
            target_valid = False
        if not target_valid:
            _fail(
                code="invalid_request",
                path="$request.target",
                message="request target is invalid",
            )
        response: HttpResponse | None = None
        try:
            response = self._transport(
                HttpRequest(
                    scheme="https",
                    host=self._host,
                    target=target,
                    headers=safe_headers,
                    connect_timeout=self._connect_timeout,
                    read_timeout=self._read_timeout,
                    max_response_bytes=self._max_response_bytes,
                )
            )
        except Exception:  # noqa: BLE001 - transport failures are redacted
            response = None
        if response is None:
            _fail(
                code="transport_failure",
                path="$transport",
                message="provider request failed",
            )
        return self._decode_json(response)


class LocalRateLimiter:
    """Thread-safe evenly spaced local request limiter."""

    _MAX_DEADLINE_CONFIRMATIONS = 8

    def __init__(
        self,
        *,
        requests_per_second: int,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if type(requests_per_second) is not int or not 1 <= requests_per_second <= 10:
            _fail(
                code="invalid_client_config",
                path="$client.rate_limit",
                message="local request limit is invalid",
            )
        if not callable(monotonic):
            _fail(
                code="invalid_client_config",
                path="$client.rate_limit.monotonic",
                message="local rate limiter monotonic clock is invalid",
            )
        if not callable(sleep):
            _fail(
                code="invalid_client_config",
                path="$client.rate_limit.sleep",
                message="local rate limiter sleep function is invalid",
            )
        self.requests_per_second = requests_per_second
        self._interval = 1.0 / requests_per_second
        self._monotonic = monotonic
        self._sleep = sleep
        self._next_allowed = 0.0
        self._lock = threading.Lock()

    @staticmethod
    def _limiter_failure() -> NoReturn:
        _fail(
            code="rate_limiter_failure",
            path="$client.rate_limit",
            message="local rate limiter is unavailable",
        )

    def _read_monotonic(self) -> float:
        failed = False
        value: object | None = None
        try:
            value = self._monotonic()
        except Exception:  # noqa: BLE001 - injected clock failures are redacted
            failed = True
        numeric = 0.0
        try:
            if type(value) is int:
                numeric = float(value)
            elif type(value) is float:
                numeric = value
            else:
                failed = True
        except (OverflowError, ValueError):
            failed = True
        if failed or not math.isfinite(numeric):
            self._limiter_failure()
        return numeric

    def _sleep_once(self, seconds: float) -> None:
        failed = False
        try:
            self._sleep(seconds)
        except Exception:  # noqa: BLE001 - injected sleeper failures are redacted
            failed = True
        if failed:
            self._limiter_failure()

    def acquire(self) -> None:
        with self._lock:
            now = self._read_monotonic()
            deadline = self._next_allowed
            confirmations = 0
            while now < deadline:
                if confirmations >= self._MAX_DEADLINE_CONFIRMATIONS:
                    self._limiter_failure()
                self._sleep_once(deadline - now)
                now = self._read_monotonic()
                confirmations += 1
            base = max(now, deadline)
            next_allowed = base + self._interval
            if not math.isfinite(next_allowed) or next_allowed <= base:
                self._limiter_failure()
            self._next_allowed = next_allowed


def _trusted_local_rate_limiter(
    *,
    requests_per_second: object,
    limiter: LocalRateLimiter | None,
) -> LocalRateLimiter:
    if type(requests_per_second) is not int or not 1 <= requests_per_second <= 10:
        _fail(
            code="invalid_client_config",
            path="$client.rate_limit",
            message="local request limit is invalid",
        )
    if limiter is None:
        return LocalRateLimiter(requests_per_second=requests_per_second)
    if type(limiter) is not LocalRateLimiter:
        _fail(
            code="invalid_client_config",
            path="$client.rate_limit",
            message="only a bounded LocalRateLimiter may be injected",
        )
    injected_rps: object | None = None
    monotonic: object | None = None
    sleep: object | None = None
    try:
        injected_rps = object.__getattribute__(limiter, "requests_per_second")
        monotonic = object.__getattribute__(limiter, "_monotonic")
        sleep = object.__getattribute__(limiter, "_sleep")
    except Exception:  # noqa: BLE001 - damaged injected state is redacted
        injected_rps = monotonic = sleep = None
    if (
        type(injected_rps) is not int
        or not 1 <= injected_rps <= 10
        or not callable(monotonic)
        or not callable(sleep)
    ):
        _fail(
            code="invalid_client_config",
            path="$client.rate_limit",
            message="only a bounded LocalRateLimiter may be injected",
        )
    return LocalRateLimiter(
        requests_per_second=injected_rps,
        monotonic=cast(Callable[[], float], monotonic),
        sleep=cast(Callable[[float], None], sleep),
    )


def _rfc3339_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _utc_instant(
    value: object,
    *,
    code: str,
    path: str,
    message: str,
) -> datetime:
    try:
        if (
            type(value) is datetime
            and value.tzinfo is not None
            and value.utcoffset() is not None
        ):
            return value.astimezone(UTC)
    except Exception:  # noqa: BLE001 - hostile tzinfo is redacted
        value = None
    _fail(code=code, path=path, message=message)


def _read_clock_utc(clock: Callable[[], datetime]) -> datetime:
    value: object | None = None
    try:
        value = clock()
    except Exception:  # noqa: BLE001 - hostile clocks are redacted
        value = None
    return _utc_instant(
        value,
        code="invalid_clock",
        path="$clock",
        message="provider clock did not return a valid timezone-aware instant",
    )


def _sec_rights() -> dict[str, object]:
    return {
        "mode": RightsMode.DERIVED_ONLY.value,
        "terms_url": _SEC_TERMS_URL,
        "cache_allowed": True,
        "derived_works_allowed": True,
        "redistribution_allowed": False,
        "attribution_required": True,
        "public_display_allowed": False,
        "retention_days": 30,
        "reviewed_at": _rfc3339_utc(_SEC_REVIEWED_AT),
    }


class SecEdgarSubmissionsAdapter:
    """Conservative pilot for SEC EDGAR submissions JSON."""

    provider_id = "sec-edgar-submissions"
    capabilities = frozenset(
        {
            ProviderCapability.GET_DISCLOSURES,
            ProviderCapability.GET_ENTITLEMENTS,
        }
    )

    def __init__(
        self,
        *,
        user_agent: str,
        transport: Transport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        requests_per_second: int = 5,
        limiter: LocalRateLimiter | None = None,
    ) -> None:
        contact = _CONTACT_EMAIL.search(user_agent) if type(user_agent) is str else None
        identity = (
            ""
            if contact is None
            else (user_agent[: contact.start()] + user_agent[contact.end() :]).strip()
        )
        if (
            type(user_agent) is not str
            or not 10 <= len(user_agent) <= 256
            or not _valid_contact_email(contact)
            or not _valid_sec_identity(identity)
            or any(
                ord(character) < 32 or ord(character) > 126 for character in user_agent
            )
        ):
            _fail(
                code="invalid_user_agent",
                path="$client.user_agent",
                message="SEC requests require a non-default contactable User-Agent",
            )
        if not callable(clock):
            _fail(
                code="invalid_client_config",
                path="$client.clock",
                message="provider clock configuration is invalid",
            )
        self._user_agent = user_agent
        self._clock = clock
        self._limiter = _trusted_local_rate_limiter(
            requests_per_second=requests_per_second,
            limiter=limiter,
        )
        self._rate_limit_rps = self._limiter.requests_per_second
        self._client = FixedHostHttpClient(
            host="data.sec.gov",
            transport=transport,
            max_response_bytes=2 * 1024 * 1024,
        )

    def get_entitlements(
        self,
        *,
        evaluation_timestamp: datetime,
    ) -> ProviderEntitlements:
        return ProviderEntitlements(
            provider_id=self.provider_id,
            evaluated_at=evaluation_timestamp,
            valid_until=None,
            source_type=SourceType.REGULATOR,
            jurisdictions=frozenset({"US"}),
            authentication_mode=AuthenticationMode.NONE,
            capabilities=self.capabilities,
            rights_mode=RightsMode.DERIVED_ONLY,
            cache_allowed=True,
            cache_ttl_seconds=3600,
            derived_works_allowed=True,
            public_display_allowed=False,
            redistribution_allowed=False,
            retention_days=30,
            attribution_required=True,
            terms_url=_SEC_TERMS_URL,
            rights_reviewed_at=_SEC_REVIEWED_AT,
            rate_limit=RateLimit(
                requests_per_period=self._rate_limit_rps,
                period_seconds=1,
                burst=1,
            ),
        )

    @staticmethod
    def _acceptance_timestamp(value: object) -> datetime:
        parsed: datetime | None = None
        if type(value) is str and _SEC_ACCEPTANCE_DATETIME.fullmatch(value) is not None:
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                pass
        if parsed is None or parsed.tzinfo is None:
            _fail(
                code="invalid_sec_payload",
                path="$.filings.recent.acceptanceDateTime",
                message="SEC filing timestamp is invalid",
            )
        return parsed.astimezone(UTC)

    def _authorize_record(
        self,
        record: dict[str, object],
        *,
        evaluation_timestamp: datetime,
    ) -> None:
        evaluation_text = _rfc3339_utc(evaluation_timestamp)
        validate_record(
            "provider_record",
            record,
            schema_version=OFFICIAL_PROVIDER_SCHEMA_VERSION,
            evaluation_timestamp=evaluation_text,
        )
        authorize_ingestion(
            self,
            record,
            schema_version=OFFICIAL_PROVIDER_SCHEMA_VERSION,
            evaluation_timestamp=evaluation_timestamp,
            request=IngestionRequest(
                capability=ProviderCapability.GET_DISCLOSURES,
                uses=frozenset({DataUse.DERIVED_WORK}),
                attribution_ready=True,
            ),
            rate_limit_budget=RateLimitBudget(
                provider_id=self.provider_id,
                period_started_at=evaluation_timestamp.astimezone(UTC).replace(
                    microsecond=0
                ),
                requests_used=0,
            ),
        )

    def _records_from_response(
        self,
        response: JsonResponse,
        *,
        cik: str,
        fetched_at: datetime,
        evaluation_timestamp: datetime,
    ) -> list[dict[str, object]]:
        document = response.document
        if type(document) is not dict:
            _fail(
                code="invalid_sec_payload",
                path="$",
                message="SEC submissions payload is invalid",
            )
        payload_cik = document.get("cik")
        if (
            type(payload_cik) is not str
            or _CIK.fullmatch(payload_cik) is None
            or payload_cik != cik
        ):
            _fail(
                code="invalid_sec_payload",
                path="$.cik",
                message="SEC payload identity does not match the requested CIK",
            )
        fetched_at = _utc_instant(
            fetched_at,
            code="invalid_fetched_at",
            path="$.fetched_at",
            message="fetch timestamp must be timezone-aware",
        )
        evaluation_timestamp = _utc_instant(
            evaluation_timestamp,
            code="invalid_evaluation_timestamp",
            path="$request.evaluation_timestamp",
            message="evaluation timestamp must be timezone-aware",
        )
        if fetched_at > evaluation_timestamp:
            _fail(
                code="invalid_sec_payload",
                path="$.fetched_at",
                message="SEC fetch timestamp violates the evaluation boundary",
            )
        name = document.get("name")
        filings = document.get("filings")
        recent = filings.get("recent") if type(filings) is dict else None
        fields = (
            "accessionNumber",
            "filingDate",
            "reportDate",
            "acceptanceDateTime",
            "form",
            "primaryDocument",
        )
        columns = [
            recent.get(field) if type(recent) is dict else None for field in fields
        ]
        if (
            type(name) is not str
            or not name
            or any(type(column) is not list for column in columns)
            or len({len(column) for column in columns if type(column) is list}) != 1
        ):
            _fail(
                code="invalid_sec_payload",
                path="$.filings.recent",
                message="SEC filing columns are invalid or inconsistent",
            )
        sec_eastern = _sec_eastern_timezone()
        fetched_text = _rfc3339_utc(fetched_at)
        records: list[dict[str, object]] = []
        for index, row in enumerate(zip(*columns, strict=True)):
            accession, filing_date, report_date, acceptance, form, primary_document = (
                row
            )
            if (
                type(accession) is not str
                or _ACCESSION.fullmatch(accession) is None
                or accession[:10] != cik
                or type(filing_date) is not str
                or type(report_date) is not str
                or _ISO_DATE.fullmatch(filing_date) is None
                or (report_date != "" and _ISO_DATE.fullmatch(report_date) is None)
                or type(form) is not str
                or not form
                or type(primary_document) is not str
                or _DOCUMENT_NAME.fullmatch(primary_document) is None
                or primary_document in {".", ".."}
            ):
                _fail(
                    code="invalid_sec_payload",
                    path=f"$.filings.recent[{index}]",
                    message="SEC filing row is invalid",
                )
            try:
                filing_day = date.fromisoformat(filing_date)
                report_day = date.fromisoformat(report_date) if report_date else None
            except ValueError:
                _fail(
                    code="invalid_sec_payload",
                    path=f"$.filings.recent[{index}]",
                    message="SEC filing date is invalid",
                )
            if report_day is not None and report_day > filing_day:
                _fail(
                    code="invalid_sec_payload",
                    path=f"$.filings.recent[{index}].reportDate",
                    message="SEC report date is later than the filing date",
                )
            published = self._acceptance_timestamp(acceptance)
            if (
                filing_day > published.astimezone(sec_eastern).date()
                or published > fetched_at.astimezone(UTC)
                or published > evaluation_timestamp.astimezone(UTC)
            ):
                _fail(
                    code="invalid_sec_payload",
                    path=f"$.filings.recent[{index}].acceptanceDateTime",
                    message="SEC filing contains future knowledge",
                )
            accession_compact = accession.replace("-", "")
            cik_compact = cik.lstrip("0") or "0"
            record: dict[str, object] = {
                "provider_id": self.provider_id,
                "provider_record_id": f"sec:{cik}:{accession}",
                "namespace": "canonical_observation",
                "source_type": SourceType.REGULATOR.value,
                "jurisdiction": "US",
                "entity_type": "issuer",
                "entity_id": f"sec:cik:{cik}",
                "field": "filing",
                "value": {
                    "name": name,
                    "form": form,
                    "accession_number": accession,
                    "filing_date": filing_date,
                    "report_date": report_date or None,
                    "primary_document": primary_document,
                },
                "unit": None,
                "currency": None,
                "timezone": "America/New_York; UTC acceptance",
                "period": filing_date,
                "frequency": "event",
                "publication_lag": (
                    "SEC acceptance timestamp is the publication proxy; "
                    "filingDate is an America/New_York calendar date"
                ),
                "revision": "Current submissions snapshot; filing metadata may be amended",
                "vintage": fetched_text,
                "as_of": _rfc3339_utc(published),
                "published_at": _rfc3339_utc(published),
                "fetched_at": fetched_text,
                "valid_from": None,
                "valid_to": None,
                "source_url": (
                    f"https://www.sec.gov/Archives/edgar/data/{cik_compact}/"
                    f"{accession_compact}/{primary_document}"
                ),
                "source_document_hash": response.sha256,
                "methodology": (
                    "Parsed from the current SEC submissions JSON snapshot; "
                    "no historical response vintage is claimed"
                ),
                "point_in_time_status": "provider_claimed",
                "quality_state": "unverified",
                "rights": _sec_rights(),
            }
            self._authorize_record(record, evaluation_timestamp=evaluation_timestamp)
            records.append(record)
        return records

    def fetch_submissions(
        self,
        *,
        cik: str,
        evaluation_timestamp: datetime | None = None,
    ) -> list[dict[str, object]]:
        if type(cik) is not str or _CIK.fullmatch(cik) is None:
            _fail(
                code="invalid_cik",
                path="$request.cik",
                message="SEC CIK must contain exactly ten ASCII digits",
            )
        explicit_evaluation_boundary = (
            None
            if evaluation_timestamp is None
            else _utc_instant(
                evaluation_timestamp,
                code="invalid_evaluation_timestamp",
                path="$request.evaluation_timestamp",
                message="evaluation timestamp must be timezone-aware",
            )
        )
        self._limiter.acquire()
        response = self._client.get_json(
            path=f"/submissions/CIK{cik}.json",
            query={},
            headers={"User-Agent": self._user_agent, "Accept": "application/json"},
        )
        fetched_at = _read_clock_utc(self._clock)
        evaluation_boundary = (
            fetched_at
            if explicit_evaluation_boundary is None
            else explicit_evaluation_boundary
        )
        return self._records_from_response(
            response,
            cik=cik,
            fetched_at=fetched_at,
            evaluation_timestamp=evaluation_boundary,
        )

    def parse_submissions_fixture(
        self,
        payload: bytes,
        *,
        cik: str,
        fetched_at: datetime,
        evaluation_timestamp: datetime,
    ) -> list[dict[str, object]]:
        """Parse a bounded offline fixture through production validation."""
        if type(cik) is not str or _CIK.fullmatch(cik) is None:
            _fail(
                code="invalid_cik",
                path="$request.cik",
                message="SEC CIK must contain exactly ten ASCII digits",
            )
        response = self._client._decode_json(
            HttpResponse(
                status=200,
                headers={"Content-Type": "application/json"},
                body=payload,
            )
        )
        return self._records_from_response(
            response,
            cik=cik,
            fetched_at=fetched_at,
            evaluation_timestamp=evaluation_timestamp,
        )


def _world_bank_rights(*, source: int) -> dict[str, object]:
    if source != _WB_REVIEWED_SOURCE:
        _fail(
            code="unreviewed_world_bank_source",
            path="$request.source",
            message="World Bank source rights have not been reviewed",
        )
    return {
        "mode": RightsMode.DERIVED_ONLY.value,
        "terms_url": _WB_TERMS_URL,
        "cache_allowed": True,
        "derived_works_allowed": True,
        "redistribution_allowed": False,
        "attribution_required": True,
        "public_display_allowed": False,
        "retention_days": 30,
        "reviewed_at": _rfc3339_utc(_WB_REVIEWED_AT),
    }


def _bounded_positive_int(value: object, *, maximum: int) -> int | None:
    if type(value) is int and 1 <= value <= maximum:
        return value
    if (
        type(value) is str
        and value.isascii()
        and value.isdigit()
        and len(value) <= len(str(maximum))
    ):
        try:
            parsed = int(value)
        except (ValueError, OverflowError):
            return None
        if 1 <= parsed <= maximum:
            return parsed
    return None


class WorldBankIndicatorsAdapter:
    """Conservative annual-series pilot for World Bank Indicators API V2."""

    provider_id = "world-bank-indicators-v2"
    capabilities = frozenset(
        {
            ProviderCapability.GET_ENTITLEMENTS,
            ProviderCapability.GET_MACRO_SERIES,
        }
    )

    def __init__(
        self,
        *,
        countries: frozenset[str],
        source: int = _WB_REVIEWED_SOURCE,
        transport: Transport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        requests_per_second: int = 5,
        limiter: LocalRateLimiter | None = None,
    ) -> None:
        if (
            type(countries) is not frozenset
            or not countries
            or any(
                type(country) is not str
                or _WB_COUNTRY.fullmatch(country) is None
                or country not in _ISO2_TO_ISO3
                for country in countries
            )
        ):
            _fail(
                code="invalid_client_config",
                path="$client.countries",
                message="World Bank adapter country scope is invalid",
            )
        if type(source) is not int or source != _WB_REVIEWED_SOURCE:
            _fail(
                code="invalid_client_config",
                path="$client.source",
                message="World Bank adapter source scope is not reviewed",
            )
        if not callable(clock):
            _fail(
                code="invalid_client_config",
                path="$client.clock",
                message="provider clock configuration is invalid",
            )
        self._countries = countries
        self._source = source
        self._clock = clock
        self._limiter = _trusted_local_rate_limiter(
            requests_per_second=requests_per_second,
            limiter=limiter,
        )
        self._rate_limit_rps = self._limiter.requests_per_second
        self._client = FixedHostHttpClient(
            host="api.worldbank.org",
            transport=transport,
            max_response_bytes=2 * 1024 * 1024,
        )

    def get_entitlements(
        self,
        *,
        evaluation_timestamp: datetime,
    ) -> ProviderEntitlements:
        return ProviderEntitlements(
            provider_id=self.provider_id,
            evaluated_at=evaluation_timestamp,
            valid_until=None,
            source_type=SourceType.INDEX_OR_MACRO_OFFICIAL_SOURCE,
            jurisdictions=self._countries,
            authentication_mode=AuthenticationMode.NONE,
            capabilities=self.capabilities,
            rights_mode=RightsMode.DERIVED_ONLY,
            cache_allowed=True,
            cache_ttl_seconds=86_400,
            derived_works_allowed=True,
            public_display_allowed=False,
            redistribution_allowed=False,
            retention_days=30,
            attribution_required=True,
            terms_url=_WB_TERMS_URL,
            rights_reviewed_at=_WB_REVIEWED_AT,
            rate_limit=RateLimit(
                requests_per_period=self._rate_limit_rps,
                period_seconds=1,
                burst=1,
            ),
            source_ids=frozenset({str(self._source)}),
            dataset_ids=frozenset({_WB_REVIEWED_DATASET}),
        )

    def _authorize_record(
        self,
        record: dict[str, object],
        *,
        evaluation_timestamp: datetime,
    ) -> None:
        validate_record(
            "provider_record",
            record,
            schema_version=OFFICIAL_PROVIDER_SCHEMA_VERSION,
            evaluation_timestamp=_rfc3339_utc(evaluation_timestamp),
        )
        authorize_ingestion(
            self,
            record,
            schema_version=OFFICIAL_PROVIDER_SCHEMA_VERSION,
            evaluation_timestamp=evaluation_timestamp,
            request=IngestionRequest(
                capability=ProviderCapability.GET_MACRO_SERIES,
                uses=frozenset({DataUse.DERIVED_WORK}),
                attribution_ready=True,
            ),
            rate_limit_budget=RateLimitBudget(
                provider_id=self.provider_id,
                period_started_at=evaluation_timestamp.astimezone(UTC).replace(
                    microsecond=0
                ),
                requests_used=0,
            ),
        )

    @staticmethod
    def _page_metadata(
        document: object,
        *,
        requested_page: int,
        requested_per_page: int,
        source: int,
    ) -> tuple[dict[str, object], list[object]]:
        if (
            type(document) is not list
            or len(document) != 2
            or type(document[0]) is not dict
            or type(document[1]) is not list
        ):
            _fail(
                code="invalid_world_bank_payload",
                path="$",
                message="World Bank page envelope is invalid",
            )
        metadata = document[0]
        page = _bounded_positive_int(metadata.get("page"), maximum=10_000)
        pages = _bounded_positive_int(metadata.get("pages"), maximum=10_000)
        per_page = _bounded_positive_int(metadata.get("per_page"), maximum=10_000)
        total = metadata.get("total")
        source_id = metadata.get("sourceid")
        last_updated = metadata.get("lastupdated")
        if (
            page != requested_page
            or pages is None
            or per_page != requested_per_page
            or type(total) is not int
            or not 0 <= total <= 10_000_000
            or type(source_id) is not str
            or source_id != str(source)
            or type(last_updated) is not str
            or _ISO_DATE.fullmatch(last_updated) is None
        ):
            _fail(
                code="invalid_world_bank_payload",
                path="$[0]",
                message="World Bank pagination metadata is invalid",
            )
        expected_pages = max(
            1,
            (total + requested_per_page - 1) // requested_per_page,
        )
        expected_rows = (
            requested_per_page
            if page < expected_pages
            else total - requested_per_page * (expected_pages - 1)
        )
        if (
            pages != expected_pages
            or len(document[1]) > requested_per_page
            or len(document[1]) != expected_rows
        ):
            _fail(
                code="invalid_world_bank_payload",
                path="$[0]",
                message="World Bank page rows do not match pagination metadata",
            )
        try:
            date.fromisoformat(last_updated)
        except ValueError:
            _fail(
                code="invalid_world_bank_payload",
                path="$[0].lastupdated",
                message="World Bank update date is invalid",
            )
        return metadata, document[1]

    def _records_from_page(
        self,
        *,
        rows: list[object],
        country: str,
        indicator: str,
        source: int,
        page: int,
        per_page: int,
        last_updated: str,
        fetched_at: datetime,
        evaluation_timestamp: datetime,
        response_hash: str,
    ) -> list[dict[str, object]]:
        fetched_at = _utc_instant(
            fetched_at,
            code="invalid_fetched_at",
            path="$.fetched_at",
            message="fetch timestamp must be timezone-aware",
        )
        evaluation_timestamp = _utc_instant(
            evaluation_timestamp,
            code="invalid_evaluation_timestamp",
            path="$request.evaluation_timestamp",
            message="evaluation timestamp must be timezone-aware",
        )
        if (
            fetched_at > evaluation_timestamp
            or date.fromisoformat(last_updated) > fetched_at.date()
        ):
            _fail(
                code="invalid_world_bank_payload",
                path="$[0].lastupdated",
                message="World Bank page contains future knowledge",
            )
        fetched_text = _rfc3339_utc(fetched_at)
        source_url = (
            f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}?"
            f"format=json&page={page}&per_page={per_page}&source={source}"
        )
        records: list[dict[str, object]] = []
        for index, raw_row in enumerate(rows):
            row = raw_row if type(raw_row) is dict else None
            row_indicator = row.get("indicator") if row is not None else None
            row_country = row.get("country") if row is not None else None
            period = row.get("date") if row is not None else None
            value = row.get("value") if row is not None else None
            unit = row.get("unit") if row is not None else None
            decimal = row.get("decimal") if row is not None else None
            country_iso3 = row.get("countryiso3code") if row is not None else None
            if (
                row is None
                or type(row_indicator) is not dict
                or row_indicator.get("id") != indicator
                or type(row_indicator.get("value")) is not str
                or type(row_country) is not dict
                or row_country.get("id") != country
                or type(row_country.get("value")) is not str
                or type(period) is not str
                or _WB_YEAR.fullmatch(period) is None
                or not 1 <= int(period) <= 9998
                or (
                    value is not None
                    and (
                        type(value) not in {int, float}
                        or (type(value) is float and not math.isfinite(value))
                        or abs(value) > _MAX_WB_ABS_VALUE
                    )
                )
                or type(unit) is not str
                or type(decimal) is not int
                or not 0 <= decimal <= 100
                or "countryiso3code" not in row
                or country_iso3 != _ISO2_TO_ISO3[country]
            ):
                _fail(
                    code="invalid_world_bank_payload",
                    path=f"$[1][{index}]",
                    message="World Bank observation row is invalid",
                )
            start = datetime(int(period), 1, 1, tzinfo=UTC)
            if start > fetched_at.astimezone(
                UTC
            ) or start > evaluation_timestamp.astimezone(UTC):
                _fail(
                    code="invalid_world_bank_payload",
                    path=f"$[1][{index}].date",
                    message="World Bank observation period is in the future",
                )
            end = datetime(int(period) + 1, 1, 1, tzinfo=UTC)
            normalized_unit = unit or None
            currency = "USD" if "US$" in unit else None
            record: dict[str, object] = {
                "provider_id": self.provider_id,
                "provider_record_id": f"wb:{source}:{country}:{indicator}:{period}",
                "namespace": "canonical_observation",
                "source_type": SourceType.INDEX_OR_MACRO_OFFICIAL_SOURCE.value,
                "jurisdiction": country,
                "entity_type": "macro_observation",
                "entity_id": f"wb:{source}:{country}:{indicator}",
                "field": "value",
                "value": {
                    "indicator": {
                        "id": indicator,
                        "name": row_indicator["value"],
                    },
                    "country": {
                        "id": country,
                        "name": row_country["value"],
                        "iso3": country_iso3,
                    },
                    "date": period,
                    "value": value,
                    "decimal": decimal,
                    "source": {
                        "id": str(source),
                        "dataset": _WB_REVIEWED_DATASET,
                        "lastupdated": last_updated,
                    },
                },
                "unit": normalized_unit,
                "currency": currency,
                "timezone": "UTC",
                "period": period,
                "frequency": "annual",
                "publication_lag": (
                    "Unknown: API lastupdated is date-only and does not expose "
                    "observation publication time"
                ),
                "revision": "Latest API view; observations may be revised",
                "vintage": last_updated,
                "as_of": _rfc3339_utc(start),
                "published_at": fetched_text,
                "fetched_at": fetched_text,
                "valid_from": _rfc3339_utc(start),
                "valid_to": _rfc3339_utc(end),
                "source_url": source_url,
                "source_document_hash": response_hash,
                "methodology": (
                    "Current World Bank Indicators API view; lastupdated has date-only "
                    "granularity, exact publication lag and historical vintage are unavailable"
                ),
                "point_in_time_status": "not_point_in_time",
                "quality_state": "missing" if value is None else "unverified",
                "rights": _world_bank_rights(source=source),
            }
            self._authorize_record(record, evaluation_timestamp=evaluation_timestamp)
            records.append(record)
        return records

    def fetch_series(
        self,
        *,
        country: str,
        indicator: str,
        source: int,
        per_page: int = 100,
        max_pages: int = 1,
        max_records: int = 1000,
        evaluation_timestamp: datetime | None = None,
    ) -> list[dict[str, object]]:
        if type(source) is int and 1 <= source <= 9999 and source != self._source:
            _fail(
                code="unreviewed_world_bank_source",
                path="$request.source",
                message="World Bank source rights have not been reviewed",
            )
        if (
            type(country) is not str
            or _WB_COUNTRY.fullmatch(country) is None
            or country not in self._countries
            or type(indicator) is not str
            or _WB_INDICATOR.fullmatch(indicator) is None
            or type(source) is not int
            or not 1 <= source <= 9999
            or type(per_page) is not int
            or not 1 <= per_page <= 1000
            or type(max_pages) is not int
            or not 1 <= max_pages <= 10
            or type(max_records) is not int
            or not 1 <= max_records <= 10_000
        ):
            _fail(
                code="invalid_world_bank_request",
                path="$request",
                message="World Bank series request is invalid",
            )
        explicit_evaluation_boundary = (
            None
            if evaluation_timestamp is None
            else _utc_instant(
                evaluation_timestamp,
                code="invalid_evaluation_timestamp",
                path="$request.evaluation_timestamp",
                message="evaluation timestamp must be timezone-aware",
            )
        )
        records: list[dict[str, object]] = []
        expected: tuple[int, int, int, str, str] | None = None
        page = 1
        while True:
            self._limiter.acquire()
            response = self._client.get_json(
                path=f"/v2/country/{country}/indicator/{indicator}",
                query={
                    "format": "json",
                    "page": str(page),
                    "per_page": str(per_page),
                    "source": str(source),
                },
                headers={"Accept": "application/json"},
            )
            metadata, rows = self._page_metadata(
                response.document,
                requested_page=page,
                requested_per_page=per_page,
                source=source,
            )
            pages = _bounded_positive_int(metadata["pages"], maximum=10_000)
            if pages is None or pages > max_pages:
                _fail(
                    code="world_bank_page_limit",
                    path="$[0].pages",
                    message="World Bank response exceeds the explicit page limit",
                )
            total = metadata["total"]
            last_updated = metadata["lastupdated"]
            source_id = metadata["sourceid"]
            if (
                type(total) is not int
                or type(last_updated) is not str
                or type(source_id) is not str
            ):
                _fail(
                    code="invalid_world_bank_payload",
                    path="$[0]",
                    message="World Bank pagination metadata is invalid",
                )
            if total > max_records:
                _fail(
                    code="world_bank_record_limit",
                    path="$[0].total",
                    message="World Bank response exceeds the explicit record limit",
                )
            current = (pages, total, per_page, source_id, last_updated)
            if expected is None:
                expected = current
            elif current != expected:
                _fail(
                    code="invalid_world_bank_payload",
                    path="$[0]",
                    message="World Bank pagination metadata changed between pages",
                )
            fetched_at = _read_clock_utc(self._clock)
            evaluation_boundary = (
                fetched_at
                if explicit_evaluation_boundary is None
                else explicit_evaluation_boundary
            )
            records.extend(
                self._records_from_page(
                    rows=rows,
                    country=country,
                    indicator=indicator,
                    source=source,
                    page=page,
                    per_page=per_page,
                    last_updated=last_updated,
                    fetched_at=fetched_at,
                    evaluation_timestamp=evaluation_boundary,
                    response_hash=response.sha256,
                )
            )
            identifiers = [record.get("provider_record_id") for record in records]
            if (
                len(records) > total
                or len(records) > max_records
                or len(set(identifiers)) != len(identifiers)
            ):
                _fail(
                    code="invalid_world_bank_payload",
                    path="$[0].total",
                    message="World Bank page rows do not reconcile to metadata",
                )
            if page >= pages:
                if len(records) != total:
                    _fail(
                        code="invalid_world_bank_payload",
                        path="$[0].total",
                        message="World Bank page rows do not reconcile to metadata",
                    )
                return records
            page += 1

    def parse_page_fixture(
        self,
        payload: bytes,
        *,
        country: str,
        indicator: str,
        source: int,
        page: int,
        per_page: int,
        fetched_at: datetime,
        evaluation_timestamp: datetime,
    ) -> list[dict[str, object]]:
        """Parse one complete, bounded offline API fixture page."""
        if type(source) is int and 1 <= source <= 9999 and source != self._source:
            _fail(
                code="unreviewed_world_bank_source",
                path="$request.source",
                message="World Bank source rights have not been reviewed",
            )
        if (
            type(country) is not str
            or _WB_COUNTRY.fullmatch(country) is None
            or country not in self._countries
            or type(indicator) is not str
            or _WB_INDICATOR.fullmatch(indicator) is None
            or type(source) is not int
            or not 1 <= source <= 9999
            or type(page) is not int
            or page != 1
            or type(per_page) is not int
            or not 1 <= per_page <= 1000
        ):
            _fail(
                code="invalid_world_bank_request",
                path="$request",
                message="World Bank fixture request is invalid",
            )
        response = self._client._decode_json(
            HttpResponse(
                status=200,
                headers={"Content-Type": "application/json"},
                body=payload,
            )
        )
        metadata, rows = self._page_metadata(
            response.document,
            requested_page=page,
            requested_per_page=per_page,
            source=source,
        )
        pages = _bounded_positive_int(metadata["pages"], maximum=10_000)
        total = metadata["total"]
        last_updated = metadata["lastupdated"]
        if pages != 1 or type(total) is not int or type(last_updated) is not str:
            _fail(
                code="invalid_world_bank_payload",
                path="$[0]",
                message="offline fixture must contain one complete page",
            )
        records = self._records_from_page(
            rows=rows,
            country=country,
            indicator=indicator,
            source=source,
            page=page,
            per_page=per_page,
            last_updated=last_updated,
            fetched_at=fetched_at,
            evaluation_timestamp=evaluation_timestamp,
            response_hash=response.sha256,
        )
        identifiers = [record.get("provider_record_id") for record in records]
        if len(records) != total or len(set(identifiers)) != len(identifiers):
            _fail(
                code="invalid_world_bank_payload",
                path="$[0].total",
                message="World Bank fixture rows do not reconcile to metadata",
            )
        return records
