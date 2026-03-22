# Backend

Backend MVP for AI code review plugin.

## What is implemented now
- Frozen API contract for UI and RAG teams (`docs/openapi.v1.yaml`)
- GitHub token session contract for UI (`docs/openapi.github-session.v1.yaml`)
- Postgres schema v1 (`db/migrations/0001_init.sql`)
- ERD (`docs/erd.mmd`)
- Handoff docs and payload examples (`docs/handoff.md`, `docs/examples/*`)
- Runtime API skeleton for all public endpoints (in-memory adapter)
- Runtime GitHub session endpoints for PAT-based demo flow

## Runtime notes
- Current runtime uses in-memory store to unblock integration work.
- SQL schema is the source for production Postgres implementation.
- API shape and enums are aligned with OpenAPI contract.


## Docker Compose

### Ollama mode
```bash
docker compose -f docker-compose.ollama.yml up --build -d
```

### Yandex mode (without Ollama)
```bash
docker compose -f docker-compose.api.yml up --build -d
```

Оба варианта автоматически подготавливают RAG-артефакты перед запуском backend. В Yandex-режиме сервис `ollama` вообще не поднимается.

Пример для Yandex Cloud AI Studio:
```env
RAG_MODEL_PROVIDER=yandex
RAG_YANDEX_BASE_URL=https://llm.api.cloud.yandex.net/v1
RAG_YANDEX_FOLDER_ID=ваш_folder_id
RAG_YANDEX_API_KEY=ваш_api_key
RAG_YANDEX_DISABLE_DATA_LOGGING=true
RAG_GENERATION_MODEL=gpt://ваш_folder_id/yandexgpt/latest
RAG_EVAL_GENERATION_MODEL=gpt://ваш_folder_id/yandexgpt/latest
RAG_EMBED_MODEL=emb://ваш_folder_id/text-search-doc/latest
RAG_QUERY_EMBED_MODEL=emb://ваш_folder_id/text-search-query/latest
RAG_REPAIR_MODEL=gpt://ваш_folder_id/yandexgpt/latest
```

## Run (Python/FastAPI)
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Single-host mode (backend + frontend on one host):
```bash
cd frontend && npm run build
cd ../backend
SERVE_FRONTEND=true FRONTEND_DIST_PATH=../frontend/dist python main.py
```
Then open `http://localhost:4000`.

## Auth
- If `API_SERVICE_TOKEN` is set, all endpoints except `/healthz`, `/readyz`, `/webhooks/github` require:
  - `Authorization: Bearer <token>`

## RAG model backends
- Recommended mode: `Yandex Cloud AI Studio` (`RAG_MODEL_PROVIDER=yandex`).
- Legacy local mode: `Ollama` (`RAG_MODEL_PROVIDER=ollama`).

Example for Yandex mode:
```bash
export RAG_MODEL_PROVIDER=yandex
export RAG_YANDEX_BASE_URL=https://llm.api.cloud.yandex.net/v1
export RAG_YANDEX_FOLDER_ID=your_folder_id
export RAG_YANDEX_API_KEY=your_api_key
export RAG_YANDEX_DISABLE_DATA_LOGGING=true
export RAG_GENERATION_MODEL=gpt://your_folder_id/yandexgpt/latest
export RAG_EVAL_GENERATION_MODEL=gpt://your_folder_id/yandexgpt/latest
export RAG_EMBED_MODEL=emb://your_folder_id/text-search-doc/latest
export RAG_QUERY_EMBED_MODEL=emb://your_folder_id/text-search-query/latest
export RAG_REPAIR_MODEL=gpt://your_folder_id/yandexgpt/latest
python main.py
```

В Yandex mode backend использует тот же RAG pipeline, но generation идёт через AI Studio Chat Completions, а embeddings через Yandex textEmbedding API.

## Contract files
- OpenAPI: `docs/openapi.v1.yaml`
- GitHub session OpenAPI: `docs/openapi.github-session.v1.yaml`
- SQL: `db/migrations/0001_init.sql`
- Handoff: `docs/handoff.md`
- Examples: `docs/examples/*.json`
- GitHub smoke test: `docs/github-smoke-test.md`
- Export 3 PR to debug mocks: `docs/debug-pr-mocks.md`
