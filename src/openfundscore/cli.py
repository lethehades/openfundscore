"""Command-line entry points for OpenFundScore."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from .ant_fortune_boundary import (
    AccessMode,
    BoundaryUse,
    BoundaryValidationError,
    decide_ant_fortune_field,
    validate_ant_fortune_boundary,
)
from .resources import (
    ResourceError,
    ResourceInfo,
    ResourceType,
    list_resources,
    resolve_resource,
)
from .score_config import (
    ConfigValidationError,
    load_score_config,
    validate_score_config,
)
from .strategy_mapping import (
    StrategyMappingError,
    load_strategy_mapping,
    map_strategy_family,
    validate_strategy_mapping,
)
from .validation import RecordType, RecordValidationError, validate_record

_MAX_RECORD_BYTES = 8 * 1024 * 1024
_MAX_BOUNDARY_BYTES = 1024 * 1024


class _DocumentFormatError(ValueError):
    pass


class _RedactedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        self.exit(
            2,
            "openfundscore: error: argument_error at $arguments: "
            "command arguments are invalid\n",
        )


def _reject_json_constant(_: str) -> object:
    raise _DocumentFormatError


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise _DocumentFormatError
        document[key] = value
    return document


def _record_error(
    *,
    record_type: str,
    schema_version: str,
    code: str,
    message: str,
) -> RecordValidationError:
    return RecordValidationError(
        record_type=record_type,
        schema_version=schema_version,
        stage="document",
        code=code,
        path="$document",
        message=message,
    )


def _load_record_document(
    path: str,
    *,
    record_type: str,
    schema_version: str,
) -> object:
    read_error: OSError | None = None
    payload: bytes | None = None
    try:
        with Path(path).open("rb") as stream:
            payload = stream.read(_MAX_RECORD_BYTES + 1)
    except OSError as exc:
        read_error = exc
    if read_error is not None or payload is None:
        raise _record_error(
            record_type=record_type,
            schema_version=schema_version,
            code="document_io",
            message="record document could not be read",
        )
    if len(payload) > _MAX_RECORD_BYTES:
        raise _record_error(
            record_type=record_type,
            schema_version=schema_version,
            code="document_too_large",
            message="record document exceeds the validation size limit",
        )

    decode_failed = False
    text: str | None = None
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        decode_failed = True
    if decode_failed or text is None:
        raise _record_error(
            record_type=record_type,
            schema_version=schema_version,
            code="document_format",
            message="record document must be strict UTF-8 JSON",
        )

    parse_failed = False
    document: object | None = None
    try:
        document = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (ValueError, RecursionError):
        parse_failed = True
    if parse_failed:
        raise _record_error(
            record_type=record_type,
            schema_version=schema_version,
            code="document_format",
            message="record document must be strict UTF-8 JSON",
        )
    return document


def _load_boundary_document(path: str) -> tuple[object, str]:
    payload: bytes | None = None
    try:
        with Path(path).open("rb") as stream:
            payload = stream.read(_MAX_BOUNDARY_BYTES + 1)
    except OSError:
        pass
    if payload is None or len(payload) > _MAX_BOUNDARY_BYTES:
        raise BoundaryValidationError(
            code="document_io",
            path="$document",
            message="boundary document could not be read within its size limit",
        ) from None
    try:
        text = payload.decode("utf-8", errors="strict")
        document = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, ValueError, RecursionError):
        raise BoundaryValidationError(
            code="document_format",
            path="$document",
            message="boundary document must be strict UTF-8 JSON",
        ) from None
    return document, hashlib.sha256(payload).hexdigest()


def _add_resource_selector(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--type",
        dest="resource_type",
        required=True,
        choices=tuple(resource_type.value for resource_type in ResourceType),
    )
    parser.add_argument("--name", required=True)
    parser.add_argument("--version", required=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = _RedactedArgumentParser(prog="openfundscore")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser(
        "validate-config", help="validate a versioned scoring configuration"
    )
    validate.add_argument("path", help="path to a scoring JSON file")

    validate_mapping = subparsers.add_parser(
        "validate-mapping",
        help="validate a versioned complex-alternatives strategy mapping",
    )
    validate_mapping.add_argument("path", help="path to a strategy mapping JSON file")

    strategy_map = subparsers.add_parser(
        "strategy-map",
        help="print the peer-bucket and score-profile decision for a strategy family",
    )
    strategy_map.add_argument("family", help="snake_case strategy family identifier")
    strategy_map.add_argument("--mapping-version", required=True)

    validate_record_command = subparsers.add_parser(
        "validate-record",
        help="validate a contract record with its schema and semantics",
    )
    validate_record_command.add_argument(
        "--type",
        dest="record_type",
        required=True,
        choices=tuple(record_type.value for record_type in RecordType),
    )
    validate_record_command.add_argument("--schema-version", required=True)
    validate_record_command.add_argument("--evaluation-timestamp")
    validate_record_command.add_argument("path", help="path to a contract JSON file")

    resources = subparsers.add_parser(
        "resources", help="inspect versioned package resources"
    )
    resource_subparsers = resources.add_subparsers(
        dest="resource_command", required=True
    )
    list_command = resource_subparsers.add_parser(
        "list", help="list packaged resources"
    )
    list_command.add_argument(
        "--type",
        dest="resource_type",
        choices=tuple(resource_type.value for resource_type in ResourceType),
    )
    resolve_command = resource_subparsers.add_parser(
        "resolve", help="resolve an exact resource selector"
    )
    _add_resource_selector(resolve_command)
    show_command = resource_subparsers.add_parser(
        "show", help="write one packaged resource to stdout"
    )
    _add_resource_selector(show_command)

    platform_boundary = subparsers.add_parser(
        "platform-boundary",
        help="validate or inspect the Ant Fortune public-data boundary",
    )
    boundary_subparsers = platform_boundary.add_subparsers(
        dest="boundary_command",
        required=True,
    )
    boundary_validate = boundary_subparsers.add_parser(
        "validate",
        help="validate the packaged Ant Fortune boundary or a local document",
    )
    boundary_validate.add_argument("path", nargs="?")
    boundary_validate.add_argument("--boundary-version", required=True)
    boundary_check = boundary_subparsers.add_parser(
        "check",
        help="check one field and requested-use set without collecting data",
    )
    boundary_check.add_argument("field_id")
    boundary_check.add_argument(
        "--access-mode",
        required=True,
        choices=tuple(item.value for item in AccessMode),
    )
    boundary_check.add_argument(
        "--use",
        dest="uses",
        required=True,
        action="append",
        choices=tuple(item.value for item in BoundaryUse),
    )
    boundary_check.add_argument("--boundary-version", required=True)
    return parser


def _resource_document(resource: ResourceInfo) -> dict[str, str]:
    return {
        "media_type": resource.media_type,
        "name": resource.key.name,
        "sha256": resource.sha256,
        "type": resource.key.resource_type.value,
        "uri": resource.uri,
        "version": resource.key.version,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the OpenFundScore CLI and return a process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "platform-boundary":
        try:
            if args.boundary_command == "validate":
                if args.path is None:
                    resource = resolve_resource(
                        resource_type="platform-boundary",
                        name="ant_fortune",
                        version=args.boundary_version,
                    )
                    boundary_document = resource.load_json()
                    boundary_sha256 = resource.info.sha256
                else:
                    boundary_document, boundary_sha256 = _load_boundary_document(
                        args.path
                    )
                decision = validate_ant_fortune_boundary(
                    boundary_document,
                    expected_version=args.boundary_version,
                    resource_sha256=boundary_sha256,
                )
                print(
                    f"valid: ant_fortune@{decision.boundary_version}; "
                    f"sha256={decision.resource_sha256}"
                )
                return 0
            decision = decide_ant_fortune_field(
                args.field_id,
                access_mode=args.access_mode,
                requested_uses=frozenset(BoundaryUse(item) for item in args.uses),
                boundary_version=args.boundary_version,
            )
            print(
                json.dumps(
                    {
                        "access_mode": decision.access_mode,
                        "affects_open_score": decision.affects_open_score,
                        "allowed_uses": dict(decision.allowed_uses),
                        "automated_adapter_allowed": decision.automated_adapter_allowed,
                        "authorization_status": decision.authorization_status,
                        "boundary_id": decision.boundary_id,
                        "boundary_version": decision.boundary_version,
                        "cache_allowed": decision.cache_allowed,
                        "derived_allowed": decision.derived_allowed,
                        "display_allowed": decision.display_allowed,
                        "field_id": decision.field_id,
                        "ingestion_allowed": decision.ingestion_allowed,
                        "namespace": decision.namespace,
                        "open_score_allowed": decision.open_score_allowed,
                        "publication_allowed": decision.publication_allowed,
                        "reason_code": decision.reason_code,
                        "redistribution_allowed": decision.redistribution_allowed,
                        "requested_uses": decision.requested_uses,
                        "resource_sha256": decision.resource_sha256,
                        "reviewed_at": decision.reviewed_at,
                        "use_decisions": dict(decision.use_decisions),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        except (BoundaryValidationError, ResourceError):
            print(
                "openfundscore: error: platform boundary operation failed",
                file=sys.stderr,
            )
            return 2

    if args.command == "validate-record":
        try:
            document = _load_record_document(
                args.path,
                record_type=args.record_type,
                schema_version=args.schema_version,
            )
            validate_record(
                args.record_type,
                document,
                schema_version=args.schema_version,
                evaluation_timestamp=args.evaluation_timestamp,
            )
        except RecordValidationError as exc:
            print(f"openfundscore: error: {exc}", file=sys.stderr)
            return 2
        print(f"valid: {args.record_type}@{args.schema_version} (schema+semantics)")
        return 0

    if args.command == "resources":
        try:
            if args.resource_command == "list":
                document = [
                    _resource_document(resource)
                    for resource in list_resources(resource_type=args.resource_type)
                ]
                print(json.dumps(document, indent=2, sort_keys=True))
                return 0

            resource = resolve_resource(
                resource_type=args.resource_type,
                name=args.name,
                version=args.version,
            )
            if args.resource_command == "resolve":
                print(
                    json.dumps(
                        _resource_document(resource.info),
                        indent=2,
                        sort_keys=True,
                    )
                )
                return 0
            if args.resource_command == "show":
                sys.stdout.write(resource.read_json_text())
                return 0
        except ResourceError as exc:
            print(f"openfundscore: error: {exc}", file=sys.stderr)
            return 2

    if args.command == "validate-config":
        try:
            config = load_score_config(args.path)
            validate_score_config(config)
        except ConfigValidationError as exc:
            print(f"openfundscore: error: {exc}", file=sys.stderr)
            return 2

        manager_total = sum(
            component["weight"] for component in config["manager_model"]["components"]
        )
        print(
            f"valid: {len(config['category_profiles'])} category profiles; "
            f"manager model: {manager_total}"
        )
        return 0

    if args.command == "validate-mapping":
        try:
            mapping = load_strategy_mapping(args.path)
            validate_strategy_mapping(mapping)
        except (ResourceError, StrategyMappingError):
            print(
                "openfundscore: error: strategy mapping validation failed",
                file=sys.stderr,
            )
            return 2

        print(
            f"valid: {len(mapping['peer_buckets'])} peer buckets; "
            f"{len(mapping['strategy_families'])} strategy families"
        )
        return 0

    if args.command == "strategy-map":
        try:
            decision = map_strategy_family(
                args.family,
                mapping_version=args.mapping_version,
            )
        except (ResourceError, StrategyMappingError):
            print(
                "openfundscore: error: strategy mapping operation failed",
                file=sys.stderr,
            )
            return 2

        print(
            json.dumps(
                {
                    "is_rated": decision.is_rated,
                    "mapping_id": decision.mapping_id,
                    "mapping_version": decision.mapping_version,
                    "peer_bucket": decision.peer_bucket,
                    "resource_sha256": decision.resource_sha256,
                    "score_profile": decision.score_profile,
                    "strategy_family": decision.strategy_family,
                    "unrated_reason": decision.unrated_reason,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
