"""Command-line entry points for OpenFundScore."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .score_config import ConfigValidationError, load_score_config, validate_score_config


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openfundscore")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser(
        "validate-config", help="validate a versioned scoring configuration"
    )
    validate.add_argument("path", help="path to a scoring JSON file")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the OpenFundScore CLI and return a process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

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
