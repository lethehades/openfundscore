"""Fail-closed semantics for provider contracts and external ratings."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .provider_semantics import (
    ProviderRecordValidationError,
    parse_rfc3339_timestamp,
)


class ContractValidationError(ValueError):
    """Stable, path-aware contract semantic failure."""

    def __init__(self, *, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        super().__init__(f"{path}: {code}: {message}")


_PROVIDER_RIGHTS: dict[str, tuple[tuple[str, bool], ...]] = {
    "unknown_blocked": (
        ("public_display_allowed", False),
        ("rights.cache_allowed", False),
        ("rights.derived_works_allowed", False),
        ("rights.redistribution_allowed", False),
        ("rights.attribution_required", False),
    ),
    "derived_only": (
        ("public_display_allowed", False),
        ("rights.derived_works_allowed", True),
        ("rights.redistribution_allowed", False),
    ),
    "display_only": (
        ("public_display_allowed", True),
        ("rights.cache_allowed", False),
        ("rights.derived_works_allowed", False),
        ("rights.redistribution_allowed", False),
        ("rights.attribution_required", True),
    ),
    "local_entitlement": (
        ("public_display_allowed", False),
        ("rights.redistribution_allowed", False),
    ),
    "open_redistributable": (("rights.redistribution_allowed", True),),
}

_EXTERNAL_DISPLAY_STATUS = {
    "open_redistributable": "allowed",
    "derived_only": "blocked",
    "local_entitlement": "local_only",
    "display_only": "allowed",
    "unknown_blocked": "unknown",
}


def _mapping(value: object, *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError(
            code="invalid_type",
            path=path,
            message="semantic input must be an object",
        )
    return value


def _field(document: Mapping[str, Any], dotted: str) -> object:
    value: object = document
    for part in dotted.split("."):
        value = _mapping(value, path=f"$.{dotted}").get(part)
    return value


def _timestamp(value: object, *, path: str) -> datetime:
    provider_error: ProviderRecordValidationError | None = None
    parsed: datetime | None = None
    try:
        parsed = parse_rfc3339_timestamp(value, path=path)
    except ProviderRecordValidationError as exc:
        provider_error = exc
    if provider_error is not None:
        raise ContractValidationError(
            code=provider_error.code,
            path=provider_error.path,
            message="timestamp violates the RFC3339 profile",
        )
    if parsed is None:  # pragma: no cover - defensive invariant
        raise ContractValidationError(
            code="invalid_rfc3339",
            path=path,
            message="timestamp violates the RFC3339 profile",
        )
    return parsed


def validate_provider_contract_semantics(document: object) -> None:
    """Recheck provider rights-mode combinations independently of JSON Schema."""
    contract = _mapping(document, path="$")
    rights = _mapping(contract.get("rights"), path="$.rights")
    mode = rights.get("mode")
    if not isinstance(mode, str) or mode not in _PROVIDER_RIGHTS:
        raise ContractValidationError(
            code="invalid_rights_mode",
            path="$.rights.mode",
            message="provider rights mode is unsupported",
        )
    for dotted, expected in _PROVIDER_RIGHTS[mode]:
        if _field(contract, dotted) is not expected:
            raise ContractValidationError(
                code="rights_mismatch",
                path=f"$.{dotted}",
                message="provider rights do not match their declared mode",
            )


def validate_external_rating_semantics(
    document: object,
    *,
    evaluation_timestamp: str,
) -> None:
    """Validate rating chronology, score isolation and display entitlement."""
    rating = _mapping(document, path="$")
    as_of = _timestamp(rating.get("as_of"), path="$.as_of")
    fetched_at = _timestamp(rating.get("fetched_at"), path="$.fetched_at")
    published_at = None
    if rating.get("published_at") is not None:
        published_at = _timestamp(
            rating.get("published_at"),
            path="$.published_at",
        )
    evaluation_at = _timestamp(
        evaluation_timestamp,
        path="$evaluation_timestamp",
    )
    if as_of > fetched_at:
        raise ContractValidationError(
            code="chronology_violation",
            path="$.as_of",
            message="as_of must be on or before fetched_at",
        )
    if published_at is not None and published_at > fetched_at:
        raise ContractValidationError(
            code="chronology_violation",
            path="$.published_at",
            message="published_at must be on or before fetched_at",
        )
    if fetched_at > evaluation_at:
        raise ContractValidationError(
            code="chronology_violation",
            path="$.fetched_at",
            message="fetched_at must be on or before the evaluation timestamp",
        )
    if as_of > evaluation_at:
        raise ContractValidationError(
            code="future_as_of",
            path="$.as_of",
            message="as_of must be on or before the evaluation timestamp",
        )
    if rating.get("affects_open_score") is not False:
        raise ContractValidationError(
            code="score_isolation_violation",
            path="$.affects_open_score",
            message="external ratings cannot affect Open Score",
        )
    rights_mode = rating.get("rights_mode")
    if not isinstance(rights_mode, str) or rights_mode not in _EXTERNAL_DISPLAY_STATUS:
        raise ContractValidationError(
            code="invalid_rights_mode",
            path="$.rights_mode",
            message="external rating rights mode is unsupported",
        )
    if rating.get("display_status") != _EXTERNAL_DISPLAY_STATUS[rights_mode]:
        raise ContractValidationError(
            code="rights_mismatch",
            path="$.display_status",
            message="display status does not match the declared rights mode",
        )
