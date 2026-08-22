"""Command-line entry points for OpenFundScore."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from .mainland_official import (
    MainlandOfficialSnapshotAdapter,
    SnapshotValidationError,
    load_mainland_entitlements,
)
from .provider_semantics import ProviderRecordValidationError, parse_rfc3339_timestamp
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

    provider = subparsers.add_parser(
        "provider", help="run explicit offline provider operations"
    )
    provider_subparsers = provider.add_subparsers(
        dest="provider_command", required=True
    )
    mainland_parse = provider_subparsers.add_parser(
        "mainland-parse",
        help="parse and authorize a local frozen Mainland official snapshot",
    )
    mainland_parse.add_argument("snapshot")
    mainland_parse.add_argument("--entitlements", required=True)
    mainland_parse.add_argument("--evaluation-timestamp", required=True)
    mainland_parse.add_argument(
        "--fund-company-host",
        action="append",
        default=[],
        metavar="EXACT_HOST=EVIDENCE_URL",
    )

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

    if args.command == "provider" and args.provider_command == "mainland-parse":
        try:
            evaluation_timestamp = parse_rfc3339_timestamp(
                args.evaluation_timestamp,
                path="$evaluation_timestamp",
            )
            host_approvals: dict[str, str] = {}
            for approval in args.fund_company_host:
                if (
                    not isinstance(approval, str)
                    or "=" not in approval
                    or not approval.split("=", 1)[0]
                    or not approval.split("=", 1)[1]
                ):
                    raise SnapshotValidationError(
                        code="invalid_host_approval",
                        path="$fund_company_hosts",
                        message="fund-company host approval is malformed",
                    )
                host, evidence_url = approval.split("=", 1)
                if host in host_approvals:
                    raise SnapshotValidationError(
                        code="invalid_host_approval",
                        path="$fund_company_hosts",
                        message="fund-company host approvals must be unique",
                    )
                host_approvals[host] = evidence_url
            entitlements = load_mainland_entitlements(Path(args.entitlements))
            records = MainlandOfficialSnapshotAdapter(
                entitlements=entitlements,
                fund_company_hosts=host_approvals,
            ).parse(
                Path(args.snapshot),
                evaluation_timestamp=evaluation_timestamp,
            )
        except SnapshotValidationError as exc:
            print(f"openfundscore: error: {exc}", file=sys.stderr)
            return 2
        except (ProviderRecordValidationError, ValueError):
            print(
                "openfundscore: error: mainland_snapshot_failed at $provider: "
                "offline provider operation failed",
                file=sys.stderr,
            )
            return 2
        print(
            json.dumps(
                records,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0

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
