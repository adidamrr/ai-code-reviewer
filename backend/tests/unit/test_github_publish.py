from __future__ import annotations

import unittest

from backend.app.store import InMemoryStore


def _seed_publish_fixture(store: InMemoryStore) -> tuple[dict, dict]:
    repo = store.upsert_repository(
        {
            "owner": "octo-org",
            "name": "octo-repo",
            "fullName": "octo-org/octo-repo",
            "defaultBranch": "main",
            "accountLogin": "octocat",
            "provider": "github",
        }
    )
    pr = store.get_or_create_pr(
        repo["id"],
        42,
        {
            "title": "Improve widget safety",
            "state": "open",
            "authorLogin": "octocat",
            "url": "https://github.com/octo-org/octo-repo/pull/42",
            "baseSha": "b" * 40,
            "headSha": "h" * 40,
        },
    )

    job = {
        "id": "job_publish",
        "prId": pr["id"],
        "snapshotId": "snap_publish",
        "status": "done",
        "scope": ["bugs"],
        "generationModelProfile": "yandexgpt-pro",
        "generationModel": "gpt://folder/yandexgpt/latest",
        "filesFilter": None,
        "maxComments": 10,
        "progress": {"filesDone": 1, "total": 1, "stage": "ranking", "stageProgress": {"done": 1, "total": 1}},
        "summary": {"totalSuggestions": 1, "partialFailures": 0, "filesSkipped": 0, "warnings": []},
        "errorMessage": None,
        "createdAt": "2026-03-21T00:00:00Z",
        "updatedAt": "2026-03-21T00:00:00Z",
    }
    suggestion = {
        "id": "sug_publish",
        "jobId": job["id"],
        "prId": pr["id"],
        "snapshotId": "snap_publish",
        "fingerprint": "fp_publish",
        "filePath": "lib/widget.dart",
        "lineStart": 14,
        "lineEnd": 14,
        "severity": "medium",
        "category": "bugs",
        "title": "Guard missing null branch",
        "body": "Handle the null response before dereferencing the widget state.",
        "deliveryMode": "inline",
        "evidence": [{"evidenceId": "code:0", "type": "code"}],
        "citations": [],
        "confidence": 0.92,
        "meta": {"language": "Dart", "fileRole": "ui"},
        "createdAt": "2026-03-21T00:00:00Z",
    }

    store.jobs[job["id"]] = job
    store.jobs_by_pr[pr["id"]] = [job["id"]]
    store.job_events_by_job[job["id"]] = []
    store.suggestions[suggestion["id"]] = suggestion
    store.suggestions_by_job[job["id"]] = [suggestion["id"]]
    store._store_feature_snapshot(suggestion)
    return pr, job


class GithubPublishTests(unittest.TestCase):
    def test_dry_run_does_not_block_live_publish(self) -> None:
        store = InMemoryStore()
        pr, job = _seed_publish_fixture(store)

        dry_result = store.publish(pr["id"], job["id"], "review_comments", True)
        live_result = store.publish(
            pr["id"],
            job["id"],
            "review_comments",
            False,
            published_comments=[
                {
                    "suggestionId": "sug_publish",
                    "providerCommentId": "12345",
                    "state": "posted",
                    "filePath": "lib/widget.dart",
                    "lineStart": 14,
                    "lineEnd": 14,
                    "body": "posted",
                    "createdAt": "2026-03-21T00:00:01Z",
                }
            ],
        )

        self.assertFalse(dry_result["idempotent"])
        self.assertEqual(dry_result["publishedCount"], 0)
        self.assertFalse(live_result["idempotent"])
        self.assertEqual(live_result["publishedCount"], 1)

    def test_publish_persists_external_provider_comment_id_and_errors(self) -> None:
        store = InMemoryStore()
        pr, job = _seed_publish_fixture(store)

        result = store.publish(
            pr["id"],
            job["id"],
            "issue_comments",
            False,
            published_comments=[
                {
                    "suggestionId": "sug_publish",
                    "providerCommentId": "98765",
                    "state": "posted",
                    "filePath": "lib/widget.dart",
                    "lineStart": 14,
                    "lineEnd": 14,
                    "body": "real GitHub comment",
                    "createdAt": "2026-03-21T00:00:02Z",
                }
            ],
            errors=["permission warning"],
        )

        self.assertEqual(result["publishedCount"], 1)
        self.assertEqual(result["errors"], ["permission warning"])
        self.assertEqual(result["comments"][0]["providerCommentId"], "98765")
        self.assertEqual(result["comments"][0]["body"], "real GitHub comment")


if __name__ == "__main__":
    unittest.main()
