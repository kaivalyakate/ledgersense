import os
from contextlib import contextmanager
import psycopg2
from psycopg2 import pool

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

_pool: pool.SimpleConnectionPool | None = None

def _get_pool() -> pool.SimpleConnectionPool:
    global _pool
    if _pool is None:
        _pool = pool.SimpleConnectionPool(1, 10, os.environ["DATABASE_URL"])
    return _pool

def get_conn():
    return _get_pool().getconn()

def put_conn(conn):
    _get_pool().putconn(conn)


@contextmanager
def get_cursor():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)
