import copy
from datetime import date

import pytest

from rastro.db import apply_sql
from rastro.ingest.load import SchemaMismatchError
from rastro.ingest.transferegov import (
    BENEFICIARIOS,
    EMPENHOS,
    PLANOS_ACAO,
    RESOURCES,
    TransferegovClient,
    TransferegovError,
    load_raw_transferegov,
)
from support import API_BASE, fake_transferegov, fixture_transferegov

UPDATED = "2026-11-10"


def client_for(data):
    return TransferegovClient(API_BASE, transport=fake_transferegov(data, updated=UPDATED))


def count(conn, table):
    return conn.execute(f"select count(*) from raw.{table}").fetchone()[0]


@pytest.fixture
def raw_db(db):
    apply_sql(db, "01_raw.sql")
    return db


@pytest.fixture
def api_data():
    return fixture_transferegov()


def santa_catarina_expected(data):
    beneficiaries = {
        b["id_beneficiario"] for b in data[BENEFICIARIOS.endpoint] if b["uf_beneficiario"] == "SC"
    }
    plans = {
        p["id_plano_acao"]
        for p in data[PLANOS_ACAO.endpoint]
        if p["id_beneficiario"] in beneficiaries
    }
    expected = {BENEFICIARIOS.table: len(beneficiaries), PLANOS_ACAO.table: len(plans)}
    for resource in RESOURCES[2:]:
        expected[resource.table] = sum(r["id_plano_acao"] in plans for r in data[resource.endpoint])
    return expected


def test_the_fixture_has_other_states_that_must_be_left_out(api_data):
    ufs = {b["uf_beneficiario"] for b in api_data[BENEFICIARIOS.endpoint]}
    assert "SC" in ufs and len(ufs) > 1


def test_loads_only_santa_catarina_into_raw(raw_db, api_data):
    loaded = load_raw_transferegov(raw_db, client_for(api_data))
    expected = santa_catarina_expected(api_data)
    assert loaded == expected
    assert all(n > 0 for n in expected.values())
    for table, rows in expected.items():
        assert count(raw_db, table) == rows
    assert raw_db.execute(
        "select distinct uf_beneficiario from raw.transferegov_beneficiarios"
    ).fetchall() == [("SC",)]


def test_raw_tables_have_exactly_the_columns_that_are_loaded(raw_db):
    for resource in RESOURCES:
        columns = [
            name
            for (name,) in raw_db.execute(
                "select column_name from information_schema.columns "
                "where table_schema = 'raw' and table_name = %s and is_identity = 'NO' "
                "order by ordinal_position",
                (resource.table,),
            )
        ]
        assert columns == list(resource.columns), resource.table


def test_values_are_stored_as_text_exactly_as_received(raw_db, api_data):
    load_raw_transferegov(raw_db, client_for(api_data))
    kinds = raw_db.execute(
        "select distinct data_type from information_schema.columns "
        "where table_schema = 'raw' and table_name like 'transferegov_%' and is_identity = 'NO'"
    ).fetchall()
    assert kinds == [("text",)]
    total = raw_db.execute(
        "select sum(valor_empenho::numeric) from raw.transferegov_empenhos"
    ).fetchone()[0]
    sc_plans = {
        r[0] for r in raw_db.execute("select id_plano_acao from raw.transferegov_planos_acao")
    }
    assert float(total) == pytest.approx(
        sum(
            float(r["valor_empenho"])
            for r in api_data[EMPENHOS.endpoint]
            if str(r["id_plano_acao"]) in sc_plans
        )
    )


def test_missing_values_are_nulls_not_the_text_none(raw_db, api_data):
    load_raw_transferegov(raw_db, client_for(api_data))
    assert (
        raw_db.execute(
            "select count(*) from raw.transferegov_planos_acao where nome_objeto = 'None'"
        ).fetchone()[0]
        == 0
    )
    assert (
        raw_db.execute(
            "select count(*) from raw.transferegov_planos_acao where nome_objeto is null"
        ).fetchone()[0]
        > 0
    )


def test_the_load_is_recorded_with_the_date_the_source_was_updated(raw_db, api_data):
    load_raw_transferegov(raw_db, client_for(api_data))
    rows = raw_db.execute(
        "select arquivo, linhas, atualizado_na_fonte, length(sha256) from raw.cargas "
        "where arquivo like 'especiais/%' order by arquivo"
    ).fetchall()
    assert [r[0] for r in rows] == sorted(f"especiais/{r.endpoint}" for r in RESOURCES)
    assert all(r[2] == date.fromisoformat(UPDATED) and r[3] == 64 for r in rows)
    expected = santa_catarina_expected(api_data)
    assert {r[0]: r[1] for r in rows} == {
        f"especiais/{r.endpoint}": expected[r.table] for r in RESOURCES
    }


def test_loading_again_replaces_rows_and_keeps_the_same_fingerprint(raw_db, api_data):
    load_raw_transferegov(raw_db, client_for(api_data))
    before = raw_db.execute("select arquivo, sha256 from raw.cargas order by arquivo").fetchall()
    load_raw_transferegov(raw_db, client_for(api_data))
    after = raw_db.execute("select arquivo, sha256 from raw.cargas order by arquivo").fetchall()
    assert before == after
    assert (
        count(raw_db, "transferegov_planos_acao")
        == santa_catarina_expected(api_data)["transferegov_planos_acao"]
    )


def test_fields_that_are_not_loaded_never_reach_the_database(raw_db, api_data):
    data = copy.deepcopy(api_data)
    for plan in data[PLANOS_ACAO.endpoint]:
        plan["email_camara"] = "contato@example.org"
        plan["numero_conta_plano_acao"] = "123456"
    load_raw_transferegov(raw_db, client_for(data))
    columns = {
        name
        for (name,) in raw_db.execute(
            "select column_name from information_schema.columns where table_schema = 'raw'"
        )
    }
    assert not {"email_camara", "numero_conta_plano_acao"} & columns


def test_a_field_missing_from_the_api_fails_without_touching_the_data(raw_db, api_data):
    load_raw_transferegov(raw_db, client_for(api_data))
    before = count(raw_db, "transferegov_empenhos")
    broken = copy.deepcopy(api_data)
    for row in broken[EMPENHOS.endpoint]:
        del row["valor_empenho"]
    with pytest.raises(SchemaMismatchError, match="valor_empenho"):
        load_raw_transferegov(raw_db, client_for(broken))
    raw_db.rollback()
    assert count(raw_db, "transferegov_empenhos") == before


def test_an_api_failure_leaves_the_previous_load_in_place(raw_db, api_data):
    load_raw_transferegov(raw_db, client_for(api_data))
    before = count(raw_db, "transferegov_planos_acao")
    broken = {k: v for k, v in api_data.items() if k != EMPENHOS.endpoint}
    with pytest.raises(TransferegovError):
        load_raw_transferegov(raw_db, client_for(broken))
    assert count(raw_db, "transferegov_planos_acao") == before
