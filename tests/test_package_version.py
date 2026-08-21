from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

import openfundscore


class PackageVersionTests(unittest.TestCase):
    def test_m1_public_api_uses_the_v0_2_development_version(self) -> None:
        pyproject = tomllib.loads(
            (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        )

        self.assertEqual(pyproject["project"]["version"], "0.2.0.dev0")
        self.assertEqual(openfundscore.__version__, "0.2.0.dev0")


if __name__ == "__main__":
    unittest.main()
