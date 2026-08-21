from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


class CiWorkflowTests(unittest.TestCase):
    def test_actions_use_node24_releases_pinned_by_full_sha(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1",
            text,
        )
        self.assertIn(
            "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0",
            text,
        )
        self.assertNotRegex(text, r"actions/(?:checkout|setup-python)@v(?:4|5)\b")

    def test_matrix_and_permissions_remain_minimal(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('python-version: ["3.11", "3.12", "3.13"]', text)
        permissions_match = re.search(
            r"(?ms)^permissions:\n(?P<body>(?:  .+\n)+)\n",
            text,
        )
        if permissions_match is None:
            self.fail("workflow must declare an explicit top-level permissions block")
        self.assertEqual("  contents: read\n", permissions_match.group("body"))


if __name__ == "__main__":
    unittest.main()
