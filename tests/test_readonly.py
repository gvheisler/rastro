import psycopg
import pytest

from rastro.db import connect_readonly
from rastro.mart import build_mart


@pytest.fixture
def readonly(staging_db, monkeypatch):
    build_mart(staging_db)
    staging_db.commit()
    monkeypatch.setenv("POSTGRES_DB", staging_db.info.dbname)
    with connect_readonly() as conn:
        yield conn


def test_readonly_role_reads_the_mart_without_schema_prefix(readonly):
    assert readonly.execute("select count(*) from emendas").fetchone()[0] > 0


def test_readonly_role_can_use_unaccent(readonly):
    row = readonly.execute("select unaccent('FLORIANÓPOLIS')").fetchone()
    assert row == ("FLORIANOPOLIS",)


@pytest.mark.parametrize(
    "query",
    ["select 1 from raw.emendas_parlamentares", "select 1 from staging.emendas"],
)
def test_readonly_role_cannot_read_upstream_layers(readonly, query):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        readonly.execute(query)


@pytest.mark.parametrize(
    "statement",
    [
        "delete from mart.emendas",
        "update mart.emendas set valor_pago = 0",
        "insert into mart.fontes (tabela) values ('x')",
        "drop table mart.emendas",
        "create table mart.x (a int)",
        "truncate mart.emendas",
    ],
)
def test_readonly_role_cannot_change_anything(readonly, statement):
    with pytest.raises(psycopg.Error):
        readonly.execute(statement)


def test_readonly_connection_has_a_statement_timeout(readonly):
    assert readonly.execute("show statement_timeout").fetchone() == ("10s",)


def test_rebuilding_the_mart_keeps_the_grants(staging_db, monkeypatch):
    build_mart(staging_db)
    build_mart(staging_db)
    staging_db.commit()
    monkeypatch.setenv("POSTGRES_DB", staging_db.info.dbname)
    with connect_readonly() as conn:
        assert conn.execute("select count(*) from emendas").fetchone()[0] > 0
