# SWAGReviewer
This repo for AI in engineering education.

## Quick Start

### Docker

#### Вариант 1: локальный Ollama
```bash
docker compose -f docker-compose.ollama.yml up --build -d
```

Этот compose поднимает `ollama`, автоматически скачивает модели и собирает RAG-индексы.

#### Вариант 2: внешний API без Ollama
```bash
docker compose -f docker-compose.api.yml up --build -d
```

Этот compose **не поднимает Ollama** и использует только внешний API из `.env` (`RAG_API_BASE_URL`, `RAG_API_KEY`).

Для Gemini вставляйте значения так:
```env
RAG_API_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
RAG_API_KEY=ваш_GEMINI_API_KEY
RAG_API_GENERATION_MODEL=gemini-3-flash-preview
RAG_API_EMBED_MODEL=gemini-embedding-2-preview
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

Optional local Ollama:
```bash
ollama pull nomic-embed-text
ollama pull qwen2.5-coder:7b
```

Alternative: remote model API (OpenAI-compatible) instead of local Ollama:
```bash
export RAG_MODEL_PROVIDER=api
export RAG_API_BASE_URL=https://your-provider.example/v1
export RAG_API_KEY=your_api_key
export RAG_GENERATION_MODEL=gpt-4.1-mini
export RAG_EMBED_MODEL=text-embedding-3-small
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
