"""
One-shot script: embeds transactions.description via OpenAI text-embedding-3-small
and stores the result in transactions.embedding (vector(1536)).

Run after load_data.py:
    python db/embed_transactions.py

Requires: OPENAI_API_KEY and DATABASE_URL in .env or environment.
"""

import os
import sys
import psycopg2
import openai

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BATCH = 100
MODEL = "text-embedding-3-small"


def vec_str(v: list[float]) -> str:
    return "[" + ",".join(str(x) for x in v) + "]"


def main():
    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    conn = psycopg2.connect(os.environ["DATABASE_URL"])

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, description FROM transactions WHERE embedding IS NULL")
            rows = cur.fetchall()

        if not rows:
            print("All transactions already embedded.")
            return

        print(f"Embedding {len(rows)} transactions in batches of {BATCH}...")

        for i in range(0, len(rows), BATCH):
            batch = rows[i : i + BATCH]
            ids = [r[0] for r in batch]
            texts = [r[1] or "" for r in batch]

            resp = client.embeddings.create(model=MODEL, input=texts)
            vecs = [item.embedding for item in resp.data]

            with conn.cursor() as cur:
                for txn_id, vec in zip(ids, vecs):
                    cur.execute(
                        "UPDATE transactions SET embedding = %s::vector WHERE id = %s",
                        (vec_str(vec), str(txn_id)),
                    )
            conn.commit()
            print(f"  {min(i + BATCH, len(rows))}/{len(rows)} done")

        print("Done.")
    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
