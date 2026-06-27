# LedgerSense

This file gives Claude Code full context on the LedgerSense project so you
can assist effectively without re-explaining decisions each session.

---

## What This Project Is

**LedgerSense** is an AI-powered bookkeeping and transaction categorization
agent built as a portfolio project targeting LiveFlow (an AI-native ERP for
physical businesses). The goal is to demonstrate AI agent development skills,
specifically the pattern of: structured data retrieval → LLM agent reasoning →
confidence-based routing → human-in-the-loop correction with explainability.

The demo's "wow moment" is the **challenge flow**: a user can look at any
agent-categorized transaction and ask "why did you categorize this as X?" —
the agent responds by citing the specific signals it used (vendor pattern,
amount range, similar past transactions), and either justifies its decision
or revises it. Every decision and correction is stored in a full audit trail.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI (Python) |
| Database | Azure Database for PostgreSQL (Flexible Server) |
| Agent / LLM | Azure AI Foundry (wrapping Claude or OpenAI — not decided yet) |
| Frontend | Next.js + React + TypeScript (Week 3, not started yet) |
| Data generation | Python + Faker |
| Local dev agent | MockProvider (no API key needed) |

**Azure AI Foundry note:** Foundry wraps the underlying model (Claude, GPT-4o,
etc.) behind a thread/run pattern. The codebase handles this by keeping model
identity as columns (`model_provider`, `model_name`, `agent_run_id`) in the
`categorizations` table rather than branching by model. Adding a Foundry
provider is a new `AgentProvider` subclass in `app/providers.py` only — nothing
else needs to change.

---

## Project Structure

```
ledgersense/
├── CLAUDE.md                  ← this file
├── .env.example               ← copy to .env and fill in your values
├── requirements.txt
├── schema.sql                 ← full Postgres DDL, run once against Azure Postgres
├── generate_transactions.py   ← synthetic data generator, run to produce CSVs
├── load_data.py               ← loads CSVs into Postgres (entities, categories, transactions)
└── app/
    ├── __init__.py
    ├── main.py                ← FastAPI app, all endpoints
    ├── providers.py           ← model-agnostic agent layer (Anthropic / OpenAI / Mock)
    ├── retrieval.py           ← structured SQL retrieval of similar past transactions
    ├── schemas.py             ← Pydantic request/response models
    └── db.py                  ← psycopg2 connection pool
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in:

```
DATABASE_URL=postgresql://user:password@your-server.postgres.database.azure.com:5432/ledgersense?sslmode=require
AGENT_PROVIDER=mock          # mock | anthropic | openai
ANTHROPIC_API_KEY=           # only needed if AGENT_PROVIDER=anthropic
ANTHROPIC_MODEL=claude-sonnet-4-6
OPENAI_API_KEY=              # only needed if AGENT_PROVIDER=openai
OPENAI_MODEL=gpt-4o
CONFIDENCE_THRESHOLD=0.80    # below this -> needs_review, above -> auto_approved
```

Start with `AGENT_PROVIDER=mock` to validate DB wiring before spending API tokens.

---

## How to Run

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Generate synthetic data (if you don't already have the CSVs)
python generate_transactions.py --n 800 --seed 42 --out transactions.csv

# 3. Stand up the schema on Azure Postgres
psql "$DATABASE_URL" -f schema.sql

# 4. Load the data
python load_data.py --data-dir .

# 5. Start the API
uvicorn app.main:app --reload

# 6. Open the auto-generated API docs
# http://localhost:8000/docs
```

---

## API Endpoints

### `POST /categorize/{transaction_id}`
Runs the agent on a single transaction. Optional query param `provider_name`
overrides the `AGENT_PROVIDER` env var (useful for A/B testing).

**Flow:**
1. Fetches transaction from DB
2. Fetches all categories from `categories` table
3. Runs `get_similar_transactions()` for few-shot context (same vendor, already resolved)
4. Calls the active `AgentProvider.categorize()`
5. Writes result to `categorizations` + updates `transactions.ai_category` / `status`
6. Writes to `audit_log`
7. Returns `CategorizationResult` with `status = auto_approved | needs_review`

### `POST /challenge`
The "why did you categorize this as X?" flow.

**Request body:** `{ transaction_id, categorization_id, user_message }`

**Flow:**
1. Fetches the original `categorization` that's being challenged
2. Re-prompts the agent using `respond_to_challenge()` — which includes the
   original category + reasoning + the human's pushback in the prompt
3. Determines resolution: `agent_justified` (category unchanged) or
   `agent_revised` (category changed)
4. Writes new row to `categorizations` with `trigger='challenge_response'`
5. Writes to `challenges` table
6. If `agent_revised`: sets `transactions.status = 'corrected'`

### `GET /transactions/{transaction_id}/history`
Returns the full ordered list of all categorization attempts for a transaction —
this is the audit trail shown in the UI's side panel.

### `GET /healthz`
Health check. Returns `{"status": "ok"}`.

---

## Database Schema — Key Decisions

### Tables in scope for Week 1
- `entities` — the 4 synthetic businesses (3 restaurant locations + 1 construction)
- `categories` — the 16 chart-of-accounts categories
- `transactions` — 800 synthetic transactions loaded from CSV
- `categorizations` — every agent prediction (append-only)
- `audit_log` — append-only event log

### Tables added to schema but not wired up yet (Week 2+)
- `challenges` — wired up in `/challenge` endpoint (Week 1 actually includes this)
- `bank_statement_lines` — for reconciliation (Week 2)

### Why `model_provider`/`model_name` are columns, not separate tables
Splitting per-model into separate tables would break cross-model comparison
queries and fragment the audit timeline. Views (`categorizations_anthropic`,
`categorizations_openai`) give the same query ergonomics without the cost.
See the comment block in `schema.sql` for the full rationale.

### Why `transactions.ai_category` is denormalized
Fast read for the UI (no join needed to render the transaction list). The full
history lives in `categorizations`. This is an intentional tradeoff documented
in the README.

---

## Agent / Provider Layer — Key Decisions

### All providers share one interface
`AgentProvider` (abstract base class in `providers.py`) exposes two methods:
- `categorize(vendor_name, description, amount, categories, similar_txns) -> dict`
- `respond_to_challenge(... , original_category, original_reasoning, user_message) -> dict`

Both internally call `_run(prompt: str) -> dict`, which each subclass implements.
This means prompts are built once (`build_prompt()` / `build_challenge_prompt()`)
and tested once — the model-specific code is only the API call mechanics.

### Tool use / function calling for structured output
Both `AnthropicProvider` and `OpenAIProvider` force structured output via tool
use (Anthropic) / function calling (OpenAI), not prompt-based JSON parsing.
The schema is `CATEGORIZATION_TOOL_SCHEMA` in `providers.py`. This makes
output parsing reliable and removes the need for stripping markdown fences.

### `signals_used` JSONB field
This is what makes the challenge flow produce *specific* explanations rather
than vague prose. The agent is required (via the tool schema) to populate:
- `vendor_pattern` — what about the vendor name drove the decision
- `amount_signal` — what the amount range suggested
- `similar_txns_influence` — how past resolved transactions influenced the call

The UI should render these as structured signals, not just dump `reasoning` text.

---

## Data Generation — Key Decisions

### Three transaction tiers
| Tier | % | Purpose |
|---|---|---|
| obvious | 60% | Clean vendor→category mapping. Tests baseline accuracy. |
| ambiguous | 30% | Same vendor, correct category depends on amount/memo (e.g. Amazon → Office Supplies at $32 vs Equipment at $1,200). This is what makes confidence scoring actually matter. |
| anomaly | 10% | Planted: duplicates, outlier amounts, round-number manual entries, off-cycle weekend payroll, split transactions. |

### `true_category` is ground truth — **never pass it to the agent**
It lives in the `transactions` table for scoring purposes only. The eval
script uses it to compute accuracy. The categorization prompt must never
include it. All agent inputs come from: `vendor_name`, `description`, `amount`,
`categories` (from the categories table), and `similar_txns` (from retrieval).

### Synthetic businesses match LiveFlow's actual customer profile
- `ent_001/002/003`: Crumbtown Bakery & Cafe (multi-location restaurant group)
- `ent_004`: Ironclad Builders LLC (construction)

This is deliberate — LiveFlow targets multi-location F&B and construction
businesses. The data matching their ICP is a small but noticeable detail in
an interview demo.

---

## Retrieval — Key Decisions

### Structured SQL retrieval, NOT vector RAG (for now)
`get_similar_transactions()` in `retrieval.py` does an exact-match vendor
name lookup against already-resolved transactions. This works because our
synthetic vendor names are clean strings.

**When to upgrade to vector RAG:** real-world bank feed descriptors are messy
(`"AMZN MKTP US*2K3L9"`, `"SQ *JOES COFFEE 04/12"`). When that's the input,
exact-match breaks. The upgrade path is: embed `description` with
`text-embedding-3-small` (OpenAI) or equivalent, store in `pgvector`
(Azure Postgres supports it natively as an extension), and swap only
`get_similar_transactions()` — the interface stays the same.

This is documented as Phase 2 in the README.

---

## Eval Loop (not built yet — Week 1 end)

Two separate eval concepts — keep them distinct:

### 1. Offline eval (uses `true_category` ground truth)
Script runs the agent over all 800 transactions, compares `predicted_category`
to `true_category`, and computes:
- **Overall accuracy**
- **Accuracy by tier** (obvious / ambiguous / anomaly separately) — the
  important number; overall accuracy is misleading if the hard cases are wrong
- **Confidence calibration** — are high-confidence predictions actually more
  accurate? Bucket by confidence range and check.
- **Anomaly recall** — what % of planted anomalies ended up in `needs_review`
  instead of `auto_approved`

If testing both Claude + OpenAI, this script produces a side-by-side table
(the `model_provider`/`model_name` columns make this a simple GROUP BY).

### 2. Production-style eval (no ground truth available — Week 3)
Monitoring proxies used instead:
- **Correction rate** — of `auto_approved` transactions, what % get corrected later
- **Challenge resolution ratio** — `agent_justified` vs `agent_revised` over time
- **Review queue size trend** — rising = agent getting less confident (or data
  distribution shifting)

---

## What's Built vs Pending

| Component | Status |
|---|---|
| Synthetic data generator (`generate_transactions.py`) | ✅ Done |
| Postgres schema (`schema.sql`) | ✅ Done |
| Data loader (`load_data.py`) | ✅ Done |
| DB connection pool (`db.py`) | ✅ Done |
| Pydantic schemas (`schemas.py`) | ✅ Done |
| Agent provider layer (`providers.py`) | ✅ Done |
| Structured retrieval (`retrieval.py`) | ✅ Done |
| `/categorize` endpoint | ✅ Done |
| `/challenge` endpoint | ✅ Done |
| `/history` endpoint | ✅ Done |
| Offline eval script | ⬜ Week 1 remaining |
| Azure Postgres provisioning + data load | ⬜ Do locally first |
| Next.js review UI | ⬜ Week 3 |
| Reconciliation (`bank_statement_lines`) | ⬜ Week 2 |
| Azure AI Foundry provider | ⬜ After Azure Postgres confirmed |
| README (architecture diagram + metrics) | ⬜ Week 3 |
| Loom demo video | ⬜ Week 3 |

---

## Phase 2 / Future Work (document in README, don't build now)

- **IRS tax-line mapping** — each COA category maps to an IRS Schedule C line
  for tax filing. Real accounting software (QuickBooks) separates management
  categorization (books) from tax-line categorization (filing). The schema
  would add a `tax_mappings` table with `coa_category`, `irs_line`, and
  `deductible_pct` (notably 50% for Meals & Entertainment under IRS rules).

- **pgvector RAG for messy bank descriptors** — see retrieval section above.

- **Azure AI Foundry `AzureFoundryProvider`** — new subclass in `providers.py`
  using the Foundry thread/run pattern. `agent_run_id` column in
  `categorizations` is reserved for this.

- **Production monitoring dashboard** — correction rate, challenge resolution
  ratio, and review queue size trend as time-series charts.

- **Hybrid routing** — a cheap classical classifier (TF-IDF + logistic
  regression) handles the "obvious" 60% instantly; the LLM agent only runs on
  ambiguous/low-confidence cases. This is the right production architecture —
  not using an LLM for everything is a feature, not a limitation.

---

## Common Mistakes to Avoid

- **Never pass `true_category` to the agent.** It's ground truth for scoring only.
- **Don't split the `categorizations` table by model.** Keep model identity as
  columns; use the views if you need filtered queries.
- **`signals_used` must always have all three keys** (`vendor_pattern`,
  `amount_signal`, `similar_txns_influence`) — the Pydantic schema enforces
  this, and the UI depends on all three being present.
- **`challenges.categorization_id`** refers to the prediction being challenged,
  not the response. `agent_response_categorization_id` is the response.
- **Azure Postgres requires `sslmode=require`** in the connection string or the
  connection will be refused.
- **Run with `AGENT_PROVIDER=mock` first** before connecting a real API key.
  The mock exercises the full DB write path so you can confirm the schema and
  queries are working before spending tokens.