import os
import uuid

import psycopg
import pytest
from psycopg import sql
from pydantic import ValidationError

from rastro.config import get_settings
from rastro.db import apply_sql, connect_readonly
from rastro.ingest.federal import load_raw
from rastro.mart import build_mart
from support import FIXTURES


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


@pytest.fixture
def staging_db(db):
    apply_sql(db, "01_raw.sql")
    load_raw(db, FIXTURES)
    apply_sql(db, "02_staging.sql")
    return db


@pytest.fixture
def mart_db(staging_db):
    apply_sql(staging_db, "03_mart.sql")
    return staging_db


@pytest.fixture
def readonly(staging_db, monkeypatch):
    """A read-only connection to a freshly built mart."""
    build_mart(staging_db)
    staging_db.commit()
    monkeypatch.setenv("POSTGRES_DB", staging_db.info.dbname)
    with connect_readonly() as conn:
        yield conn
