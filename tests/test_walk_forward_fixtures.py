from __future__ import annotations

import unittest

from openfundscore.walk_forward import run_walk_forward
from openfundscore.walk_forward_fixtures import synthetic_walk_forward_fixture


class WalkForwardFixtureTests(unittest.TestCase):
    def test_fixture_covers_lifecycle_versions_and_publication_lag_deterministically(
        self,
    ) -> None:
        first = synthetic_walk_forward_fixture()
        second = synthetic_walk_forward_fixture()

        self.assertEqual(first, second)
        statuses = {
            interval.status
            for candidate in first.candidates
            for interval in candidate.lifecycle
        }
        self.assertEqual(statuses, {"active", "closed", "merged", "transformed"})
        active_classifications = tuple(
            item.value
            for item in first.snapshots
            if item.strategy_id == "synthetic-active"
            and item.domain == "classification"
        )
        self.assertEqual(active_classifications, ("equity-old", "mixed-new"))
        self.assertTrue(
            any(item.effective_from < item.published_at for item in first.snapshots)
        )
        active_classification_revisions = tuple(
            item
            for item in first.snapshots
            if item.strategy_id == "synthetic-active"
            and item.domain == "classification"
        )
        self.assertEqual(
            {item.effective_from for item in active_classification_revisions},
            {active_classification_revisions[0].effective_from},
        )
        self.assertEqual(
            active_classification_revisions[1].supersedes_revision_id,
            active_classification_revisions[0].revision_id,
        )
        closed_lifecycle = next(
            item.lifecycle
            for item in first.candidates
            if item.strategy_id == "synthetic-closed"
        )
        self.assertEqual(
            {item.effective_from for item in closed_lifecycle},
            {closed_lifecycle[0].effective_from},
        )
        self.assertEqual(closed_lifecycle[1].supersedes_revision_id, "lifecycle-r1")
        self.assertTrue(
            any(item.inception_at.year == 2022 for item in first.candidates)
        )
        self.assertEqual(
            {
                item.domain
                for item in first.snapshots
                if item.strategy_id == "synthetic-active"
            },
            {
                "availability",
                "benchmark",
                "classification",
                "fee_bps",
                "feature:downside_risk",
                "manager",
            },
        )

        report = run_walk_forward(
            first.config,
            candidates=first.candidates,
            snapshots=first.snapshots,
            outcomes=first.outcomes,
            precomputed_scores=first.precomputed_scores,
        )
        self.assertEqual(len(report.folds), 2)
        self.assertEqual(report.folds[1].retained_terminal_count, 3)
        self.assertEqual(report.folds[1].universe_count, 4)
        self.assertEqual(report.folds[1].eligible_count, 1)
        self.assertIn(
            (
                "synthetic-active",
                "score-synthetic-active-v1",
                "score-revision-r1",
            ),
            report.folds[0].audit_score_ids,
        )
        self.assertNotIn(
            (
                "synthetic-active",
                "score-synthetic-active-v2",
                "score-revision-r2",
            ),
            report.folds[0].audit_score_ids,
        )
        self.assertEqual(
            report.folds[1].audit_score_ids,
            (
                (
                    "synthetic-active",
                    "score-synthetic-active-v2",
                    "score-revision-r2",
                ),
            ),
        )


if __name__ == "__main__":
    unittest.main()
