"""Strict JSON boundary and deterministic serialization for walk-forward research."""

from __future__ import annotations

import math
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from typing import Any, cast

from .provider_semantics import ProviderRecordValidationError, parse_rfc3339_timestamp
from .walk_forward import (
    CandidateFund,
    FoldWindow,
    FutureOutcome,
    LifecycleInterval,
    PrecomputedScore,
    ScoreComponent,
    VersionedSnapshot,
    WalkForwardConfig,
    WalkForwardError,
    WalkForwardReport,
)
from .walk_forward_fixtures import synthetic_walk_forward_fixture

_SCHEMA_VERSION = "0.1.0"
_MAX_ITEMS = 100_000
_MAX_JSON_DEPTH = 64


def _fail(code: str, path: str, message: str) -> None:
    raise WalkForwardError(code=code, path=path, message=message)


def _object(value: object, path: str) -> dict[str, object]:
    if type(value) is not dict:
        _fail("invalid_type", path, "value must be a JSON object")
    return cast(dict[str, object], value)


def _array(value: object, path: str) -> list[object]:
    if type(value) is not list:
        _fail("invalid_type", path, "value must be a JSON array")
    items = cast(list[object], value)
    if len(items) > _MAX_ITEMS:
        _fail("input_too_large", path, "array exceeds the size limit")
    return items


def _timestamp(value: object, path: str) -> datetime:
    try:
        return parse_rfc3339_timestamp(value, path=path)
    except ProviderRecordValidationError:
        _fail("invalid_timestamp", path, "timestamp violates the RFC3339 profile")


def _optional_timestamp(value: object, path: str) -> datetime | None:
    return None if value is None else _timestamp(value, path)


def _exact_keys(document: dict[str, object], expected: set[str], path: str) -> None:
    if set(document) != expected:
        _fail("invalid_fields", path, "object fields do not match the contract")


def _validate_json_structure(value: object) -> None:
    stack: list[tuple[object, int]] = [(value, 0)]
    seen_containers: set[int] = set()
    node_count = 0
    while stack:
        item, depth = stack.pop()
        if depth > _MAX_JSON_DEPTH:
            _fail("json_too_deep", "$", "JSON nesting exceeds the depth limit")
        node_count += 1
        if node_count > _MAX_ITEMS:
            _fail("json_too_wide", "$", "JSON structure exceeds the node limit")
        if type(item) is dict:
            identity = id(item)
            if identity in seen_containers:
                _fail("cyclic_json", "$", "JSON structure must be acyclic")
            seen_containers.add(identity)
            mapping = cast(dict[object, object], item)
            if len(mapping) > _MAX_ITEMS:
                _fail("json_too_wide", "$", "JSON container exceeds the width limit")
            for key, child in mapping.items():
                if not isinstance(key, str):
                    _fail("invalid_json_value", "$", "JSON object keys must be strings")
                try:
                    cast(str, key).encode("utf-8", errors="strict")
                except UnicodeEncodeError:
                    _fail("invalid_unicode", "$", "JSON strings must be valid Unicode")
                stack.append((child, depth + 1))
            continue
        if type(item) is list:
            identity = id(item)
            if identity in seen_containers:
                _fail("cyclic_json", "$", "JSON structure must be acyclic")
            seen_containers.add(identity)
            sequence = cast(list[object], item)
            if len(sequence) > _MAX_ITEMS:
                _fail("json_too_wide", "$", "JSON container exceeds the width limit")
            stack.extend((child, depth + 1) for child in sequence)
            continue
        if isinstance(item, str):
            try:
                item.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                _fail("invalid_unicode", "$", "JSON strings must be valid Unicode")
        elif type(item) is float and not math.isfinite(cast(float, item)):
            _fail("invalid_json_value", "$", "JSON numbers must be finite")
        elif type(item) not in {str, int, float, bool, type(None)}:
            _fail("invalid_json_value", "$", "value is not representable as JSON")


def _lifecycle(document: object, path: str) -> LifecycleInterval:
    item = _object(document, path)
    _exact_keys(
        item,
        {
            "status",
            "effective_from",
            "effective_to",
            "published_at",
            "knowledge_at",
            "successor_strategy_id",
            "revision_id",
            "supersedes_revision_id",
        },
        path,
    )
    return LifecycleInterval(
        status=cast(str, item["status"]),
        effective_from=_timestamp(item["effective_from"], f"{path}.effective_from"),
        effective_to=_optional_timestamp(item["effective_to"], f"{path}.effective_to"),
        published_at=_timestamp(item["published_at"], f"{path}.published_at"),
        knowledge_at=_timestamp(item["knowledge_at"], f"{path}.knowledge_at"),
        successor_strategy_id=cast(str | None, item["successor_strategy_id"]),
        revision_id=cast(str, item["revision_id"]),
        supersedes_revision_id=cast(str | None, item["supersedes_revision_id"]),
    )


def _candidate(document: object, path: str) -> CandidateFund:
    item = _object(document, path)
    _exact_keys(
        item,
        {"share_class_id", "strategy_id", "inception_at", "lifecycle"},
        path,
    )
    lifecycle = _array(item["lifecycle"], f"{path}.lifecycle")
    return CandidateFund(
        share_class_id=cast(str, item["share_class_id"]),
        strategy_id=cast(str, item["strategy_id"]),
        inception_at=_timestamp(item["inception_at"], f"{path}.inception_at"),
        lifecycle=tuple(
            _lifecycle(value, f"{path}.lifecycle[{index}]")
            for index, value in enumerate(lifecycle)
        ),
    )


def _snapshot(document: object, path: str) -> VersionedSnapshot:
    item = _object(document, path)
    _exact_keys(
        item,
        {
            "snapshot_id",
            "provider_id",
            "provider_snapshot_id",
            "provider_version",
            "strategy_id",
            "domain",
            "value",
            "as_of",
            "published_at",
            "knowledge_at",
            "effective_from",
            "effective_to",
            "revision_id",
            "supersedes_revision_id",
        },
        path,
    )
    return VersionedSnapshot(
        snapshot_id=cast(str, item["snapshot_id"]),
        provider_id=cast(str, item["provider_id"]),
        provider_snapshot_id=cast(str, item["provider_snapshot_id"]),
        provider_version=cast(str, item["provider_version"]),
        strategy_id=cast(str, item["strategy_id"]),
        domain=cast(str, item["domain"]),
        value=cast(str | int | float | bool | None, item["value"]),
        as_of=_timestamp(item["as_of"], f"{path}.as_of"),
        published_at=_timestamp(item["published_at"], f"{path}.published_at"),
        knowledge_at=_timestamp(item["knowledge_at"], f"{path}.knowledge_at"),
        effective_from=_timestamp(item["effective_from"], f"{path}.effective_from"),
        effective_to=_optional_timestamp(item["effective_to"], f"{path}.effective_to"),
        revision_id=cast(str, item["revision_id"]),
        supersedes_revision_id=cast(str | None, item["supersedes_revision_id"]),
    )


def _score_component(document: object, path: str) -> ScoreComponent:
    item = _object(document, path)
    _exact_keys(item, {"name", "contribution", "component_version"}, path)
    return ScoreComponent(
        name=cast(str, item["name"]),
        contribution=cast(float | None, item["contribution"]),
        component_version=cast(str, item["component_version"]),
    )


def _score(document: object, path: str) -> PrecomputedScore:
    item = _object(document, path)
    _exact_keys(
        item,
        {
            "score_id",
            "strategy_id",
            "total_score",
            "components",
            "model_version",
            "provider_id",
            "provider_snapshot_id",
            "provider_version",
            "score_as_of",
            "published_at",
            "knowledge_at",
            "effective_from",
            "effective_to",
            "revision_id",
            "supersedes_revision_id",
        },
        path,
    )
    components = _array(item["components"], f"{path}.components")
    return PrecomputedScore(
        score_id=cast(str, item["score_id"]),
        strategy_id=cast(str, item["strategy_id"]),
        total_score=cast(float, item["total_score"]),
        components=tuple(
            _score_component(value, f"{path}.components[{index}]")
            for index, value in enumerate(components)
        ),
        model_version=cast(str, item["model_version"]),
        provider_id=cast(str, item["provider_id"]),
        provider_snapshot_id=cast(str, item["provider_snapshot_id"]),
        provider_version=cast(str, item["provider_version"]),
        score_as_of=_timestamp(item["score_as_of"], f"{path}.score_as_of"),
        published_at=_timestamp(item["published_at"], f"{path}.published_at"),
        knowledge_at=_timestamp(item["knowledge_at"], f"{path}.knowledge_at"),
        effective_from=_timestamp(item["effective_from"], f"{path}.effective_from"),
        effective_to=_optional_timestamp(item["effective_to"], f"{path}.effective_to"),
        revision_id=cast(str, item["revision_id"]),
        supersedes_revision_id=cast(str | None, item["supersedes_revision_id"]),
    )


def _outcome(document: object, path: str) -> FutureOutcome:
    item = _object(document, path)
    _exact_keys(
        item,
        {
            "outcome_id",
            "strategy_id",
            "window_start",
            "window_end",
            "period_returns",
            "peer_period_returns",
        },
        path,
    )
    period_returns = _array(item["period_returns"], f"{path}.period_returns")
    peer_returns = _array(item["peer_period_returns"], f"{path}.peer_period_returns")
    return FutureOutcome(
        outcome_id=cast(str, item["outcome_id"]),
        strategy_id=cast(str, item["strategy_id"]),
        window_start=_timestamp(item["window_start"], f"{path}.window_start"),
        window_end=_timestamp(item["window_end"], f"{path}.window_end"),
        period_returns=tuple(cast(float, value) for value in period_returns),
        peer_period_returns=tuple(cast(float, value) for value in peer_returns),
    )


def _fold(document: object, path: str) -> FoldWindow:
    item = _object(document, path)
    names = {
        "fold_id",
        "train_start",
        "train_end",
        "validation_start",
        "validation_end",
        "decision_at",
        "outcome_start",
        "outcome_end",
        "embargo_seconds",
    }
    _exact_keys(item, names, path)
    return FoldWindow(
        fold_id=cast(str, item["fold_id"]),
        train_start=_timestamp(item["train_start"], f"{path}.train_start"),
        train_end=_timestamp(item["train_end"], f"{path}.train_end"),
        validation_start=_timestamp(
            item["validation_start"], f"{path}.validation_start"
        ),
        validation_end=_timestamp(item["validation_end"], f"{path}.validation_end"),
        decision_at=_timestamp(item["decision_at"], f"{path}.decision_at"),
        outcome_start=_timestamp(item["outcome_start"], f"{path}.outcome_start"),
        outcome_end=_timestamp(item["outcome_end"], f"{path}.outcome_end"),
        embargo_seconds=cast(int, item["embargo_seconds"]),
    )


def walk_forward_from_document(
    document: object,
) -> tuple[
    WalkForwardConfig,
    tuple[CandidateFund, ...],
    tuple[VersionedSnapshot, ...],
    tuple[FutureOutcome, ...],
    tuple[PrecomputedScore, ...],
]:
    """Decode the exact versioned CLI input contract into immutable API objects."""
    _validate_json_structure(document)
    root = _object(document, "$")
    _exact_keys(
        root,
        {
            "schema_version",
            "config",
            "candidates",
            "snapshots",
            "outcomes",
            "precomputed_scores",
        },
        "$",
    )
    if root["schema_version"] != _SCHEMA_VERSION:
        _fail("unsupported_version", "$.schema_version", "schema version is unsupported")
    config_document = _object(root["config"], "$.config")
    _exact_keys(config_document, {"folds", "select_count"}, "$.config")
    folds = _array(config_document["folds"], "$.config.folds")
    candidates = _array(root["candidates"], "$.candidates")
    snapshots = _array(root["snapshots"], "$.snapshots")
    outcomes = _array(root["outcomes"], "$.outcomes")
    scores = _array(root["precomputed_scores"], "$.precomputed_scores")
    return (
        WalkForwardConfig(
            folds=tuple(
                _fold(value, f"$.config.folds[{index}]")
                for index, value in enumerate(folds)
            ),
            select_count=cast(int, config_document["select_count"]),
        ),
        tuple(
            _candidate(value, f"$.candidates[{index}]")
            for index, value in enumerate(candidates)
        ),
        tuple(
            _snapshot(value, f"$.snapshots[{index}]")
            for index, value in enumerate(snapshots)
        ),
        tuple(
            _outcome(value, f"$.outcomes[{index}]")
            for index, value in enumerate(outcomes)
        ),
        tuple(
            _score(value, f"$.precomputed_scores[{index}]")
            for index, value in enumerate(scores)
        ),
    )


def _jsonable(value: object) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if type(value) is float:
        numeric = cast(float, value)
        if not math.isfinite(numeric):
            _fail("serialization_failed", "$report", "report contains a non-finite number")
        return numeric
    if type(value) in {str, int, bool, type(None)}:
        return value
    _fail("serialization_failed", "$report", "report contains an unsupported value")


def walk_forward_input_document(
    config: WalkForwardConfig,
    candidates: tuple[CandidateFund, ...],
    snapshots: tuple[VersionedSnapshot, ...],
    outcomes: tuple[FutureOutcome, ...],
    precomputed_scores: tuple[PrecomputedScore, ...],
) -> dict[str, object]:
    """Serialize immutable API inputs to the exact CLI contract."""
    return {
        "schema_version": _SCHEMA_VERSION,
        "config": _jsonable(config),
        "candidates": _jsonable(candidates),
        "snapshots": _jsonable(snapshots),
        "outcomes": _jsonable(outcomes),
        "precomputed_scores": _jsonable(precomputed_scores),
    }


def synthetic_fixture_document() -> dict[str, object]:
    fixture = synthetic_walk_forward_fixture()
    return walk_forward_input_document(
        fixture.config,
        fixture.candidates,
        fixture.snapshots,
        fixture.outcomes,
        fixture.precomputed_scores,
    )


def walk_forward_report_document(report: WalkForwardReport) -> dict[str, object]:
    """Serialize a report with explicit metric definitions and limitations."""
    return {
        "schema_version": _SCHEMA_VERSION,
        "methodology": {
            "component_correlation": (
                "Pearson correlation using pairwise-complete component contributions"
            ),
            "future_outcome": "equal-weight selected-strategy simple returns minus matched peer returns",
            "selection_turnover": "Jaccard distance",
            "score_audit_identity": "(strategy_id, audit_id, revision_id)",
            "sensitivity": (
                "leave one additive component out without refitting or using outcomes"
            ),
            "score_stability": (
                "Spearman rank correlation on scores for overlapping eligible strategies"
            ),
            "uncertainty": "95% normal approximation for the arithmetic mean; insufficient below two observations",
            "wealth": "simple-return wealth beginning at 1.0; drawdown uses running peak including initial wealth",
        },
        "limitations": [
            "synthetic or user-supplied local research only",
            "no parameter optimization, trading, network access, live rating, or return guarantee",
            "normal-approximation intervals are descriptive and may be unreliable for small samples",
        ],
        "report": _jsonable(report),
    }
