"""Command-line entry points for OpenFundScore."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from .resources import (
    ResourceError,
    ResourceInfo,
    ResourceType,
    list_resources,
    resolve_resource,
)
from .score_config import ConfigValidationError, load_score_config, validate_score_config


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
    parser = argparse.ArgumentParser(prog="openfundscore")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser(
        "validate-config", help="validate a versioned scoring configuration"
    )
    validate.add_argument("path", help="path to a scoring JSON file")

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
