# RAG/ML

Локальный RAG-слой для AI code review. Runtime рассчитан на `Ollama` и вызывается backend'ом in-process через `backend/app/rag_adapter.py`.

## Структура
- `kb/` — локальные docpacks и shared packs.
- `src/rag_ml/` — build/runtime код.
- `scripts/` — inventory, build и evaluation.
- `build/` — локальные артефакты индексации (в git не коммитятся).

## Обязательные модели
```bash
ollama pull qwen2.5-coder:7b
ollama pull nomic-embed-text
```

Или одной командой:
```bash
cd backend
npm run rag:pull-models
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
