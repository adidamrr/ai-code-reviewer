from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

PR_URL_RE = re.compile(r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)(?:/.*)?$", re.IGNORECASE)
PR_SHORT_RE = re.compile(r"^(?P<owner>[^/\s]+)/(?P<repo>[^#\s]+)#(?P<number>\d+)$")
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent


@dataclass
class PRTarget:
    owner: str
    repo: str
    pr_number: int


class ScriptError(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_pr_target(raw: str) -> PRTarget:
    value = raw.strip()

    url_match = PR_URL_RE.match(value)
    if url_match:
        return PRTarget(
            owner=url_match.group("owner"),
            repo=url_match.group("repo"),
            pr_number=int(url_match.group("number")),
        )

    short_match = PR_SHORT_RE.match(value)
    if short_match:
        return PRTarget(
            owner=short_match.group("owner"),
            repo=short_match.group("repo"),
            pr_number=int(short_match.group("number")),
        )

    raise ScriptError(
        "Неверный формат PR. Используй URL вида https://github.com/owner/repo/pull/123 или owner/repo#123"
    )


def github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "SWAGReviewer-MockExport",
    }


def request_json(client: httpx.Client, url: str, token: str) -> Any:
    response = client.get(url, headers=github_headers(token), timeout=60)

    try:
        payload = response.json() if response.text else None
    except json.JSONDecodeError:
        payload = None

    if response.status_code >= 400:
        message = payload.get("message") if isinstance(payload, dict) else response.reason_phrase
        raise ScriptError(f"GitHub API error {response.status_code} for {url}: {message}")

    return payload


def fetch_pr(client: httpx.Client, token: str, target: PRTarget) -> dict[str, Any]:
    url = f"https://api.github.com/repos/{target.owner}/{target.repo}/pulls/{target.pr_number}"
    payload = request_json(client, url, token)
    if not isinstance(payload, dict):
        raise ScriptError(f"Некорректный ответ GitHub для PR {target.owner}/{target.repo}#{target.pr_number}")
    return payload


def fetch_pr_files(client: httpx.Client, token: str, target: PRTarget, max_pages: int = 20) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []

    for page in range(1, max_pages + 1):
        url = (
            f"https://api.github.com/repos/{target.owner}/{target.repo}/pulls/{target.pr_number}/files"
            f"?per_page=100&page={page}"
        )
        chunk = request_json(client, url, token)
        if not isinstance(chunk, list) or len(chunk) == 0:
            break

        files.extend(item for item in chunk if isinstance(item, dict))
        if len(chunk) < 100:
            break

    return files


def map_file_status(status: str) -> str:
    if status in {"added", "removed", "renamed"}:
        return status
    return "modified"


def sanitize_slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()


def resolve_repo_path(raw: str) -> Path:
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    return (REPO_ROOT / candidate).resolve()


def build_mock_record(
    target: PRTarget,
    pr: dict[str, Any],
    files: list[dict[str, Any]],
    preset_id: str,
    label: str,
    default_scope: list[str],
    max_comments: int,
    max_files: int,
) -> dict[str, Any]:
    author = pr.get("user") if isinstance(pr.get("user"), dict) else {}
    base = pr.get("base") if isinstance(pr.get("base"), dict) else {}
    head = pr.get("head") if isinstance(pr.get("head"), dict) else {}

    selected_files = files[:max_files]

    sync_payload = {
        "title": pr.get("title") or f"PR #{target.pr_number}",
        "state": "open" if pr.get("state") == "open" else "closed",
        "authorLogin": author.get("login") or "unknown",
        "url": pr.get("html_url") or f"https://github.com/{target.owner}/{target.repo}/pull/{target.pr_number}",
        "baseSha": base.get("sha") or "",
        "headSha": head.get("sha") or "",
        "commitSha": head.get("sha") or "",
        "files": [
            {
                "path": item.get("filename") or "unknown",
                "status": map_file_status(str(item.get("status") or "modified")),
                "patch": item.get("patch") or "",
                "additions": item.get("additions") or 0,
                "deletions": item.get("deletions") or 0,
            }
            for item in selected_files
        ],
    }

    return {
        "preset": {
            "id": preset_id,
            "label": label,
            "owner": target.owner,
            "repo": target.repo,
            "prNumber": target.pr_number,
            "scope": default_scope,
            "maxComments": max_comments,
        },
        "source": {
            "fetchedAt": now_iso(),
            "prTitle": pr.get("title"),
            "prUrl": pr.get("html_url"),
            "changedFiles": len(files),
            "storedFiles": len(selected_files),
            "truncated": len(files) > len(selected_files),
        },
        "syncPayload": sync_payload,
    }


def write_presets_ts(path: Path, records: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    lines.append('import type { SuggestionScope } from "../types";')
    lines.append("")
    lines.append("export interface DebugPrPreset {")
    lines.append("  id: string;")
    lines.append("  label: string;")
    lines.append("  owner: string;")
    lines.append("  repo: string;")
    lines.append("  prNumber: number;")
    lines.append("  scope?: SuggestionScope[];")
    lines.append("  maxComments?: number;")
    lines.append("}")
    lines.append("")
    lines.append("// Autogenerated by backend/scripts/export_pr_mocks.py")
    lines.append("export const DEBUG_PR_PRESETS: DebugPrPreset[] = [")

    for record in records:
        preset = record["preset"]
        scope_list = ", ".join(f'"{entry}"' for entry in preset["scope"])
        lines.append("  {")
        lines.append(f'    id: "{preset["id"]}",')
        lines.append(f'    label: "{preset["label"]}",')
        lines.append(f'    owner: "{preset["owner"]}",')
        lines.append(f'    repo: "{preset["repo"]}",')
        lines.append(f'    prNumber: {preset["prNumber"]},')
        lines.append(f"    scope: [{scope_list}],")
        lines.append(f'    maxComments: {preset["maxComments"]},')
        lines.append("  },")

    lines.append("];\n")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Скачать 3 PR из GitHub и сохранить как mock-файлы для debug suite",
    )
    parser.add_argument(
        "--pr",
        action="append",
        required=True,
        help="PR URL (https://github.com/owner/repo/pull/123) или owner/repo#123. Используй флаг 3 раза.",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("GITHUB_TOKEN", ""),
        help="GitHub token (по умолчанию берется из GITHUB_TOKEN)",
    )
    parser.add_argument(
        "--out-dir",
        default="frontend/src/debug/mocks",
        help="Куда сохранить mock JSON файлы (относительный путь считается от корня репозитория)",
    )
    parser.add_argument(
        "--scope",
        nargs="+",
        default=["security", "bugs", "style"],
        help="Scope по умолчанию для debug preset",
    )
    parser.add_argument(
        "--max-comments",
        type=int,
        default=40,
        help="maxComments по умолчанию для debug preset",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=500,
        help="Сколько файлов максимум сохранять в syncPayload (по умолчанию 500)",
    )
    parser.add_argument(
        "--write-presets",
        action="store_true",
        help="Перезаписать frontend/src/debug/presets.ts на основе загруженных PR",
    )
    parser.add_argument(
        "--presets-path",
        default="frontend/src/debug/presets.ts",
        help="Путь до presets.ts (используется с --write-presets, относительный путь считается от корня репозитория)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    token = (args.token or "").strip()
    if not token:
        raise ScriptError("Не передан GitHub token. Укажи --token или GITHUB_TOKEN")

    if len(args.pr) != 3:
        raise ScriptError("Для debug-suite нужно ровно 3 PR. Передай --pr три раза.")

    targets = [parse_pr_target(raw) for raw in args.pr]

    out_dir = resolve_repo_path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []

    with httpx.Client() as client:
        for index, target in enumerate(targets, start=1):
            print(f"[{index}/3] Fetching {target.owner}/{target.repo}#{target.pr_number} ...")
            pr = fetch_pr(client, token, target)
            files = fetch_pr_files(client, token, target)

            preset_id = f"preset-{index}"
            label = f"{target.owner}/{target.repo}#{target.pr_number}"
            record = build_mock_record(
                target=target,
                pr=pr,
                files=files,
                preset_id=preset_id,
                label=label,
                default_scope=[str(item) for item in args.scope],
                max_comments=max(1, int(args.max_comments)),
                max_files=max(1, int(args.max_files)),
            )

            filename = f"{index:02d}-{sanitize_slug(target.owner)}-{sanitize_slug(target.repo)}-pr-{target.pr_number}.json"
            file_path = out_dir / filename
            file_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"  saved: {file_path}")

            records.append(record)

    manifest_files = []
    for index, target in enumerate(targets, start=1):
        filename = f"{index:02d}-{sanitize_slug(target.owner)}-{sanitize_slug(target.repo)}-pr-{target.pr_number}.json"
        manifest_files.append(
            {
                "path": str((out_dir / filename).resolve()),
                "presetId": records[index - 1]["preset"]["id"],
                "owner": records[index - 1]["preset"]["owner"],
                "repo": records[index - 1]["preset"]["repo"],
                "prNumber": records[index - 1]["preset"]["prNumber"],
            }
        )

    manifest = {
        "generatedAt": now_iso(),
        "count": len(records),
        "files": manifest_files,
    }

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"manifest: {manifest_path}")

    if args.write_presets:
        presets_path = resolve_repo_path(args.presets_path)
        write_presets_ts(presets_path, records)
        print(f"presets updated: {presets_path}")

    print("Done. Теперь можно использовать эти PR в debug suite.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ScriptError as error:
        print(f"ERROR: {error}")
        raise SystemExit(1)
