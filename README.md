# SWAGReviewer
This repo for AI in engineering education.

## Quick Start

### Docker
```bash
docker compose up --build -d
docker compose exec ollama ollama pull nomic-embed-text
docker compose exec ollama ollama pull qwen2.5-coder:7b
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
