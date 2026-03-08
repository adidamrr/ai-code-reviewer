from __future__ import annotations

from collections import defaultdict

from .file_classifier import classify_file, supports_full_review
from .hunk_selector import select_hunks
from .schemas import HunkTask, PROverview, RagRequest, StaticChecksResult


def _base_categories(requested_scope: set[str], file_path: str, static_types: set[str], file_class: str) -> list[str]:
    categories: list[str] = []
    path = file_path.lower()
    if file_class in {"docs", "resource", "generated"}:
        return []
    if file_class == "test":
        if "bugs" in requested_scope:
            categories.append("bugs")
        return categories
    if "style" in requested_scope:
        categories.append("style")
    if "bugs" in requested_scope:
        categories.append("bugs")
    if "performance" in requested_scope and (
        "perf-loop" in static_types or "large-change" in static_types or any(token in path for token in ("list", "sort", "cache"))
    ):
        categories.append("performance")
    if "security" in requested_scope and (
        "auth-change" in static_types
        or "sql-change" in static_types
        or any(token in path for token in ("auth", "token", "secret", "session"))
    ):
        categories.append("security")
    return categories


def plan_hotspot_tasks(
    request: RagRequest,
    overview: PROverview,
    static_checks: StaticChecksResult,
    *,
    max_hunks_per_file: int,
    max_hotspot_tasks: int,
) -> list[HunkTask]:
    hotspot_boost = {item.filePath: item.risk for item in overview.hotspots}
    signals_by_file = defaultdict(list)
    for signal in [*static_checks.signals, *static_checks.toolFindings]:
        signals_by_file[signal.filePath].append(signal)

    requested_scope = {scope for scope in request.scope if scope in {"style", "bugs", "performance", "security"}}
    planned: list[HunkTask] = []
    for file in request.files:
        file_class = classify_file(file)
        if not supports_full_review(file_class):
            continue
        raw_hunks = select_hunks(file, max_hunks_per_file)
        if not raw_hunks:
            continue
        file_signals = signals_by_file.get(file.path, [])
        static_types = {signal.type for signal in file_signals}
        categories = _base_categories(requested_scope, file.path, static_types, file_class)
        if not categories:
            continue
        signal_ids = [signal.signalId for signal in file_signals]
        signal_messages = [signal.type for signal in file_signals]
        base_boost = hotspot_boost.get(file.path, 0.0) + 0.15 * len(file_signals)
        if file_class in {"repository", "logic", "api"}:
            base_boost += 0.2
        if file_class == "model":
            base_boost += 0.05
        if file.changedBlocks:
            base_boost += min(0.25, 0.08 * len(file.changedBlocks))
        if file.relatedCallSites:
            base_boost += min(0.25, 0.05 * len(file.relatedCallSites))
        for task in raw_hunks:
            planned.append(
                task.model_copy(
                    update={
                        "priority": min(0.99, task.priority / 20.0 + base_boost),
                        "fileClass": file_class,
                        "categories": categories,
                        "reasons": signal_messages or ["diff-priority"],
                        "staticSignalIds": signal_ids,
                    }
                )
            )

    planned.sort(key=lambda item: item.priority, reverse=True)
    return planned[:max_hotspot_tasks]
