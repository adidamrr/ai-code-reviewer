-- Feedback-driven adaptation v1: feature snapshots, aggregated priors, and trained model versions.

CREATE TABLE IF NOT EXISTS suggestion_feature_snapshots (
  suggestion_id UUID PRIMARY KEY REFERENCES suggestions(id) ON DELETE CASCADE,
  fingerprint TEXT NOT NULL,
  job_id UUID NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
  pr_id UUID NOT NULL REFERENCES pull_requests(id) ON DELETE CASCADE,
  snapshot_id UUID NOT NULL REFERENCES pr_snapshots(id) ON DELETE CASCADE,
  model_version TEXT NOT NULL,
  confidence NUMERIC(6, 5) NOT NULL,
  rank_score NUMERIC(10, 6) NOT NULL,
  retrieval_score NUMERIC(10, 6) NOT NULL,
  planner_priority NUMERIC(10, 6) NOT NULL,
  static_support NUMERIC(10, 6) NOT NULL,
  repo_feedback_score NUMERIC(10, 6) NOT NULL DEFAULT 0,
  delivery_mode TEXT NOT NULL,
  category suggestion_category NOT NULL,
  severity suggestion_severity NOT NULL,
  language TEXT NOT NULL,
  file_role TEXT NOT NULL,
  evidence_signature TEXT NOT NULL,
  title_template TEXT NOT NULL,
  confidence_bucket TEXT NOT NULL,
  prompt_context_version TEXT NOT NULL DEFAULT 'rag-v2',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_suggestion_feature_snapshots_fingerprint ON suggestion_feature_snapshots(fingerprint);
CREATE INDEX IF NOT EXISTS idx_suggestion_feature_snapshots_template ON suggestion_feature_snapshots(title_template);
CREATE INDEX IF NOT EXISTS idx_suggestion_feature_snapshots_model_version ON suggestion_feature_snapshots(model_version);

CREATE TABLE IF NOT EXISTS adaptation_feature_stats (
  id BIGSERIAL PRIMARY KEY,
  key_type TEXT NOT NULL,
  key_value TEXT NOT NULL,
  up_count INTEGER NOT NULL DEFAULT 0,
  down_count INTEGER NOT NULL DEFAULT 0,
  vote_count INTEGER NOT NULL DEFAULT 0,
  score INTEGER NOT NULL DEFAULT 0,
  smoothed_utility NUMERIC(10, 6) NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (key_type, key_value)
);

CREATE INDEX IF NOT EXISTS idx_adaptation_feature_stats_key_type ON adaptation_feature_stats(key_type);

CREATE TABLE IF NOT EXISTS adaptation_model_versions (
  version TEXT PRIMARY KEY,
  trained_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  training_examples INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  weights_json JSONB NOT NULL,
  metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_adaptation_model_versions_status ON adaptation_model_versions(status);
