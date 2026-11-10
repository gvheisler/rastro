import re
from decimal import Decimal

import pytest

from support import scalar

TABLES = {
    "transferegov_beneficiarios": "raw.transferegov_beneficiarios",
    "transferegov_planos_acao": "raw.transferegov_planos_acao",
    "transferegov_executores": "raw.transferegov_executores",
    "transferegov_planos_trabalho": "raw.transferegov_planos_trabalho",
    "transferegov_empenhos": "raw.transferegov_empenhos",
}


@pytest.mark.parametrize(("staging", "raw"), TABLES.items())
def test_staging_has_the_same_rows_as_raw(staging_db, staging, raw):
    assert scalar(staging_db, f"select count(*) from staging.{staging}") == scalar(
        staging_db, f"select count(*) from {raw}"
    )
    assert scalar(staging_db, f"select count(*) from staging.{staging}") > 0


def column_types(conn, table):
    return dict(
        conn.execute(
            "select column_name, data_type from information_schema.columns "
            "where table_schema = 'staging' and table_name = %s",
            (table,),
        ).fetchall()
    )


def test_ids_values_and_dates_are_typed(staging_db):
    plans = column_types(staging_db, "transferegov_planos_acao")
    assert plans["id_plano_acao"] == "integer"
    assert plans["ano_plano"] == "smallint"
    assert plans["valor_custeio"] == plans["valor_investimento"] == "numeric"
    assert plans["data_aceite"] == "date"
    commitments = column_types(staging_db, "transferegov_empenhos")
    assert commitments["valor"] == "numeric"
    assert commitments["data_emissao"] == "date"
    work = column_types(staging_db, "transferegov_planos_trabalho")
    assert work["data_inicio_execucao"] == work["data_fim_execucao"] == "date"


def test_plan_values_match_the_raw_text(staging_db):
    raw = scalar(
        staging_db,
        "select sum(valor_custeio_plano_acao::numeric + valor_investimento_plano_acao::numeric) "
        "from raw.transferegov_planos_acao",
    )
    typed = scalar(
        staging_db,
        "select sum(valor_custeio + valor_investimento) from staging.transferegov_planos_acao",
    )
    assert typed == Decimal(raw).quantize(Decimal("0.01"))


def test_the_amendment_code_is_the_twelve_digit_text_used_by_the_portal(staging_db):
    codes = [
        r[0]
        for r in staging_db.execute("select codigo_emenda from staging.transferegov_planos_acao")
    ]
    assert all(re.fullmatch(r"[0-9]{12}", c) for c in codes)
    in_portal = scalar(
        staging_db,
        "select count(*) from staging.transferegov_planos_acao p "
        "join staging.emendas e using (codigo_emenda)",
    )
    assert in_portal > 0


def test_the_amendment_year_agrees_with_the_code(staging_db):
    assert (
        scalar(
            staging_db,
            "select count(*) from staging.transferegov_planos_acao "
            "where ano_emenda <> left(codigo_emenda, 4)::smallint",
        )
        == 0
    )


def test_missing_text_stays_null(staging_db):
    assert (
        scalar(
            staging_db,
            "select count(*) from staging.transferegov_planos_acao where nome_objeto is null",
        )
        > 0
    )
    assert (
        scalar(
            staging_db,
            "select count(*) from staging.transferegov_planos_acao where btrim(nome_objeto) = ''",
        )
        == 0
    )


def test_every_plan_points_to_a_beneficiary(staging_db):
    assert (
        scalar(
            staging_db,
            "select count(*) from staging.transferegov_planos_acao p "
            "left join staging.transferegov_beneficiarios b using (id_beneficiario) "
            "where b.id_beneficiario is null",
        )
        == 0
    )
