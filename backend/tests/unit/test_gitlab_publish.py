from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from backend.app.errors import HttpError
from backend.app.main import build_gitlab_discussion_payload, publish_gitlab_comments


class GitlabPublishTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.suggestion = {
            "id": "sug_gitlab",
            "filePath": "src/app.py",
            "lineStart": 18,
            "lineEnd": 20,
            "title": "Use timeout",
            "body": "Pass an explicit timeout to avoid hanging requests.",
            "category": "performance",
            "severity": "medium",
            "confidence": 0.81,
            "citations": [],
        }

    def test_build_gitlab_discussion_payload_targets_end_line(self) -> None:
        payload = build_gitlab_discussion_payload(
            self.suggestion,
            body="body",
            base_sha="base",
            start_sha="start",
            head_sha="head",
        )

        self.assertEqual(payload["position[position_type]"], "text")
        self.assertEqual(payload["position[new_path]"], "src/app.py")
        self.assertEqual(payload["position[old_path]"], "src/app.py")
        self.assertEqual(payload["position[new_line]"], "20")

    async def test_issue_comment_publish_uses_merge_request_notes(self) -> None:
        client = object()
        response = {"id": 123, "created_at": "2026-03-22T00:00:00Z"}
        mock_request = AsyncMock(return_value=response)

        with patch("backend.app.main.gitlab_api_request", mock_request):
            comments, errors = await publish_gitlab_comments(
                client,  # type: ignore[arg-type]
                "token",
                project_ref="group/project",
                mr_iid=7,
                base_sha="base",
                start_sha="start",
                head_sha="head",
                mode="issue_comments",
                suggestions=[self.suggestion],
            )

        self.assertEqual(errors, [])
        self.assertEqual(comments[0]["providerCommentId"], "123")
        self.assertEqual(comments[0]["mode"], "issue_comments")
        self.assertIn("src/app.py:18-20", comments[0]["body"])
        mock_request.assert_awaited_once()
        self.assertIn("/merge_requests/7/notes", mock_request.await_args.args[3])

    async def test_review_comment_publish_falls_back_to_note_when_diff_position_is_rejected(self) -> None:
        client = object()
        mock_request = AsyncMock(
            side_effect=[
                HttpError(422, "gitlab_api_error", "GitLab API error: position is invalid"),
                {"id": 456, "created_at": "2026-03-22T00:00:01Z"},
            ]
        )

        with patch("backend.app.main.gitlab_api_request", mock_request):
            comments, errors = await publish_gitlab_comments(
                client,  # type: ignore[arg-type]
                "token",
                project_ref="group/project",
                mr_iid=8,
                base_sha="base",
                start_sha="start",
                head_sha="head",
                mode="review_comments",
                suggestions=[self.suggestion],
            )

        self.assertEqual(errors, [])
        self.assertEqual(comments[0]["providerCommentId"], "456")
        self.assertEqual(comments[0]["mode"], "issue_comments")
        self.assertIn("src/app.py:18-20", comments[0]["body"])
        self.assertEqual(mock_request.await_count, 2)
        self.assertIn("/merge_requests/8/discussions", mock_request.await_args_list[0].args[3])
        self.assertIn("/merge_requests/8/notes", mock_request.await_args_list[1].args[3])

    async def test_review_comment_publish_reads_note_id_from_discussion_response(self) -> None:
        client = object()
        mock_request = AsyncMock(
            return_value={
                "id": "discussion-1",
                "notes": [{"id": 789, "created_at": "2026-03-22T00:00:02Z"}],
            }
        )

        with patch("backend.app.main.gitlab_api_request", mock_request):
            comments, errors = await publish_gitlab_comments(
                client,  # type: ignore[arg-type]
                "token",
                project_ref="group/project",
                mr_iid=9,
                base_sha="base",
                start_sha="start",
                head_sha="head",
                mode="review_comments",
                suggestions=[self.suggestion],
            )

        self.assertEqual(errors, [])
        self.assertEqual(comments[0]["providerCommentId"], "789")
        self.assertEqual(comments[0]["mode"], "review_comments")
        self.assertNotIn("src/app.py:18-20", comments[0]["body"])


if __name__ == "__main__":
    unittest.main()
