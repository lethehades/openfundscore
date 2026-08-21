"""Semantic validation for manager research records."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import unquote

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
            r"\b(?:home\s+address|residential\s+address|private\s+life|email|social\s+security)\b"
            r"|\bphone(?=\s*(?:number|withheld|unavailable|unknown|not\s+disclosed)\b|\s*[:+0-9])"
            r"|家庭住址|家庭地址|住址|私人生活|手机号|电子邮箱|身份证"
            r"|(?:联系)?电话(?:号码)?(?=(?:未披露|未知|不详)|\s*[:：]|\s*[+\d])",
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
        "obfuscated email address",
        re.compile(
            r"(?<![\w.+-])[\w.+-]+\s*(?:\[at\]|\(at\))\s*"
            r"[\w-]+(?:\.[\w-]+)+(?![\w.-])",
            re.IGNORECASE,
        ),
    ),
    (
        "Chinese mobile number",
        re.compile(r"(?<!\d)(?:(?:\+?86)[\s.-]*)?1[3-9](?:[\s.-]*\d){9}(?!\d)"),
    ),
    (
        "Chinese identity number",
        re.compile(
            r"(?<!\d)(?:(?:\d[\s.-]*){17}[0-9Xx]|(?:\d[\s.-]*){14}\d)(?![0-9Xx])"
        ),
    ),
    (
        "North American phone number",
        re.compile(
            r"(?<!\d)(?:\+?1[\s.-]?)?"
            r"(?:\([2-9]\d{2}\)[\s.-]?[2-9]\d{2}[\s.-]\d{4}"
            r"|[2-9]\d{2}[\s.-][2-9]\d{2}[\s.-]\d{4})(?!\d)"
        ),
    ),
    (
        "international phone number",
        re.compile(r"(?<!\w)\+(?=(?:[^\d]*\d){7,15}(?!\d))[\d\s().-]+\d"),
    ),
)

_SECURITY_TEXT_TRANSLATION = str.maketrans({"。": ".", "．": ".", "｡": "."})
_UNSEPARATED_NORTH_AMERICAN_PHONE = re.compile(
    r"(?<!\d)(?:\+?1)?[2-9]\d{2}[2-9]\d{2}\d{4}(?!\d)"
)


def _security_text_view(value: str) -> str:
    normalized = unicodedata.normalize(
        "NFKD", value.translate(_SECURITY_TEXT_TRANSLATION)
    )
    return "".join(
        character
        for character in normalized
        if unicodedata.category(character)[0] not in {"C", "M"}
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
        security_view = _security_text_view(value)
        for label, pattern in _SENSITIVE_TEXT_PATTERNS:
            if pattern.search(security_view):
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


def validate_public_professional_source_url(
    value: str, path: str = "$.source_url"
) -> None:
    """Apply the public-text boundary plus URL-specific compact phone detection."""
    decoded = value
    for _ in range(32):
        updated = unquote(decoded)
        if updated == decoded:
            break
        decoded = updated
    else:
        raise ManagerResearchValidationError(
            f"{path}: URL encoding nesting is too deep"
        )
    validate_public_professional_text(decoded, path)
    if _UNSEPARATED_NORTH_AMERICAN_PHONE.search(_security_text_view(decoded)):
        raise ManagerResearchValidationError(
            f"{path}: sensitive private information is not permitted "
            "(North American phone number)"
        )


def _validate_evidence_source_urls(document: Mapping[str, Any]) -> None:
    for index, evidence in enumerate(document.get("evidence", ())):
        if not isinstance(evidence, Mapping):
            continue
        source_url = evidence.get("source_url")
        if isinstance(source_url, str):
            validate_public_professional_source_url(
                source_url, f"$.evidence[{index}].source_url"
            )


def _require_canonical_identifier(value: Any, path: str) -> None:
    if isinstance(value, str) and (
        unicodedata.normalize("NFKC", value) != value
        or any(
            unicodedata.category(character)[0] in {"C", "M", "Z"} for character in value
        )
    ):
        raise ManagerResearchValidationError(
            f"{path}: identifier must not contain invisible, combining, "
            "spacing, or compatibility characters"
        )


def _validate_identifier_text(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = _child_path(path, key)
            if isinstance(key, str) and (key.endswith("_id") or key == "name"):
                _require_canonical_identifier(child, child_path)
            elif (
                isinstance(key, str)
                and key.endswith("_ids")
                and isinstance(child, Sequence)
                and not isinstance(child, (str, bytes, bytearray))
            ):
                for index, identifier in enumerate(child):
                    _require_canonical_identifier(
                        identifier, _child_path(child_path, index)
                    )
            _validate_identifier_text(child, child_path)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _validate_identifier_text(child, _child_path(path, index))


def _validate_evidence_references(
    value: Any,
    evidence_ids: set[str],
    path: str = "$",
) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = _child_path(path, key)
            if key == "evidence_ids" and isinstance(child, Sequence):
                if len(child) != len(set(child)):
                    raise ManagerResearchValidationError(
                        f"{child_path}: evidence references must be unique"
                    )
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
    assessment = document.get("compliance_assessment")
    assessment_references = (
        assessment.get("evidence_ids", ()) if isinstance(assessment, Mapping) else ()
    )
    evidence_supports = {
        evidence.get("evidence_id"): set(evidence.get("supports_components", ()))
        for evidence in document.get("evidence", ())
        if isinstance(evidence, Mapping)
        and isinstance(evidence.get("evidence_id"), str)
        and isinstance(evidence.get("supports_components"), list)
    }
    structured_references = {
        reference
        for reference in assessment_references
        if isinstance(reference, str)
        and reference in references
        and "compliance_integrity" in evidence_supports.get(reference, set())
    }
    has_qualifying_evidence = any(
        evidence_tiers.get(reference, set()) & {"A", "B", "C"}
        for reference in structured_references
    )
    if not has_qualifying_evidence:
        raise ManagerResearchValidationError(
            "$.score_components.compliance_integrity.evidence_ids: "
            "a numeric score or high confidence requires at least one Tier A, B, or C evidence reference"
        )


def _validate_unique_entity_ids(document: Mapping[str, Any]) -> None:
    for collection, field in (
        ("evidence", "evidence_id"),
        ("compliance_events", "event_id"),
        ("performance_evidence", "observation_id"),
    ):
        seen: set[str] = set()
        for index, item in enumerate(document.get(collection, ())):
            if not isinstance(item, Mapping):
                continue
            value = item.get(field)
            if not isinstance(value, str):
                continue
            if value in seen:
                raise ManagerResearchValidationError(
                    f"$.{collection}[{index}].{field}: identifiers must be unique"
                )
            seen.add(value)

    factor_evidence_tenures: dict[str, str] = {}
    factor_signature_tenures: dict[tuple[object, ...], str] = {}
    for index, item in enumerate(document.get("performance_evidence", ())):
        factor_residual = (
            item.get("factor_residual") if isinstance(item, Mapping) else None
        )
        if (
            not isinstance(item, Mapping)
            or isinstance(factor_residual, bool)
            or not isinstance(factor_residual, (int, float))
        ):
            continue
        tenure_id = item.get("tenure_id")
        if not isinstance(tenure_id, str):
            continue
        signature = (
            item.get("window_start"),
            item.get("window_end"),
            item.get("metric_id"),
            factor_residual,
        )
        prior_signature_tenure = factor_signature_tenures.get(signature)
        if prior_signature_tenure is not None and prior_signature_tenure != tenure_id:
            raise ManagerResearchValidationError(
                f"$.performance_evidence[{index}]: factor-residual observation cannot be duplicated across tenures"
            )
        factor_signature_tenures[signature] = tenure_id
        evidence_ids = item.get("evidence_ids")
        if not isinstance(evidence_ids, Sequence) or isinstance(
            evidence_ids, (str, bytes, bytearray)
        ):
            continue
        for evidence_id in evidence_ids:
            if not isinstance(evidence_id, str):
                continue
            prior_tenure = factor_evidence_tenures.get(evidence_id)
            if prior_tenure is not None and prior_tenure != tenure_id:
                raise ManagerResearchValidationError(
                    f"$.performance_evidence[{index}].evidence_ids: factor-residual evidence cannot be reused across tenures"
                )
            factor_evidence_tenures[evidence_id] = tenure_id


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
    evidence_times: dict[str, tuple[datetime, datetime]] = {}
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
        evidence_id = evidence.get("evidence_id")
        if isinstance(evidence_id, str):
            evidence_times[evidence_id] = (published_at, fetched_at)

    compliance = document.get("compliance_assessment")
    if isinstance(compliance, Mapping) and any(
        value not in (None, [], {}) for value in compliance.values()
    ):
        reviewed_at = _timestamp(
            compliance.get("reviewed_at"),
            path="$.compliance_assessment.reviewed_at",
        )
        if reviewed_at > as_of:
            raise ManagerResearchValidationError(
                "$.compliance_assessment.reviewed_at: review cannot be after record as_of"
            )
        for evidence_id in compliance.get("evidence_ids", ()):
            evidence_time = evidence_times.get(evidence_id)
            if evidence_time is None:
                continue
            published_at, fetched_at = evidence_time
            if published_at > reviewed_at or fetched_at > reviewed_at:
                raise ManagerResearchValidationError(
                    "$.compliance_assessment.reviewed_at: assessment cannot use evidence learned later"
                )


def _validate_performance_windows(document: Mapping[str, Any]) -> None:
    as_of_date = (
        _timestamp(document.get("as_of"), path="$.as_of").astimezone(UTC).date()
    )
    tenures: dict[str, tuple[date, date, date]] = {}
    strategy_windows: dict[str, list[tuple[date, date]]] = {}
    for index, tenure in enumerate(document.get("tenures", ())):
        if not isinstance(tenure, Mapping):
            continue
        base = f"$.tenures[{index}]"
        tenure_id = tenure.get("tenure_id")
        if not isinstance(tenure_id, str):
            continue
        if tenure_id in tenures:
            raise ManagerResearchValidationError(
                f"{base}.tenure_id: tenure identifiers must be unique"
            )
        start = _date_value(tenure.get("start_date"), path=f"{base}.start_date")
        end_value = tenure.get("end_date")
        end = (
            as_of_date
            if end_value is None
            else _date_value(end_value, path=f"{base}.end_date")
        )
        strategy_id = tenure.get("fund_strategy_id")
        if isinstance(strategy_id, str):
            windows = strategy_windows.setdefault(strategy_id, [])
            if any(
                start <= other_end and other_start <= end
                for other_start, other_end in windows
            ):
                raise ManagerResearchValidationError(
                    f"{base}.start_date: tenures for one strategy cannot overlap"
                )
            windows.append((start, end))
        transition_days = tenure.get("transition_window_days", 0)
        if (
            type(transition_days) is not int
            or transition_days < 0
            or transition_days > 3_650
        ):
            raise ManagerResearchValidationError(
                f"{base}.transition_window_days: transition window must be a bounded non-negative integer"
            )
        earliest = start + timedelta(days=transition_days)
        if earliest > end:
            raise ManagerResearchValidationError(
                f"{base}.transition_window_days: transition window cannot consume the tenure"
            )
        tenures[tenure_id] = (start, earliest, end)

    metric_windows: dict[tuple[str, str], list[tuple[date, date]]] = {}
    for index, item in enumerate(document.get("performance_evidence", ())):
        if not isinstance(item, Mapping):
            continue
        base = f"$.performance_evidence[{index}]"
        tenure_id = item.get("tenure_id")
        if not isinstance(tenure_id, str):
            raise ManagerResearchValidationError(
                f"{base}.tenure_id: performance evidence must reference a defined tenure"
            )
        tenure = tenures.get(tenure_id)
        if tenure is None:
            raise ManagerResearchValidationError(
                f"{base}.tenure_id: performance evidence must reference a defined tenure"
            )
        tenure_start, earliest_attributed, tenure_end = tenure
        window_start = _date_value(
            item.get("window_start"), path=f"{base}.window_start"
        )
        window_end = _date_value(item.get("window_end"), path=f"{base}.window_end")
        metric_id = item.get("metric_id")
        if isinstance(metric_id, str):
            windows = metric_windows.setdefault((tenure_id, metric_id), [])
            if any(
                window_start <= other_end and other_start <= window_end
                for other_start, other_end in windows
            ):
                raise ManagerResearchValidationError(
                    f"{base}.window_start: duplicate metric windows cannot overlap"
                )
            windows.append((window_start, window_end))
        if window_start < tenure_start:
            raise ManagerResearchValidationError(
                f"{base}.window_start: performance begins before the exact tenure"
            )
        if window_start < earliest_attributed and item.get("confidence") not in {
            "low",
            "insufficient",
        }:
            raise ManagerResearchValidationError(
                f"{base}.window_start: transition evidence cannot have high or medium confidence"
            )
        if window_end > tenure_end:
            raise ManagerResearchValidationError(
                f"{base}.window_end: performance extends beyond the exact tenure"
            )


def _validate_attribution(document: Mapping[str, Any]) -> None:
    manager_id = document.get("manager_id")
    for index, tenure in enumerate(document.get("tenures", ())):
        if not isinstance(tenure, Mapping):
            continue
        base = f"$.tenures[{index}]"
        co_managers = tenure.get("co_manager_ids", ())
        if not isinstance(co_managers, list):
            continue
        if len(set(co_managers)) != len(co_managers) or manager_id in co_managers:
            raise ManagerResearchValidationError(
                f"{base}.co_manager_ids: co-manager identities must be unique and exclude the subject"
            )
        mode = tenure.get("attribution_mode")
        role = tenure.get("role")
        share = tenure.get("attribution_share")
        if mode == "individual" and (role != "lead" or co_managers):
            raise ManagerResearchValidationError(
                f"{base}.attribution_mode: individual credit requires a sole lead tenure"
            )
        if mode == "team" and not co_managers:
            raise ManagerResearchValidationError(
                f"{base}.co_manager_ids: team attribution requires at least one co-manager"
            )
        if mode == "role_weighted":
            if (
                not co_managers
                or isinstance(share, bool)
                or not isinstance(share, (int, float))
            ):
                raise ManagerResearchValidationError(
                    f"{base}.attribution_share: role-weighted credit requires co-managers and an explicit share"
                )
            if not 0 < share < 1:
                raise ManagerResearchValidationError(
                    f"{base}.attribution_share: role-weighted share must be strictly between zero and one"
                )
        elif share is not None:
            raise ManagerResearchValidationError(
                f"{base}.attribution_share: only role-weighted attribution accepts a share"
            )


def _performance_observation_is_usable(item: Mapping[str, Any]) -> bool:
    value = item.get("value")
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and item.get("confidence") != "insufficient"
    )


def _tenure_attribution(document: Mapping[str, Any]) -> dict[str, Any]:
    component = document.get("score_components", {}).get(
        "tenure_attributed_performance", {}
    )
    if not isinstance(component, Mapping) or component.get("score") is None:
        return {"aggregate_factor": None, "tenures": [], "observations": []}
    references = set(component.get("evidence_ids", ()))
    evidence_supports = {
        evidence.get("evidence_id"): set(evidence.get("supports_components", ()))
        for evidence in document.get("evidence", ())
        if isinstance(evidence, Mapping)
        and isinstance(evidence.get("evidence_id"), str)
        and isinstance(evidence.get("supports_components"), list)
    }
    tenure_ids: list[str] = []
    observations: list[dict[str, Any]] = []
    for item in document.get("performance_evidence", ()):
        if not isinstance(item, Mapping):
            continue
        evidence_ids = item.get("evidence_ids", ())
        tenure_id = item.get("tenure_id")
        qualified_evidence_ids = [
            evidence_id
            for evidence_id in evidence_ids
            if evidence_id in references
            and "tenure_attributed_performance"
            in evidence_supports.get(evidence_id, set())
        ]
        if (
            isinstance(tenure_id, str)
            and isinstance(item.get("factor_residual"), (int, float))
            and not isinstance(item.get("factor_residual"), bool)
            and isinstance(evidence_ids, Sequence)
            and not isinstance(evidence_ids, (str, bytes, bytearray))
            and qualified_evidence_ids
            and _performance_observation_is_usable(item)
        ):
            if tenure_id not in tenure_ids:
                tenure_ids.append(tenure_id)
            observations.append(
                {
                    "observation_id": item.get("observation_id"),
                    "tenure_id": tenure_id,
                    "metric_id": item.get("metric_id"),
                    "window_start": item.get("window_start"),
                    "window_end": item.get("window_end"),
                    "evidence_ids": qualified_evidence_ids,
                }
            )

    tenures = {
        tenure.get("tenure_id"): tenure
        for tenure in document.get("tenures", ())
        if isinstance(tenure, Mapping) and isinstance(tenure.get("tenure_id"), str)
    }
    details: list[dict[str, Any]] = []
    for tenure_id in tenure_ids:
        tenure = tenures[tenure_id]
        mode = tenure.get("attribution_mode")
        if mode == "individual":
            factor = 1.0
        elif mode == "role_weighted":
            factor = float(tenure["attribution_share"])
        elif mode == "team":
            factor = round(1 / (1 + len(tenure.get("co_manager_ids", ()))), 6)
        else:
            raise ManagerResearchValidationError(
                "$.score_components.tenure_attributed_performance: unresolved tenure attribution cannot receive a numeric score"
            )
        details.append(
            {
                "tenure_id": tenure_id,
                "mode": mode,
                "factor": factor,
                "co_manager_ids": list(tenure.get("co_manager_ids", ())),
            }
        )
    if not details:
        raise ManagerResearchValidationError(
            "$.score_components.tenure_attributed_performance: no attributable tenure evidence"
        )
    aggregate = round(
        sum(detail["factor"] for detail in details) / len(details),
        6,
    )
    return {
        "aggregate_factor": aggregate,
        "tenures": details,
        "observations": observations,
    }


def _has_substantive_value(value: object) -> bool:
    if isinstance(value, str):
        return any(
            unicodedata.category(character)[0] in {"L", "N"} for character in value
        )
    return value not in (None, {}, [])


def _validate_style_and_workload_evidence(document: Mapping[str, Any]) -> None:
    for section_name in ("style_fingerprint", "workload"):
        section = document.get(section_name)
        if not isinstance(section, Mapping):
            continue
        has_research = any(
            key != "evidence_ids" and _has_substantive_value(value)
            for key, value in section.items()
        )
        evidence_ids = section.get("evidence_ids")
        if has_research and (
            not isinstance(evidence_ids, Sequence)
            or isinstance(evidence_ids, (str, bytes, bytearray))
            or not evidence_ids
        ):
            raise ManagerResearchValidationError(
                f"$.{section_name}.evidence_ids: researched values require evidence"
            )

    workload = document.get("workload")
    if not isinstance(workload, Mapping):
        return
    aum = workload.get("assets_under_management")
    currency = workload.get("aum_currency")
    if (aum is None) != (currency is None):
        raise ManagerResearchValidationError(
            "$.workload.aum_currency: AUM value and currency must be supplied together"
        )
    if currency is not None and (
        not isinstance(currency, str) or re.fullmatch(r"[A-Z]{3}", currency) is None
    ):
        raise ManagerResearchValidationError(
            "$.workload.aum_currency: currency must be a three-letter uppercase code"
        )


def _validate_style_chronology(document: Mapping[str, Any]) -> None:
    style = document.get("style_fingerprint")
    if not isinstance(style, Mapping):
        return
    record_as_of = _timestamp(document.get("as_of"), path="$.as_of")
    evidence_times: dict[str, tuple[datetime, datetime]] = {}
    for index, evidence in enumerate(document.get("evidence", ())):
        if not isinstance(evidence, Mapping) or not isinstance(
            evidence.get("evidence_id"), str
        ):
            continue
        evidence_times[evidence["evidence_id"]] = (
            _timestamp(
                evidence.get("published_at"),
                path=f"$.evidence[{index}].published_at",
            ),
            _timestamp(
                evidence.get("fetched_at"),
                path=f"$.evidence[{index}].fetched_at",
            ),
        )
    style_evidence_ids = style.get("evidence_ids", ())
    for section_name, snapshot in style.items():
        if section_name in {"change_points", "evidence_ids"} or not isinstance(
            snapshot, Mapping
        ):
            continue
        base = f"$.style_fingerprint.{section_name}"
        snapshot_as_of = _timestamp(snapshot.get("as_of"), path=f"{base}.as_of")
        if snapshot_as_of > record_as_of:
            raise ManagerResearchValidationError(
                f"{base}.as_of: style snapshot cannot be after record as_of"
            )
        for evidence_id in style_evidence_ids:
            evidence_time = evidence_times.get(evidence_id)
            if evidence_time is None:
                continue
            published_at, fetched_at = evidence_time
            if published_at > snapshot_as_of or fetched_at > snapshot_as_of:
                raise ManagerResearchValidationError(
                    f"{base}.as_of: style snapshot cannot use future evidence"
                )
        names: list[str] = []
        for measure in snapshot.get("measures", ()):
            if isinstance(measure, Mapping) and isinstance(measure.get("name"), str):
                names.append(measure["name"])
        if len(names) != len(set(names)):
            raise ManagerResearchValidationError(
                f"{base}.measures: measure names must be unique"
            )

    as_of_date = record_as_of.astimezone(UTC).date()
    for index, change_point in enumerate(style.get("change_points", ())):
        if not isinstance(change_point, Mapping):
            continue
        base = f"$.style_fingerprint.change_points[{index}]"
        effective_path = f"{base}.effective_date"
        if (
            _date_value(change_point.get("effective_date"), path=effective_path)
            > as_of_date
        ):
            raise ManagerResearchValidationError(
                f"{effective_path}: change point cannot be after record as_of"
            )
        known_at = _timestamp(change_point.get("known_at"), path=f"{base}.known_at")
        if known_at > record_as_of:
            raise ManagerResearchValidationError(
                f"{base}.known_at: knowledge time cannot be after record as_of"
            )
        for evidence_id in change_point.get("evidence_ids", ()):
            evidence_time = evidence_times.get(evidence_id)
            if evidence_time is None:
                continue
            published_at, fetched_at = evidence_time
            if published_at > known_at or fetched_at > known_at:
                raise ManagerResearchValidationError(
                    f"{base}.known_at: change point cannot use evidence learned later"
                )


def _validate_scored_domain_evidence(document: Mapping[str, Any]) -> None:
    score_components = document.get("score_components")
    if not isinstance(score_components, Mapping):
        return
    performance = tuple(
        item
        for item in document.get("performance_evidence", ())
        if isinstance(item, Mapping)
    )
    evidence_supports: dict[str, set[str]] = {}
    for item in document.get("evidence", ()):
        if not isinstance(item, Mapping):
            continue
        evidence_id = item.get("evidence_id")
        supports = item.get("supports_components")
        if (
            isinstance(evidence_id, str)
            and isinstance(supports, Sequence)
            and not isinstance(supports, (str, bytes, bytearray))
        ):
            evidence_supports[evidence_id] = {
                component_id
                for component_id in supports
                if isinstance(component_id, str)
            }

    def component(component_id: str) -> Mapping[str, Any] | None:
        value = score_components.get(component_id)
        return value if isinstance(value, Mapping) else None

    def is_scored(component_id: str) -> bool:
        value = component(component_id)
        return value is not None and value.get("score") is not None

    def component_evidence_ids(component_id: str) -> set[str]:
        value = component(component_id)
        if value is None:
            return set()
        references = value.get("evidence_ids")
        if not isinstance(references, Sequence) or isinstance(
            references, (str, bytes, bytearray)
        ):
            return set()
        return {reference for reference in references if isinstance(reference, str)}

    def qualified_evidence_ids(
        evidence_ids: object,
        component_id: str,
    ) -> set[str]:
        if not isinstance(evidence_ids, Sequence) or isinstance(
            evidence_ids, (str, bytes, bytearray)
        ):
            return set()
        references = component_evidence_ids(component_id)
        return {
            evidence_id
            for evidence_id in evidence_ids
            if isinstance(evidence_id, str)
            and evidence_id in references
            and component_id in evidence_supports.get(evidence_id, set())
        }

    def item_matches_component(item: Mapping[str, Any], component_id: str) -> bool:
        return bool(qualified_evidence_ids(item.get("evidence_ids"), component_id))

    for component_id in score_components:
        if not isinstance(component_id, str) or not is_scored(component_id):
            continue
        references = component_evidence_ids(component_id)
        if not any(
            component_id in evidence_supports.get(reference, set())
            for reference in references
        ):
            raise ManagerResearchValidationError(
                f"$.score_components.{component_id}.evidence_ids: scored component requires semantically matched evidence"
            )

    if is_scored("tenure_attributed_performance") and not any(
        isinstance(item.get("factor_residual"), (int, float))
        and not isinstance(item.get("factor_residual"), bool)
        and _performance_observation_is_usable(item)
        and item_matches_component(item, "tenure_attributed_performance")
        for item in performance
    ):
        raise ManagerResearchValidationError(
            "$.score_components.tenure_attributed_performance: scored attribution requires cited factor-residual evidence"
        )

    downside_metrics = {
        "max_drawdown",
        "expected_shortfall",
        "downside_capture",
        "recovery_time",
    }
    if is_scored("downside_control") and not any(
        item.get("metric_id") in downside_metrics
        and _performance_observation_is_usable(item)
        and item_matches_component(item, "downside_control")
        for item in performance
    ):
        raise ManagerResearchValidationError(
            "$.score_components.downside_control: scored downside control requires cited downside evidence"
        )

    regime_windows = [
        (
            regime,
            _date_value(
                item.get("window_start"), path="$.performance_evidence.window_start"
            ),
            _date_value(
                item.get("window_end"), path="$.performance_evidence.window_end"
            ),
        )
        for item in performance
        if item_matches_component(item, "cross_cycle_consistency")
        and _performance_observation_is_usable(item)
        and isinstance((regime := item.get("regime")), str)
    ]
    has_independent_regimes = any(
        first_regime != second_regime
        and (first_end < second_start or second_end < first_start)
        for first_index, (first_regime, first_start, first_end) in enumerate(
            regime_windows
        )
        for second_regime, second_start, second_end in regime_windows[first_index + 1 :]
    )
    if is_scored("cross_cycle_consistency") and not has_independent_regimes:
        raise ManagerResearchValidationError(
            "$.score_components.cross_cycle_consistency: scored consistency requires cited evidence from at least two non-overlapping regimes"
        )

    def section_has_cited_research(section_name: str, component_id: str) -> bool:
        section = document.get(section_name)
        if not isinstance(section, Mapping):
            return False
        evidence_ids = section.get("evidence_ids")
        return any(
            key != "evidence_ids" and _has_substantive_value(value)
            for key, value in section.items()
        ) and bool(qualified_evidence_ids(evidence_ids, component_id))

    def style_has_cited_research() -> bool:
        style = document.get("style_fingerprint")
        if not isinstance(style, Mapping):
            return False
        has_quantitative_snapshot = any(
            key not in {"change_points", "evidence_ids"}
            and _has_substantive_value(value)
            for key, value in style.items()
        )
        if has_quantitative_snapshot and qualified_evidence_ids(
            style.get("evidence_ids"),
            "style_discipline",
        ):
            return True
        return any(
            isinstance(change_point, Mapping)
            and bool(
                qualified_evidence_ids(
                    change_point.get("evidence_ids"),
                    "style_discipline",
                )
            )
            for change_point in style.get("change_points", ())
        )

    if is_scored("style_discipline") and not style_has_cited_research():
        raise ManagerResearchValidationError(
            "$.score_components.style_discipline: scored style discipline requires cited style evidence"
        )
    if is_scored("workload_capacity") and not section_has_cited_research(
        "workload", "workload_capacity"
    ):
        raise ManagerResearchValidationError(
            "$.score_components.workload_capacity: scored workload capacity requires cited workload evidence"
        )

    career_evidence_ids: list[str] = []
    for section_name in ("employment_history", "tenures"):
        for item in document.get(section_name, ()):
            if not isinstance(item, Mapping):
                continue
            if section_name == "employment_history" and not (
                _has_substantive_value(item.get("organisation"))
                and _has_substantive_value(item.get("role"))
            ):
                continue
            references = item.get("evidence_ids")
            if isinstance(references, Sequence) and not isinstance(
                references, (str, bytes, bytearray)
            ):
                career_evidence_ids.extend(
                    reference for reference in references if isinstance(reference, str)
                )
    if is_scored("career_track_record") and not qualified_evidence_ids(
        career_evidence_ids,
        "career_track_record",
    ):
        raise ManagerResearchValidationError(
            "$.score_components.career_track_record: scored career record requires cited employment or tenure evidence"
        )

    platform = document.get("research_platform")
    platform_has_research = isinstance(platform, Mapping) and (
        any(
            isinstance(platform.get(field), int)
            and not isinstance(platform.get(field), bool)
            for field in ("team_size", "analyst_count")
        )
        or _has_substantive_value(platform.get("decision_process"))
        or platform.get("succession_status") in {"documented", "undocumented"}
    )
    if is_scored("research_platform_team") and (
        not platform_has_research
        or not qualified_evidence_ids(
            platform.get("evidence_ids") if isinstance(platform, Mapping) else None,
            "research_platform_team",
        )
    ):
        raise ManagerResearchValidationError(
            "$.score_components.research_platform_team: scored research platform requires cited structured platform evidence"
        )

    compliance = document.get("compliance_assessment")
    compliance_status = (
        compliance.get("review_status") if isinstance(compliance, Mapping) else None
    )
    compliance_evidence = (
        compliance.get("evidence_ids") if isinstance(compliance, Mapping) else None
    )
    if is_scored("compliance_integrity") and (
        compliance_status not in {"no_verified_events", "events_reviewed"}
        or not qualified_evidence_ids(compliance_evidence, "compliance_integrity")
    ):
        raise ManagerResearchValidationError(
            "$.score_components.compliance_integrity: scored compliance requires a cited structured assessment"
        )
    if compliance_status == "events_reviewed" and not document.get("compliance_events"):
        raise ManagerResearchValidationError(
            "$.compliance_assessment.review_status: events_reviewed requires at least one compliance event"
        )
    if compliance_status == "no_verified_events" and any(
        isinstance(event, Mapping) and event.get("status") == "final_verified"
        for event in document.get("compliance_events", ())
    ):
        raise ManagerResearchValidationError(
            "$.compliance_assessment.review_status: no_verified_events conflicts with a final verified event"
        )


def validate_manager_research(document: Mapping[str, Any]) -> None:
    """Validate manager-research semantics beyond the JSON Schema contract."""
    _validate_text(document)
    _validate_identifier_text(document)
    _validate_evidence_source_urls(document)
    _validate_unique_entity_ids(document)
    _validate_manager_chronology(document)
    _validate_performance_windows(document)
    _validate_attribution(document)
    _validate_style_and_workload_evidence(document)
    _validate_style_chronology(document)
    _validate_scored_domain_evidence(document)
    _tenure_attribution(document)
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


def _canonical_manager_snapshot(document: Mapping[str, Any]) -> dict[str, Any]:
    """Rebuild untrusted JSON containers before validation and scoring."""
    active: set[int] = set()
    nodes = 0

    def copy_value(value: object, *, depth: int) -> object:
        nonlocal nodes
        nodes += 1
        if nodes > 10_000 or depth > 512:
            raise ManagerResearchValidationError(
                "manager research exceeds the canonical snapshot limit"
            )
        value_type = type(value)
        if value is None or value_type is bool:
            return value
        if isinstance(value, str):
            return str.__str__(value)
        if isinstance(value, int) and not isinstance(value, bool):
            return int.__int__(value)
        if isinstance(value, float):
            return float.__float__(value)
        if isinstance(value, dict):
            identity = id(value)
            if identity in active:
                raise ManagerResearchValidationError(
                    "manager research must be a finite JSON data structure"
                )
            active.add(identity)
            try:
                copied: dict[str, object] = {}
                for raw_key, raw_child in dict.items(value):
                    if not isinstance(raw_key, str):
                        raise ManagerResearchValidationError(
                            "manager research object keys must be strings"
                        )
                    key = str.__str__(raw_key)
                    if key in copied:
                        raise ManagerResearchValidationError(
                            "manager research object keys must be unique"
                        )
                    copied[key] = copy_value(raw_child, depth=depth + 1)
                return copied
            finally:
                active.remove(identity)
        if isinstance(value, list):
            identity = id(value)
            if identity in active:
                raise ManagerResearchValidationError(
                    "manager research must be a finite JSON data structure"
                )
            active.add(identity)
            try:
                return [
                    copy_value(child, depth=depth + 1) for child in list.__iter__(value)
                ]
            finally:
                active.remove(identity)
        raise ManagerResearchValidationError(
            "manager research must contain only JSON data"
        )

    try:
        snapshot = copy_value(document, depth=0)
    except ManagerResearchValidationError:
        raise
    except Exception:  # noqa: BLE001 - hostile container boundary
        raise ManagerResearchValidationError(
            "manager research could not be safely canonicalized"
        ) from None
    if type(snapshot) is not dict:
        raise ManagerResearchValidationError("manager research must be an object")
    return snapshot


def score_manager_research(document: Mapping[str, Any]) -> dict[str, Any]:
    """Return an auditable weighted manager score or explicit insufficiency."""
    from .resources import resolve_resource
    from .score_config import validate_score_config
    from .validation import validate_record

    snapshot = _canonical_manager_snapshot(document)
    validate_record(
        "manager_research",
        snapshot,
        schema_version="0.1.0",
    )
    try:
        config = resolve_resource(
            resource_type="scoring-config",
            name="openfundscore-core",
            version="0.1.0",
        ).load_json()
        validate_score_config(config)
        manager_model = config["manager_model"]
        configured_components = manager_model["components"]
        model_version = config["model_version"]
    except Exception as exc:
        if exc.__class__.__module__ == "openfundscore.validation":
            raise
        raise ManagerResearchValidationError(
            "manager scoring configuration is unavailable"
        ) from None

    components = snapshot["score_components"]
    tenure_attribution = _tenure_attribution(snapshot)
    contributions: dict[str, float | None] = {}
    component_evidence_ids: dict[str, list[str]] = {}
    weights: dict[str, int] = {}
    insufficient: list[str] = []
    confidence_rank = {"high": 0, "medium": 1, "low": 2, "insufficient": 3}
    overall_confidence = "high"

    for configured in configured_components:
        component_id = configured["id"]
        weight = configured["weight"]
        component = components[component_id]
        score = component["score"]
        confidence = component["confidence"]
        component_evidence_ids[component_id] = list(component["evidence_ids"])
        weights[component_id] = weight
        if confidence_rank[confidence] > confidence_rank[overall_confidence]:
            overall_confidence = confidence
        if score is None or confidence == "insufficient":
            insufficient.append(component_id)
            contributions[component_id] = None
        else:
            effective_score = float(score)
            if component_id == "tenure_attributed_performance":
                effective_score *= tenure_attribution["aggregate_factor"]
            contributions[component_id] = round(effective_score * weight / 100, 6)

    result_score = (
        None
        if insufficient
        else round(
            sum(value for value in contributions.values() if value is not None), 6
        )
    )
    return {
        "manager_id": snapshot["manager_id"],
        "as_of": snapshot["as_of"],
        "model_version": model_version,
        "status": "insufficient" if insufficient else "scored",
        "score": result_score,
        "confidence": "insufficient" if insufficient else overall_confidence,
        "component_weights": weights,
        "component_contributions": contributions,
        "component_evidence_ids": component_evidence_ids,
        "tenure_attribution": tenure_attribution,
        "insufficient_components": insufficient,
    }
