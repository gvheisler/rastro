import re

import pytest

from rastro.db import apply_sql
from support import column, money, read_csv, scalar

MAIN = "EmendasParlamentares.csv"
CONV = "EmendasParlamentares_Convenios.csv"
FAV = "EmendasParlamentares_PorFavorecido.csv"

TABLES = [
    "emendas",
    "convenios",
    "pagamentos_favorecidos",
    "transferencias_especiais",
    "transferencias_especiais_empenhos",
    "fontes",
]


def sc_emenda_codes() -> set[str]:
    header, rows = read_csv(MAIN)
    uf, code = header.index("UF"), header.index("Código da Emenda")
    return {r[code] for r in rows if r[uf] == "SANTA CATARINA" and r[code] != "Sem informação"}


def test_mart_has_the_expected_tables(mart_db):
    found = {
        row[0]
        for row in mart_db.execute(
            "select table_name from information_schema.tables where table_schema = 'mart'"
        )
    }
    assert found == set(TABLES)


def test_emendas_keeps_only_santa_catarina(mart_db):
    expected = column(MAIN, "UF").count("SANTA CATARINA")
    assert scalar(mart_db, "select count(*) from mart.emendas") == expected


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("Valor Empenhado", "valor_empenhado"),
        ("Valor Liquidado", "valor_liquidado"),
        ("Valor Pago", "valor_pago"),
    ],
)
def test_emendas_values_match_the_csv_for_santa_catarina(mart_db, source, target):
    header, rows = read_csv(MAIN)
    uf, value = header.index("UF"), header.index(source)
    expected = sum(money(r[value]) for r in rows if r[uf] == "SANTA CATARINA")
    assert scalar(mart_db, f"select sum({target}) from mart.emendas") == expected


def test_emendas_columns_are_in_portuguese_without_accents(mart_db):
    columns = {
        row[0]
        for row in mart_db.execute(
            "select column_name from information_schema.columns "
            "where table_schema = 'mart' and table_name = 'emendas'"
        )
    }
    assert {"ano", "autor", "municipio", "funcao", "valor_pago", "valor_empenhado"} <= columns
    assert all(re.fullmatch(r"[a-z_]+", c) for c in columns)


def test_emendas_year_is_the_amendment_year(mart_db):
    assert scalar(mart_db, "select count(*) from mart.emendas where ano is null or ano < 2014") == 0


def test_convenios_keep_only_santa_catarina(mart_db):
    places = column(CONV, "Localidade do gasto")
    expected = sum(p.endswith(" - SC") or p == "SANTA CATARINA (UF)" for p in places)
    assert scalar(mart_db, "select count(*) from mart.convenios") == expected


def test_pagamentos_follow_the_amendment_destination_not_the_favorecido_uf(mart_db):
    header, rows = read_csv(FAV)
    code, value = header.index("Código da Emenda"), header.index("Valor Recebido")
    codes = sc_emenda_codes()
    expected = sum(money(r[value]) for r in rows if r[code] in codes)
    total = scalar(mart_db, "select sum(valor_recebido) from mart.pagamentos_favorecidos")
    assert total == expected
    assert (
        scalar(
            mart_db,
            "select count(*) from mart.pagamentos_favorecidos where uf_favorecido <> 'SC'",
        )
        > 0
    )


def test_pagamentos_carry_the_amendment_year_and_author(mart_db):
    assert (
        scalar(
            mart_db,
            "select count(*) from mart.pagamentos_favorecidos p "
            "join mart.emendas e using (codigo_emenda) where p.ano_emenda <> e.ano",
        )
        == 0
    )


def test_pagamento_year_comes_from_competencia(mart_db):
    assert (
        scalar(
            mart_db,
            "select count(*) from mart.pagamentos_favorecidos "
            "where ano_pagamento <> extract(year from competencia)",
        )
        == 0
    )


def test_pessoa_fisica_name_and_code_are_not_exposed(staging_db):
    staging_db.execute(
        """
        insert into staging.pagamentos_favorecido
            (codigo_emenda, tipo_favorecido, nome_favorecido, codigo_favorecido,
             competencia, valor_recebido)
        select codigo_emenda, 'Pessoa Física', 'MARIA APARECIDA DA SILVA', '***.123.456-**',
               date '2024-01-01', 10
        from staging.emendas where uf_sigla = 'SC' and codigo_emenda is not null limit 1
        """
    )
    apply_sql(staging_db, "03_mart.sql")
    row = staging_db.execute(
        "select nome_favorecido, codigo_favorecido from mart.pagamentos_favorecidos "
        "where tipo_favorecido = 'Pessoa Física' and valor_recebido = 10"
    ).fetchone()
    assert row == ("Pessoa física (nome omitido)", None)


def test_eleven_digit_sequences_in_names_are_masked(staging_db):
    staging_db.execute(
        """
        insert into staging.pagamentos_favorecido
            (codigo_emenda, tipo_favorecido, nome_favorecido, codigo_favorecido,
             competencia, valor_recebido)
        select codigo_emenda, 'Pessoa Jurídica', 'JOAO DA SILVA 12345678901', '12345678000190',
               date '2024-01-01', 11
        from staging.emendas where uf_sigla = 'SC' and codigo_emenda is not null limit 1
        """
    )
    apply_sql(staging_db, "03_mart.sql")
    name = scalar(
        staging_db,
        "select nome_favorecido from mart.pagamentos_favorecidos where valor_recebido = 11",
    )
    assert name == "JOAO DA SILVA ***"


def test_no_text_in_the_mart_looks_like_a_cpf(mart_db):
    cpf = r"(\*\*\*\.\d{3}\.\d{3}-\*\*|\d{3}\.\d{3}\.\d{3}-\d{2}|(?<![0-9])[0-9]{11}(?![0-9]))"
    columns = mart_db.execute(
        "select table_name, column_name from information_schema.columns "
        "where table_schema = 'mart' and data_type = 'text'"
    ).fetchall()
    for table, col in columns:
        hits = scalar(
            mart_db,
            f'select count(*) from mart.{table} where "{col}" ~ %s',
            (cpf,),
        )
        assert hits == 0, f"{table}.{col}"


def test_every_mart_table_and_column_has_a_comment(mart_db):
    missing_tables = mart_db.execute(
        """
        select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'mart' and c.relkind = 'r' and obj_description(c.oid) is null
        """
    ).fetchall()
    missing_columns = mart_db.execute(
        """
        select c.relname, a.attname from pg_attribute a
        join pg_class c on c.oid = a.attrelid join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'mart' and c.relkind = 'r' and a.attnum > 0 and not a.attisdropped
          and col_description(c.oid, a.attnum) is null
        """
    ).fetchall()
    assert missing_tables == []
    assert missing_columns == []


def test_fontes_describe_each_data_table(mart_db):
    rows = mart_db.execute("select tabela, ano_inicio, ano_fim from mart.fontes").fetchall()
    assert {r[0] for r in rows} == set(TABLES) - {"fontes"}
    assert all(r[1] <= r[2] for r in rows)


def test_mart_rebuild_does_not_duplicate_rows(mart_db):
    before = scalar(mart_db, "select count(*) from mart.emendas")
    apply_sql(mart_db, "03_mart.sql")
    assert scalar(mart_db, "select count(*) from mart.emendas") == before
