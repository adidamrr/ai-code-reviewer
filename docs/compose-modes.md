# Docker Compose modes

Проект поддерживает два отдельных compose-режима.

## 1. Ollama mode

```bash
docker compose -f docker-compose.ollama.yml up --build -d
```

Этот режим поднимает локальный `ollama`, автоматически подтягивает модели и собирает RAG-артефакты.

## 2. API mode

```bash
docker compose -f docker-compose.api.yml up --build -d
```

Этот режим не поднимает `ollama` и использует внешний OpenAI-compatible API. По умолчанию здесь включён sparse-only режим (`RAG_ENABLE_DENSE=false`), чтобы Gemini/OpenAI-compatible провайдеры без доступных embeddings не падали на bootstrap.


### Gemini example

Заполните `.env` так:

```env
RAG_API_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
RAG_API_KEY=ваш_GEMINI_API_KEY
RAG_API_GENERATION_MODEL=gemini-3-flash-preview
RAG_API_EVAL_GENERATION_MODEL=gemini-3-flash-preview
RAG_API_EMBED_MODEL=gemini-embedding-2-preview
RAG_ENABLE_DENSE=false
```

Если ваш провайдер точно поддерживает embeddings, dense retrieval можно вернуть через `RAG_ENABLE_DENSE=true`.


### Если упал bootstrap

```bash
docker compose -f docker-compose.api.yml logs --tail=200 rag-bootstrap
```
