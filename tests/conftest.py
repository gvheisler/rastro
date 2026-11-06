import os
import uuid

import psycopg
import pytest
from psycopg import sql
from pydantic import ValidationError

from rastro.config import get_settings


@pytest.fixture
def db():
    """A connection to an empty, throwaway database on the configured Postgres server."""
    try:
        settings = get_settings()
        admin = psycopg.connect(settings.dsn, autocommit=True)
    except (ValidationError, psycopg.OperationalError):
        if os.environ.get("CI"):
            raise
        pytest.skip("Postgres unavailable; run `make up`")

    name = f"rastro_test_{uuid.uuid4().hex[:8]}"
    admin.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
    conn = psycopg.connect(settings.model_copy(update={"postgres_db": name}).dsn)
    try:
        yield conn
    finally:
        conn.close()
        admin.execute(sql.SQL("drop database {} with (force)").format(sql.Identifier(name)))
        admin.close()
