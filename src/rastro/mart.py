from psycopg import Connection, sql

from rastro.config import get_settings
from rastro.db import apply_sql

STATEMENT_TIMEOUT = "10s"


def build_mart(conn: Connection) -> None:
    """Rebuild the mart schema and make sure the read-only role can query it."""
    settings = get_settings()
    role = sql.Identifier(settings.readonly_user)
    password = sql.Literal(settings.readonly_password)
    with conn.transaction():
        exists = conn.execute(
            "select 1 from pg_roles where rolname = %s", (settings.readonly_user,)
        ).fetchone()
        verb = "alter" if exists else "create"
        conn.execute(sql.SQL("{} role {} login password {}").format(sql.SQL(verb), role, password))
        conn.execute(
            sql.SQL("alter role {} set statement_timeout = {}").format(
                role, sql.Literal(STATEMENT_TIMEOUT)
            )
        )
        conn.execute(sql.SQL("alter role {} set search_path = mart, public").format(role))
        apply_sql(conn, "03_mart.sql")
        conn.execute(sql.SQL("grant usage on schema mart to {}").format(role))
        conn.execute(sql.SQL("grant select on all tables in schema mart to {}").format(role))
