"""Semantic validation for manager research records."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

from .provider_semantics import (
    ProviderRecordValidationError,
    parse_rfc3339_timestamp,
)


class ManagerResearchValidationError(ValueError):
    """Raised when manager research violates a semantic boundary."""


_SENSITIVE_TEXT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private-information marker",
        re.compile(
            r"\b(?:home\s+address|residential\s+address|private\s+life|phone|email|social\s+security)\b"
            r"|家庭住址|家庭地址|住址|私人生活|手机号|电话|电子邮箱|身份证",
            re.IGNORECASE,
        ),
    ),
    (
        "email address",
        re.compile(
            r"(?<![\w.+-])[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])"
        ),
    ),
    (
        "Chinese mobile number",
        re.compile(r"(?<!\d)(?:(?:\+?86)[\s-]?)?1[3-9]\d{9}(?!\d)"),
    ),
    (
        "Chinese identity number",
        re.compile(r"(?<!\d)(?:\d{17}[0-9Xx]|\d{15})(?![0-9Xx])"),
    ),
    (
        "North American phone number",
        re.compile(
            r"(?<!\d)(?:\+?1[\s.-]?)?"
            r"(?:\([2-9]\d{2}\)|[2-9]\d{2})[\s.-]?"
            r"[2-9]\d{2}[\s.-]?\d{4}(?!\d)"
        ),
    ),
    (
        "international phone number",
        re.compile(r"(?<!\w)\+(?=(?:[^\d]*\d){7,15}(?!\d))[\d\s().-]+\d"),
    ),
)


def _child_path(path: str, key: object) -> str:
    if isinstance(key, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        return f"{path}.{key}"
    if isinstance(key, int):
        return f"{path}[{key}]"
    escaped = str(key).replace("\\", "\\\\").replace('"', '\\"')
    return f'{path}["{escaped}"]'


def _validate_text(value: Any, path: str = "$") -> None:
    if isinstance(value, str):
        for label, pattern in _SENSITIVE_TEXT_PATTERNS:
            if pattern.search(value):
                raise ManagerResearchValidationError(
                    f"{path}: sensitive private information is not permitted ({label})"
                )
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            _validate_text(child, _child_path(path, key))
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _validate_text(child, _child_path(path, index))


def validate_public_professional_text(value: Any, path: str = "$") -> None:
    """Reject sensitive private content in public-professional text containers."""
    _validate_text(value, path)


def _validate_evidence_references(
    value: Any,
    evidence_ids: set[str],
    path: str = "$",
) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = _child_path(path, key)
            if key == "evidence_ids" and isinstance(child, Sequence):
                for index, reference in enumerate(child):
                    if reference not in evidence_ids:
                        reference_path = _child_path(child_path, index)
                        raise ManagerResearchValidationError(
                            f"{reference_path}: evidence reference {reference!r} "
                            "does not exist in $.evidence"
                        )
            _validate_evidence_references(child, evidence_ids, child_path)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _validate_evidence_references(
                child,
                evidence_ids,
                _child_path(path, index),
            )


def _validate_compliance_evidence_tiers(
    document: Mapping[str, Any],
    evidence_tiers: Mapping[str, set[str]],
) -> None:
    component = document.get("score_components", {}).get("compliance_integrity", {})
    score = component.get("score")
    is_scored = isinstance(score, (int, float)) and not isinstance(score, bool)
    is_high_confidence = component.get("confidence") == "high"
    if not (is_scored or is_high_confidence):
        return

    references = component.get("evidence_ids", ())
    has_qualifying_evidence = any(
        evidence_tiers.get(reference, set()) & {"A", "B", "C"}
        for reference in references
    )
    if not has_qualifying_evidence:
        raise ManagerResearchValidationError(
            "$.score_components.compliance_integrity.evidence_ids: "
            "a numeric score or high confidence requires at least one Tier A, B, or C evidence reference"
        )


def _timestamp(value: object, *, path: str) -> datetime:
    provider_error: ProviderRecordValidationError | None = None
    parsed: datetime | None = None
    try:
        parsed = parse_rfc3339_timestamp(value, path=path)
    except ProviderRecordValidationError as exc:
        provider_error = exc
    if provider_error is not None or parsed is None:
        raise ManagerResearchValidationError(
            f"{path}: timestamp violates the RFC3339 profile"
        )
    return parsed


def _date_value(value: object, *, path: str) -> date:
    parsed: date | None = None
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            pass
    if parsed is None:
        raise ManagerResearchValidationError(f"{path}: date must be valid ISO 8601")
    return parsed


def _validate_dated_ranges(
    document: Mapping[str, Any],
    *,
    collection: str,
    start_field: str,
    end_field: str,
    as_of_date: date,
) -> None:
    for index, item in enumerate(document.get(collection, ())):
        if not isinstance(item, Mapping):
            continue
        base = f"$.{collection}[{index}]"
        start = _date_value(item.get(start_field), path=f"{base}.{start_field}")
        end_value = item.get(end_field)
        end = (
            _date_value(end_value, path=f"{base}.{end_field}")
            if end_value is not None
            else None
        )
        if end is not None and start > end:
            raise ManagerResearchValidationError(
                f"{base}.{start_field}: start must be on or before end"
            )
        if start > as_of_date:
            raise ManagerResearchValidationError(
                f"{base}.{start_field}: date must be on or before record as_of"
            )
        if end is not None and end > as_of_date:
            raise ManagerResearchValidationError(
                f"{base}.{end_field}: date must be on or before record as_of"
            )


def _validate_manager_chronology(document: Mapping[str, Any]) -> None:
    as_of = _timestamp(document.get("as_of"), path="$.as_of")
    as_of_date = as_of.astimezone(UTC).date()
    _validate_dated_ranges(
        document,
        collection="employment_history",
        start_field="start_date",
        end_field="end_date",
        as_of_date=as_of_date,
    )
    _validate_dated_ranges(
        document,
        collection="tenures",
        start_field="start_date",
        end_field="end_date",
        as_of_date=as_of_date,
    )
    _validate_dated_ranges(
        document,
        collection="performance_evidence",
        start_field="window_start",
        end_field="window_end",
        as_of_date=as_of_date,
    )
    for index, event in enumerate(document.get("compliance_events", ())):
        if not isinstance(event, Mapping) or event.get("effective_date") is None:
            continue
        path = f"$.compliance_events[{index}].effective_date"
        if _date_value(event["effective_date"], path=path) > as_of_date:
            raise ManagerResearchValidationError(
                f"{path}: date must be on or before record as_of"
            )
    for index, evidence in enumerate(document.get("evidence", ())):
        if not isinstance(evidence, Mapping):
            continue
        base = f"$.evidence[{index}]"
        published_at = _timestamp(
            evidence.get("published_at"),
            path=f"{base}.published_at",
        )
        fetched_at = _timestamp(
            evidence.get("fetched_at"),
            path=f"{base}.fetched_at",
        )
        if published_at > fetched_at:
            raise ManagerResearchValidationError(
                f"{base}.published_at: published_at must be on or before fetched_at"
            )
        if fetched_at > as_of:
            raise ManagerResearchValidationError(
                f"{base}.fetched_at: fetched_at must be on or before record as_of"
            )


def validate_manager_research(document: Mapping[str, Any]) -> None:
    """Validate manager-research semantics beyond the JSON Schema contract."""
    _validate_text(document)
    _validate_manager_chronology(document)
    evidence_tiers: dict[str, set[str]] = {}
    for evidence in document.get("evidence", ()):
        if not isinstance(evidence, Mapping):
            continue
        evidence_id = evidence.get("evidence_id")
        tier = evidence.get("tier")
        if isinstance(evidence_id, str) and isinstance(tier, str):
            evidence_tiers.setdefault(evidence_id, set()).add(tier)

    _validate_evidence_references(document, set(evidence_tiers))
    _validate_compliance_evidence_tiers(document, evidence_tiers)
