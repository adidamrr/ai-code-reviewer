# RAG/ML

Локальный RAG-слой для AI code review. Runtime рассчитан на `Ollama` и вызывается backend'ом in-process через `backend/app/rag_adapter.py`.

## Структура
- `kb/` — локальные docpacks и shared packs.
- `src/rag_ml/` — build/runtime код.
- `scripts/` — inventory, build и evaluation.
- `build/` — локальные артефакты индексации (в git не коммитятся).

## Провайдер моделей
По умолчанию runtime использует локальный `Ollama`:
```bash
ollama pull qwen2.5-coder:7b
ollama pull nomic-embed-text
```

Или одной командой:
```bash
cd backend
npm run rag:pull-models
```

Можно переключить runtime на удалённый OpenAI-compatible API:
```bash
export RAG_MODEL_PROVIDER=api
export RAG_API_BASE_URL=https://your-provider.example/v1
export RAG_API_KEY=your_api_key
export RAG_GENERATION_MODEL=gpt-4.1-mini
export RAG_EMBED_MODEL=text-embedding-3-small
```

В этом режиме и генерация, и embeddings берутся из внешнего API.


## Docker Compose

### Ollama mode
```bash
docker compose -f docker-compose.ollama.yml up --build -d
```

### API mode (without Ollama)
```bash
docker compose -f docker-compose.api.yml up --build -d
```

В API-режиме compose не поднимает `ollama`, а bootstrap использует внешний API для embeddings/generation и сборки артефактов.

Пример для Gemini OpenAI-compat:
```env
RAG_API_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
RAG_API_KEY=ваш_GEMINI_API_KEY
RAG_API_GENERATION_MODEL=gemini-3-flash-preview
RAG_API_EMBED_MODEL=gemini-embedding-2-preview
```

## Сборка KB
```bash
cd backend
source .venv/bin/activate
npm run rag:inventory
npm run rag:build
```

Если нужно ускорить dense build на Apple Silicon, можно поднять batch:
```bash
export RAG_EMBED_BATCH_SIZE=64
export RAG_GENERATION_MAX_TOKENS=256
```

Проверить готовность backend + RAG:
```bash
curl http://localhost:4000/readyz
```

## Evaluation на debug PR
```bash
cd backend
source .venv/bin/activate
npm run rag:eval
```

## Примечание по security
`security` по умолчанию отключен (`RAG_ENABLE_SECURITY=false`), пока в `kb/shared/security-pack/` не появятся реальные локальные источники, которые можно цитировать.
