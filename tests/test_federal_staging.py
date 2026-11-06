from datetime import date
from decimal import Decimal

import pytest

from rastro.db import apply_sql
from rastro.ingest.federal import load_raw
from support import FIXTURES, read_csv

MAIN = "EmendasParlamentares.csv"
CONV = "EmendasParlamentares_Convenios.csv"
FAV = "EmendasParlamentares_PorFavorecido.csv"


@pytest.fixture
def staging_db(db):
    apply_sql(db, "01_raw.sql")
    load_raw(db, FIXTURES)
    apply_sql(db, "02_staging.sql")
    return db


def column(filename: str, name: str) -> list[str]:
    header, rows = read_csv(filename)
    i = header.index(name)
    return [r[i] for r in rows]


def money(text: str) -> Decimal:
    return Decimal(text.replace(",", "."))


def scalar(conn, query: str, params=None):
    return conn.execute(query, params).fetchone()[0]


@pytest.mark.parametrize(
    ("table", "raw_table"),
    [
        ("emendas", "emendas_parlamentares"),
        ("convenios", "emendas_convenios"),
        ("pagamentos_favorecido", "emendas_por_favorecido"),
    ],
)
def test_staging_keeps_every_row(staging_db, table, raw_table):
    assert scalar(staging_db, f"select count(*) from staging.{table}") == scalar(
        staging_db, f"select count(*) from raw.{raw_table}"
    )


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("Valor Empenhado", "valor_empenhado"),
        ("Valor Liquidado", "valor_liquidado"),
        ("Valor Pago", "valor_pago"),
        ("Valor Restos A Pagar Inscritos", "valor_restos_a_pagar_inscritos"),
        ("Valor Restos A Pagar Cancelados", "valor_restos_a_pagar_cancelados"),
        ("Valor Restos A Pagar Pagos", "valor_restos_a_pagar_pagos"),
    ],
)
def test_emendas_money_columns_sum_to_the_csv_totals(staging_db, source, target):
    expected = sum(money(v) for v in column(MAIN, source))
    assert scalar(staging_db, f"select sum({target}) from staging.emendas") == expected


def test_valor_recebido_keeps_negative_amounts(staging_db):
    values = [money(v) for v in column(FAV, "Valor Recebido")]
    assert any(v < 0 for v in values)
    assert scalar(staging_db, "select sum(valor_recebido) from staging.pagamentos_favorecido") == (
        sum(values)
    )


def test_valor_convenio_sums_to_the_csv_total(staging_db):
    expected = sum(money(v) for v in column(CONV, "Valor Convênio"))
    assert scalar(staging_db, "select sum(valor_convenio) from staging.convenios") == expected


def test_placeholders_become_null(staging_db):
    codes = column(MAIN, "Código da Emenda")
    authors = column(MAIN, "Código do Autor da Emenda")
    assert scalar(
        staging_db, "select count(*) from staging.emendas where codigo_emenda is null"
    ) == (codes.count("Sem informação"))
    assert scalar(
        staging_db, "select count(*) from staging.emendas where codigo_autor is null"
    ) == (authors.count("S/I"))
    assert (
        scalar(
            staging_db, "select count(*) from staging.emendas where municipio = 'Sem informação'"
        )
        == 0
    )


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("localidade_aplicacao = 'MÚLTIPLO'", "multiplo"),
        ("localidade_aplicacao = 'Nacional'", "nacional"),
        ("localidade_aplicacao = 'SANTA CATARINA (UF)'", "estado"),
        ("localidade_aplicacao like '% - SC'", "municipio"),
    ],
)
def test_localidade_is_classified(staging_db, condition, expected):
    found = staging_db.execute(
        f"select distinct localidade_tipo from staging.emendas where {condition}"
    ).fetchall()
    assert found == [(expected,)]


def test_every_localidade_has_a_known_type(staging_db):
    for table in ("emendas", "convenios"):
        assert (
            scalar(
                staging_db, f"select count(*) from staging.{table} where localidade_tipo = 'outro'"
            )
            == 0
        )


def test_uf_comes_from_ibge_code_and_agrees_with_source_name(staging_db):
    mismatches = scalar(
        staging_db,
        """
        select count(*) from staging.emendas e
        join raw.emendas_parlamentares r using (linha_arquivo)
        join staging.uf u on u.sigla = e.uf_sigla
        where u.nome <> r.uf
        """,
    )
    assert mismatches == 0
    assert (
        scalar(
            staging_db,
            "select count(*) from staging.emendas where codigo_uf_ibge > 0 and uf_sigla is null",
        )
        == 0
    )


def test_santa_catarina_rows_match_the_csv(staging_db):
    expected = column(MAIN, "UF").count("SANTA CATARINA")
    assert scalar(staging_db, "select count(*) from staging.emendas where uf_sigla = 'SC'") == (
        expected
    )


def test_convenios_get_uf_and_municipio_from_localidade(staging_db):
    places = column(CONV, "Localidade do gasto")
    expected = sum(p.endswith(" - SC") or p == "SANTA CATARINA (UF)" for p in places)
    assert scalar(staging_db, "select count(*) from staging.convenios where uf_sigla = 'SC'") == (
        expected
    )
    assert (
        scalar(
            staging_db,
            """
        select count(*) from staging.convenios
        where localidade_tipo = 'municipio'
          and localidade_gasto <> municipio || ' - ' || uf_sigla
        """,
        )
        == 0
    )
    assert (
        scalar(
            staging_db,
            """
            select count(*) from staging.convenios
            where localidade_tipo = 'estado' and uf_sigla is null
            """,
        )
        == 0
    )


def test_convenio_dates_are_parsed(staging_db):
    dates = [
        date(int(d[6:]), int(d[3:5]), int(d[:2])) for d in column(CONV, "Data Publicação Convênio")
    ]
    low, high = staging_db.execute(
        "select min(data_publicacao), max(data_publicacao) from staging.convenios"
    ).fetchone()
    assert (low, high) == (min(dates), max(dates))


def test_pagamento_competencia_is_first_day_of_month(staging_db):
    months = {f"{m[:4]}-{m[4:]}-01" for m in column(FAV, "Ano/Mês")}
    found = staging_db.execute(
        "select distinct competencia::text from staging.pagamentos_favorecido"
    ).fetchall()
    assert {row[0] for row in found} == months


def test_tipo_favorecido_is_normalized(staging_db):
    staging_db.execute(
        """
        insert into raw.emendas_por_favorecido
            (codigo_da_emenda, tipo_favorecido, valor_recebido)
        values
            ('201900000001', 'Inscrição Genéric', '1,00'),
            ('201900000001', 'Pessoa Fisica', '1,00')
        """
    )
    apply_sql(staging_db, "02_staging.sql")
    found = {
        row[0]
        for row in staging_db.execute(
            "select distinct tipo_favorecido from staging.pagamentos_favorecido"
        )
    }
    assert "Inscrição Genérica" in found
    assert "Pessoa Física" in found
    assert not found & {"Inscrição Genéric", "Pessoa Fisica", "Sem informação"}


def test_staging_rebuild_does_not_duplicate_rows(staging_db):
    before = scalar(staging_db, "select count(*) from staging.pagamentos_favorecido")
    apply_sql(staging_db, "02_staging.sql")
    assert scalar(staging_db, "select count(*) from staging.pagamentos_favorecido") == before
