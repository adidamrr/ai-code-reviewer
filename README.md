# SWAGReviewer
This repo for AI in engineering education.

## Quick Start

### Docker

#### Вариант 1: локальный Ollama
```bash
docker compose -f docker-compose.ollama.yml up --build -d
```

Этот compose поднимает `ollama`, автоматически скачивает модели и собирает RAG-индексы.

#### Вариант 2: Yandex Cloud AI Studio
```bash
docker compose -f docker-compose.api.yml up --build -d
```

Этот compose **не поднимает Ollama** и использует Yandex Cloud AI Studio из `.env`.

Заполните `.env` так:
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

Open:
- Frontend: `http://localhost:5173`
- Backend: `http://localhost:4000/healthz`

Stop:
```bash
docker compose down
```

### Local Dev
Backend:
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm install
npm run dev
```

Frontend:
```bash
cd frontend
npm install
VITE_BACKEND_BASE_URL=http://localhost:4000 npm run dev
```

Yandex Cloud runtime:
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

Useful checks:
```bash
curl http://localhost:4000/healthz
curl http://localhost:4000/readyz
curl http://localhost:4000/repos
```

## Workspaces
- `backend` — Python/FastAPI API, contracts, schema, tests
- `frontend` — UI control center for GitHub PR review flow
- `rag-ml` — reserved for RAG/ML team
- `research` — reserved for research artifacts
