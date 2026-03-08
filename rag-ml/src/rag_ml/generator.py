from __future__ import annotations

from .ollama_client import OllamaClient, OllamaError
from .prompt_builder import build_messages
from .schemas import CandidateSuggestionEnvelope, HunkTask, RetrievalHit


class SuggestionGenerator:
    def __init__(self, client: OllamaClient) -> None:
        self.client = client
        self.schema = CandidateSuggestionEnvelope.model_json_schema()

    async def generate(self, task: HunkTask, category: str, hits: list[RetrievalHit], *, max_suggestions: int = 2) -> CandidateSuggestionEnvelope:
        messages = build_messages(task, category, hits, max_suggestions=max_suggestions)
        last_error: Exception | None = None
        for _attempt in range(3):
            try:
                payload = await self.client.chat_structured(messages, self.schema)
                return CandidateSuggestionEnvelope.model_validate(payload)
            except (OllamaError, ValueError) as error:
                last_error = error
        if last_error:
            raise last_error
        return CandidateSuggestionEnvelope(suggestions=[])
