"""Peer-bucket and score-profile mapping for complex alternative strategies.

The mapping is a versioned packaged resource
(``strategy-mapping / complex_alternatives / 0.1.0``). Every decision is derived
from that document. Products without sufficient evidence or comparable peer
samples stay explicitly ``unrated``; no default mapping is ever invented.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .resources import ResourceError, resolve_resource
from .score_config import validate_score_config


class StrategyMappingError(ValueError):
    """Raised when a strategy mapping violates its public contract."""


UNRATED_PROFILE = "unrated"

_ALLOWED_STATUSES = {"research-preview"}
_MAPPING_IDENTITY_CONTRACT = {
    "mapping_id": "complex_alternatives",
    "mapping_version": "0.1.0",
}
_SCORING_CONFIG_CONTRACT = {
    "type": "scoring-config",
    "name": "openfundscore-core",
    "version": "0.1.0",
}
_TOP_LEVEL_FIELDS = {
    "mapping_id",
    "mapping_version",
    "status",
    "scoring_config",
    "unrated_reasons",
    "peer_buckets",
    "strategy_families",
}
_BUCKET_FIELDS = {
    "label",
    "included_strategies",
    "score_profile",
    "unrated_reason",
    "admission_requirements",
}
_ADMISSION_FIELDS = {"min_peer_count", "min_track_months", "required_disclosures"}
_FAMILY_FIELDS = {"peer_bucket"}
_IDENTIFIER_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", re.ASCII)
_MIN_PEER_COUNT = 2
_MIN_TRACK_MONTHS = 1
_MAX_MAPPING_BYTES = 1024 * 1024
_MAX_IDENTIFIER_CHARS = 128
_MAX_TEXT_CHARS = 4096
_MAX_COLLECTION_ITEMS = 256
_MAX_OBJECT_ENTRIES = 64
_MAX_PEER_COUNT = 1_000_000
_MAX_TRACK_MONTHS = 1_200

_EXPECTED_FAMILY_BUCKETS = {
    "market_neutral": "market_neutral",
    "long_short_equity": "long_short_equity",
    "absolute_return": "absolute_return_multi_strategy",
    "derivatives_heavy": "managed_futures_derivatives",
    "other_complex_alternative": "other_complex_alternative",
}

_PACKAGED_SELECTOR = {
    "resource_type": "strategy-mapping",
    "name": _MAPPING_IDENTITY_CONTRACT["mapping_id"],
}


@dataclass(frozen=True, slots=True)
class MappingDecision:
    """One explicit strategy-family mapping outcome.

    ``score_profile`` is either a category profile from the referenced scoring
    configuration or the literal ``unrated``. An unrated decision always carries
    a documented ``unrated_reason``; a rated decision never does.
    """

    strategy_family: str
    peer_bucket: str
    score_profile: str
    unrated_reason: str | None
    mapping_id: str
    mapping_version: str
    resource_sha256: str

    @property
    def is_rated(self) -> bool:
        """Whether the family currently maps to a real scoring profile."""
        return self.score_profile != UNRATED_PROFILE


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate JSON object key")
        document[key] = value
    return document


def _reject_non_finite(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def load_strategy_mapping(path: str | Path) -> dict[str, Any]:
    """Load one bounded, strict JSON mapping with redacted failures."""
    mapping_path = Path(path)
    payload: bytes | None = None
    try:
        with mapping_path.open("rb") as handle:
            payload = handle.read(_MAX_MAPPING_BYTES + 1)
    except OSError:
        pass
    if payload is None:
        raise StrategyMappingError("strategy mapping could not be read")
    if len(payload) > _MAX_MAPPING_BYTES:
        raise StrategyMappingError("strategy mapping exceeds the supported size")
    text: str | None = None
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        pass
    if text is None:
        raise StrategyMappingError("strategy mapping is not valid UTF-8")
    parsed = False
    document: Any = None
    try:
        document = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_non_finite,
        )
        parsed = True
    except (json.JSONDecodeError, RecursionError, ValueError):
        pass
    if not parsed:
        raise StrategyMappingError("strategy mapping is not valid strict JSON")

    if type(document) is not dict:
        raise StrategyMappingError("strategy mapping must be a JSON object")
    return document


def _reject_unknown_fields(
    value: Mapping[str, Any], *, allowed: set[str], label: str
) -> None:
    if len(value) > len(allowed):
        raise StrategyMappingError(f"{label} has unknown fields")
    unknown = set(value) - allowed
    if unknown:
        raise StrategyMappingError(f"{label} has unknown fields")


def _require_identifier(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > _MAX_IDENTIFIER_CHARS
        or _IDENTIFIER_PATTERN.fullmatch(value) is None
    ):
        raise StrategyMappingError(
            f"{label} must use the lowercase snake_case ASCII profile"
        )
    return value


def _require_non_empty_string_list(value: Any, *, label: str) -> None:
    if not isinstance(value, list) or not value or len(value) > _MAX_COLLECTION_ITEMS:
        raise StrategyMappingError(f"{label} must be a non-empty array")
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item) > _MAX_TEXT_CHARS:
            raise StrategyMappingError(f"{label} items must be non-empty strings")
        if item in seen:
            raise StrategyMappingError(f"{label} items must be unique")
        seen.add(item)


def _validated_admission_requirements(value: Any, *, label: str) -> None:
    if type(value) is not dict:
        raise StrategyMappingError(f"{label} admission_requirements must be an object")
    _reject_unknown_fields(
        value, allowed=_ADMISSION_FIELDS, label=f"{label} admission_requirements"
    )
    for field in _ADMISSION_FIELDS:
        if field not in value:
            raise StrategyMappingError(
                f"{label} admission_requirements.{field} is required"
            )

    min_peer_count = value["min_peer_count"]
    if (
        isinstance(min_peer_count, bool)
        or not isinstance(min_peer_count, int)
        or not _MIN_PEER_COUNT <= min_peer_count <= _MAX_PEER_COUNT
    ):
        raise StrategyMappingError(
            f"{label} admission_requirements.min_peer_count must be an integer "
            f">= {_MIN_PEER_COUNT}"
        )
    min_track_months = value["min_track_months"]
    if (
        isinstance(min_track_months, bool)
        or not isinstance(min_track_months, int)
        or not _MIN_TRACK_MONTHS <= min_track_months <= _MAX_TRACK_MONTHS
    ):
        raise StrategyMappingError(
            f"{label} admission_requirements.min_track_months must be an integer "
            f">= {_MIN_TRACK_MONTHS}"
        )
    _require_non_empty_string_list(
        value["required_disclosures"],
        label=f"{label} admission_requirements.required_disclosures",
    )


def _scoring_config_profile_ids() -> set[str]:
    document: dict[str, Any] | None = None
    try:
        document = resolve_resource(
            resource_type=_SCORING_CONFIG_CONTRACT["type"],
            name=_SCORING_CONFIG_CONTRACT["name"],
            version=_SCORING_CONFIG_CONTRACT["version"],
        ).load_json()
        validate_score_config(document)
    except Exception:  # noqa: BLE001 - normalize the packaged validation boundary
        document = None
    if document is None:
        raise StrategyMappingError(
            "referenced scoring configuration is unavailable or invalid"
        )
    profiles = document.get("category_profiles")
    if not isinstance(profiles, Mapping) or not profiles:
        raise StrategyMappingError(
            "referenced scoring_config exposes no category profiles"
        )
    return set(profiles)


def validate_strategy_mapping(document: Mapping[str, Any]) -> None:
    """Validate the stable v0 complex-alternatives mapping contract."""
    if type(document) is not dict:
        raise StrategyMappingError("strategy mapping must be an object")
    _reject_unknown_fields(
        document, allowed=_TOP_LEVEL_FIELDS, label="strategy mapping"
    )

    for field, expected in _MAPPING_IDENTITY_CONTRACT.items():
        value = document.get(field)
        if not isinstance(value, str) or not value:
            raise StrategyMappingError(f"{field} must be a non-empty string")
        if value != expected:
            raise StrategyMappingError(f"{field} must be {expected!r}")

    status = document.get("status")
    if not isinstance(status, str) or status not in _ALLOWED_STATUSES:
        allowed = ", ".join(sorted(_ALLOWED_STATUSES))
        raise StrategyMappingError(f"status must be one of: {allowed}")

    scoring_config = document.get("scoring_config")
    if type(scoring_config) is not dict:
        raise StrategyMappingError("scoring_config must be an object")
    _reject_unknown_fields(
        scoring_config,
        allowed=set(_SCORING_CONFIG_CONTRACT),
        label="scoring_config",
    )
    for field, expected in _SCORING_CONFIG_CONTRACT.items():
        if scoring_config.get(field) != expected:
            raise StrategyMappingError(f"scoring_config.{field} must be {expected!r}")

    reasons = document.get("unrated_reasons")
    if type(reasons) is not dict or not reasons or len(reasons) > _MAX_OBJECT_ENTRIES:
        raise StrategyMappingError("unrated_reasons must be a non-empty object")
    for reason_id, description in reasons.items():
        _require_identifier(reason_id, label="unrated_reasons")
        if (
            not isinstance(description, str)
            or not description.strip()
            or len(description) > _MAX_TEXT_CHARS
        ):
            raise StrategyMappingError(
                "unrated_reasons values must be non-empty strings"
            )

    buckets = document.get("peer_buckets")
    if type(buckets) is not dict or not buckets or len(buckets) > _MAX_OBJECT_ENTRIES:
        raise StrategyMappingError("peer_buckets must be a non-empty object")

    category_profile_ids = _scoring_config_profile_ids()
    used_reasons: set[str] = set()
    for bucket_id, bucket in buckets.items():
        _require_identifier(bucket_id, label="peer_buckets")
        label = "peer_buckets entry"
        if type(bucket) is not dict:
            raise StrategyMappingError(f"{label} must be an object")
        _reject_unknown_fields(bucket, allowed=_BUCKET_FIELDS, label=label)

        bucket_label = bucket.get("label")
        if (
            not isinstance(bucket_label, str)
            or not bucket_label.strip()
            or len(bucket_label) > _MAX_TEXT_CHARS
        ):
            raise StrategyMappingError(f"{label}.label must be a non-empty string")
        _require_non_empty_string_list(
            bucket.get("included_strategies"),
            label=f"{label}.included_strategies",
        )

        score_profile = bucket.get("score_profile")
        if (
            not isinstance(score_profile, str)
            or not score_profile
            or len(score_profile) > _MAX_IDENTIFIER_CHARS
        ):
            raise StrategyMappingError(f"{label}.score_profile must be a string")
        if score_profile == UNRATED_PROFILE:
            reason = bucket.get("unrated_reason")
            if (
                not isinstance(reason, str)
                or len(reason) > _MAX_IDENTIFIER_CHARS
                or reason not in reasons
            ):
                raise StrategyMappingError(
                    f"{label}.unrated_reason must reference a defined unrated reason"
                )
            used_reasons.add(reason)
        elif score_profile in category_profile_ids:
            if "unrated_reason" in bucket:
                raise StrategyMappingError(
                    f"{label}.unrated_reason is forbidden when score_profile "
                    "names a category profile"
                )
        else:
            raise StrategyMappingError(
                f"{label}.score_profile must be {UNRATED_PROFILE!r} or a category "
                "profile of the referenced scoring_config"
            )

        _validated_admission_requirements(
            bucket.get("admission_requirements"), label=label
        )

    unused_reasons = set(reasons) - used_reasons
    if unused_reasons:
        raise StrategyMappingError("unrated_reasons defines unused entries")

    families = document.get("strategy_families")
    if (
        type(families) is not dict
        or not families
        or len(families) > _MAX_OBJECT_ENTRIES
    ):
        raise StrategyMappingError("strategy_families must be a non-empty object")
    if set(buckets) != set(_EXPECTED_FAMILY_BUCKETS.values()):
        raise StrategyMappingError("peer_buckets does not match the v0 contract")
    if set(families) != set(_EXPECTED_FAMILY_BUCKETS):
        raise StrategyMappingError("strategy_families does not match the v0 contract")
    for family_id, family in families.items():
        _require_identifier(family_id, label="strategy_families")
        label = "strategy_families entry"
        if type(family) is not dict:
            raise StrategyMappingError(f"{label} must be an object")
        _reject_unknown_fields(family, allowed=_FAMILY_FIELDS, label=label)
        peer_bucket = family.get("peer_bucket")
        if (
            not isinstance(peer_bucket, str)
            or len(peer_bucket) > _MAX_IDENTIFIER_CHARS
            or peer_bucket not in buckets
        ):
            raise StrategyMappingError(
                f"{label}.peer_bucket must reference a defined peer bucket"
            )
        if peer_bucket != _EXPECTED_FAMILY_BUCKETS[family_id]:
            raise StrategyMappingError(
                "strategy_families entry must use its designated v0 peer bucket"
            )


def _resolve_packaged_mapping(mapping_version: str):
    if not isinstance(mapping_version, str) or not mapping_version:
        raise StrategyMappingError("mapping_version must be a non-empty string")
    resource_error = False
    resource = None
    try:
        resource = resolve_resource(
            **_PACKAGED_SELECTOR,
            version=mapping_version,
        )
    except ResourceError:
        resource_error = True
    if resource_error or resource is None:
        raise StrategyMappingError(
            "requested strategy mapping version is not available; no fallback applied"
        )
    return resource


def _load_packaged_mapping_document(resource: Any) -> dict[str, Any]:
    document: Any = None
    try:
        document = resource.load_json()
    except ResourceError:
        pass
    if type(document) is not dict:
        raise StrategyMappingError(
            "packaged strategy mapping is unavailable or invalid"
        )
    return document


def load_packaged_strategy_mapping(*, mapping_version: str) -> dict[str, Any]:
    """Resolve, verify and validate one explicit packaged mapping version."""
    resource = _resolve_packaged_mapping(mapping_version)
    document = _load_packaged_mapping_document(resource)
    validate_strategy_mapping(document)
    return document


def map_strategy_family(
    family: str,
    *,
    mapping_version: str,
) -> MappingDecision:
    """Map a family using one explicit, digest-verified packaged resource.

    Unknown or malformed families fail closed with ``StrategyMappingError``;
    they never receive a default or best-effort mapping. Caller-provided mapping
    documents cannot authorize a scoring decision under a packaged version ID.
    """
    _require_identifier(family, label="strategy_family")
    resource = _resolve_packaged_mapping(mapping_version)
    document = _load_packaged_mapping_document(resource)
    validate_strategy_mapping(document)

    families = document["strategy_families"]
    entry = families.get(family)
    if entry is None:
        raise StrategyMappingError(
            "strategy_family has no defined mapping; the product stays unrated "
            "and no default mapping is applied"
        )

    bucket_id = entry["peer_bucket"]
    bucket = document["peer_buckets"][bucket_id]
    return MappingDecision(
        strategy_family=family,
        peer_bucket=bucket_id,
        score_profile=bucket["score_profile"],
        unrated_reason=bucket.get("unrated_reason"),
        mapping_id=document["mapping_id"],
        mapping_version=document["mapping_version"],
        resource_sha256=resource.info.sha256,
    )
