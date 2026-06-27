import json
import re
from typing import Optional

from app.db import get_cursor
from app.providers import AgentProvider

SQL_GENERATION_TOOL = {
    "name": "submit_sql",
    "description": (
        "Submit the SQL query to answer the user's question. "
        "Return only the raw SQL string — no markdown, no explanation, no backticks."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "Raw SQL SELECT query only"},
        },
        "required": ["sql"],
    },
}

ANSWER_GENERATION_TOOL = {
    "name": "submit_answer",
    "description": "Submit the plain English answer to the user's financial question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "description": "Plain English answer with specific numbers from the query results",
            },
            "follow_up_suggestions": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
                "description": "Up to 3 related questions the user might want to ask next",
            },
            "data_sufficient": {
                "type": "boolean",
                "description": "false if the query returned 0 rows or the question couldn't be answered",
            },
        },
        "required": ["answer", "follow_up_suggestions", "data_sufficient"],
    },
}

_DANGEROUS = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE)\b", re.IGNORECASE)
_MULTI_STMT = re.compile(r";\s*\S")


def validate_sql(sql: str) -> tuple[bool, str]:
    s = sql.strip()
    if not s.upper().startswith("SELECT"):
        return False, "Query must start with SELECT"
    if "true_category" in s.lower():
        return False, "Query must not reference true_category"
    m = _DANGEROUS.search(s)
    if m:
        return False, f"Query must not contain {m.group().upper()}"
    if _MULTI_STMT.search(s):
        return False, "Multi-statement queries are not allowed"
    return True, "ok"


def build_schema_context(entity_ids: Optional[list] = None) -> str:
    with get_cursor() as cur:
        if entity_ids:
            cur.execute(
                "SELECT id, name, entity_type FROM entities WHERE id = ANY(%s) ORDER BY id",
                (entity_ids,),
            )
        else:
            cur.execute("SELECT id, name, entity_type FROM entities ORDER BY id")
        entities = cur.fetchall()

        cur.execute("SELECT name FROM categories ORDER BY name")
        categories = [r[0] for r in cur.fetchall()]

        cur.execute("SELECT MIN(txn_date), MAX(txn_date) FROM transactions")
        min_date, max_date = cur.fetchone()

    entity_lines = "\n".join(f"  {e[0]}: {e[1]} ({e[2]})" for e in entities)
    cat_lines = "\n".join(f"  - {c}" for c in categories)

    return f"""Database schema (PostgreSQL):

Tables:
  transactions(id, entity_id, txn_date, vendor_name, description, amount, ai_category, status, tier)
  entities(id, name, entity_type)
  categories(id, name)
  categorizations(id, transaction_id, predicted_category, confidence, reasoning, model_provider, model_name, trigger, created_at)

Active entities:
{entity_lines}

Chart of accounts (ai_category values):
{cat_lines}

Date range in DB: {min_date} to {max_date}

Rules — you MUST follow these:
- SELECT only. Never use INSERT, UPDATE, DELETE, DROP, TRUNCATE, ALTER, or CREATE.
- Filter by ai_category, never true_category.
- Use ABS(amount) when summing expenses (amounts may be stored as negative).
- JOIN entities ON entity_id = entities.id to include entity names.
- Always add LIMIT 200."""


def ask(question: str, entity_ids: Optional[list], provider: AgentProvider) -> dict:
    model_provider = provider.model_provider
    model_name = provider.model_name

    schema_ctx = build_schema_context(entity_ids)

    # Call 1: generate SQL
    sql_prompt = f"""{schema_ctx}

Write a SQL query to answer the following question about the business's financial data:

{question}

Use the submit_sql tool. Return only the raw SQL string."""

    raw1 = provider._run(sql_prompt, tool=SQL_GENERATION_TOOL)
    sql = raw1.get("sql", "").strip()

    is_valid, reason = validate_sql(sql)
    if not is_valid:
        return {
            "question": question,
            "answer": f"I couldn't generate a valid query to answer this. Reason: {reason}",
            "sql": sql,
            "sql_valid": False,
            "row_count": 0,
            "follow_up_suggestions": [],
            "model_provider": model_provider,
            "model_name": model_name,
        }

    # Execute SQL
    with get_cursor() as cur:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(200)
    results = [dict(zip(cols, row)) for row in rows]
    row_count = len(results)

    # Call 2: answer in plain English
    answer_prompt = f"""Please answer the following question about the business's financial data in plain English.

Question: {question}

SQL executed:
{sql}

Results ({row_count} rows):
{json.dumps(results, default=str)}

Use the submit_answer tool to return a clear, specific answer with numbers from the data."""

    raw2 = provider._run(answer_prompt, tool=ANSWER_GENERATION_TOOL)

    answer = raw2.get("answer", "")
    if not raw2.get("data_sufficient", True):
        answer = "The available data isn't sufficient to fully answer this. " + answer

    return {
        "question": question,
        "answer": answer,
        "sql": sql,
        "sql_valid": True,
        "row_count": row_count,
        "follow_up_suggestions": raw2.get("follow_up_suggestions", []),
        "model_provider": model_provider,
        "model_name": model_name,
    }
