import psycopg

from rastro.config import SQL_DIR, get_settings


def connect() -> psycopg.Connection:
    return psycopg.connect(get_settings().dsn)


def apply_sql(conn: psycopg.Connection, filename: str) -> None:
    """Run a script from the sql/ directory in a single transaction."""
    with conn.transaction():
        conn.execute((SQL_DIR / filename).read_text(encoding="utf-8"))
