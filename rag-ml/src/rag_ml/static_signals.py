from __future__ import annotations

import re

from .schemas import RagFile, StaticChecksResult, StaticSignal

ASYNC_TOKENS = {"await", "future", "async", "then("}
AUTH_TOKENS = {"auth", "token", "login", "session", "refresh", "password", "secret", "bearer"}
PERF_TOKENS = {"for (", "while (", ".map(", ".where(", ".forEach(", "sort(", "fold("}
NULL_TOKENS = {"!", "??", "null", "late "}
NETWORK_TOKENS = {"http", "dio", "request", "response", "fetch", "query", "db"}


def _added_lines(file: RagFile) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    current_new = 1
    for raw_line in file.patch.splitlines():
        if raw_line.startswith("@@"):
            match = re.search(r"\+(\d+)", raw_line)
            current_new = int(match.group(1)) if match else 1
            continue
        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            lines.append((current_new, raw_line[1:]))
            current_new += 1
            continue
        if raw_line.startswith("-") and not raw_line.startswith("---"):
            continue
        current_new += 1
    return lines


def _contains_any(text: str, tokens: set[str]) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in tokens)


def collect_static_signals(files: list[RagFile]) -> StaticChecksResult:
    signals: list[StaticSignal] = []
    for file in files:
        added = _added_lines(file)
        joined = "\n".join(text for _, text in added)
        if not joined.strip():
            continue

        if _contains_any(file.path, AUTH_TOKENS) or _contains_any(joined, AUTH_TOKENS):
            signals.append(
                StaticSignal(
                    signalId=f"{file.path}:auth-change",
                    filePath=file.path,
                    type="auth-change",
                    severity="medium",
                    message="Изменения затрагивают auth/token/session код.",
                )
            )

        async_lines = [line_no for line_no, text in added if _contains_any(text, ASYNC_TOKENS)]
        if async_lines:
            signals.append(
                StaticSignal(
                    signalId=f"{file.path}:async-risk",
                    filePath=file.path,
                    type="async-risk",
                    severity="medium",
                    message="В измененных строках есть async/await flow.",
                    lineStart=min(async_lines),
                    lineEnd=max(async_lines),
                )
            )

        if any(_contains_any(text, PERF_TOKENS) for _, text in added):
            perf_lines = [line_no for line_no, text in added if _contains_any(text, PERF_TOKENS)]
            signals.append(
                StaticSignal(
                    signalId=f"{file.path}:perf-loop",
                    filePath=file.path,
                    type="perf-loop",
                    severity="low",
                    message="В patch есть потенциально дорогая итерация или коллекционная операция.",
                    lineStart=min(perf_lines),
                    lineEnd=max(perf_lines),
                )
            )

        null_lines = [line_no for line_no, text in added if _contains_any(text, NULL_TOKENS)]
        if null_lines and _contains_any(joined, NETWORK_TOKENS):
            signals.append(
                StaticSignal(
                    signalId=f"{file.path}:null-network",
                    filePath=file.path,
                    type="null-network",
                    severity="medium",
                    message="Есть работа с сетевым/IO результатом и nullable/null-like конструкциями.",
                    lineStart=min(null_lines),
                    lineEnd=max(null_lines),
                )
            )

        if len(added) >= 20:
            signals.append(
                StaticSignal(
                    signalId=f"{file.path}:large-change",
                    filePath=file.path,
                    type="large-change",
                    severity="info",
                    message="Файл содержит крупный diff и повышенный риск шумовых регрессий.",
                )
            )

    return StaticChecksResult(signals=signals, toolFindings=[])
