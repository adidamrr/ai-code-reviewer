from __future__ import annotations

from .ollama_client import OllamaClient, OllamaError
from .prompt_builder import build_detection_messages, build_explainer_messages
from .schemas import (
    CandidateFinding,
    ContextPack,
    FindingExplanation,
    FindingOutline,
    FindingOutlineEnvelope,
    HunkTask,
)


class SuggestionGenerator:
    def __init__(self, client: OllamaClient) -> None:
        self.client = client
        self.outline_schema = FindingOutlineEnvelope.model_json_schema()
        self.explainer_schema = FindingExplanation.model_json_schema()

    async def detect(
        self,
        task: HunkTask,
        categories: list[str],
        context_pack: ContextPack,
        *,
        max_findings: int = 2,
    ) -> FindingOutlineEnvelope:
        messages = build_detection_messages(task, categories, context_pack, max_findings=max_findings)
        last_error: Exception | None = None
        for _attempt in range(2):
            try:
                payload = await self.client.chat_structured(messages, self.outline_schema)
                return FindingOutlineEnvelope.model_validate(payload)
            except (OllamaError, ValueError) as error:
                last_error = error
        if last_error:
            raise last_error
        return FindingOutlineEnvelope(findings=[])

    async def explain(
        self,
        task: HunkTask,
        outline: FindingOutline,
        context_pack: ContextPack,
    ) -> CandidateFinding:
        messages = build_explainer_messages(task, outline, context_pack)
        title = outline.shortLabel.strip().capitalize()
        body = (
            f"Potential {outline.category} issue near the changed lines. "
            f"Review the affected code path and confirm the behavior around {outline.shortLabel}."
        )
        try:
            payload = await self.client.chat_structured(messages, self.explainer_schema)
            explanation = FindingExplanation.model_validate(payload)
            title = explanation.title.strip() or title
            body = explanation.body.strip() or body
        except (OllamaError, ValueError):
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
