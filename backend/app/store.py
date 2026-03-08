from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .adaptation import rerank_suggestions
from .diff_utils import (
    build_related_call_sites,
    count_patch_changes,
    detect_language,
    extract_changed_blocks_from_patch,
    extract_changed_symbols_from_patch,
    extract_imports_from_patch,
    extract_surrounding_code_from_patch,
    infer_file_role,
    parse_unified_diff,
)
from .errors import HttpError
from .hashing import normalize_title, sha256
from .pagination import paginate
from .rag_adapter import analyze_with_rag

MAX_SYNC_FILES = 500
PATCH_CAP_BYTES = 300 * 1024


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def random_sha() -> str:
    return sha256(str(uuid4()))[:40]


def random_installation_id() -> int:
    return int(1_000_000 + (uuid4().int % 9_000_000))


def generate_default_sync_files(pr_number: int) -> list[dict[str, Any]]:
    return [
        {
            "path": "src/security/auth.ts",
            "status": "modified",
            "patch": "\n".join(
                [
                    "@@ -10,6 +10,9 @@ export async function login(userInput) {",
                    "-  const query = `SELECT * FROM users WHERE email = '${userInput.email}'`;",
                    "+  const query = `SELECT * FROM users WHERE email = $1`;",
                    "+  const params = [userInput.email];",
                    "+  return db.query(query, params);",
                    "   return db.query(query);",
                    " }",
                ]
            ),
        },
        {
            "path": f"src/services/pr-{pr_number}.ts",
            "status": "added",
            "patch": "\n".join(
                [
                    "@@ -0,0 +1,8 @@",
                    "+export function expensiveLoop(items: number[]) {",
                    "+  let sum = 0;",
                    "+  for (let i = 0; i < items.length; i += 1) {",
                    "+    for (let j = 0; j < items.length; j += 1) {",
                    "+      sum += items[i] * items[j];",
                    "+    }",
                    "+  }",
                    "+  return sum;",
                    "+}",
                ]
            ),
        },
    ]


class InMemoryStore:
    def __init__(self) -> None:
        self.installations: dict[str, dict[str, Any]] = {}
        self.repositories: dict[str, dict[str, Any]] = {}
        self.pull_requests: dict[str, dict[str, Any]] = {}
        self.snapshots: dict[str, dict[str, Any]] = {}
        self.snapshot_files: dict[str, dict[str, Any]] = {}
        self.snapshot_files_by_snapshot: dict[str, list[str]] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.jobs_by_pr: dict[str, list[str]] = {}
        self.job_events_by_job: dict[str, list[str]] = {}
        self.job_events: dict[str, dict[str, Any]] = {}
        self.suggestions: dict[str, dict[str, Any]] = {}
        self.suggestions_by_job: dict[str, list[str]] = {}
        self.comments: dict[str, dict[str, Any]] = {}
        self.comments_by_pr: dict[str, list[str]] = {}
        self.feedback_votes: dict[str, dict[str, Any]] = {}
        self.feedback_by_comment: dict[str, list[str]] = {}
        self.publish_runs: dict[str, dict[str, Any]] = {}
        self.analysis_tasks: dict[str, asyncio.Task[Any]] = {}
        self.seed()

    def seed(self) -> None:
        created_at = now_iso()
        installation = {
            "id": "inst_demo",
            "installationId": 123456,
            "accountLogin": "acme-org",
            "createdAt": created_at,
            "updatedAt": created_at,
        }
        repo = {
            "id": "repo_demo",
            "provider": "github",
            "installationId": installation["id"],
            "owner": "acme-org",
            "name": "demo-service",
            "fullName": "acme-org/demo-service",
            "defaultBranch": "main",
            "createdAt": created_at,
            "updatedAt": created_at,
        }
        self.installations[installation["id"]] = installation
        self.repositories[repo["id"]] = repo

    def upsert_github_installation(self, installation_id: int, account_login: str) -> dict[str, Any]:
        existing = next(
            (item for item in self.installations.values() if item["installationId"] == installation_id),
            None,
        )
        now = now_iso()

        if existing:
            existing["accountLogin"] = account_login
            existing["updatedAt"] = now
            return existing

        created = {
            "id": f"inst_{uuid4()}",
            "installationId": installation_id,
            "accountLogin": account_login,
            "createdAt": now,
            "updatedAt": now,
        }
        self.installations[created["id"]] = created

        repo = {
            "id": f"repo_{uuid4()}",
            "provider": "github",
            "installationId": created["id"],
            "owner": account_login,
            "name": f"repo-{str(installation_id)[-4:]}",
            "fullName": f"{account_login}/repo-{str(installation_id)[-4:]}",
            "defaultBranch": "main",
            "createdAt": now,
            "updatedAt": now,
        }
        self.repositories[repo["id"]] = repo
        return created

    def upsert_repository(self, data: dict[str, str]) -> dict[str, Any]:
        now = now_iso()
        existing = next((item for item in self.repositories.values() if item["fullName"] == data["fullName"]), None)

        if existing:
            existing["owner"] = data["owner"]
            existing["name"] = data["name"]
            existing["defaultBranch"] = data["defaultBranch"]
            existing["updatedAt"] = now
            return existing

        installation = next(
            (item for item in self.installations.values() if item["accountLogin"] == data["accountLogin"]),
            None,
        )
        if not installation:
            installation = self.upsert_github_installation(random_installation_id(), data["accountLogin"])

        created = {
            "id": f"repo_{uuid4()}",
            "provider": "github",
            "installationId": installation["id"],
            "owner": data["owner"],
            "name": data["name"],
            "fullName": data["fullName"],
            "defaultBranch": data["defaultBranch"],
            "createdAt": now,
            "updatedAt": now,
        }
        self.repositories[created["id"]] = created
        return created

    def list_repos(self, cursor: Any, limit: Any) -> dict[str, Any]:
        repos = sorted(self.repositories.values(), key=lambda item: item["fullName"])
        return paginate(repos, cursor, limit)

    def get_repo(self, repo_id: str) -> dict[str, Any]:
        repo = self.repositories.get(repo_id)
        if not repo:
            raise HttpError(404, "repo_not_found", f"Repository not found: {repo_id}")
        return repo

    def get_or_create_pr(self, repo_id: str, number: int, payload: dict[str, Any] | None) -> dict[str, Any]:
        existing = next(
            (item for item in self.pull_requests.values() if item["repoId"] == repo_id and item["number"] == number),
            None,
        )
        if existing:
            return existing

        now = now_iso()
        pr = {
            "id": f"pr_{uuid4()}",
            "repoId": repo_id,
            "number": number,
            "title": payload.get("title") if payload and payload.get("title") else f"PR #{number}",
            "state": payload.get("state") if payload and payload.get("state") else "open",
            "authorLogin": payload.get("authorLogin") if payload and payload.get("authorLogin") else "unknown",
            "url": payload.get("url") if payload and payload.get("url") else "https://github.com/",
            "baseSha": payload.get("baseSha") if payload and payload.get("baseSha") else random_sha(),
            "headSha": payload.get("headSha") if payload and payload.get("headSha") else random_sha(),
            "latestSnapshotId": None,
            "createdAt": now,
            "updatedAt": now,
        }
        self.pull_requests[pr["id"]] = pr
        self.jobs_by_pr[pr["id"]] = []
        self.comments_by_pr[pr["id"]] = []
        return pr

    def build_snapshot_file(self, snapshot_id: str, file_input: dict[str, Any], created_at: str) -> dict[str, Any]:
        patch = str(file_input.get("patch") or "")
        patch_bytes = len(patch.encode("utf-8"))
        too_large = patch_bytes > PATCH_CAP_BYTES

        changes = count_patch_changes(patch)
        parsed = {"hunks": [], "lineMap": []} if too_large else parse_unified_diff(patch)

        return {
            "id": f"file_{uuid4()}",
            "snapshotId": snapshot_id,
            "path": file_input["path"],
            "status": file_input.get("status", "modified"),
            "language": file_input.get("language") or detect_language(file_input["path"]),
            "fileRole": infer_file_role(file_input["path"]),
            "additions": file_input.get("additions", changes["additions"]),
            "deletions": file_input.get("deletions", changes["deletions"]),
            "patch": "" if too_large else patch,
            "hunks": None if too_large else parsed["hunks"],
            "lineMap": None if too_large else parsed["lineMap"],
            "imports": [] if too_large else extract_imports_from_patch(patch),
            "changedSymbols": [] if too_large else extract_changed_symbols_from_patch(patch),
            "surroundingCode": [] if too_large else extract_surrounding_code_from_patch(patch),
            "changedBlocks": [] if too_large else extract_changed_blocks_from_patch(patch, file_input["path"]),
            "relatedCallSites": [],
            "patchHash": sha256(patch),
            "isTooLarge": too_large,
            "createdAt": created_at,
        }

    def sync_pull_request(self, repo_id: str, pr_number: int, payload: dict[str, Any] | None) -> dict[str, Any]:
        repo = self.get_repo(repo_id)
        pr = self.get_or_create_pr(repo["id"], pr_number, payload)
        now = now_iso()

        head_sha = payload.get("headSha") if payload and payload.get("headSha") else pr["headSha"]
        base_sha = payload.get("baseSha") if payload and payload.get("baseSha") else pr["baseSha"]
        commit_sha = payload.get("commitSha") if payload and payload.get("commitSha") else head_sha

        latest_snapshot = self.snapshots.get(pr["latestSnapshotId"]) if pr.get("latestSnapshotId") else None
        if latest_snapshot and latest_snapshot["headSha"] == head_sha:
            return {
                "pr": pr,
                "snapshot": latest_snapshot,
                "counts": {
                    "files": latest_snapshot["filesCount"],
                    "additions": latest_snapshot["additions"],
                    "deletions": latest_snapshot["deletions"],
                },
                "idempotent": True,
            }

        files_input = payload.get("files") if payload and payload.get("files") else generate_default_sync_files(pr_number)
        if len(files_input) > MAX_SYNC_FILES:
            raise HttpError(
                422,
                "sync_limit_exceeded",
                f"PR has {len(files_input)} files, limit is {MAX_SYNC_FILES}",
            )

        snapshot_id = f"snap_{uuid4()}"
        snapshot = {
            "id": snapshot_id,
            "prId": pr["id"],
            "commitSha": commit_sha,
            "baseSha": base_sha,
            "headSha": head_sha,
            "filesCount": len(files_input),
            "additions": 0,
            "deletions": 0,
            "createdAt": now,
        }
        self.snapshots[snapshot_id] = snapshot
        self.snapshot_files_by_snapshot[snapshot_id] = []

        additions = 0
        deletions = 0
        for file_input in files_input:
            normalized = self.build_snapshot_file(snapshot_id, file_input, now)
            additions += int(normalized["additions"])
            deletions += int(normalized["deletions"])
            self.snapshot_files[normalized["id"]] = normalized
            self.snapshot_files_by_snapshot[snapshot_id].append(normalized["id"])

        snapshot_files = [
            self.snapshot_files[item_id]
            for item_id in self.snapshot_files_by_snapshot[snapshot_id]
            if item_id in self.snapshot_files
        ]
        build_related_call_sites(snapshot_files)

        snapshot["additions"] = additions
        snapshot["deletions"] = deletions

        pr["baseSha"] = base_sha
        pr["headSha"] = head_sha
        pr["latestSnapshotId"] = snapshot_id
        pr["updatedAt"] = now

        if payload:
            if payload.get("title"):
                pr["title"] = payload["title"]
            if payload.get("state"):
                pr["state"] = payload["state"]
            if payload.get("authorLogin"):
                pr["authorLogin"] = payload["authorLogin"]
            if payload.get("url"):
                pr["url"] = payload["url"]

        return {
            "pr": pr,
            "snapshot": snapshot,
            "counts": {"files": snapshot["filesCount"], "additions": additions, "deletions": deletions},
            "idempotent": False,
        }

    def get_pr(self, pr_id: str) -> dict[str, Any]:
        pr = self.pull_requests.get(pr_id)
        if not pr:
            raise HttpError(404, "pr_not_found", f"PR not found: {pr_id}")
        return pr

    def list_pr_files(self, pr_id: str, cursor: Any, limit: Any) -> dict[str, Any]:
        pr = self.get_pr(pr_id)
        latest = pr.get("latestSnapshotId")
        if not latest:
            return paginate([], cursor, limit)

        ids = self.snapshot_files_by_snapshot.get(latest, [])
        files = [self.snapshot_files[item_id] for item_id in ids if item_id in self.snapshot_files]
        return paginate(files, cursor, limit)

    def get_pr_diff(self, pr_id: str, file_path: str | None) -> list[dict[str, Any]]:
        pr = self.get_pr(pr_id)
        latest = pr.get("latestSnapshotId")
        if not latest:
            raise HttpError(404, "snapshot_not_found", f"No snapshot for PR: {pr_id}")

        ids = self.snapshot_files_by_snapshot.get(latest, [])
        files = [self.snapshot_files[item_id] for item_id in ids if item_id in self.snapshot_files]
        if not file_path:
            return files

        match = next((item for item in files if item["path"] == file_path), None)
        if not match:
            raise HttpError(404, "file_not_found", f"File not found in latest snapshot: {file_path}")
        return [match]

    def list_pr_snapshots(self, pr_id: str) -> list[dict[str, Any]]:
        self.get_pr(pr_id)
        snapshots = [item for item in self.snapshots.values() if item["prId"] == pr_id]
        return sorted(snapshots, key=lambda item: item["createdAt"], reverse=True)

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        snapshot = self.snapshots.get(snapshot_id)
        if not snapshot:
            raise HttpError(404, "snapshot_not_found", f"Snapshot not found: {snapshot_id}")

        ids = self.snapshot_files_by_snapshot.get(snapshot_id, [])
        files = [self.snapshot_files[item_id] for item_id in ids if item_id in self.snapshot_files]
        return {"snapshot": snapshot, "files": files}

    async def create_analysis_job(self, pr_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        pr = self.get_pr(pr_id)
        snapshot = self.snapshots.get(payload["snapshotId"])
        if not snapshot or snapshot["prId"] != pr["id"]:
            raise HttpError(422, "invalid_snapshot", "snapshotId does not belong to this PR")

        snapshot_file_ids = self.snapshot_files_by_snapshot.get(snapshot["id"], [])
        snapshot_files = [self.snapshot_files[item_id] for item_id in snapshot_file_ids if item_id in self.snapshot_files]

        files_filter = payload.get("files")
        files = [item for item in snapshot_files if item["path"] in files_filter] if files_filter else snapshot_files

        now = now_iso()
        job = {
            "id": f"job_{uuid4()}",
            "prId": pr_id,
            "snapshotId": snapshot["id"],
            "status": "queued",
            "scope": payload["scope"],
            "filesFilter": files_filter if files_filter else None,
            "maxComments": payload["maxComments"],
            "progress": {
                "filesDone": 0,
                "total": len(files),
                "stage": "overview",
                "stageProgress": {"done": 0, "total": 1},
            },
            "summary": {
                "totalSuggestions": 0,
                "partialFailures": 0,
                "filesSkipped": 0,
                "warnings": [],
            },
            "errorMessage": None,
            "createdAt": now,
            "updatedAt": now,
        }

        self.jobs[job["id"]] = job
        self.jobs_by_pr.setdefault(pr_id, []).append(job["id"])
        self.job_events_by_job[job["id"]] = []
        self.suggestions_by_job[job["id"]] = []

        self.append_job_event(job["id"], "info", "Задача анализа создана и поставлена в очередь.", stage="overview")
        task = asyncio.create_task(self.run_analysis_job(job["id"], files))
        self.analysis_tasks[job["id"]] = task
        task.add_done_callback(lambda _task, current_job_id=job["id"]: self.analysis_tasks.pop(current_job_id, None))
        return self.get_job(job["id"])

    def _store_generated_suggestions(self, job_id: str, suggestions_input: list[dict[str, Any]]) -> int:
        job = self.jobs.get(job_id)
        if not job:
            return 0

        created_at = now_iso()
        created_count = 0
        for suggestion_input in suggestions_input:
            fingerprint = suggestion_input.get("fingerprint") or sha256(
                f"{suggestion_input['filePath']}:{suggestion_input['lineStart']}:"
                f"{suggestion_input['lineEnd']}:{normalize_title(suggestion_input['title'])}"
            )

            existing_ids = self.suggestions_by_job.get(job["id"], [])
            duplicated = False
            for suggestion_id in existing_ids:
                suggestion = self.suggestions.get(suggestion_id)
                if suggestion and suggestion["fingerprint"] == fingerprint:
                    duplicated = True
                    break
            if duplicated:
                continue

            suggestion = {
                "id": f"sug_{uuid4()}",
                "jobId": job["id"],
                "prId": job["prId"],
                "snapshotId": job["snapshotId"],
                "fingerprint": fingerprint,
                "filePath": suggestion_input["filePath"],
                "lineStart": suggestion_input["lineStart"],
                "lineEnd": suggestion_input["lineEnd"],
                "severity": suggestion_input["severity"],
                "category": suggestion_input["category"],
                "title": suggestion_input["title"],
                "body": suggestion_input["body"],
                "deliveryMode": suggestion_input.get("deliveryMode", "inline"),
                "evidence": suggestion_input.get("evidence", []),
                "citations": suggestion_input.get("citations", []),
                "confidence": suggestion_input["confidence"],
                "meta": suggestion_input.get("meta", {}),
                "createdAt": created_at,
            }
            self.suggestions[suggestion["id"]] = suggestion
            self.suggestions_by_job.setdefault(job["id"], []).append(suggestion["id"])
            created_count += 1

        return created_count

    async def run_analysis_job(self, job_id: str, files: list[dict[str, Any]]) -> None:
        job = self.jobs.get(job_id)
        if not job:
            return

        job["status"] = "running"
        job["updatedAt"] = now_iso()
        self.append_job_event(job["id"], "info", "Задача анализа запущена.", stage="overview")

        partial_failures = 0
        files_skipped = 0

        try:
            eligible_files = [file for file in files if not file.get("isTooLarge") and str(file.get("patch") or "").strip()]
            files_skipped = len(files) - len(eligible_files)
            if files_skipped:
                for skipped in [file for file in files if file.get("isTooLarge")]:
                    self.append_job_event(
                        job["id"],
                        "warn",
                        "Файл пропущен из-за лимита размера patch.",
                        skipped.get("path"),
                        {"reason": "patch_too_large"},
                        stage="review",
                    )

            pr = self.get_pr(job["prId"])

            async def on_progress(update: dict[str, Any]) -> None:
                current = self.jobs.get(job_id)
                if not current:
                    return
                stage = update.get("stage") or current["progress"].get("stage") or "review"
                current["progress"]["stage"] = stage
                stage_done = update.get("stageDone")
                stage_total = update.get("stageTotal")
                current["progress"]["stageProgress"] = {
                    "done": int(stage_done if stage_done is not None else current["progress"]["stageProgress"].get("done", 0)),
                    "total": int(stage_total if stage_total is not None else current["progress"]["stageProgress"].get("total", 1)),
                }
                if update.get("filesDone") is not None:
                    current["progress"]["filesDone"] = int(update["filesDone"])
                if update.get("filesTotal") is not None:
                    current["progress"]["total"] = int(update["filesTotal"])
                current["updatedAt"] = now_iso()
                self.append_job_event(
                    job_id,
                    update.get("level", "info"),
                    str(update.get("message") or ""),
                    update.get("filePath"),
                    update.get("meta"),
                    stage=stage,
                )

            request = {
                "jobId": job["id"],
                "prId": pr["id"],
                "snapshotId": job["snapshotId"],
                "title": pr["title"],
                "description": "",
                "baseSha": pr["baseSha"],
                "headSha": pr["headSha"],
                "scope": job["scope"],
                "files": [
                    {
                        "path": file["path"],
                        "language": file["language"],
                        "patch": file["patch"],
                        "hunks": file.get("hunks"),
                        "lineMap": file.get("lineMap"),
                        "fileRole": file.get("fileRole"),
                        "imports": file.get("imports"),
                        "changedSymbols": file.get("changedSymbols"),
                        "surroundingCode": file.get("surroundingCode"),
                        "changedBlocks": file.get("changedBlocks"),
                        "relatedCallSites": file.get("relatedCallSites"),
                    }
                    for file in eligible_files
                ],
                "limits": {"maxComments": job["maxComments"], "maxPerFile": 3},
            }

            try:
                result = await analyze_with_rag(request, on_progress)
                created_count = self._store_generated_suggestions(job["id"], result["suggestions"])
                partial_failures += int(result.get("partialFailures", 0))
                meta = result.get("meta", {})
                self.append_job_event(
                    job["id"],
                    "info",
                    "Анализ pull request завершил все стадии.",
                    None,
                    {
                        "createdSuggestions": created_count,
                        "partialFailures": int(result.get("partialFailures", 0)),
                        "taskCount": meta.get("taskCount"),
                    },
                    stage="ranking",
                )
            except asyncio.CancelledError:
                job["status"] = "canceled"
                job["updatedAt"] = now_iso()
                self.append_job_event(job["id"], "warn", "Задача отменена пользователем.", stage="review")
                return
            except Exception as error:
                partial_failures += 1
                self.append_job_event(
                    job["id"],
                    "error",
                    f"Ошибка анализа PR: {error}",
                    None,
                    None,
                    stage=job["progress"].get("stage", "review"),
                )
                raise

            job = self.jobs.get(job_id)
            if not job or job["status"] == "canceled":
                return

            job["summary"]["totalSuggestions"] = len(self.suggestions_by_job.get(job["id"], []))
            job["summary"]["partialFailures"] = partial_failures
            job["summary"]["filesSkipped"] = files_skipped
            job["summary"]["warnings"] = []
            if files_skipped > 0:
                job["summary"]["warnings"].append("Some files were skipped due to patch size limits.")
            job["status"] = "done"
            job["progress"]["stage"] = "ranking"
            job["progress"]["stageProgress"] = {"done": 1, "total": 1}
            job["updatedAt"] = now_iso()
            self.append_job_event(
                job["id"],
                "info",
                "Анализ завершен.",
                None,
                {
                    "suggestions": job["summary"]["totalSuggestions"],
                    "partialFailures": job["summary"]["partialFailures"],
                    "filesSkipped": job["summary"]["filesSkipped"],
                },
                stage="ranking",
            )
        except asyncio.CancelledError:
            job = self.jobs.get(job_id)
            if job:
                job["status"] = "canceled"
                job["updatedAt"] = now_iso()
                self.append_job_event(job["id"], "warn", "Задача отменена пользователем.", stage=job["progress"].get("stage"))
            return
        except Exception as error:
            job = self.jobs.get(job_id)
            if job:
                job["status"] = "failed"
                job["errorMessage"] = str(error)
                job["updatedAt"] = now_iso()
                self.append_job_event(job["id"], "error", job["errorMessage"], stage=job["progress"].get("stage"))

    def list_pr_analysis_jobs(self, pr_id: str, cursor: Any, limit: Any) -> dict[str, Any]:
        self.get_pr(pr_id)
        ids = self.jobs_by_pr.get(pr_id, [])
        items = [self.jobs[item_id] for item_id in ids if item_id in self.jobs]
        items.sort(key=lambda item: item["createdAt"], reverse=True)
        return paginate(items, cursor, limit)

    def get_job(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get(job_id)
        if not job:
            raise HttpError(404, "job_not_found", f"Analysis job not found: {job_id}")
        return job

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job["status"] in {"done", "failed"}:
            return job
        job["status"] = "canceled"
        job["updatedAt"] = now_iso()
        self.append_job_event(job_id, "warn", "Задача отменена пользователем.")
        task = self.analysis_tasks.get(job_id)
        if task and not task.done():
            task.cancel()
        return job

    def list_job_events(self, job_id: str, cursor: Any, limit: Any) -> dict[str, Any]:
        self.get_job(job_id)
        ids = self.job_events_by_job.get(job_id, [])
        items = [self.job_events[item_id] for item_id in ids if item_id in self.job_events]
        items.sort(key=lambda item: item["createdAt"])
        return paginate(items, cursor, limit)

    def feedback_score_by_fingerprint(self) -> dict[str, int]:
        scores: dict[str, int] = {}
        for comment in self.comments.values():
            suggestion = self.suggestions.get(comment["suggestionId"])
            if not suggestion:
                continue

            vote_ids = self.feedback_by_comment.get(comment["id"], [])
            votes = [self.feedback_votes[vote_id] for vote_id in vote_ids if vote_id in self.feedback_votes]
            score = sum(1 if vote["vote"] == "up" else -1 for vote in votes)
            scores[suggestion["fingerprint"]] = scores.get(suggestion["fingerprint"], 0) + score

        return scores

    def list_job_suggestions(self, job_id: str, cursor: Any, limit: Any) -> dict[str, Any]:
        self.get_job(job_id)
        ids = self.suggestions_by_job.get(job_id, [])
        items = [self.suggestions[item_id] for item_id in ids if item_id in self.suggestions]
        ranked = rerank_suggestions(items, self.feedback_score_by_fingerprint())
        return paginate(ranked, cursor, limit)

    def publish(self, pr_id: str, job_id: str, mode: str, dry_run: bool) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job["prId"] != pr_id:
            raise HttpError(422, "job_pr_mismatch", "jobId does not belong to this PR")

        idempotency_key = f"{pr_id}:{job_id}:{mode}"
        existing = self.publish_runs.get(idempotency_key)
        if existing:
            comments = [self.comments[item_id] for item_id in existing["publishedCommentIds"] if item_id in self.comments]
            return {
                "publishRunId": existing["id"],
                "publishedCount": len(existing["publishedCommentIds"]),
                "errors": existing["errors"],
                "comments": comments,
                "idempotent": True,
            }

        suggestion_ids = self.suggestions_by_job.get(job["id"], [])
        suggestions = [
            self.suggestions[item_id]
            for item_id in suggestion_ids
            if item_id in self.suggestions and self.suggestions[item_id].get("deliveryMode", "inline") == "inline"
        ]

        run = {
            "id": f"pubrun_{uuid4()}",
            "key": idempotency_key,
            "prId": pr_id,
            "jobId": job_id,
            "mode": mode,
            "dryRun": dry_run,
            "publishedCommentIds": [],
            "errors": [],
            "createdAt": now_iso(),
        }

        if not dry_run:
            for suggestion in suggestions:
                comment = {
                    "id": f"cmt_{uuid4()}",
                    "prId": pr_id,
                    "jobId": job_id,
                    "suggestionId": suggestion["id"],
                    "providerCommentId": f"ghc_{str(uuid4())[:8]}",
                    "mode": mode,
                    "state": "posted",
                    "filePath": suggestion["filePath"],
                    "lineStart": suggestion["lineStart"],
                    "lineEnd": suggestion["lineEnd"],
                    "body": suggestion["body"],
                    "createdAt": run["createdAt"],
                }
                self.comments[comment["id"]] = comment
                self.comments_by_pr.setdefault(pr_id, []).append(comment["id"])
                self.feedback_by_comment[comment["id"]] = []
                run["publishedCommentIds"].append(comment["id"])

        self.publish_runs[idempotency_key] = run
        comments = [self.comments[item_id] for item_id in run["publishedCommentIds"] if item_id in self.comments]
        return {
            "publishRunId": run["id"],
            "publishedCount": len(run["publishedCommentIds"]),
            "errors": run["errors"],
            "comments": comments,
            "idempotent": False,
        }

    def list_pr_comments(self, pr_id: str, cursor: Any, limit: Any) -> dict[str, Any]:
        self.get_pr(pr_id)
        ids = self.comments_by_pr.get(pr_id, [])
        items = [self.comments[item_id] for item_id in ids if item_id in self.comments]
        items.sort(key=lambda item: item["createdAt"])
        return paginate(items, cursor, limit)

    def list_repo_runs(self, repo_id: str, cursor: Any, limit: Any) -> dict[str, Any]:
        repo = self.get_repo(repo_id)
        prs = [item for item in self.pull_requests.values() if item["repoId"] == repo["id"]]
        runs: list[dict[str, Any]] = []

        for pr in prs:
            job_ids = self.jobs_by_pr.get(pr["id"], [])
            for job_id in job_ids:
                job = self.jobs.get(job_id)
                if not job:
                    continue

                suggestion_count = len(self.suggestions_by_job.get(job["id"], []))
                comments = [item for item in self.comments.values() if item["jobId"] == job["id"]]

                feedback_score = 0
                for comment in comments:
                    vote_ids = self.feedback_by_comment.get(comment["id"], [])
                    votes = [self.feedback_votes[item_id] for item_id in vote_ids if item_id in self.feedback_votes]
                    feedback_score += sum(1 if vote["vote"] == "up" else -1 for vote in votes)

                runs.append(
                    {
                        "runId": job["id"],
                        "jobId": job["id"],
                        "repoId": repo["id"],
                        "repoFullName": repo["fullName"],
                        "prId": pr["id"],
                        "prNumber": pr["number"],
                        "prTitle": pr["title"],
                        "status": job["status"],
                        "totalSuggestions": suggestion_count,
                        "publishedComments": len(comments),
                        "feedbackScore": feedback_score,
                        "createdAt": job["createdAt"],
                        "updatedAt": job["updatedAt"],
                    }
                )

        runs.sort(key=lambda item: item["createdAt"], reverse=True)
        return paginate(runs, cursor, limit)

    def upsert_feedback(self, comment_id: str, user_id: str, vote: str, reason: str | None) -> dict[str, Any]:
        comment = self.comments.get(comment_id)
        if not comment:
            raise HttpError(404, "comment_not_found", f"Comment not found: {comment_id}")

        vote_ids = self.feedback_by_comment.get(comment["id"], [])
        existing = next(
            (
                self.feedback_votes[item_id]
                for item_id in vote_ids
                if item_id in self.feedback_votes and self.feedback_votes[item_id]["userId"] == user_id
            ),
            None,
        )

        now = now_iso()
        if existing:
            existing["vote"] = vote
            existing["reason"] = reason
            existing["updatedAt"] = now
            return existing

        feedback = {
            "id": f"fb_{uuid4()}",
            "commentId": comment_id,
            "userId": user_id,
            "vote": vote,
            "reason": reason,
            "createdAt": now,
            "updatedAt": now,
        }
        self.feedback_votes[feedback["id"]] = feedback
        self.feedback_by_comment.setdefault(comment_id, []).append(feedback["id"])
        return feedback

    def get_comment_feedback(self, comment_id: str) -> dict[str, Any]:
        comment = self.comments.get(comment_id)
        if not comment:
            raise HttpError(404, "comment_not_found", f"Comment not found: {comment_id}")

        vote_ids = self.feedback_by_comment.get(comment["id"], [])
        votes = [self.feedback_votes[item_id] for item_id in vote_ids if item_id in self.feedback_votes]
        votes.sort(key=lambda item: item["updatedAt"], reverse=True)

        up = len([item for item in votes if item["vote"] == "up"])
        down = len([item for item in votes if item["vote"] == "down"])

        return {
            "comment": comment,
            "votes": votes,
            "totals": {"up": up, "down": down, "score": up - down},
        }

    def get_pr_feedback_summary(self, pr_id: str) -> dict[str, Any]:
        self.get_pr(pr_id)
        comment_ids = self.comments_by_pr.get(pr_id, [])

        by_file: dict[str, dict[str, int]] = {}
        by_category: dict[str, dict[str, int]] = {}
        by_severity: dict[str, dict[str, int]] = {}

        total_up = 0
        total_down = 0

        for comment_id in comment_ids:
            comment = self.comments.get(comment_id)
            if not comment:
                continue

            suggestion = self.suggestions.get(comment["suggestionId"])
            if not suggestion:
                continue

            vote_ids = self.feedback_by_comment.get(comment["id"], [])
            votes = [self.feedback_votes[item_id] for item_id in vote_ids if item_id in self.feedback_votes]

            up = len([item for item in votes if item["vote"] == "up"])
            down = len([item for item in votes if item["vote"] == "down"])
            score = up - down

            total_up += up
            total_down += down

            file_agg = by_file.setdefault(comment["filePath"], {"up": 0, "down": 0, "score": 0, "comments": 0})
            file_agg["up"] += up
            file_agg["down"] += down
            file_agg["score"] += score
            file_agg["comments"] += 1

            category_agg = by_category.setdefault(suggestion["category"], {"up": 0, "down": 0, "score": 0})
            category_agg["up"] += up
            category_agg["down"] += down
            category_agg["score"] += score

            severity_agg = by_severity.setdefault(suggestion["severity"], {"up": 0, "down": 0, "score": 0})
            severity_agg["up"] += up
            severity_agg["down"] += down
            severity_agg["score"] += score

        return {
            "prId": pr_id,
            "overall": {"up": total_up, "down": total_down, "score": total_up - total_down},
            "byFile": [{"filePath": key, **value} for key, value in by_file.items()],
            "byCategory": [{"category": key, **value} for key, value in by_category.items()],
            "bySeverity": [{"severity": key, **value} for key, value in by_severity.items()],
        }

    def append_job_event(
        self,
        job_id: str,
        level: str,
        message: str,
        file_path: str | None = None,
        meta: dict[str, Any] | None = None,
        stage: str | None = None,
    ) -> None:
        event = {
            "id": f"evt_{uuid4()}",
            "jobId": job_id,
            "level": level,
            "message": message,
            "filePath": file_path,
            "stage": stage,
            "meta": meta,
            "createdAt": now_iso(),
        }
        self.job_events[event["id"]] = event
        self.job_events_by_job.setdefault(job_id, []).append(event["id"])
