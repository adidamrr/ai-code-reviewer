-- Runtime persistence for the Python/FastAPI store implementation.

CREATE TABLE IF NOT EXISTS runtime_store_state (
  id TEXT PRIMARY KEY,
  state JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
