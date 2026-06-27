import os
import openai
from app.db import get_conn, put_conn

def _embed(text: str) -> str:
    """Calls OpenAI embeddings and returns a pgvector-compatible string."""
    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    resp = client.embeddings.create(model="text-embedding-3-small", input=text)
    vec = resp.data[0].embedding
    return "[" + ",".join(str(x) for x in vec) + "]"

def get_similar_by_embedding(query: str, limit: int = 5) -> list[dict]:
    vec_str = _embed(query)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, vendor_name, description, amount, ai_category,
                       round((1 - (embedding <=> %s::vector))::numeric, 4) AS similarity
                FROM transactions
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (vec_str, vec_str, limit),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        put_conn(conn)
