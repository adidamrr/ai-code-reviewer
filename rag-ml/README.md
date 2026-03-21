# RAG/ML

Локальный RAG-слой для AI code review. Основной runtime рассчитан на `Yandex Cloud AI Studio` и вызывается backend'ом in-process через `backend/app/rag_adapter.py`.

## Структура
- `kb/` — локальные docpacks и shared packs.
- `src/rag_ml/` — build/runtime код.
- `scripts/` — inventory, build и evaluation.
- `build/` — локальные артефакты индексации (в git не коммитятся).

## Провайдер моделей
Рекомендуемый runtime использует `Yandex Cloud AI Studio`:
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
```

В этом режиме generation идёт через AI Studio Chat Completions, а embeddings через native Yandex textEmbedding API.


## Docker Compose

### Ollama mode
```bash
docker compose -f docker-compose.ollama.yml up --build -d
```

### Yandex mode (without Ollama)
```bash
docker compose -f docker-compose.api.yml up --build -d
```

В Yandex-режиме compose не поднимает `ollama`, а bootstrap использует AI Studio для embeddings/generation и сборки артефактов.

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
`dense` retrieval включен по умолчанию (`RAG_ENABLE_DENSE=true`) и использует пару моделей `text-search-doc` / `text-search-query`. Для временного troubleshooting можно переключиться в sparse-only режим через `RAG_ENABLE_DENSE=false`.
