"""Deterministically apply the v0.1.0 formula semantic manifest.

This maintainer script does not calculate raw metrics. It copies the explicit,
auditable economic contract for each upstream formula into all 120 profile rows
and embeds the same 92-row manifest in the packaged catalog.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
CATALOG = (
    ROOT / "src/openfundscore/_resources/metric-catalog/"
    "openfundscore-category-metrics/0.1.0.json"
)
INDEX = ROOT / "src/openfundscore/_resources/index.json"
TAXONOMY = ROOT / "src/openfundscore/metric_taxonomy.py"


def _load_taxonomy() -> ModuleType:
    spec = importlib.util.spec_from_file_location("metric_taxonomy", TAXONOMY)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load metric taxonomy module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    taxonomy = _load_taxonomy()
    manifest = taxonomy.FORMULA_SEMANTICS
    if type(manifest) is not dict or len(manifest) != 92:
        raise RuntimeError("semantic manifest must define exactly 92 formulas")

    document = json.loads(CATALOG.read_text(encoding="utf-8"))
    formulas: set[str] = set()
    entry_count = 0
    for profile in document["profiles"].values():
        for metrics in profile["dimensions"].values():
            for metric in metrics:
                formula = metric["formula"]
                try:
                    semantic = manifest[formula]
                except KeyError:
                    raise RuntimeError(
                        f"formula missing from semantic manifest: {formula}"
                    ) from None
                metric.update(deepcopy(semantic))
                formulas.add(formula)
                entry_count += 1

    if entry_count != 120 or formulas != set(manifest):
        missing = sorted(formulas - set(manifest))
        unused = sorted(set(manifest) - formulas)
        raise RuntimeError(
            f"catalog/manifest mismatch: entries={entry_count}, "
            f"missing={missing}, unused={unused}"
        )
    document["formula_semantics"] = deepcopy(manifest)

    payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    CATALOG.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    index = json.loads(INDEX.read_text(encoding="utf-8"))
    for entry in index["resources"]:
        if (
            entry["internal_path"]
            == "metric-catalog/openfundscore-category-metrics/0.1.0.json"
        ):
            entry["sha256"] = digest
            break
    else:
        raise RuntimeError("metric catalog resource missing from index")
    INDEX.write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {entry_count} entries / {len(manifest)} formulas / {digest}")


if __name__ == "__main__":
    main()
