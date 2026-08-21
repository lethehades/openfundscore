"""Fail-closed public-publication release boundary.

OpenFundScore currently has no authenticated legal-review, provider-clearance or
release-approval verifier.  Consequently this module cannot emit a public GO.
It records either an explicit hosted-publication NO_GO or a LOCAL_ONLY result.
Caller-supplied approval metadata is deliberately never treated as authority.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .provider_semantics import (
    ProviderRecordValidationError,
    parse_rfc3339_timestamp,
)


class PublicationDecision(str, Enum):
    """Decisions available without authenticated approval infrastructure."""

    NO_GO = "no_go"
    LOCAL_ONLY = "local_only"


class PublicationGateError(ValueError):
    """Stable, redacted error for a malformed gate request."""

    def __init__(self, *, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        super().__init__(f"{code} at {path}: {message}")


@dataclass(frozen=True, slots=True)
class PublicationGateResult:
    """Auditable local record of a decision that never grants publication."""

    decision: PublicationDecision
    reason_codes: tuple[str, ...]
    jurisdictions: tuple[str, ...]
    request_id: str
    evaluation_timestamp: str

    @property
    def reasons(self) -> tuple[str, ...]:
        """Alias retained for concise machine checks."""
        return self.reason_codes

    @property
    def authorizes_publication(self) -> bool:
        """Always false until a trusted verifier is implemented and reviewed."""
        return False


_PUBLICATION_MODES = frozenset({"hosted_public_rating", "local_private_research"})
_JURISDICTION_RE = re.compile(r"^[A-Z]{2}$", re.ASCII)
_MAX_TOP_LEVEL_FIELDS = 32
_MAX_REQUEST_ID_CHARS = 128
_MAX_JURISDICTIONS = 32


def _invalid(path: str, message: str) -> PublicationGateError:
    return PublicationGateError(
        code="invalid_publication_request",
        path=path,
        message=message,
    )


def _request_mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("$", "request must be an object")
    if len(value) > _MAX_TOP_LEVEL_FIELDS:
        raise _invalid("$", "request exceeds the field-count limit")
    if any(not isinstance(key, str) for key in value):
        raise _invalid("$", "request keys must be strings")
    return value


def _request_id(document: Mapping[str, Any]) -> str:
    value = document.get("request_id")
    if (
        not isinstance(value, str)
        or not value
        or not value.isprintable()
        or not value.strip()
        or len(value) > _MAX_REQUEST_ID_CHARS
    ):
        raise _invalid("$.request_id", "must be a bounded non-empty string")
    return value


def _evaluation_timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(
            "$evaluation_timestamp",
            "must be a strict RFC3339 timestamp",
        )
    failed = False
    try:
        parse_rfc3339_timestamp(value, path="$evaluation_timestamp")
    except ProviderRecordValidationError:
        failed = True
    if failed:
        raise _invalid(
            "$evaluation_timestamp",
            "must be a strict RFC3339 timestamp",
        )
    return value


def _jurisdictions(document: Mapping[str, Any]) -> tuple[str, ...]:
    value = document.get("jurisdictions", [])
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise _invalid("$.jurisdictions", "must be an array")
    if len(value) > _MAX_JURISDICTIONS:
        raise _invalid("$.jurisdictions", "exceeds the jurisdiction-count limit")
    result: set[str] = set()
    for item in value:
        if not isinstance(item, str) or _JURISDICTION_RE.fullmatch(item) is None:
            raise _invalid("$.jurisdictions[*]", "contains an invalid code")
        result.add(item)
    return tuple(sorted(result))


def evaluate_publication_gate(
    request: Mapping[str, Any],
    *,
    evaluation_timestamp: str,
) -> PublicationGateResult:
    """Return a deterministic local-only or hosted-publication NO_GO record.

    Legal reviews, licence assertions, hashes, roles and control booleans supplied
    by the caller are not traversed or trusted.  A future public GO requires a new
    versioned interface backed by authenticated artifact and manifest verification.
    """
    document = _request_mapping(request)
    request_id = _request_id(document)
    evaluated_at = _evaluation_timestamp(evaluation_timestamp)
    mode = document.get("publication_mode")
    if not isinstance(mode, str) or mode not in _PUBLICATION_MODES:
        raise _invalid("$.publication_mode", "is not supported")
    jurisdictions = _jurisdictions(document)

    if mode == "local_private_research":
        return PublicationGateResult(
            decision=PublicationDecision.LOCAL_ONLY,
            reason_codes=("not_authorized_for_publication",),
            jurisdictions=jurisdictions,
            request_id=request_id,
            evaluation_timestamp=evaluated_at,
        )

    return PublicationGateResult(
        decision=PublicationDecision.NO_GO,
        reason_codes=(
            "jurisdiction_review_not_obtained",
            "not_authorized_for_publication",
            "publication_manifest_not_verified",
            "trusted_publication_verifier_unavailable",
        ),
        jurisdictions=jurisdictions,
        request_id=request_id,
        evaluation_timestamp=evaluated_at,
    )
