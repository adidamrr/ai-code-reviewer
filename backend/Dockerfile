FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY backend/ /app/
COPY rag-ml/ /rag-ml/

ENV PORT=4000 \
    RAG_ENABLED=true \
    RAG_OLLAMA_BASE_URL=http://ollama:11434 \
    RAG_BUILD_DIR=/rag-ml/build \
    RAG_KB_DIR=/rag-ml/kb

EXPOSE 4000
CMD ["python", "main.py"]
