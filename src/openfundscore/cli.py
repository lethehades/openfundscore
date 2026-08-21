"""Command-line entry points for OpenFundScore."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

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
from .validation import RecordType, RecordValidationError, validate_record

_MAX_RECORD_BYTES = 8 * 1024 * 1024


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

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
