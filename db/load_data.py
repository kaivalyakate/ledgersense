"""
LedgerSense Data Loader
========================
Loads entities.csv, categories.csv, and transactions.csv (produced by
generate_transactions.py) into a Postgres database -- targeting Azure
Database for PostgreSQL (Flexible Server), but works against any
Postgres instance.

This only populates the Week 1 subset of the schema:
    entities, categories, transactions
The categorizations / challenges / bank_statement_lines / audit_log
tables stay empty until the agent endpoints are built.

Setup:
    pip install psycopg2-binary python-dotenv --break-system-packages

    Create a .env file (or export env vars directly) with:
        DATABASE_URL=postgresql://<user>:<password>@<host>:5432/<dbname>?sslmode=require

    Azure Postgres Flexible Server requires sslmode=require by default.

Usage:
    python load_data.py --data-dir .
"""

import argparse
import csv
import os
import sys

import psycopg2
from psycopg2.extras import execute_values

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional; env vars can be set directly


def get_connection():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL environment variable not set.")
        print("Set it to your Azure Postgres connection string, e.g.:")
        print('  export DATABASE_URL="postgresql://user:pass@host:5432/dbname?sslmode=require"')
        sys.exit(1)
    return psycopg2.connect(db_url)


def load_entities(cur, data_dir):
    path = os.path.join(data_dir, "entities.csv")
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        rows = [(r["id"], r["name"], r["type"]) for r in reader]

    execute_values(
        cur,
        """
        INSERT INTO entities (id, name, entity_type)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            entity_type = EXCLUDED.entity_type
        """,
        rows,
    )
    print(f"  entities: {len(rows)} rows upserted")


def load_categories(cur, data_dir):
    path = os.path.join(data_dir, "categories.csv")
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        rows = [(r["category"],) for r in reader]

    execute_values(
        cur,
        """
        INSERT INTO categories (name)
        VALUES %s
        ON CONFLICT (name) DO NOTHING
        """,
        rows,
    )
    print(f"  categories: {len(rows)} rows upserted")


def load_transactions(cur, data_dir):
    path = os.path.join(data_dir, "transactions.csv")
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for r in reader:
            rows.append((
                r["id"],
                r["entity_id"],
                r["date"],
                r["vendor_name"],
                r["description"],
                r["amount"],
                r["true_category"],
                r["anomaly_type"] or None,
                r["tier"],
            ))

    execute_values(
        cur,
        """
        INSERT INTO transactions
            (id, entity_id, txn_date, vendor_name, description, amount,
             true_category, anomaly_type, tier)
        VALUES %s
        ON CONFLICT (id) DO NOTHING
        """,
        rows,
    )
    print(f"  transactions: {len(rows)} rows inserted (skipping existing ids)")


def main():
    parser = argparse.ArgumentParser(description="Load LedgerSense CSVs into Postgres.")
    parser.add_argument("--data-dir", type=str, default=".", help="Directory containing the CSV files")
    args = parser.parse_args()

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                print("Loading data...")
                load_entities(cur, args.data_dir)
                load_categories(cur, args.data_dir)
                load_transactions(cur, args.data_dir)
        print("Done. All changes committed.")
    except Exception as e:
        conn.rollback()
        print(f"ERROR: load failed, rolled back. {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
