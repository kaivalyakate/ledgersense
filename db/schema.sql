-- ============================================================
-- LedgerSense Database Schema
-- Target: Azure Database for PostgreSQL (Flexible Server)
-- ============================================================
-- Run with: psql "<connection_string>" -f schema.sql
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS vector;      -- pgvector: cosine similarity search

-- ============================================================
-- Core reference tables
-- ============================================================

CREATE TABLE entities (
    id              TEXT PRIMARY KEY,          -- e.g. 'ent_001'
    name            TEXT NOT NULL,
    entity_type     TEXT NOT NULL,             -- 'restaurant' | 'construction'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE categories (
    id              SERIAL PRIMARY KEY,
    name            TEXT UNIQUE NOT NULL,      -- 'Cost of Goods Sold', etc.
    description     TEXT                       -- optional, useful as agent context
);

-- ============================================================
-- Transactions (loaded from the synthetic data generator)
-- ============================================================

CREATE TABLE transactions (
    id              UUID PRIMARY KEY,
    entity_id       TEXT NOT NULL REFERENCES entities(id),
    txn_date        DATE NOT NULL,
    vendor_name     TEXT NOT NULL,
    description     TEXT,
    amount          NUMERIC(12,2) NOT NULL,

    -- ground truth, hidden from the agent at inference time,
    -- used only for scoring
    true_category   TEXT,
    anomaly_type    TEXT,                      -- '' or null if not planted
    tier            TEXT,                      -- 'obvious' | 'ambiguous' | 'anomaly'

    -- agent's current best prediction (denormalized for fast UI reads;
    -- full history lives in categorizations table below)
    ai_category     TEXT,
    confidence      NUMERIC(4,3),              -- 0.000 - 1.000
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','auto_approved','needs_review','corrected')),

    -- pgvector: populated by db/embed_transactions.py after load_data.py
    embedding       vector(1536),

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_transactions_entity ON transactions(entity_id);
CREATE INDEX idx_transactions_status ON transactions(status);
-- ponytail: HNSW over IVFFlat — better recall at query time, slower build, fine for 800 rows
CREATE INDEX idx_transactions_embedding ON transactions USING hnsw (embedding vector_cosine_ops);

-- ============================================================
-- Every categorization attempt (not just the latest) -- this is
-- what makes "explain when challenged" possible: the full history
-- of the agent's opinions on a single transaction lives here.
-- ============================================================

CREATE TABLE categorizations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id  UUID NOT NULL REFERENCES transactions(id),

    predicted_category TEXT NOT NULL,
    confidence      NUMERIC(4,3) NOT NULL,
    reasoning       TEXT NOT NULL,             -- free-text explanation from the agent
    signals_used    JSONB,                     -- structured: {"vendor_pattern": "...", "amount_range": "...", "similar_txns": [...]}

    -- model identity as columns, NOT separate tables per model --
    -- keeps cross-model comparison and the audit timeline unified.
    model_provider  TEXT NOT NULL,             -- 'anthropic' | 'openai'
    model_name      TEXT NOT NULL,             -- 'claude-sonnet-4-6' | 'gpt-4o' etc.
    agent_run_id    TEXT,                      -- Azure AI Foundry thread/run id, if applicable

    trigger         TEXT NOT NULL DEFAULT 'initial'
                    CHECK (trigger IN ('initial','re_run','challenge_response')),

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_categorizations_txn ON categorizations(transaction_id);
CREATE INDEX idx_categorizations_model ON categorizations(model_provider, model_name);

-- Convenience views for querying a single model's results without
-- splitting the underlying table (see README for rationale)
CREATE VIEW categorizations_anthropic AS
    SELECT * FROM categorizations WHERE model_provider = 'anthropic';

CREATE VIEW categorizations_openai AS
    SELECT * FROM categorizations WHERE model_provider = 'openai';

-- ============================================================
-- Human challenges/corrections -- the "why did you categorize
-- this as X?" flow writes here, and the agent's reply becomes a
-- new row in categorizations with trigger='challenge_response'
-- ============================================================

CREATE TABLE challenges (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id      UUID NOT NULL REFERENCES transactions(id),
    categorization_id   UUID NOT NULL REFERENCES categorizations(id),  -- which prediction is being challenged

    user_message        TEXT NOT NULL,         -- "this should be Travel, not Meals"
    agent_response_categorization_id UUID REFERENCES categorizations(id), -- resulting new prediction, if any
    resolution          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (resolution IN ('pending','agent_justified','agent_revised','human_overrode')),

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- Reconciliation: matches transactions against a synthetic
-- bank statement feed (Week 2 scope, schema included now since
-- DDL is cheap to stand up ahead of time)
-- ============================================================

CREATE TABLE bank_statement_lines (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       TEXT NOT NULL REFERENCES entities(id),
    txn_date        DATE NOT NULL,
    amount          NUMERIC(12,2) NOT NULL,
    raw_description TEXT,
    matched_transaction_id UUID REFERENCES transactions(id),
    match_confidence NUMERIC(4,3),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- Audit log -- append-only, for the "trust" story in the demo
-- ============================================================

CREATE TABLE audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id  UUID NOT NULL REFERENCES transactions(id),
    event_type      TEXT NOT NULL,             -- 'categorized' | 'challenged' | 'corrected' | 'reconciled'
    actor           TEXT NOT NULL,             -- 'agent' | 'user:kaiwalya'
    detail          JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_log_txn ON audit_log(transaction_id);

-- ============================================================
-- NL Q&A -- every /ask call is logged here for auditing and
-- future fine-tuning (both successful answers and failures)
-- ============================================================

CREATE TABLE questions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_ids      TEXT[],
    question        TEXT NOT NULL,
    generated_sql   TEXT,
    sql_valid       BOOLEAN,
    row_count       INTEGER,
    answer          TEXT,
    follow_ups      JSONB,
    model_provider  TEXT,
    model_name      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
