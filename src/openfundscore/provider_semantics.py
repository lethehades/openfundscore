"""Fail-closed semantic validation for provider records."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

_RFC3339_TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])$"
)
_POINT_IN_TIME_STATUSES = {
    "verified",
    "provider_claimed",
    "reconstructed",
    "not_point_in_time",
    "unknown",
}
_QUALITY_STATES = {
    "verified",
    "unverified",
    "stale",
    "conflict",
    "missing",
    "not_applicable",
}
_RIGHTS_REQUIREMENTS: dict[str, tuple[tuple[str, bool], ...]] = {
    "unknown_blocked": (
        ("cache_allowed", False),
        ("derived_works_allowed", False),
        ("redistribution_allowed", False),
        ("attribution_required", False),
        ("public_display_allowed", False),
    ),
    "derived_only": (
        ("derived_works_allowed", True),
        ("redistribution_allowed", False),
    ),
    "display_only": (
        ("cache_allowed", False),
        ("derived_works_allowed", False),
        ("redistribution_allowed", False),
        ("attribution_required", True),
        ("public_display_allowed", True),
    ),
    "local_entitlement": (
        ("redistribution_allowed", False),
        ("public_display_allowed", False),
    ),
    "open_redistributable": (("redistribution_allowed", True),),
}


class ProviderRecordValidationError(ValueError):
    """A stable, path-aware provider-record semantic validation failure."""

    def __init__(self, *, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        super().__init__(f"{path}: {code}: {message}")


def _parse_timestamp_value(value: object, *, path: str) -> datetime:
    if not isinstance(value, str):
        raise ProviderRecordValidationError(
            code="invalid_type",
            path=path,
            message="timestamp must be a string",
        )
    if _RFC3339_TIMESTAMP.fullmatch(value) is None or value.endswith("-00:00"):
        raise ProviderRecordValidationError(
            code="invalid_rfc3339",
            path=path,
            message=(
                "timestamp must use the OpenFundScore RFC3339 profile "
                "with uppercase T/Z, a known valid offset, and at most "
                "six fractional digits"
            ),
        )
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None
    if parsed is None:
        raise ProviderRecordValidationError(
            code="invalid_rfc3339",
            path=path,
            message="timestamp must be a valid RFC3339-profile instant",
        ) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProviderRecordValidationError(
            code="invalid_rfc3339",
            path=path,
            message="timestamp must include an explicit offset",
        )
    return parsed


def parse_rfc3339_timestamp(value: object, *, path: str) -> datetime:
    """Parse the shared strict RFC3339 profile with a path-aware error."""
    return _parse_timestamp_value(value, path=path)


def _parse_required_timestamp(record: Mapping[str, Any], field: str) -> datetime:
    path = f"$.{field}"
    if field not in record:
        raise ProviderRecordValidationError(
            code="missing_field",
            path=path,
            message="required timestamp is missing",
        )
    return _parse_timestamp_value(record[field], path=path)


def _parse_optional_timestamp(record: Mapping[str, Any], field: str) -> datetime | None:
    value = record.get(field)
    if value is None:
        return None
    return _parse_timestamp_value(value, path=f"$.{field}")


def _require_enum(
    record: Mapping[str, Any],
    field: str,
    allowed: set[str],
) -> str:
    path = f"$.{field}"
    if field not in record:
        raise ProviderRecordValidationError(
            code="missing_field",
            path=path,
            message="required semantic field is missing",
        )
    value = record[field]
    if not isinstance(value, str) or value not in allowed:
        raise ProviderRecordValidationError(
            code="invalid_enum",
            path=path,
            message="semantic field has an unsupported value",
        )
    return value


def _require_methodology_and_lower_quality(
    record: Mapping[str, Any],
    *,
    status_label: str,
    quality_state: str,
) -> None:
    methodology = record.get("methodology")
    if not isinstance(methodology, str) or not methodology.strip():
        raise ProviderRecordValidationError(
            code="missing_methodology",
            path="$.methodology",
            message=f"{status_label} records must document their methodology",
        )
    if quality_state == "verified":
        raise ProviderRecordValidationError(
            code="incompatible_quality",
            path="$.quality_state",
            message=f"{status_label} records cannot claim verified quality",
        )


def _validate_rights(rights: Mapping[str, Any]) -> None:
    mode = rights.get("mode")
    if not isinstance(mode, str) or mode not in _RIGHTS_REQUIREMENTS:
        raise ProviderRecordValidationError(
            code="invalid_rights_mode",
            path="$.rights.mode",
            message="rights mode is unsupported",
        )
    for field, expected in _RIGHTS_REQUIREMENTS[mode]:
        if rights.get(field) is not expected:
            raise ProviderRecordValidationError(
                code="rights_mismatch",
                path=f"$.rights.{field}",
                message="rights do not match their declared mode",
            )


def validate_provider_record_semantics(
    record: object,
    *,
    evaluation_timestamp: str,
) -> None:
    """Validate provider-record semantics without mutating the input."""
    if not isinstance(record, Mapping):
        raise ProviderRecordValidationError(
            code="invalid_type",
            path="$",
            message="provider record must be an object",
        )
    published_at = _parse_required_timestamp(record, "published_at")
    fetched_at = _parse_required_timestamp(record, "fetched_at")
    as_of = _parse_required_timestamp(record, "as_of")
    valid_from = _parse_optional_timestamp(record, "valid_from")
    valid_to = _parse_optional_timestamp(record, "valid_to")
    if "rights" not in record:
        raise ProviderRecordValidationError(
            code="missing_field",
            path="$.rights",
            message="required rights object is missing",
        )
    rights = record["rights"]
    if not isinstance(rights, Mapping):
        raise ProviderRecordValidationError(
            code="invalid_type",
            path="$.rights",
            message="rights must be an object",
        )
    if rights.get("reviewed_at") is not None:
        _parse_timestamp_value(
            rights["reviewed_at"],
            path="$.rights.reviewed_at",
        )
    _validate_rights(rights)
    evaluation_at = _parse_timestamp_value(
        evaluation_timestamp,
        path="$evaluation_timestamp",
    )
    if published_at > fetched_at:
        raise ProviderRecordValidationError(
            code="chronology_violation",
            path="$.published_at",
            message="published_at must be on or before fetched_at",
        )
    if fetched_at > evaluation_at:
        raise ProviderRecordValidationError(
            code="chronology_violation",
            path="$.fetched_at",
            message="fetched_at must be on or before the evaluation timestamp",
        )
    if valid_from is not None and valid_to is not None and valid_from > valid_to:
        raise ProviderRecordValidationError(
            code="chronology_violation",
            path="$.valid_from",
            message="valid_from must be on or before valid_to",
        )
    if as_of > evaluation_at:
        raise ProviderRecordValidationError(
            code="future_as_of",
            path="$.as_of",
            message="as_of must be on or before the evaluation timestamp",
        )
    if as_of > fetched_at:
        raise ProviderRecordValidationError(
            code="chronology_violation",
            path="$.as_of",
            message="as_of must be on or before fetched_at",
        )
    point_in_time_status = _require_enum(
        record,
        "point_in_time_status",
        _POINT_IN_TIME_STATUSES,
    )
    quality_state = _require_enum(record, "quality_state", _QUALITY_STATES)
    if point_in_time_status == "verified":
        for field in ("provider_record_id", "source_document_hash"):
            value = record.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ProviderRecordValidationError(
                    code="missing_provenance",
                    path=f"$.{field}",
                    message="verified point-in-time status requires provenance",
                )
    if point_in_time_status == "reconstructed":
        _require_methodology_and_lower_quality(
            record,
            status_label="reconstructed",
            quality_state=quality_state,
        )
    if point_in_time_status == "not_point_in_time":
        _require_methodology_and_lower_quality(
            record,
            status_label="not-point-in-time",
            quality_state=quality_state,
        )
    if point_in_time_status == "unknown" and quality_state == "verified":
        raise ProviderRecordValidationError(
            code="incompatible_quality",
            path="$.quality_state",
            message="unknown point-in-time status cannot claim verified quality",
        )
