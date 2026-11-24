from contextlib import contextmanager
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from .config import DATABASE_URL

_ISOLATION_LEVELS = {
    "READ COMMITTED": psycopg.IsolationLevel.READ_COMMITTED,
    "REPEATABLE READ": psycopg.IsolationLevel.REPEATABLE_READ,
    "SERIALIZABLE": psycopg.IsolationLevel.SERIALIZABLE,
}


@contextmanager
def get_conn(isolation_level=None):
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    if isolation_level is not None:
        conn.isolation_level = _ISOLATION_LEVELS[isolation_level]
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    migrations_dir = Path(__file__).resolve().parents[1] / "migrations"
    with get_conn() as conn:
        for migration in sorted(migrations_dir.glob("*.sql")):
            conn.execute(migration.read_text())
