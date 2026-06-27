import json
from typing import Optional

from fastapi import FastAPI, Query, HTTPException

from app.db import get_cursor
from app.guardrails import check_question, REJECTION_MESSAGE
from app.nl_query import ask as nl_ask
from app.providers import get_provider
from app.retrieval import get_similar_by_embedding
from app.schemas import AskIn, AskResult

app = FastAPI(title="LedgerSense")


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.get("/search")
def search(
    q: str = Query(..., description="Natural language query, e.g. 'office supplies from Amazon'"),
    limit: int = Query(5, ge=1, le=50),
):
    try:
        results = get_similar_by_embedding(q, limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"query": q, "count": len(results), "results": results}


@app.post("/ask", response_model=AskResult)
def ask_question(request: AskIn, provider_name: Optional[str] = None):
    allowed, reason = check_question(request.question)
    if not allowed:
        # Log the rejected attempt then return the standard rejection message
        with get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO questions (entity_ids, question, sql_valid, row_count, answer)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (request.entity_ids, request.question, False, 0, f"REJECTED:{reason}"),
            )
        return AskResult(
            question=request.question,
            answer=REJECTION_MESSAGE,
            sql="",
            row_count=0,
            follow_up_suggestions=[],
            model_provider="",
            model_name="",
        )

    provider = get_provider(provider_name)
    result = nl_ask(request.question, request.entity_ids, provider)

    # Log every call regardless of success/failure
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO questions
                (entity_ids, question, generated_sql, sql_valid, row_count,
                 answer, follow_ups, model_provider, model_name)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                request.entity_ids,
                result["question"],
                result["sql"],
                result["sql_valid"],
                result["row_count"],
                result["answer"],
                json.dumps(result["follow_up_suggestions"]),
                result["model_provider"],
                result["model_name"],
            ),
        )

    return AskResult(
        question=result["question"],
        answer=result["answer"],
        sql=result["sql"],
        row_count=result["row_count"],
        follow_up_suggestions=result["follow_up_suggestions"],
        model_provider=result["model_provider"],
        model_name=result["model_name"],
    )
