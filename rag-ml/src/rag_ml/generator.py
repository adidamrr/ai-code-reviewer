from __future__ import annotations

from .model_client import ModelClientError, ModelClientProtocol, StructuredOutputError
from .prompt_builder import (
    build_detection_line_messages,
    build_detection_messages,
    build_explainer_messages,
    build_json_repair_messages,
)
from .schemas import (
    CandidateFinding,
    ContextPack,
    FindingExplanation,
    FindingOutline,
    FindingOutlineEnvelope,
    HunkTask,
)


SEVERITY_ALIASES = {
    "warn": "medium",
    "warning": "medium",
    "minor": "low",
    "moderate": "medium",
    "major": "high",
    "error": "high",
    "fatal": "critical",
}

CATEGORY_ALIASES = {
    "bug": "bugs",
    "bugs": "bugs",
    "style": "style",
    "perf": "performance",
    "performance": "performance",
    "security": "security",
    "sec": "security",
}


class SuggestionGenerator:
    def __init__(self, client: ModelClientProtocol) -> None:
        self.client = client
        self.outline_schema = FindingOutlineEnvelope.model_json_schema()
        self.explainer_schema = FindingExplanation.model_json_schema()

    async def detect(
        self,
        task: HunkTask,
        categories: list[str],
        context_pack: ContextPack,
        *,
        generation_model: str | None = None,
        repair_model: str | None = None,
        max_findings: int = 2,
    ) -> FindingOutlineEnvelope:
        messages = build_detection_messages(task, categories, context_pack, max_findings=max_findings)
        last_error: Exception | None = None
        for _attempt in range(2):
            try:
                payload = await self.client.chat_structured(messages, self.outline_schema, model=generation_model)
                return self._normalize_envelope(
                    FindingOutlineEnvelope.model_validate(payload),
                    task,
                    context_pack,
                )
            except StructuredOutputError as error:
                last_error = error
                repaired = await self._repair_invalid_json(
                    task,
                    categories,
                    context_pack,
                    error.raw_content,
                    repair_model=repair_model,
                    max_findings=max_findings,
                )
                if repaired is not None:
                    return repaired
            except (ModelClientError, ValueError) as error:
                last_error = error
        line_fallback = await self._detect_with_line_format(
            task,
            categories,
            context_pack,
            generation_model=generation_model,
            max_findings=max_findings,
        )
        if line_fallback is not None:
            return line_fallback
        if last_error:
            raise last_error
        return FindingOutlineEnvelope(findings=[])

    async def explain(
        self,
        task: HunkTask,
        outline: FindingOutline,
        context_pack: ContextPack,
        *,
        generation_model: str | None = None,
    ) -> CandidateFinding:
        messages = build_explainer_messages(task, outline, context_pack)
        title = outline.shortLabel.strip().capitalize()
        body = (
            f"Potential {outline.category} issue near the changed lines. "
            f"Review the affected code path and confirm the behavior around {outline.shortLabel}."
        )
        try:
            payload = await self.client.chat_structured(messages, self.explainer_schema, model=generation_model)
            explanation = FindingExplanation.model_validate(payload)
            title = explanation.title.strip() or title
            body = explanation.body.strip() or body
        except (ModelClientError, ValueError):
            pass
        return CandidateFinding(
            filePath=outline.filePath,
            lineStart=outline.lineStart,
            lineEnd=outline.lineEnd,
            severity=outline.severity,
            category=outline.category,
            title=title,
            body=body,
            confidence=outline.confidence,
            evidenceRefs=outline.evidenceRefs,
        )

    async def _repair_invalid_json(
        self,
        task: HunkTask,
        categories: list[str],
        context_pack: ContextPack,
        invalid_content: str,
        *,
        repair_model: str | None = None,
        max_findings: int,
    ) -> FindingOutlineEnvelope | None:
        repair_messages = build_json_repair_messages(
            task,
            categories,
            context_pack,
            invalid_content,
            max_findings=max_findings,
        )
        try:
            payload = await self.client.chat_structured(
                repair_messages,
                self.outline_schema,
                model=repair_model or getattr(self.client, "repair_model", None),
            )
            return self._normalize_envelope(
                FindingOutlineEnvelope.model_validate(payload),
                task,
                context_pack,
            )
        except (ModelClientError, ValueError):
            return None

    async def _detect_with_line_format(
        self,
        task: HunkTask,
        categories: list[str],
        context_pack: ContextPack,
        *,
        generation_model: str | None = None,
        max_findings: int,
    ) -> FindingOutlineEnvelope | None:
        if not hasattr(self.client, "chat_text"):
            return None
        messages = build_detection_line_messages(task, categories, context_pack, max_findings=max_findings)
        try:
            content = await self.client.chat_text(messages, model=generation_model)
        except ModelClientError:
            return None
        return self._normalize_envelope(
            self._parse_line_format(content, task),
            task,
            context_pack,
        )

    def _parse_line_format(self, content: str, task: HunkTask) -> FindingOutlineEnvelope:
        findings: list[FindingOutline] = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line == "NO_FINDINGS":
                continue
            if not line.startswith("FINDING|"):
                continue
            parts = line.split("|", 6)
            if len(parts) != 7:
                continue
            _, category, severity, line_start, line_end, short_label, evidence_blob = parts
            findings.append(
                FindingOutline(
                    filePath=task.filePath,
                    lineStart=self._safe_int(line_start, task.firstChangedLine),
                    lineEnd=self._safe_int(line_end, task.firstChangedLine),
                    severity=severity.strip(),
                    category=category.strip(),
                    shortLabel=short_label.strip(),
                    confidence=0.72,
                    evidenceRefs=[
                        ref.strip()
                        for ref in evidence_blob.split(",")
                        if ref.strip()
                    ],
                )
            )
        return FindingOutlineEnvelope(findings=findings)

    @staticmethod
    def _safe_int(value: str, default: int) -> int:
        try:
            return int(value.strip())
        except (TypeError, ValueError):
            return default

    def _normalize_envelope(
        self,
        envelope: FindingOutlineEnvelope,
        task: HunkTask,
        context_pack: ContextPack,
    ) -> FindingOutlineEnvelope:
        allowed_refs = {
            candidate.refId
            for candidate in (
                context_pack.codeEvidenceCandidates
                + context_pack.ruleEvidenceCandidates
                + context_pack.docEvidenceCandidates
                + context_pack.historyEvidenceCandidates
            )
        }
        normalized_findings: list[FindingOutline] = []
        for finding in envelope.findings:
            severity = self._normalize_severity(finding.severity)
            category = self._normalize_category(finding.category)
            evidence_refs = [ref for ref in finding.evidenceRefs if ref in allowed_refs]
            normalized_findings.append(
                finding.model_copy(
                    update={
                        "filePath": finding.filePath or task.filePath,
                        "severity": severity,
                        "category": category,
                        "evidenceRefs": evidence_refs,
                    }
                )
            )
        return FindingOutlineEnvelope(findings=normalized_findings)

    @staticmethod
    def _normalize_severity(value: str) -> str:
        key = value.strip().lower()
        return SEVERITY_ALIASES.get(key, key)

    @staticmethod
    def _normalize_category(value: str) -> str:
        key = value.strip().lower()
        return CATEGORY_ALIASES.get(key, key)
