from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

import httpx


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env: {name}")
    return value


def request_json(client: httpx.Client, method: str, url: str, **kwargs: Any) -> Any:
    response = client.request(method, url, **kwargs)
    try:
        data = response.json() if response.text else None
    except json.JSONDecodeError:
        data = None

    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code} {response.reason_phrase} for {url}\n{json.dumps(data, indent=2)}")

    return data


def map_file_status(status: str) -> str:
    if status in {"added", "removed", "renamed"}:
        return status
    return "modified"


def fetch_pr_files(client: httpx.Client, owner: str, repo: str, pr_number: int, headers: dict[str, str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 1

    while True:
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files?per_page=100&page={page}"
        chunk = request_json(client, "GET", url, headers=headers)
        if not isinstance(chunk, list) or len(chunk) == 0:
            break

        items.extend(chunk)
        if len(chunk) < 100:
            break

        page += 1

    return items


def main() -> int:
    github_token = require_env("GITHUB_TOKEN")
    owner = require_env("GH_OWNER")
    repo = require_env("GH_REPO")

    try:
        pr_number = int(require_env("GH_PR_NUMBER"))
    except ValueError as error:
        raise RuntimeError("GH_PR_NUMBER must be a positive integer") from error

    if pr_number <= 0:
        raise RuntimeError("GH_PR_NUMBER must be a positive integer")

    backend_base_url = os.getenv("BACKEND_BASE_URL", "http://localhost:4000")
    api_service_token = os.getenv("API_SERVICE_TOKEN", "").strip()
    installation_id = int(os.getenv("GITHUB_INSTALLATION_ID", "999001"))
    account_login = os.getenv("GITHUB_ACCOUNT_LOGIN", owner)
    publish_dry_run = os.getenv("PUBLISH_DRY_RUN", "true").lower() != "false"

    gh_headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "SWAGReviewer-Smoke",
    }

    backend_headers = {"Content-Type": "application/json"}
    if api_service_token:
        backend_headers["Authorization"] = f"Bearer {api_service_token}"

    with httpx.Client(timeout=60.0) as client:
        print("[1/8] Validating GitHub token...")
        user = request_json(client, "GET", "https://api.github.com/user", headers=gh_headers)
        print(f"GitHub user: {user['login']}")

        print("[2/8] Reading sample repos from your account...")
        sample_repos = request_json(client, "GET", "https://api.github.com/user/repos?per_page=5&sort=updated", headers=gh_headers)
        for item in sample_repos:
            suffix = " (private)" if item.get("private") else ""
            print(f"- {item.get('full_name')}{suffix}")

        print(f"[3/8] Fetching PR {owner}/{repo}#{pr_number}...")
        pr = request_json(client, "GET", f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}", headers=gh_headers)

        print("[4/8] Fetching changed files...")
        pr_files = fetch_pr_files(client, owner, repo, pr_number, gh_headers)
        print(f"Changed files in PR: {len(pr_files)}")

        print("[5/8] Registering installation in local backend...")
        request_json(
            client,
            "POST",
            f"{backend_base_url}/integrations/github/install",
            headers=backend_headers,
            json={"installation_id": installation_id, "account_login": account_login},
        )

        list_repos_headers = {"Authorization": f"Bearer {api_service_token}"} if api_service_token else None
        backend_repos = request_json(client, "GET", f"{backend_base_url}/repos", headers=list_repos_headers)
        target_repo = next((item for item in backend_repos["items"] if item.get("owner") == account_login), None)
        if not target_repo:
            if not backend_repos["items"]:
                raise RuntimeError("No repos available in backend after installation registration")
            target_repo = backend_repos["items"][0]

        print(f"[6/8] Syncing PR into backend repoId={target_repo['id']}...")
        sync_payload = {
            "title": pr.get("title"),
            "state": "open" if pr.get("state") == "open" else "closed",
            "authorLogin": (pr.get("user") or {}).get("login"),
            "url": pr.get("html_url"),
            "baseSha": (pr.get("base") or {}).get("sha"),
            "headSha": (pr.get("head") or {}).get("sha"),
            "commitSha": (pr.get("head") or {}).get("sha"),
            "files": [
                {
                    "path": item.get("filename"),
                    "status": map_file_status(str(item.get("status") or "modified")),
                    "patch": item.get("patch") or "",
                    "additions": item.get("additions"),
                    "deletions": item.get("deletions"),
                }
                for item in pr_files[:500]
            ],
        }

        sync_response = request_json(
            client,
            "POST",
            f"{backend_base_url}/repos/{target_repo['id']}/prs/{pr.get('number')}/sync",
            headers=backend_headers,
            json=sync_payload,
        )

        print(f"[7/8] Running analysis job for prId={sync_response['prId']}...")
        job = request_json(
            client,
            "POST",
            f"{backend_base_url}/prs/{sync_response['prId']}/analysis-jobs",
            headers=backend_headers,
            json={
                "snapshotId": sync_response["snapshotId"],
                "scope": ["security", "bugs", "style"],
                "maxComments": 30,
            },
        )

        results_headers = {"Authorization": f"Bearer {api_service_token}"} if api_service_token else None
        deadline = time.time() + 15 * 60
        while time.time() < deadline:
            current_job = request_json(client, "GET", f"{backend_base_url}/analysis-jobs/{job['jobId']}", headers=results_headers)
            if current_job["status"] in {"done", "failed", "canceled"}:
                job = current_job
                break
            time.sleep(2)
        else:
            raise RuntimeError("Timeout ожидания завершения job (15m).")

        results = request_json(client, "GET", f"{backend_base_url}/analysis-jobs/{job['jobId']}/results", headers=results_headers)

        print(f"[8/8] Publishing (dryRun={publish_dry_run})...")
        publish = request_json(
            client,
            "POST",
            f"{backend_base_url}/prs/{sync_response['prId']}/publish",
            headers=backend_headers,
            json={
                "jobId": job["jobId"],
                "mode": "review_comments",
                "dryRun": publish_dry_run,
            },
        )

    print("\nSmoke test completed:")
    print(f"- PR synced: {sync_response['prId']}")
    print(f"- Snapshot: {sync_response['snapshotId']}, files={sync_response['counts']['files']}")
    print(f"- Job: {job['jobId']}, status={job['status']}")
    print(f"- Suggestions: {len(results['items'])}")
    if results["items"]:
        first = results["items"][0]
        print(f"- First suggestion: [{first.get('category')}] {first.get('title')}")
    print(f"- Published: {publish['publishedCount']} (idempotent={publish['idempotent']})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print("Smoke test failed:")
        print(error)
        raise SystemExit(1)
