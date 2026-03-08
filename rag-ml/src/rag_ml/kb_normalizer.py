from __future__ import annotations

import re
from pathlib import Path

from .schemas import DocumentDescriptor, NormalizedDocument, SectionSpan

MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
TEXT_HEADING = re.compile(r"^(?:[A-Z][A-Z0-9 /()_-]{2,}|\d+(?:\.\d+)*\s+.+|[A-Z][A-Za-z0-9 /()_-]{3,}:)$")
RST_UNDERLINE = re.compile(r"^([=\-`:'\"~^_*+#<>])\1{2,}\s*$")


def _normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\t", "    ")
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip() + "\n"


def _extract_sections(text: str, source_title: str, suffix: str) -> list[SectionSpan]:
    lines = text.splitlines(keepends=True)
    markers: list[tuple[int, list[str]]] = []
    stack: list[str] = [source_title]
    offset = 0

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            offset += len(line)
            continue

        match = MARKDOWN_HEADING.match(stripped) if suffix == ".md" else None
        if match:
            level = len(match.group(1))
            title = match.group(2).strip()
            stack = stack[:level]
            if len(stack) == 0:
                stack = [source_title]
            if len(stack) == level:
                stack[-1] = title
            else:
                stack.append(title)
            markers.append((offset, stack.copy()))
            offset += len(line)
            continue

        prev_blank = index == 0 or not lines[index - 1].strip()
        next_stripped = lines[index + 1].strip() if index + 1 < len(lines) else ""
        if suffix == ".txt" and len(stripped) <= 160 and RST_UNDERLINE.match(next_stripped):
            markers.append((offset, [source_title, stripped.rstrip(":")]))
        elif (
            suffix == ".txt"
            and prev_blank
            and len(stripped) <= 100
            and TEXT_HEADING.match(stripped)
            and (not next_stripped or RST_UNDERLINE.match(next_stripped))
        ):
            markers.append((offset, [source_title, stripped.rstrip(":")]))

        offset += len(line)

    if not markers:
        return [SectionSpan(headingPath=[source_title], charStart=0, charEnd=len(text))]

    sections: list[SectionSpan] = []
    for marker_index, (start, heading_path) in enumerate(markers):
        end = markers[marker_index + 1][0] if marker_index + 1 < len(markers) else len(text)
        if end <= start:
            continue
        sections.append(SectionSpan(headingPath=heading_path, charStart=start, charEnd=end))

    if sections[0].charStart > 0:
        sections.insert(0, SectionSpan(headingPath=[source_title], charStart=0, charEnd=sections[0].charStart))

    return sections


def normalize_descriptor(descriptor: DocumentDescriptor) -> NormalizedDocument:
    doc_path = Path(descriptor.docPath)
    raw_text = doc_path.read_text(encoding="utf-8", errors="ignore")
    text = _normalize_text(raw_text)
    suffix = doc_path.suffix.lower()
    sections = _extract_sections(text, descriptor.sourceTitle, suffix)
    document_id = f"{descriptor.namespace}:{descriptor.sourceId}:{doc_path.stem}"
    return NormalizedDocument(
        documentId=document_id,
        namespace=descriptor.namespace,
        language=descriptor.language,
        sourceId=descriptor.sourceId,
        sourceTitle=descriptor.sourceTitle,
        sourceUrl=descriptor.sourceUrl,
        docPath=descriptor.docPath,
        text=text,
        sections=sections,
    )
