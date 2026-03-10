from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.store import InMemoryStore, now_iso


class AdaptationV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryStore()
        self.pr = self.store.get_or_create_pr(
            "repo_demo",
            101,
            {
                "title": "Improve service",
                "state": "open",
                "authorLogin": "dev",
                "url": "https://example.test/pr/101",
                "baseSha": "a" * 40,
                "headSha": "b" * 40,
            },
        )
        self.job = {
            "id": "job_demo",
            "prId": self.pr["id"],
            "snapshotId": "snap_demo",
            "status": "done",
            "scope": ["bugs", "style"],
            "filesFilter": [],
            "maxComments": 20,
            "progress": {"stage": "ranking", "stageProgress": {"done": 1, "total": 1}, "filesDone": 1, "total": 1},
            "summary": {"totalSuggestions": 0, "partialFailures": 0, "filesSkipped": 0, "warnings": []},
            "errorMessage": None,
            "createdAt": now_iso(),
            "updatedAt": now_iso(),
        }
        self.store.jobs[self.job["id"]] = self.job
        self.store.jobs_by_pr[self.pr["id"]] = [self.job["id"]]
        self.store.suggestions_by_job[self.job["id"]] = []
        self.store.comments_by_pr.setdefault(self.pr["id"], [])

    def _add_suggestion(
        self,
        suggestion_id: str,
        *,
        fingerprint: str,
        title: str,
        category: str = "bugs",
        severity: str = "medium",
        confidence: float = 0.8,
        rank_score: float = 0.8,
        file_path: str = "src/service.py",
        line_start: int = 10,
        line_end: int = 10,
        delivery_mode: str = "inline",
    ) -> dict:
        suggestion = {
            "id": suggestion_id,
            "jobId": self.job["id"],
            "prId": self.pr["id"],
            "snapshotId": self.job["snapshotId"],
            "fingerprint": fingerprint,
            "filePath": file_path,
            "lineStart": line_start,
            "lineEnd": line_end,
            "severity": severity,
            "category": category,
            "title": title,
            "body": title,
            "deliveryMode": delivery_mode,
            "evidence": [{"type": "code"}, {"type": "doc"}],
            "citations": [],
            "confidence": confidence,
            "meta": {
                "language": "python",
                "fileRole": "logic",
                "promptContextVersion": "rag-v2",
                "rankFeatures": {
                    "confidence": confidence,
                    "rankScore": rank_score,
                    "retrievalScore": 0.4,
                    "plannerPriority": 0.6,
                    "staticSupport": 0.3,
                    "repoFeedbackScore": 0.0,
                    "evidenceStrength": 0.9,
                    "evidenceSignature": "code+doc",
                    "titleTemplate": f"{category}:{title.lower()}",
                    "deliveryMode": delivery_mode,
                    "category": category,
                    "severity": severity,
                },
            },
            "createdAt": now_iso(),
        }
        self.store.suggestions[suggestion["id"]] = suggestion
        self.store.suggestions_by_job[self.job["id"]].append(suggestion["id"])
        self.store._store_feature_snapshot(suggestion)
        self.job["summary"]["totalSuggestions"] = len(self.store.suggestions_by_job[self.job["id"]])
        return suggestion

    def _add_comment(self, comment_id: str, suggestion_id: str) -> dict:
        suggestion = self.store.suggestions[suggestion_id]
        comment = {
            "id": comment_id,
            "prId": self.pr["id"],
            "jobId": self.job["id"],
            "suggestionId": suggestion_id,
            "providerCommentId": f"gh_{comment_id}",
            "mode": "review_comments",
            "state": "posted",
            "filePath": suggestion["filePath"],
            "lineStart": suggestion["lineStart"],
            "lineEnd": suggestion["lineEnd"],
            "body": suggestion["body"],
            "createdAt": now_iso(),
        }
        self.store.comments[comment_id] = comment
        self.store.comments_by_pr[self.pr["id"]].append(comment_id)
        self.store.feedback_by_comment[comment_id] = []
        return comment

    def _vote_many(self, comment_id: str, vote: str, count: int) -> None:
        for index in range(count):
            self.store.upsert_feedback(comment_id, f"user_{vote}_{index}", vote, None)

    def test_without_feedback_preserves_base_ordering(self) -> None:
        self._add_suggestion("s_high", fingerprint="fp_high", title="High confidence", rank_score=0.92)
        self._add_suggestion("s_low", fingerprint="fp_low", title="Low confidence", rank_score=0.25)

        page = self.store.list_job_suggestions(self.job["id"], None, 50)

        self.assertEqual([item["id"] for item in page["items"][:2]], ["s_high", "s_low"])
        self.assertEqual(page["items"][0]["meta"]["adaptation"]["modelVersion"], "bootstrap")

    def test_single_upvote_improves_feedback_prior_without_overriding_strong_base_rank(self) -> None:
        self._add_suggestion("s_high", fingerprint="fp_high", title="Strong baseline", rank_score=0.95)
        self._add_suggestion("s_low", fingerprint="fp_low", title="Needs work", rank_score=0.10)
        self._add_comment("c_low", "s_low")
        self.store.upsert_feedback("c_low", "reviewer_1", "up", "useful")

        page = self.store.list_job_suggestions(self.job["id"], None, 50)
        by_id = {item["id"]: item for item in page["items"]}

        self.assertEqual([item["id"] for item in page["items"][:2]], ["s_high", "s_low"])
        self.assertGreater(by_id["s_low"]["meta"]["adaptation"]["feedbackPrior"], 0.0)

    def test_three_downvotes_downgrade_inline_suggestion_to_summary(self) -> None:
        self._add_suggestion("s_bad", fingerprint="fp_bad", title="Noisy finding", rank_score=0.90)
        self._add_comment("c_bad", "s_bad")
        self._vote_many("c_bad", "down", 3)

        page = self.store.list_job_suggestions(self.job["id"], None, 50)
        self.assertEqual(page["items"], [])

    def test_two_downvotes_reduce_confidence_before_full_suppression(self) -> None:
        self._add_suggestion("s_warn", fingerprint="fp_warn", title="Potential issue", rank_score=0.90, confidence=0.80)
        self._add_comment("c_warn", "s_warn")
        self._vote_many("c_warn", "down", 2)

        page = self.store.list_job_suggestions(self.job["id"], None, 50)
        item = next(entry for entry in page["items"] if entry["id"] == "s_warn")

        self.assertLess(item["confidence"], 0.80)
        self.assertLess(item["meta"]["adaptation"]["feedbackPrior"], 0.0)
        self.assertFalse(item["meta"]["adaptation"]["suppressedByFeedback"])

    def test_template_prior_transfers_feedback_to_similar_suggestions(self) -> None:
        self._add_suggestion("s_hist", fingerprint="fp_hist", title="Mutable default argument", rank_score=0.45)
        self._add_comment("c_hist", "s_hist")
        self._vote_many("c_hist", "down", 8)

        self._add_suggestion("s_same_template", fingerprint="fp_new_1", title="Mutable default argument", rank_score=0.60, line_start=20, line_end=20)
        self._add_suggestion("s_other_template", fingerprint="fp_new_2", title="Inefficient nested loop", rank_score=0.60, line_start=30, line_end=30)

        page = self.store.list_job_suggestions(self.job["id"], None, 50)
        ordered_ids = [item["id"] for item in page["items"]]
        same_template = next(item for item in page["items"] if item["id"] == "s_same_template")

        self.assertLess(ordered_ids.index("s_other_template"), ordered_ids.index("s_same_template"))
        self.assertLess(same_template["meta"]["adaptation"]["templatePrior"], 0.0)

    def test_duplicate_vote_remains_idempotent_and_updates_totals(self) -> None:
        self._add_suggestion("s_dup", fingerprint="fp_dup", title="Duplicate vote test", rank_score=0.55)
        self._add_comment("c_dup", "s_dup")

        first = self.store.upsert_feedback("c_dup", "same_user", "down", "noisy")
        second = self.store.upsert_feedback("c_dup", "same_user", "up", "actually useful")
        feedback = self.store.get_comment_feedback("c_dup")

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(feedback["votes"]), 1)
        self.assertEqual(feedback["totals"]["up"], 1)
        self.assertEqual(feedback["totals"]["down"], 0)

    def test_retrain_creates_new_model_version_and_runtime_uses_it(self) -> None:
        self._add_suggestion("s_train_1", fingerprint="fp_train_1", title="Cache mutable state", rank_score=0.30, confidence=0.72)
        self._add_suggestion("s_train_2", fingerprint="fp_train_2", title="Use explicit timeout", rank_score=0.85, confidence=0.91)
        self._add_comment("c_train_1", "s_train_1")
        self._add_comment("c_train_2", "s_train_2")
        self._vote_many("c_train_1", "down", 4)
        self._vote_many("c_train_2", "up", 4)

        status = self.store.retrain_adaptation_model()
        page = self.store.list_job_suggestions(self.job["id"], None, 50)

        self.assertNotEqual(status["currentVersion"], "bootstrap")
        self.assertGreaterEqual(status["trainingExamples"], 2)
        self.assertEqual(page["items"][0]["meta"]["adaptation"]["modelVersion"], status["currentVersion"])

    def test_upvote_increases_confidence(self) -> None:
        self._add_suggestion("s_up", fingerprint="fp_up", title="Helpful note", rank_score=0.40, confidence=0.60)
        self._add_comment("c_up", "s_up")
        self._vote_many("c_up", "up", 2)

        page = self.store.list_job_suggestions(self.job["id"], None, 50)
        item = next(entry for entry in page["items"] if entry["id"] == "s_up")

        self.assertGreater(item["confidence"], 0.60)

    def test_smoothed_utility_prevents_extreme_score_from_single_vote(self) -> None:
        self._add_suggestion("s_smooth", fingerprint="fp_smooth", title="Sparse feedback", rank_score=0.40)
        self._add_comment("c_smooth", "s_smooth")
        self.store.upsert_feedback("c_smooth", "reviewer", "up", None)

        fingerprint_stat = self.store.adaptation_feature_stats["fingerprint"]["fp_smooth"]

        self.assertEqual(fingerprint_stat["score"], 1)
        self.assertAlmostEqual(fingerprint_stat["smoothedUtility"], 1.0 / 3.0, places=6)


if __name__ == "__main__":
    unittest.main()
