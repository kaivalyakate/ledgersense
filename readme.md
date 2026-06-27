# LedgerSense

An AI-powered bookkeeping agent that categorizes financial transactions, explains its reasoning, and answers natural language questions about business spend — built as a portfolio project targeting LiveFlow (AI-native ERP for physical businesses).

---

## What it does

- **Auto-categorizes transactions** into a 16-item chart of accounts using an LLM agent
- **Explains every decision** via structured signals (vendor pattern, amount range, similar past transactions)
- **Challenge flow** — ask "why did you categorize this as X?" and the agent either justifies or revises its call
- **Natural language Q&A** — ask plain English questions about spend and get SQL-backed answers
- **Semantic search** — find similar transactions via pgvector cosine similarity (OpenAI embeddings)
- **Full audit trail** — every categorization attempt and correction is stored append-only

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI (Python) |
| Database | PostgreSQL (Azure Flexible Server) + pgvector |
| Agent / LLM | Anthropic Claude or OpenAI GPT-4o (swappable) |
| Embeddings | OpenAI `text-embedding-3-small` |
| Local dev | `MockProvider` — no API key needed |

---

## Setup

```bash
pip install -r requirements.txt

# Copy and fill in environment variables
cp .env.example .env

# Apply schema to Postgres (run once)
psql "$DATABASE_URL" -f db/schema.sql

# Load synthetic data
python db/load_data.py --data-dir sample-data

# Embed transaction descriptions (requires OPENAI_API_KEY)
python db/embed_transactions.py

# Start the API
uvicorn app.main:app --reload
# Docs at http://localhost:8000/docs
```

`.env` variables:
```
DATABASE_URL=postgresql://user:pass@host:5432/ledgersense?sslmode=require
AGENT_PROVIDER=mock          # mock | anthropic | openai
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-6
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o
CONFIDENCE_THRESHOLD=0.80
```

Start with `AGENT_PROVIDER=mock` to validate DB wiring before spending API tokens.

---

## API endpoints

### `POST /categorize/{transaction_id}`
Runs the agent on a transaction. Returns a categorization with confidence score, reasoning, and structured signals. Writes to `categorizations` and `audit_log`. Status is `auto_approved` if confidence ≥ threshold, otherwise `needs_review`.

### `POST /challenge`
The explainability flow. Body: `{ transaction_id, categorization_id, user_message }`. Agent sees the original category, its reasoning, and the user's pushback — then either justifies or revises. Resolution is `agent_justified` or `agent_revised`.

### `GET /transactions/{transaction_id}/history`
Full ordered history of every categorization attempt for a transaction — the audit trail.

### `POST /ask`
Natural language Q&A over the transaction database. Two-call agentic pattern:
1. LLM generates a SQL query from the question
2. SQL is validated (SELECT-only, blocks `true_category`, injection-safe), executed, and results sent back to the LLM for a plain English answer

Input is filtered by a regex guardrail (`guardrail.md`) before any LLM call is made.

### `GET /search?q=...&limit=5`
Semantic similarity search over transaction descriptions using pgvector cosine distance.

### `GET /healthz`
Health check.

---

## Architecture

```
POST /ask
  └─ guardrails.py       regex checks (topic, injection, nastiness)
  └─ nl_query.py         Call 1: SQL gen → validate → execute
                         Call 2: plain English answer
  └─ questions table     every call logged, success or failure

POST /categorize / POST /challenge
  └─ providers.py        AgentProvider ABC → Anthropic / OpenAI / Mock
                         _run(prompt, tool) → structured output via tool use
  └─ retrieval.py        exact-match vendor lookup for few-shot context
  └─ categorizations     append-only, model identity as columns not tables

GET /search
  └─ retrieval.py        embed query → pgvector <=> cosine distance
  └─ transactions.embedding  vector(1536), HNSW index
```

### Key design decisions

**Provider layer** — `AnthropicProvider`, `OpenAIProvider`, and `MockProvider` all subclass `AgentProvider`. Prompts are built once; only the API call differs per provider. Switching models is one env var change.

**Structured output** — both real providers use tool use / function calling (not JSON parsing) to force structured responses. The `signals_used` JSONB field (`vendor_pattern`, `amount_signal`, `similar_txns_influence`) is what makes the challenge flow produce specific explanations rather than vague prose.

**`categorizations` is append-only** — model identity (`model_provider`, `model_name`) is stored as columns, not split into separate tables. This keeps cross-model comparison queries simple and the audit timeline unified.

**`transactions.ai_category` is denormalized** — fast UI reads with no join. Full history is in `categorizations`.

**Retrieval** — currently exact-match vendor lookup. Upgrade path: embed descriptions with `text-embedding-3-small`, store in pgvector, swap only `get_similar_transactions()` — interface stays the same.

---

## Synthetic data

800 transactions across 4 entities: Crumbtown Bakery & Cafe (3 locations, `ent_001–003`) and Ironclad Builders LLC (`ent_004`) — matching LiveFlow's actual customer profile (multi-location F&B and construction).

Three tiers:
- **obvious** (60%) — clean vendor→category mapping
- **ambiguous** (30%) — same vendor, correct category depends on amount/memo
- **anomaly** (10%) — planted duplicates, outlier amounts, off-cycle payroll

`true_category` is ground truth for offline eval only — never passed to the agent.

---

## Project status

| Component | Status |
|---|---|
| Schema + synthetic data | ✅ |
| Agent provider layer (Anthropic / OpenAI / Mock) | ✅ |
| `/categorize`, `/challenge`, `/history` endpoints | ✅ |
| pgvector semantic search + `/search` endpoint | ✅ |
| NL Q&A (`/ask`) with guardrails | ✅ |
| Offline eval script | ⬜ |
| Next.js review UI | ⬜ |
| Azure AI Foundry provider | ⬜ |
