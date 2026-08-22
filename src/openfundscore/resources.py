"""Versioned package-resource discovery for OpenFundScore."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from importlib.resources import files
from typing import Any

_RESOURCE_PACKAGE = "openfundscore._resources"
_NAME_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:[_-][a-z0-9]+)*", re.ASCII)
_VERSION_PATTERN = re.compile(r"[0-9]+(?:\.[0-9]+){2}", re.ASCII)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}", re.ASCII)


class ResourceError(ValueError):
    """Stable package-resource boundary error."""

    def __init__(self, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        super().__init__(f"{code} at {path}: {message}")


class _StrictJSONError(ValueError):
    """Internal sentinel for duplicate keys and non-finite JSON constants."""


def _strict_json_loads(text: str) -> Any:
    def object_from_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise _StrictJSONError("duplicate object key")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise _StrictJSONError("non-finite numeric constant")

    return json.loads(
        text,
        object_pairs_hook=object_from_pairs,
        parse_constant=reject_constant,
    )


class ResourceType(StrEnum):
    """Published OpenFundScore resource families."""

    METRIC_CATALOG = "metric-catalog"
    PEER_ADMISSION = "peer-admission"
    SCHEMA = "schema"
    SCORING_CONFIG = "scoring-config"
    STRATEGY_MAPPING = "strategy-mapping"


@dataclass(frozen=True, slots=True)
class ResourceKey:
    """A complete, explicit resource selector."""

    resource_type: ResourceType
    name: str
    version: str


@dataclass(frozen=True, slots=True)
class ResourceInfo:
    """Stable public metadata for one packaged resource."""

    key: ResourceKey
    uri: str
    media_type: str
    sha256: str


@dataclass(frozen=True, slots=True)
class _CatalogEntry:
    info: ResourceInfo
    internal_path: str


@dataclass(frozen=True, slots=True)
class ResolvedResource:
    """Read-only access to a resolved package resource."""

    info: ResourceInfo
    _internal_path: str

    def __post_init__(self) -> None:
        if not isinstance(self.info, ResourceInfo) or not isinstance(
            self.info.key, ResourceKey
        ):
            raise ResourceError(
                "invalid_resource_handle",
                "$resource",
                "resource handle identity is invalid",
            )
        key = self.info.key
        valid_type = isinstance(key.resource_type, ResourceType)
        valid_name = (
            isinstance(key.name, str) and _NAME_PATTERN.fullmatch(key.name) is not None
        )
        valid_version = (
            isinstance(key.version, str)
            and _VERSION_PATTERN.fullmatch(key.version) is not None
        )
        if not valid_type or not valid_name or not valid_version:
            raise ResourceError(
                "invalid_resource_handle",
                "$resource",
                "resource handle identity is invalid",
            )
        extension = (
            ".schema.json" if key.resource_type is ResourceType.SCHEMA else ".json"
        )
        expected_path = f"{key.resource_type.value}/{key.name}/{key.version}{extension}"
        expected_uri = (
            f"openfundscore://{key.resource_type.value}/{key.name}/{key.version}"
        )
        expected_media_type = (
            "application/schema+json"
            if key.resource_type is ResourceType.SCHEMA
            else "application/json"
        )
        if (
            self._internal_path != expected_path
            or self.info.uri != expected_uri
            or self.info.media_type != expected_media_type
            or not isinstance(self.info.sha256, str)
            or _SHA256_PATTERN.fullmatch(self.info.sha256) is None
        ):
            raise ResourceError(
                "invalid_resource_handle",
                "$resource",
                "resource handle metadata is inconsistent",
            )

    def read_bytes(self) -> bytes:
        """Read resource bytes after verifying the catalog digest."""
        payload: bytes | None = None
        try:
            payload = (
                files(_RESOURCE_PACKAGE)
                .joinpath(*self._internal_path.split("/"))
                .read_bytes()
            )
        except OSError:
            pass
        if payload is None:
            raise ResourceError(
                "resource_unavailable",
                "$resource",
                "packaged resource could not be read",
            )
        if hashlib.sha256(payload).hexdigest() != self.info.sha256:
            raise ResourceError(
                "resource_integrity",
                "$resource",
                "packaged resource digest does not match the catalog",
            )
        return payload

    def read_text(self) -> str:
        """Read the resource as strict UTF-8 text."""
        text: str | None = None
        try:
            text = self.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            pass
        if text is None:
            raise ResourceError(
                "resource_format",
                "$resource",
                "packaged resource is not valid UTF-8",
            )
        return text

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any]:
        parsed = False
        document: Any = None
        try:
            document = _strict_json_loads(text)
            parsed = True
        except (json.JSONDecodeError, RecursionError, _StrictJSONError):
            pass
        if not parsed:
            raise ResourceError(
                "resource_format",
                "$resource",
                "packaged resource is not valid JSON",
            )
        if not isinstance(document, dict):
            raise ResourceError(
                "resource_format",
                "$resource",
                "packaged JSON resource must be an object",
            )
        return document

    def read_json_text(self) -> str:
        """Read exact UTF-8 text after validating that it is a JSON object."""
        text = self.read_text()
        self._parse_json_object(text)
        return text

    def load_json(self) -> dict[str, Any]:
        """Load the resource as a JSON object."""
        return self._parse_json_object(self.read_text())


def _parse_catalog(document: object) -> tuple[_CatalogEntry, ...]:
    if not isinstance(document, dict):
        raise ResourceError(
            "catalog_invalid",
            "$catalog",
            "package-resource catalog must be an object",
        )
    if set(document) != {"format_version", "resources"}:
        raise ResourceError(
            "catalog_invalid",
            "$catalog",
            "package-resource catalog fields are closed",
        )
    if (
        type(document.get("format_version")) is not int
        or document["format_version"] != 1
    ):
        raise ResourceError(
            "catalog_invalid",
            "$catalog",
            "unsupported package-resource catalog format",
        )
    resources = document["resources"]
    if not isinstance(resources, list):
        raise ResourceError(
            "catalog_invalid",
            "$catalog",
            "catalog resources must be an array",
        )
    entries: list[_CatalogEntry] = []
    seen_keys: set[ResourceKey] = set()
    expected_fields = {
        "type",
        "name",
        "version",
        "internal_path",
        "media_type",
        "sha256",
    }
    for item in resources:
        if not isinstance(item, dict) or set(item) != expected_fields:
            raise ResourceError(
                "catalog_invalid",
                "$catalog",
                "package-resource catalog entry fields are closed",
            )
        resource_type: ResourceType | None = None
        try:
            resource_type = ResourceType(item["type"])
        except (TypeError, ValueError):
            pass
        if resource_type is None:
            raise ResourceError(
                "catalog_invalid",
                "$catalog",
                "catalog resource type is unsupported",
            )
        name = item["name"]
        version = item["version"]
        if (
            not isinstance(name, str)
            or _NAME_PATTERN.fullmatch(name) is None
            or not isinstance(version, str)
            or _VERSION_PATTERN.fullmatch(version) is None
        ):
            raise ResourceError(
                "catalog_invalid",
                "$catalog",
                "catalog selectors must use the supported ASCII profile",
            )
        key = ResourceKey(
            resource_type=resource_type,
            name=name,
            version=version,
        )
        extension = ".schema.json" if resource_type is ResourceType.SCHEMA else ".json"
        expected_path = f"{resource_type.value}/{key.name}/{key.version}{extension}"
        if item["internal_path"] != expected_path:
            raise ResourceError(
                "catalog_invalid",
                "$catalog",
                "resource path must be derived from its complete selector",
            )
        sha256 = item["sha256"]
        if not isinstance(sha256, str) or _SHA256_PATTERN.fullmatch(sha256) is None:
            raise ResourceError(
                "catalog_invalid",
                "$catalog",
                "resource digest must be lowercase SHA-256",
            )
        expected_media_type = (
            "application/schema+json"
            if resource_type is ResourceType.SCHEMA
            else "application/json"
        )
        if item["media_type"] != expected_media_type:
            raise ResourceError(
                "catalog_invalid",
                "$catalog",
                "resource media type must match its resource type",
            )
        if key in seen_keys:
            raise ResourceError(
                "catalog_invalid",
                "$catalog",
                "resource selectors must be unique",
            )
        seen_keys.add(key)
        info = ResourceInfo(
            key=key,
            uri=(f"openfundscore://{resource_type.value}/{key.name}/{key.version}"),
            media_type=item["media_type"],
            sha256=item["sha256"],
        )
        entries.append(_CatalogEntry(info=info, internal_path=item["internal_path"]))
    return tuple(
        sorted(
            entries,
            key=lambda entry: (
                entry.info.key.resource_type.value,
                entry.info.key.name,
                entry.info.key.version,
            ),
        )
    )


def _load_catalog() -> tuple[_CatalogEntry, ...]:
    text: str | None = None
    try:
        text = files(_RESOURCE_PACKAGE).joinpath("index.json").read_text("utf-8")
    except (OSError, UnicodeError):
        pass
    if text is None:
        raise ResourceError(
            "catalog_unavailable",
            "$catalog",
            "package-resource catalog could not be read",
        )
    parsed = False
    document: Any = None
    try:
        document = _strict_json_loads(text)
        parsed = True
    except (json.JSONDecodeError, RecursionError, _StrictJSONError):
        pass
    if not parsed:
        raise ResourceError(
            "catalog_invalid",
            "$catalog",
            "package-resource catalog is not valid JSON",
        )
    return _parse_catalog(document)


_CATALOG = _load_catalog()


def _select_resource_type(value: ResourceType | str) -> ResourceType:
    try:
        return ResourceType(value)
    except (TypeError, ValueError):
        raise ResourceError(
            "invalid_selector",
            "$resource_type",
            "resource type must be a supported ASCII value",
        ) from None


def _validate_selector(value: object, *, path: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ResourceError(
            "invalid_selector",
            path,
            "selector must use the supported ASCII profile",
        )
    return value


def list_resources(
    *, resource_type: ResourceType | str | None = None
) -> tuple[ResourceInfo, ...]:
    """Return published resources in deterministic selector order."""
    if resource_type is None:
        return tuple(entry.info for entry in _CATALOG)
    selected_type = _select_resource_type(resource_type)
    return tuple(
        entry.info
        for entry in _CATALOG
        if entry.info.key.resource_type is selected_type
    )


def resolve_resource(
    *,
    resource_type: ResourceType | str,
    name: str,
    version: str,
) -> ResolvedResource:
    """Resolve one complete selector without version fallback."""
    selected_type = _select_resource_type(resource_type)
    selected_name = _validate_selector(name, path="$name", pattern=_NAME_PATTERN)
    selected_version = _validate_selector(
        version,
        path="$version",
        pattern=_VERSION_PATTERN,
    )
    for entry in _CATALOG:
        key = entry.info.key
        if (
            key.resource_type is selected_type
            and key.name == selected_name
            and key.version == selected_version
        ):
            return ResolvedResource(
                info=entry.info,
                _internal_path=entry.internal_path,
            )
    raise ResourceError(
        "resource_not_found",
        "$resource",
        "no packaged resource matches the complete selector",
    )
