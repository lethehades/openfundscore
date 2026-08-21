"""Unified fail-closed validation for OpenFundScore contract records."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, NoReturn, cast

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from .contract_semantics import (
    ContractValidationError,
    validate_external_rating_semantics,
    validate_provider_contract_semantics,
)
from .evidence_usage import (
    MAX_USAGE_ITEMS,
    EvidenceUsageValidationError,
    validate_score_evidence_usage,
)
from .manager_research import ManagerResearchValidationError, validate_manager_research
from .provider_semantics import (
    ProviderRecordValidationError,
    validate_provider_record_semantics,
)
from .resources import ResourceError, resolve_resource

MAX_PROVIDER_VALUE_ITEMS = 10_000
MAX_JSON_NODES = 10_000
MAX_JSON_CONTAINER_ITEMS = 10_000


class RecordType(StrEnum):
    """Versioned contract-record types accepted by the validation boundary."""

    EXTERNAL_RATING = "external_rating"
    MANAGER_RESEARCH = "manager_research"
    PROVIDER_CONTRACT = "provider_contract"
    PROVIDER_RECORD = "provider_record"
    SCORE_EVIDENCE_USAGE = "score_evidence_usage"


class RecordValidationError(ValueError):
    """Stable, path-aware failure from schema or semantic validation."""

    def __init__(
        self,
        *,
        record_type: str,
        schema_version: str,
        stage: str,
        code: str,
        path: str,
        message: str,
    ) -> None:
        self.record_type = record_type
        self.schema_version = schema_version
        self.stage = stage
        self.code = code
        self.path = path
        super().__init__(f"{stage} {code} at {path}: {message}")


_PATH = re.compile(
    r'^\$(?:\.[A-Za-z_][A-Za-z0-9_]*|\[[0-9]+\]|\["(?:[^"\\]|\\.)*"\])*$'
)


def _child_path(path: str, part: object) -> str:
    if isinstance(part, int):
        return f"{path}[{part}]"
    if isinstance(part, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part):
        return f"{path}.{part}"
    return path


def _schema_error_path(error: Any) -> str:
    path = "$"
    for part in error.absolute_path:
        path = _child_path(path, part)
    if error.validator == "required" and isinstance(error.instance, Mapping):
        for field in error.validator_value:
            if field not in error.instance:
                return _child_path(path, field)
    return path


def _first_schema_error(validator: Any, document: object) -> Any | None:
    return next(validator.iter_errors(cast(Any, document)), None)


def _semantic_path(error: ValueError) -> str:
    message = str(error)
    candidate = message.split(": ", 1)[0]
    if _PATH.fullmatch(candidate) is not None:
        return candidate
    usage = re.search(r"usage\[([0-9]+)\](?:\.([A-Za-z_][A-Za-z0-9_]*))?", message)
    if usage is not None:
        path = f"$.usage[{usage.group(1)}]"
        if usage.group(2) is not None:
            path += f".{usage.group(2)}"
        return path
    return "$"


_FORMAT_SENTINELS = {
    "date": "not-a-date",
    "date-time": "not-a-date-time",
    "uri": "not a uri",
}


def _format_checker(
    record_type: RecordType,
    *,
    schema_version: str,
) -> FormatChecker:
    checker = FormatChecker()
    for format_name, invalid_value in _FORMAT_SENTINELS.items():
        if checker.conforms(invalid_value, format_name):
            raise RecordValidationError(
                record_type=record_type.value,
                schema_version=schema_version,
                stage="schema",
                code="format_checker_unavailable",
                path="$schema",
                message="required JSON Schema format checking is unavailable",
            )
    return checker


def _validate_json_data(
    record_type: RecordType,
    document: object,
    *,
    schema_version: str,
) -> object:
    active_containers: set[int] = set()
    visited_nodes = 0

    def reject(*, path: str, code: str = "non_json_value") -> NoReturn:
        raise RecordValidationError(
            record_type=record_type.value,
            schema_version=schema_version,
            stage="document" if code == "record_too_complex" else "schema",
            code=code,
            path=path,
            message=(
                "record exceeds the validation complexity limit"
                if code == "record_too_complex"
                else "record must be a finite JSON data structure"
            ),
        )

    def copy_value(value: object, *, path: str, depth: int) -> object:
        nonlocal visited_nodes
        visited_nodes += 1
        if visited_nodes > MAX_JSON_NODES:
            reject(path=path, code="record_too_complex")
        if depth > 512:
            reject(path=path)
        if value is None:
            return None
        if isinstance(value, str):
            return str.__str__(value)
        if type(value) is bool:
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            return int.__int__(value)
        if isinstance(value, float):
            normalized_float = float.__float__(value)
            if math.isfinite(normalized_float):
                return normalized_float
            reject(path=path)
        if isinstance(value, dict):
            identity = id(value)
            if identity in active_containers:
                reject(path=path)
            pairs: tuple[tuple[object, object], ...] | None = None
            size = MAX_JSON_CONTAINER_ITEMS + 1
            try:
                size = dict.__len__(value)
                if size <= MAX_JSON_CONTAINER_ITEMS:
                    pairs = tuple(dict.items(value))
            except Exception:  # noqa: BLE001 - mapping subclasses are untrusted
                pairs = None
            if pairs is None or size > MAX_JSON_CONTAINER_ITEMS:
                reject(path=path, code="record_too_complex")
            active_containers.add(identity)
            result: dict[str, object] = {}
            try:
                for raw_key, child in pairs:
                    if not isinstance(raw_key, str):
                        reject(path=path)
                    key = str.__str__(raw_key)
                    if key in result:
                        reject(path=path)
                    result[key] = copy_value(
                        child,
                        path=_child_path(path, key),
                        depth=depth + 1,
                    )
            finally:
                active_containers.discard(identity)
            return result
        if isinstance(value, list):
            identity = id(value)
            if identity in active_containers:
                reject(path=path)
            children: tuple[object, ...] | None = None
            size = MAX_JSON_CONTAINER_ITEMS + 1
            try:
                size = list.__len__(value)
                if size <= MAX_JSON_CONTAINER_ITEMS:
                    children = tuple(
                        list.__getitem__(value, index) for index in range(size)
                    )
            except Exception:  # noqa: BLE001 - list subclasses are untrusted
                children = None
            if children is None or size > MAX_JSON_CONTAINER_ITEMS:
                reject(path=path, code="record_too_complex")
            active_containers.add(identity)
            try:
                return [
                    copy_value(
                        child,
                        path=_child_path(path, index),
                        depth=depth + 1,
                    )
                    for index, child in enumerate(children)
                ]
            finally:
                active_containers.discard(identity)
        reject(path=path)
        raise AssertionError("unreachable")

    try:
        return copy_value(document, path="$", depth=0)
    except RecursionError:
        raise RecordValidationError(
            record_type=record_type.value,
            schema_version=schema_version,
            stage="schema",
            code="non_json_value",
            path="$",
            message="record must be a finite JSON data structure",
        ) from None


def _validate_record_complexity(
    record_type: RecordType,
    document: object,
    *,
    schema_version: str,
) -> None:
    if record_type is RecordType.PROVIDER_RECORD and isinstance(document, Mapping):
        value = document.get("value")
        if isinstance(value, (dict, list)) and len(value) > MAX_PROVIDER_VALUE_ITEMS:
            raise RecordValidationError(
                record_type=record_type.value,
                schema_version=schema_version,
                stage="document",
                code="record_too_complex",
                path="$.value",
                message="record exceeds the validation complexity limit",
            )
        return
    if record_type is not RecordType.SCORE_EVIDENCE_USAGE:
        return
    if not isinstance(document, Mapping):
        return
    usage = document.get("usage")
    if isinstance(usage, list) and len(usage) > MAX_USAGE_ITEMS:
        raise RecordValidationError(
            record_type=record_type.value,
            schema_version=schema_version,
            stage="document",
            code="record_too_complex",
            path="$.usage",
            message="record exceeds the validation complexity limit",
        )


def _validate_schema(
    record_type: RecordType,
    document: object,
    *,
    schema_version: str,
) -> None:
    resource_error: ResourceError | None = None
    schema: dict[str, Any] | None = None
    try:
        schema = resolve_resource(
            resource_type="schema",
            name=record_type.value,
            version=schema_version,
        ).load_json()
    except ResourceError as exc:
        resource_error = exc
    if resource_error is not None or schema is None:
        raise RecordValidationError(
            record_type=record_type.value,
            schema_version=schema_version,
            stage="schema",
            code="schema_unavailable",
            path="$schema",
            message="the selected packaged schema is unavailable",
        )
    schema_error: BaseException | None = None
    try:
        Draft202012Validator.check_schema(schema)
    except (SchemaError, RecursionError) as exc:
        schema_error = exc
    if schema_error is not None:
        raise RecordValidationError(
            record_type=record_type.value,
            schema_version=schema_version,
            stage="schema",
            code="schema_unavailable",
            path="$schema",
            message="the selected packaged schema is invalid",
        )

    validator = Draft202012Validator(
        schema,
        format_checker=_format_checker(
            record_type,
            schema_version=schema_version,
        ),
    )
    validation_error: BaseException | None = None
    error: Any | None = None
    try:
        error = _first_schema_error(validator, document)
    except (SchemaError, RecursionError) as exc:
        validation_error = exc
    if validation_error is not None:
        raise RecordValidationError(
            record_type=record_type.value,
            schema_version=schema_version,
            stage="schema",
            code="schema_validation_failed",
            path="$",
            message="record could not be safely validated against its schema",
        )
    if error is not None:
        raise RecordValidationError(
            record_type=record_type.value,
            schema_version=schema_version,
            stage="schema",
            code=f"schema_{error.validator}",
            path=_schema_error_path(error),
            message="record violates the packaged schema",
        )


def validate_record(
    record_type: RecordType | str,
    document: object,
    *,
    schema_version: str,
    evaluation_timestamp: str | None = None,
) -> None:
    """Run packaged JSON Schema validation and required semantic validation."""
    selected: RecordType | None = None
    try:
        selected = RecordType(record_type)
    except (TypeError, ValueError):
        pass
    if selected is None:
        raise RecordValidationError(
            record_type="unknown",
            schema_version=schema_version,
            stage="schema",
            code="invalid_record_type",
            path="$record_type",
            message="record type is unsupported",
        )
    document = _validate_json_data(
        selected,
        document,
        schema_version=schema_version,
    )
    _validate_record_complexity(selected, document, schema_version=schema_version)
    _validate_schema(selected, document, schema_version=schema_version)

    semantic_error: ValueError | None = None
    semantic_code = "semantic_violation"
    semantic_path = "$"
    if selected is RecordType.MANAGER_RESEARCH:
        try:
            validate_manager_research(cast(Mapping[str, Any], document))
        except ManagerResearchValidationError as exc:
            semantic_error = exc
            semantic_path = _semantic_path(exc)
    elif selected is RecordType.PROVIDER_RECORD:
        if evaluation_timestamp is None:
            raise RecordValidationError(
                record_type=selected.value,
                schema_version=schema_version,
                stage="semantic",
                code="missing_evaluation_timestamp",
                path="$evaluation_timestamp",
                message="provider record validation requires an evaluation timestamp",
            )
        try:
            validate_provider_record_semantics(
                document,
                evaluation_timestamp=evaluation_timestamp,
            )
        except ProviderRecordValidationError as exc:
            semantic_error = exc
            semantic_code = exc.code
            semantic_path = exc.path
    elif selected is RecordType.PROVIDER_CONTRACT:
        try:
            validate_provider_contract_semantics(document)
        except ContractValidationError as exc:
            semantic_error = exc
            semantic_code = exc.code
            semantic_path = exc.path
    elif selected is RecordType.EXTERNAL_RATING:
        if evaluation_timestamp is None:
            raise RecordValidationError(
                record_type=selected.value,
                schema_version=schema_version,
                stage="semantic",
                code="missing_evaluation_timestamp",
                path="$evaluation_timestamp",
                message="external rating validation requires an evaluation timestamp",
            )
        try:
            validate_external_rating_semantics(
                document,
                evaluation_timestamp=evaluation_timestamp,
            )
        except ContractValidationError as exc:
            semantic_error = exc
            semantic_code = exc.code
            semantic_path = exc.path
    elif selected is RecordType.SCORE_EVIDENCE_USAGE:
        try:
            validate_score_evidence_usage(cast(Mapping[str, Any], document))
        except EvidenceUsageValidationError as exc:
            semantic_error = exc
            semantic_path = _semantic_path(exc)

    if semantic_error is not None:
        raise RecordValidationError(
            record_type=selected.value,
            schema_version=schema_version,
            stage="semantic",
            code=semantic_code,
            path=semantic_path,
            message="record violates semantic validation rules",
        )
