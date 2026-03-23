from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import AppConfig, load_config
from .errors import HttpError
from .github_session import GithubSessionStore
from .pagination import paginate
from .rag_adapter import get_rag_status
from .store import InMemoryStore

API_PREFIXES = (
    "/healthz",
    "/readyz",
    "/webhooks",
    "/integrations",
    "/github/session",
    "/gitlab/session",
    "/repos",
    "/prs",
    "/snapshots",
    "/analysis-jobs",
    "/comments",
)
EXCLUDED_AUTH_PREFIXES = ("/healthz", "/readyz", "/webhooks/github")


def safe_compare(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def is_api_path(pathname: str) -> bool:
    return pathname.startswith(API_PREFIXES)


def parse_scope(raw: Any) -> list[str]:
    valid_scope = {"security", "bugs", "performance"}
    if not isinstance(raw, list) or len(raw) == 0:
        return ["bugs"]

    scope = [str(entry) for entry in raw]
    invalid = next((entry for entry in scope if entry not in valid_scope), None)
    if invalid:
        raise HttpError(400, "validation_error", f"Unsupported scope value: {invalid}")

    return scope


def resolve_generation_model(raw: Any) -> tuple[str, str]:
    profile = str(raw or "yandexgpt-pro").strip() or "yandexgpt-pro"
    folder_id = (os.getenv("RAG_YANDEX_FOLDER_ID") or "").strip()
    fallback = (os.getenv("RAG_GENERATION_MODEL") or "").strip()

    if not folder_id:
        if fallback:
            return profile, fallback
        raise HttpError(500, "model_config_error", "RAG_YANDEX_FOLDER_ID is not configured")

    allowed = {
        "yandexgpt-pro": f"gpt://{folder_id}/yandexgpt/latest",
        "yandexgpt-lite": f"gpt://{folder_id}/yandexgpt-lite",
        "qwen3-235b": f"gpt://{folder_id}/qwen3-235b-a22b-fp8/latest",
        "gpt-oss-120b": f"gpt://{folder_id}/gpt-oss-120b/latest",
    }
    model_uri = allowed.get(profile)
    if not model_uri:
        raise HttpError(400, "validation_error", f"Unsupported modelProfile value: {profile}")
    return profile, model_uri


def normalize_pr_state(value: Any) -> str:
    if value == "closed":
        return "closed"
    if value == "all":
        return "all"
    return "open"


def map_file_status(value: str) -> str:
    if value in {"added", "removed", "renamed"}:
        return value
    return "modified"


def normalize_gitlab_mr_state(value: Any) -> str:
    if value == "opened":
        return "open"
    return "closed"


def map_gitlab_file_status(item: dict[str, Any]) -> str:
    if bool(item.get("new_file")):
        return "added"
    if bool(item.get("deleted_file")):
        return "removed"
    if bool(item.get("renamed_file")):
        return "renamed"
    return "modified"


async def github_request(client: httpx.AsyncClient, token: str, url: str) -> Any:
    return await github_api_request(client, token, "GET", url)


async def github_api_request(
    client: httpx.AsyncClient,
    token: str,
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    response = await client.request(
        method,
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "SWAGReviewer-Python",
        },
        json=payload,
    )

    text = response.text
    try:
        data = json.loads(text) if text else None
    except json.JSONDecodeError:
        data = None

    if response.status_code >= 400:
        message = data.get("message") if isinstance(data, dict) else response.reason_phrase
        raise HttpError(
            response.status_code,
            "github_api_error",
            f"GitHub API error: {message}",
            {"url": url, "status": response.status_code},
        )

    return data


async def github_post(client: httpx.AsyncClient, token: str, url: str, payload: dict[str, Any]) -> Any:
    return await github_api_request(client, token, "POST", url, payload)


def build_publish_comment_body(suggestion: dict[str, Any], mode: str) -> str:
    confidence = suggestion.get("confidence")
    confidence_text = "?"
    if isinstance(confidence, (int, float)):
        confidence_text = str(int(round(float(confidence) * 100)))

    lines = [
        f"Title: {str(suggestion.get('title') or '').strip()}",
        f"Why it matters: {str(suggestion.get('body') or '').strip()}",
        f"Location: {suggestion.get('filePath')}:{suggestion.get('lineStart')}-{suggestion.get('lineEnd')}",
    ]
    if mode == "issue_comments":
        lines.append("Delivery: summary")
    lines.extend(
        [
            f"Category: {suggestion.get('category')}",
            f"Severity: {suggestion.get('severity')}",
            f"Confidence: {confidence_text}%",
        ]
    )

    citations = [
        item for item in (suggestion.get("citations") or [])
        if isinstance(item, dict) and item.get("url") and item.get("title")
    ]
    if citations:
        lines.append("")
        lines.append("References:")
        for citation in citations[:2]:
            lines.append(f"- [{citation['title']}]({citation['url']})")

    return "\n\n".join([line for line in lines if line])


def humanize_github_publish_error(error: HttpError, mode: str) -> str:
    raw_message = error.message.removeprefix("GitHub API error: ").strip()
    if error.status_code in {401, 403} and "personal access token" in raw_message.lower():
        if mode == "issue_comments":
            return "Токен не имеет прав на публикацию Conversation comments. Проверьте Issues: write или repo scope."
        return "Токен не имеет прав на публикацию review comments. Проверьте Pull requests: write или repo scope."
    if error.status_code == 404:
        return "GitHub не дал доступ к этому PR или репозиторию. Обычно это неверный repo scope или токен не видит репозиторий."
    if error.status_code == 422:
        return f"GitHub не принял comment для текущего diff: {raw_message or 'invalid review comment payload'}"
    return raw_message or error.message


async def publish_github_comments(
    client: httpx.AsyncClient,
    token: str,
    *,
    owner: str,
    repo: str,
    pr_number: int,
    commit_sha: str,
    mode: str,
    suggestions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    comments: list[dict[str, Any]] = []
    errors: list[str] = []

    for suggestion in suggestions:
        body = build_publish_comment_body(suggestion, mode)
        try:
            if mode == "issue_comments":
                payload = {"body": body}
                response = await github_post(
                    client,
                    token,
                    f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments",
                    payload,
                )
            else:
                line_start = int(suggestion.get("lineStart") or 1)
                line_end = int(suggestion.get("lineEnd") or line_start)
                payload = {
                    "body": body,
                    "commit_id": commit_sha,
                    "path": str(suggestion.get("filePath") or ""),
                    "line": line_end,
                    "side": "RIGHT",
                }
                if line_start < line_end:
                    payload["start_line"] = line_start
                    payload["start_side"] = "RIGHT"
                response = await github_post(
                    client,
                    token,
                    f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/comments",
                    payload,
                )

            if not isinstance(response, dict):
                raise HttpError(502, "github_api_error", "GitHub API error: invalid publish response")

            comments.append(
                {
                    "suggestionId": suggestion["id"],
                    "providerCommentId": str(response.get("id") or ""),
                    "state": "posted",
                    "filePath": suggestion["filePath"],
                    "lineStart": suggestion["lineStart"],
                    "lineEnd": suggestion["lineEnd"],
                    "body": body,
                    "createdAt": response.get("created_at") or datetime_utc_iso(),
                }
            )
        except HttpError as error:
            errors.append(
                f"{suggestion['filePath']}:{suggestion['lineStart']}: {humanize_github_publish_error(error, mode)}"
            )

    return comments, errors


def humanize_gitlab_publish_error(error: HttpError, mode: str) -> str:
    raw_message = error.message.removeprefix("GitLab API error: ").strip()
    if error.status_code in {401, 403}:
        if mode == "issue_comments":
            return "Токен не имеет прав на публикацию MR notes в GitLab."
        return "Токен не имеет прав на публикацию diff discussions в GitLab."
    if error.status_code == 404:
        return "GitLab не дал доступ к merge request или проекту."
    if error.status_code == 422:
        return f"GitLab не принял позицию комментария: {raw_message or 'invalid discussion payload'}"
    return raw_message or error.message


def build_gitlab_discussion_payload(
    suggestion: dict[str, Any],
    *,
    body: str,
    base_sha: str,
    start_sha: str,
    head_sha: str,
) -> dict[str, Any]:
    file_path = str(suggestion.get("filePath") or "")
    line_end = int(suggestion.get("lineEnd") or suggestion.get("lineStart") or 1)
    return {
        "body": body,
        "position[position_type]": "text",
        "position[base_sha]": base_sha,
        "position[start_sha]": start_sha,
        "position[head_sha]": head_sha,
        "position[old_path]": file_path,
        "position[new_path]": file_path,
        "position[new_line]": str(line_end),
    }


async def publish_gitlab_comments(
    client: httpx.AsyncClient,
    token: str,
    *,
    project_ref: str,
    mr_iid: int,
    base_sha: str,
    start_sha: str,
    head_sha: str,
    mode: str,
    suggestions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    comments: list[dict[str, Any]] = []
    errors: list[str] = []
    encoded_project = quote(project_ref, safe="")

    for suggestion in suggestions:
        diff_body = build_publish_comment_body(suggestion, mode)
        overview_body = build_publish_comment_body(suggestion, "issue_comments")
        try:
            actual_mode = mode
            response: Any
            if mode == "issue_comments":
                response = await gitlab_api_request(
                    client,
                    token,
                    "POST",
                    f"https://gitlab.com/api/v4/projects/{encoded_project}/merge_requests/{mr_iid}/notes",
                    {"body": overview_body},
                )
            else:
                try:
                    response = await gitlab_api_request(
                        client,
                        token,
                        "POST",
                        f"https://gitlab.com/api/v4/projects/{encoded_project}/merge_requests/{mr_iid}/discussions",
                        build_gitlab_discussion_payload(
                            suggestion,
                            body=diff_body,
                            base_sha=base_sha,
                            start_sha=start_sha,
                            head_sha=head_sha,
                        ),
                    )
                except HttpError as error:
                    if error.status_code not in {400, 404, 409, 422}:
                        raise
                    actual_mode = "issue_comments"
                    response = await gitlab_api_request(
                        client,
                        token,
                        "POST",
                        f"https://gitlab.com/api/v4/projects/{encoded_project}/merge_requests/{mr_iid}/notes",
                        {"body": overview_body},
                    )

            if not isinstance(response, dict):
                raise HttpError(502, "gitlab_api_error", "GitLab API error: invalid publish response")

            provider_comment_id = response.get("id")
            created_at = response.get("created_at")

            if actual_mode == "review_comments":
                notes = response.get("notes")
                first_note = notes[0] if isinstance(notes, list) and notes else None
                if isinstance(first_note, dict):
                    provider_comment_id = first_note.get("id") or provider_comment_id
                    created_at = first_note.get("created_at") or created_at

            comments.append(
                {
                    "suggestionId": suggestion["id"],
                    "providerCommentId": str(provider_comment_id or ""),
                    "state": "posted",
                    "mode": actual_mode,
                    "filePath": suggestion["filePath"],
                    "lineStart": suggestion["lineStart"],
                    "lineEnd": suggestion["lineEnd"],
                    "body": overview_body if actual_mode == "issue_comments" else diff_body,
                    "createdAt": created_at or datetime_utc_iso(),
                }
            )
        except HttpError as error:
            errors.append(
                f"{suggestion['filePath']}:{suggestion['lineStart']}: {humanize_gitlab_publish_error(error, mode)}"
            )

    return comments, errors


async def fetch_user_repos(client: httpx.AsyncClient, token: str) -> list[dict[str, Any]]:
    repos: list[dict[str, Any]] = []
    for page in range(1, 11):
        chunk = await github_request(client, token, f"https://api.github.com/user/repos?sort=updated&per_page=100&page={page}")
        if not isinstance(chunk, list) or len(chunk) == 0:
            break

        repos.extend(chunk)
        if len(chunk) < 100:
            break

    return repos


async def fetch_pull_files(client: httpx.AsyncClient, token: str, owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for page in range(1, 21):
        chunk = await github_request(
            client,
            token,
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files?per_page=100&page={page}",
        )

        if not isinstance(chunk, list) or len(chunk) == 0:
            break

        files.extend(chunk)
        if len(chunk) < 100:
            break

    return files


async def gitlab_api_request(
    client: httpx.AsyncClient,
    token: str,
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    response = await client.request(
        method,
        url,
        headers={
            "PRIVATE-TOKEN": token,
            "User-Agent": "SWAGReviewer-Python",
        },
        data=payload,
    )

    text = response.text
    try:
        data = json.loads(text) if text else None
    except json.JSONDecodeError:
        data = None

    if response.status_code >= 400:
        message = data.get("message") if isinstance(data, dict) else response.reason_phrase
        raise HttpError(
            response.status_code,
            "gitlab_api_error",
            f"GitLab API error: {message}",
            {"url": url, "status": response.status_code},
        )

    return data


async def gitlab_request(client: httpx.AsyncClient, token: str, url: str) -> Any:
    return await gitlab_api_request(client, token, "GET", url)


async def fetch_gitlab_projects(client: httpx.AsyncClient, token: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for page in range(1, 11):
        chunk = await gitlab_request(client, token, f"https://gitlab.com/api/v4/projects?membership=true&per_page=100&page={page}")
        if not isinstance(chunk, list) or len(chunk) == 0:
            break
        items.extend(chunk)
        if len(chunk) < 100:
            break
    return items


async def fetch_gitlab_mr_changes(client: httpx.AsyncClient, token: str, project_id: str, mr_iid: int) -> list[dict[str, Any]]:
    payload = await gitlab_request(client, token, f"https://gitlab.com/api/v4/projects/{project_id}/merge_requests/{mr_iid}/changes")
    if not isinstance(payload, dict):
        return []
    changes = payload.get("changes")
    if not isinstance(changes, list):
        return []
    return [item for item in changes if isinstance(item, dict)]


async def fetch_gitlab_mr_version(client: httpx.AsyncClient, token: str, project_ref: str, mr_iid: int) -> dict[str, Any] | None:
    encoded_project = quote(project_ref, safe="")
    payload = await gitlab_request(
        client,
        token,
        f"https://gitlab.com/api/v4/projects/{encoded_project}/merge_requests/{mr_iid}/versions",
    )
    if not isinstance(payload, list) or not payload:
        return None

    latest = payload[0]
    return latest if isinstance(latest, dict) else None


async def parse_json_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
        if isinstance(body, dict):
            return body
        return {}
    except Exception:
        return {}


def create_app(config: AppConfig) -> FastAPI:
    app = FastAPI(title="SWAGReviewer Backend (Python)", version="1.0.0")
    store = InMemoryStore()
    github_sessions = GithubSessionStore()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-User-Id"],
    )

    @app.middleware("http")
    async def service_token_auth(request: Request, call_next):  # type: ignore[override]
        token = config.api_service_token
        if not token:
            return await call_next(request)

        if request.url.path.startswith(EXCLUDED_AUTH_PREFIXES):
            return await call_next(request)

        authorization = request.headers.get("authorization")
        expected = f"Bearer {token}"
        if authorization != expected:
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "unauthorized",
                        "message": "Invalid or missing service token",
                    }
                },
            )

        return await call_next(request)

    @app.exception_handler(HttpError)
    async def http_error_handler(_request: Request, error: HttpError):  # type: ignore[override]
        payload: dict[str, Any] = {"code": error.code, "message": error.message}
        if error.details is not None:
            payload["details"] = error.details

        return JSONResponse(status_code=error.status_code, content={"error": payload})

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, error: RequestValidationError):  # type: ignore[override]
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Invalid request payload",
                    "details": error.errors(),
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def starlette_error_handler(request: Request, error: StarletteHTTPException):  # type: ignore[override]
        if error.status_code == 404:
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "code": "not_found",
                        "message": f"Route not found: {request.method} {request.url.path}",
                    }
                },
            )

        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": {
                    "code": "http_error",
                    "message": str(error.detail),
                }
            },
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz(response: Response) -> dict[str, Any]:
        rag = await get_rag_status()
        if not rag.get("ready", False):
            response.status_code = 503
            return {"status": "not_ready", "rag": rag}
        return {"status": "ready", "rag": rag}

    @app.post("/webhooks/github", status_code=202)
    async def github_webhook(request: Request) -> dict[str, Any]:
        delivery_id = request.headers.get("x-github-delivery", "unknown")
        event = request.headers.get("x-github-event", "unknown")

        raw_body = await request.body()
        if config.github_webhook_secret:
            signature = request.headers.get("x-hub-signature-256")
            if not signature:
                raise HttpError(401, "signature_missing", "Missing x-hub-signature-256 header")

            digest = "sha256=" + hmac.new(
                config.github_webhook_secret.encode("utf-8"),
                raw_body,
                hashlib.sha256,
            ).hexdigest()

            if not safe_compare(signature, digest):
                raise HttpError(401, "signature_invalid", "Invalid webhook signature")

        return {
            "received": True,
            "event": event,
            "deliveryId": delivery_id,
            "processedAt": datetime_utc_iso(),
        }

    @app.post("/integrations/github/install", status_code=201)
    async def github_install(request: Request) -> dict[str, Any]:
        body = await parse_json_body(request)

        try:
            installation_id = int(body.get("installation_id"))
        except Exception:
            installation_id = -1

        account_login = str(body.get("account_login") or "unknown-org")

        if installation_id <= 0:
            raise HttpError(400, "validation_error", "installation_id must be a positive number")

        installation = store.upsert_github_installation(installation_id, account_login)
        return {
            "installation": {
                "id": installation["id"],
                "installationId": installation["installationId"],
                "accountLogin": installation["accountLogin"],
                "createdAt": installation["createdAt"],
                "updatedAt": installation["updatedAt"],
            }
        }

    @app.post("/github/session", status_code=201)
    async def create_github_session(request: Request) -> dict[str, Any]:
        body = await parse_json_body(request)
        token = str(body.get("token") or "").strip()
        if not token:
            raise HttpError(400, "validation_error", "token is required")

        async with httpx.AsyncClient(timeout=30.0) as client:
            user = await github_request(client, token, "https://api.github.com/user")

        github_login = str(user.get("login") or "") if isinstance(user, dict) else ""
        if not github_login:
            raise HttpError(502, "github_api_error", "GitHub API error: Invalid /user response")

        session = github_sessions.create(token, github_login, provider="github")
        return {
            "sessionId": session["id"],
            "provider": "github",
            "githubLogin": session["githubLogin"],
            "expiresAt": session["expiresAt"],
        }

    @app.get("/github/session/{session_id}")
    async def get_github_session(session_id: str) -> dict[str, Any]:
        session = github_sessions.get_for_provider(session_id, "github")
        return {
            "sessionId": session["id"],
            "provider": session.get("provider", "github"),
            "githubLogin": session["githubLogin"],
            "expiresAt": session["expiresAt"],
            "createdAt": session["createdAt"],
        }

    @app.delete("/github/session/{session_id}", status_code=204)
    async def delete_github_session(session_id: str):
        github_sessions.delete(session_id)
        return Response(status_code=204)

    @app.get("/github/session/{session_id}/repos")
    async def github_session_repos(session_id: str, request: Request) -> dict[str, Any]:
        session = github_sessions.get_for_provider(session_id, "github")

        async with httpx.AsyncClient(timeout=60.0) as client:
            repos = await fetch_user_repos(client, session["token"])

        normalized = []
        for repo in repos:
            if not isinstance(repo, dict):
                continue

            owner_info = repo.get("owner") or {}
            owner_login = str(owner_info.get("login") or "unknown")
            repo_name = str(repo.get("name") or "")
            full_name = str(repo.get("full_name") or f"{owner_login}/{repo_name}")
            default_branch = str(repo.get("default_branch") or "main")

            backend_repo = store.upsert_repository(
                {
                    "owner": owner_login,
                    "name": repo_name,
                    "fullName": full_name,
                    "defaultBranch": default_branch,
                    "accountLogin": session["githubLogin"],
                    "provider": "github",
                }
            )

            normalized.append(
                {
                    "repoId": backend_repo["id"],
                    "providerRepoId": repo.get("id"),
                    "provider": "github",
                    "owner": owner_login,
                    "name": repo_name,
                    "fullName": full_name,
                    "defaultBranch": default_branch,
                    "private": bool(repo.get("private", False)),
                }
            )

        page = paginate(normalized, request.query_params.get("cursor"), request.query_params.get("limit"))
        return {
            "items": page["items"],
            "nextCursor": page["nextCursor"],
            "limit": page["limit"],
        }

    @app.get("/github/session/{session_id}/repos/{owner}/{repo}/prs")
    async def github_session_prs(session_id: str, owner: str, repo: str, request: Request) -> dict[str, Any]:
        session = github_sessions.get_for_provider(session_id, "github")
        state = normalize_pr_state(request.query_params.get("state"))

        async with httpx.AsyncClient(timeout=30.0) as client:
            prs = await github_request(
                client,
                session["token"],
                f"https://api.github.com/repos/{owner}/{repo}/pulls?state={state}&per_page=100",
            )

        if not isinstance(prs, list):
            prs = []

        items = []
        for pr in prs:
            if not isinstance(pr, dict):
                continue

            base = pr.get("base") or {}
            head = pr.get("head") or {}
            user = pr.get("user") or {}

            items.append(
                {
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "state": pr.get("state"),
                    "url": pr.get("html_url"),
                    "authorLogin": user.get("login"),
                    "baseSha": base.get("sha"),
                    "headSha": head.get("sha"),
                    "updatedAt": pr.get("updated_at"),
                }
            )

        return {"items": items, "count": len(items)}

    @app.post("/github/session/{session_id}/repos/{owner}/{repo}/prs/{pr_number}/sync")
    async def github_session_sync(session_id: str, owner: str, repo: str, pr_number: int) -> dict[str, Any]:
        if pr_number <= 0:
            raise HttpError(400, "validation_error", "prNumber must be a positive integer")

        session = github_sessions.get_for_provider(session_id, "github")

        async with httpx.AsyncClient(timeout=60.0) as client:
            pr, files = await gather_pr_data(client, session["token"], owner, repo, pr_number)

        backend_repo = store.upsert_repository(
            {
                "owner": owner,
                "name": repo,
                "fullName": f"{owner}/{repo}",
                "defaultBranch": "main",
                "accountLogin": session["githubLogin"],
                "provider": "github",
            }
        )

        sync_result = store.sync_pull_request(
            backend_repo["id"],
            int(pr.get("number") or pr_number),
            {
                "title": pr.get("title"),
                "state": "open" if pr.get("state") == "open" else "closed",
                "authorLogin": (pr.get("user") or {}).get("login"),
                "url": pr.get("html_url"),
                "baseSha": (pr.get("base") or {}).get("sha"),
                "headSha": (pr.get("head") or {}).get("sha"),
                "commitSha": (pr.get("head") or {}).get("sha"),
                "files": [
                    {
                        "path": file.get("filename"),
                        "status": map_file_status(str(file.get("status") or "modified")),
                        "patch": file.get("patch") or "",
                        "additions": file.get("additions"),
                        "deletions": file.get("deletions"),
                    }
                    for file in files[:500]
                    if isinstance(file, dict)
                ],
            },
        )

        return {
            "repoId": backend_repo["id"],
            "prId": sync_result["pr"]["id"],
            "snapshotId": sync_result["snapshot"]["id"],
            "counts": sync_result["counts"],
            "idempotent": sync_result["idempotent"],
            "source": "github_session",
        }

    @app.post("/gitlab/session", status_code=201)
    async def create_gitlab_session(request: Request) -> dict[str, Any]:
        body = await parse_json_body(request)
        token = str(body.get("token") or "").strip()
        if not token:
            raise HttpError(400, "validation_error", "token is required")

        async with httpx.AsyncClient(timeout=30.0) as client:
            user = await gitlab_request(client, token, "https://gitlab.com/api/v4/user")

        gitlab_login = str(user.get("username") or "") if isinstance(user, dict) else ""
        if not gitlab_login:
            raise HttpError(502, "gitlab_api_error", "GitLab API error: Invalid /user response")

        session = github_sessions.create(token, gitlab_login, provider="gitlab")
        return {"sessionId": session["id"], "provider": "gitlab", "githubLogin": session["githubLogin"], "expiresAt": session["expiresAt"]}

    @app.delete("/gitlab/session/{session_id}", status_code=204)
    async def delete_gitlab_session(session_id: str):
        github_sessions.delete(session_id)
        return Response(status_code=204)

    @app.get("/gitlab/session/{session_id}/repos")
    async def gitlab_session_repos(session_id: str, request: Request) -> dict[str, Any]:
        session = github_sessions.get_for_provider(session_id, "gitlab")
        async with httpx.AsyncClient(timeout=60.0) as client:
            repos = await fetch_gitlab_projects(client, session["token"])

        normalized = []
        for repo in repos:
            owner_login = str((repo.get("namespace") or {}).get("path") or session["githubLogin"])
            repo_name = str(repo.get("path") or "")
            full_name = str(repo.get("path_with_namespace") or f"{owner_login}/{repo_name}")
            default_branch = str(repo.get("default_branch") or "main")
            project_id = str(repo.get("id") or "")

            backend_repo = store.upsert_repository(
                {
                    "owner": owner_login,
                    "name": repo_name,
                    "fullName": full_name,
                    "defaultBranch": default_branch,
                    "accountLogin": session["githubLogin"],
                    "provider": "gitlab",
                }
            )

            normalized.append(
                {
                    "repoId": backend_repo["id"],
                    "providerRepoId": project_id,
                    "provider": "gitlab",
                    "owner": owner_login,
                    "name": repo_name,
                    "fullName": full_name,
                    "defaultBranch": default_branch,
                    "private": str(repo.get("visibility") or "private") != "public",
                }
            )

        page = paginate(normalized, request.query_params.get("cursor"), request.query_params.get("limit"))
        return {"items": page["items"], "nextCursor": page["nextCursor"], "limit": page["limit"]}

    @app.get("/gitlab/session/{session_id}/repos/{project_id}/mrs")
    async def gitlab_session_mrs(session_id: str, project_id: str, request: Request) -> dict[str, Any]:
        session = github_sessions.get_for_provider(session_id, "gitlab")
        state = normalize_pr_state(request.query_params.get("state"))
        gitlab_state = "opened" if state == "open" else state
        async with httpx.AsyncClient(timeout=30.0) as client:
            mrs = await gitlab_request(client, session["token"], f"https://gitlab.com/api/v4/projects/{project_id}/merge_requests?scope=all&state={gitlab_state}&per_page=100")
        if not isinstance(mrs, list):
            mrs = []
        items = []
        for mr in mrs:
            if not isinstance(mr, dict):
                continue

            diff_refs = mr.get("diff_refs") or {}
            items.append(
                {
                    "number": mr.get("iid"),
                    "title": mr.get("title"),
                    "state": normalize_gitlab_mr_state(mr.get("state")),
                    "url": mr.get("web_url"),
                    "authorLogin": (mr.get("author") or {}).get("username"),
                    "baseSha": diff_refs.get("base_sha"),
                    "headSha": mr.get("sha"),
                    "updatedAt": mr.get("updated_at"),
                }
            )
        return {"items": items, "count": len(items)}

    @app.post("/gitlab/session/{session_id}/repos/{project_id}/mrs/{mr_iid}/sync")
    async def gitlab_session_sync(session_id: str, project_id: str, mr_iid: int) -> dict[str, Any]:
        if mr_iid <= 0:
            raise HttpError(400, "validation_error", "mrIid must be a positive integer")
        session = github_sessions.get_for_provider(session_id, "gitlab")
        async with httpx.AsyncClient(timeout=60.0) as client:
            mr = await gitlab_request(client, session["token"], f"https://gitlab.com/api/v4/projects/{project_id}/merge_requests/{mr_iid}")
            files = await fetch_gitlab_mr_changes(client, session["token"], project_id, mr_iid)
            project = await gitlab_request(client, session["token"], f"https://gitlab.com/api/v4/projects/{project_id}")
        full_name = str((project or {}).get("path_with_namespace") or f"gitlab/{project_id}")
        owner = full_name.split("/")[0]
        name = full_name.split("/")[-1]
        backend_repo = store.upsert_repository(
            {
                "owner": owner,
                "name": name,
                "fullName": full_name,
                "defaultBranch": str((project or {}).get("default_branch") or "main"),
                "accountLogin": session["githubLogin"],
                "provider": "gitlab",
            }
        )
        sync_result = store.sync_pull_request(
            backend_repo["id"],
            int(mr.get("iid") or mr_iid),
            {
                "title": mr.get("title"),
                "state": normalize_gitlab_mr_state(mr.get("state")),
                "authorLogin": (mr.get("author") or {}).get("username"),
                "url": mr.get("web_url"),
                "baseSha": (mr.get("diff_refs") or {}).get("base_sha"),
                "headSha": mr.get("sha"),
                "commitSha": mr.get("sha"),
                "files": [
                    {
                        "path": file.get("new_path") or file.get("old_path"),
                        "status": map_gitlab_file_status(file),
                        "patch": file.get("diff") or "",
                    }
                    for file in files[:500]
                ],
            },
        )
        return {
            "repoId": backend_repo["id"],
            "prId": sync_result["pr"]["id"],
            "snapshotId": sync_result["snapshot"]["id"],
            "counts": sync_result["counts"],
            "idempotent": sync_result["idempotent"],
            "source": "gitlab_session",
        }

    @app.get("/repos")
    async def list_repos(request: Request) -> dict[str, Any]:
        page = store.list_repos(request.query_params.get("cursor"), request.query_params.get("limit"))
        return {"items": page["items"], "nextCursor": page["nextCursor"], "limit": page["limit"]}

    @app.get("/repos/{repo_id}/runs")
    async def list_repo_runs(repo_id: str, request: Request) -> dict[str, Any]:
        page = store.list_repo_runs(repo_id, request.query_params.get("cursor"), request.query_params.get("limit"))
        return {"items": page["items"], "nextCursor": page["nextCursor"], "limit": page["limit"]}

    @app.post("/repos/{repo_id}/prs/{pr_number}/sync")
    async def sync_pr(repo_id: str, pr_number: int, request: Request) -> dict[str, Any]:
        if pr_number <= 0:
            raise HttpError(400, "validation_error", "prNumber must be a positive integer")

        body = await parse_json_body(request)
        sync_result = store.sync_pull_request(repo_id, pr_number, body)

        return {
            "prId": sync_result["pr"]["id"],
            "snapshotId": sync_result["snapshot"]["id"],
            "counts": sync_result["counts"],
            "idempotent": sync_result["idempotent"],
        }

    @app.get("/prs/{pr_id}")
    async def get_pr(pr_id: str) -> dict[str, Any]:
        pr = store.get_pr(pr_id)
        latest_snapshot = store.get_snapshot(pr["latestSnapshotId"])["snapshot"] if pr.get("latestSnapshotId") else None
        return {"pr": pr, "latestSnapshot": latest_snapshot}

    @app.get("/prs/{pr_id}/files")
    async def get_pr_files(pr_id: str, request: Request) -> dict[str, Any]:
        page = store.list_pr_files(pr_id, request.query_params.get("cursor"), request.query_params.get("limit"))
        return {"items": page["items"], "nextCursor": page["nextCursor"], "limit": page["limit"]}

    @app.get("/prs/{pr_id}/diff")
    async def get_pr_diff(pr_id: str, request: Request) -> dict[str, Any]:
        file_path = request.query_params.get("file")
        items = store.get_pr_diff(pr_id, file_path)
        return {"items": items, "count": len(items)}

    @app.get("/prs/{pr_id}/snapshots")
    async def get_pr_snapshots(pr_id: str) -> dict[str, Any]:
        items = store.list_pr_snapshots(pr_id)
        return {"items": items, "count": len(items)}

    @app.get("/snapshots/{snapshot_id}")
    async def get_snapshot(snapshot_id: str) -> dict[str, Any]:
        result = store.get_snapshot(snapshot_id)
        return {
            "snapshot": result["snapshot"],
            "files": result["files"],
            "counts": {
                "files": len(result["files"]),
                "additions": result["snapshot"]["additions"],
                "deletions": result["snapshot"]["deletions"],
            },
        }

    @app.post("/prs/{pr_id}/analysis-jobs", status_code=201)
    async def create_analysis_job(pr_id: str, request: Request) -> dict[str, Any]:
        body = await parse_json_body(request)
        snapshot_id = str(body.get("snapshotId") or "")
        if not snapshot_id:
            raise HttpError(400, "validation_error", "snapshotId is required")

        try:
            max_comments = int(body.get("maxComments") or 50)
        except Exception:
            max_comments = -1

        if max_comments <= 0:
            raise HttpError(400, "validation_error", "maxComments must be a positive number")

        scope = parse_scope(body.get("scope"))
        model_profile, generation_model = resolve_generation_model(body.get("modelProfile"))
        files = [str(item) for item in body.get("files", [])] if isinstance(body.get("files"), list) else None

        job = await store.create_analysis_job(
            pr_id,
            {
                "snapshotId": snapshot_id,
                "scope": scope,
                "files": files,
                "maxComments": max_comments,
                "generationModelProfile": model_profile,
                "generationModel": generation_model,
            },
        )

        return {
            "jobId": job["id"],
            "status": job["status"],
            "progress": job["progress"],
        }

    @app.get("/prs/{pr_id}/analysis-jobs")
    async def list_analysis_jobs(pr_id: str, request: Request) -> dict[str, Any]:
        page = store.list_pr_analysis_jobs(pr_id, request.query_params.get("cursor"), request.query_params.get("limit"))
        return {"items": page["items"], "nextCursor": page["nextCursor"], "limit": page["limit"]}

    @app.get("/analysis-jobs/{job_id}")
    async def get_analysis_job(job_id: str) -> dict[str, Any]:
        return store.get_job(job_id)

    @app.post("/analysis-jobs/{job_id}/cancel")
    async def cancel_analysis_job(job_id: str) -> dict[str, Any]:
        return store.cancel_job(job_id)

    @app.get("/analysis-jobs/{job_id}/results")
    async def get_analysis_results(job_id: str, request: Request) -> dict[str, Any]:
        page = store.list_job_suggestions(job_id, request.query_params.get("cursor"), request.query_params.get("limit"))
        return {"items": page["items"], "nextCursor": page["nextCursor"], "limit": page["limit"]}

    @app.get("/analysis-jobs/{job_id}/events")
    async def get_analysis_events(job_id: str, request: Request) -> dict[str, Any]:
        page = store.list_job_events(job_id, request.query_params.get("cursor"), request.query_params.get("limit"))
        return {"items": page["items"], "nextCursor": page["nextCursor"], "limit": page["limit"]}

    @app.post("/prs/{pr_id}/publish")
    async def publish(pr_id: str, request: Request) -> dict[str, Any]:
        body = await parse_json_body(request)
        job_id = str(body.get("jobId") or "")
        if not job_id:
            raise HttpError(400, "validation_error", "jobId is required")

        mode = str(body.get("mode") or "review_comments")
        if mode not in {"review_comments", "issue_comments"}:
            raise HttpError(400, "validation_error", "mode must be review_comments or issue_comments")

        dry_run = bool(body.get("dryRun"))
        session_id = str(body.get("sessionId") or "").strip()

        existing = store.get_publish_result(pr_id, job_id, mode, dry_run)
        if existing:
            return existing

        if dry_run:
            result = store.publish(pr_id, job_id, mode, dry_run)
            return {
                "publishRunId": result["publishRunId"],
                "publishedCount": result["publishedCount"],
                "errors": result["errors"],
                "comments": result["comments"],
                "idempotent": result["idempotent"],
            }

        pr = store.get_pr(pr_id)
        repo = store.get_repo(pr["repoId"])
        provider = str(repo.get("provider") or "github")
        if provider not in {"github", "gitlab"}:
            raise HttpError(501, "publish_not_supported", f"Real publish is not supported for provider: {provider}")
        if not session_id:
            raise HttpError(400, "validation_error", f"sessionId is required for real {provider} publish")

        job = store.get_job(job_id)
        snapshot = store.get_snapshot(job["snapshotId"])["snapshot"]
        suggestions = store.get_publish_candidates(pr_id, job_id)

        async with httpx.AsyncClient(timeout=60.0) as client:
            if provider == "gitlab":
                session = github_sessions.get_for_provider(session_id, "gitlab")
                version = await fetch_gitlab_mr_version(client, session["token"], repo["fullName"], pr["number"])
                diff_refs = version or {}
                published_comments, errors = await publish_gitlab_comments(
                    client,
                    session["token"],
                    project_ref=repo["fullName"],
                    mr_iid=pr["number"],
                    base_sha=str(diff_refs.get("base_commit_sha") or pr["baseSha"]),
                    start_sha=str(diff_refs.get("start_commit_sha") or pr["baseSha"]),
                    head_sha=str(diff_refs.get("head_commit_sha") or snapshot.get("commitSha") or pr["headSha"]),
                    mode=mode,
                    suggestions=suggestions,
                )
            else:
                session = github_sessions.get_for_provider(session_id, "github")
                published_comments, errors = await publish_github_comments(
                    client,
                    session["token"],
                    owner=repo["owner"],
                    repo=repo["name"],
                    pr_number=pr["number"],
                    commit_sha=str(snapshot.get("commitSha") or pr["headSha"]),
                    mode=mode,
                    suggestions=suggestions,
                )

        result = store.publish(
            pr_id,
            job_id,
            mode,
            dry_run,
            published_comments=published_comments,
            errors=errors,
        )
        return {
            "publishRunId": result["publishRunId"],
            "publishedCount": result["publishedCount"],
            "errors": result["errors"],
            "comments": result["comments"],
            "idempotent": result["idempotent"],
        }

    @app.get("/prs/{pr_id}/comments")
    async def get_pr_comments(pr_id: str, request: Request) -> dict[str, Any]:
        page = store.list_pr_comments(pr_id, request.query_params.get("cursor"), request.query_params.get("limit"))
        return {"items": page["items"], "nextCursor": page["nextCursor"], "limit": page["limit"]}

    @app.put("/comments/{comment_id}/feedback")
    async def upsert_feedback(comment_id: str, request: Request) -> dict[str, Any]:
        body = await parse_json_body(request)
        vote = str(body.get("vote") or "")
        if vote not in {"up", "down"}:
            raise HttpError(400, "validation_error", "vote must be up or down")

        user_id = str(body.get("userId") or request.headers.get("x-user-id") or "anonymous")
        reason = str(body["reason"]) if body.get("reason") else None

        return store.upsert_feedback(comment_id, user_id, vote, reason)

    @app.get("/comments/{comment_id}/feedback")
    async def get_comment_feedback(comment_id: str) -> dict[str, Any]:
        result = store.get_comment_feedback(comment_id)
        return {
            "comment": result["comment"],
            "votes": result["votes"],
            "totals": result["totals"],
        }

    @app.get("/prs/{pr_id}/feedback-summary")
    async def get_feedback_summary(pr_id: str) -> dict[str, Any]:
        return store.get_pr_feedback_summary(pr_id)

    @app.post("/prs/{pr_id}/feedback-dataset")
    async def save_feedback_dataset(pr_id: str) -> dict[str, Any]:
        return store.save_pr_feedback_dataset(pr_id)

    @app.get("/adaptation/status")
    async def get_adaptation_status() -> dict[str, Any]:
        return store.get_adaptation_status()

    @app.post("/adaptation/retrain")
    async def retrain_adaptation() -> dict[str, Any]:
        return store.retrain_adaptation_model()

    frontend_dist = config.frontend_dist_path
    index_file = (frontend_dist / "index.html") if frontend_dist else None

    if config.serve_frontend and frontend_dist and index_file and index_file.exists():

        @app.get("/{full_path:path}", include_in_schema=False)
        async def frontend_catch_all(full_path: str):
            pathname = f"/{full_path}"
            if is_api_path(pathname):
                raise HttpError(404, "not_found", f"Route not found: GET {pathname}")

            requested_file = (frontend_dist / full_path).resolve()
            if full_path and requested_file.is_file() and _is_inside(frontend_dist, requested_file):
                return FileResponse(requested_file)

            return FileResponse(index_file)

    return app


async def gather_pr_data(client: httpx.AsyncClient, token: str, owner: str, repo: str, pr_number: int):
    pr = await github_request(client, token, f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}")
    files = await fetch_pull_files(client, token, owner, repo, pr_number)

    if not isinstance(pr, dict):
        raise HttpError(502, "github_api_error", "GitHub API error: invalid pull request payload")

    return pr, files


def datetime_utc_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_inside(base: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(base)
        return True
    except ValueError:
        return False


app = create_app(load_config())


if __name__ == "__main__":
    import uvicorn

    cfg = load_config()
    uvicorn.run("app.main:app", host="0.0.0.0", port=cfg.port, reload=False)
