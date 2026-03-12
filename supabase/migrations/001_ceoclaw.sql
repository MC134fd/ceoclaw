-- CEOClaw Supabase schema
-- Run once against your Supabase project (SQL editor or CLI: supabase db push)

-- Agent cross-run memory
CREATE TABLE IF NOT EXISTS agent_memory (
    namespace  TEXT        NOT NULL,
    key        TEXT        NOT NULL,
    value      TEXT        NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (namespace, key)
);

-- Enable RLS (service-role key bypasses it; fine for server-side usage)
ALTER TABLE agent_memory ENABLE ROW LEVEL SECURITY;

-- Index for namespace scans
CREATE INDEX IF NOT EXISTS idx_agent_memory_ns ON agent_memory (namespace);
