"""Semantic validation for manager research records."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


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
        re.compile(r"(?<![\w.+-])[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])"),
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


def validate_manager_research(document: Mapping[str, Any]) -> None:
    """Validate manager-research semantics beyond the JSON Schema contract."""
    _validate_text(document)
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
