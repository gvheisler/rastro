import pytest

from rastro.agent.sql_guard import GuardError, guard_sql


@pytest.mark.parametrize(
    "query",
    [
        "select sum(valor_pago) from emendas where ano = 2024",
        "SELECT * FROM mart.emendas LIMIT 5;",
        "select e.autor, count(distinct e.codigo_emenda) from emendas e group by 1 order by 2 desc",
        "select * from emendas e join convenios c on c.codigo_emenda = e.codigo_emenda",
        "with t as (select ano, sum(valor_pago) v from emendas group by ano) select * from t",
        "select ano from emendas union select ano_emenda from convenios",
        "select * from emendas where municipio in (select municipio from emendas limit 3)",
        "select autor, rank() over (order by sum(valor_pago) desc) from emendas group by autor",
        "select * from emendas where unaccent(municipio) ilike '%florianopolis%'",
        "select 1 -- comment\n from emendas",
        "select * from EMENDAS",
        "select * from fontes",
    ],
)
def test_valid_selects_are_accepted(query):
    assert guard_sql(query).sql.lower().startswith(("select", "with"))


@pytest.mark.parametrize(
    "query",
    [
        "",
        "   ",
        "select 1; select 2",
        "select 1; drop table emendas",
        "drop table emendas",
        "delete from emendas",
        "update emendas set valor_pago = 0",
        "insert into fontes (tabela) values ('x')",
        "truncate emendas",
        "create table x as select * from emendas",
        "alter table emendas add column x int",
        "grant all on emendas to public",
        "copy emendas to stdout",
        "explain select * from emendas",
        "set role postgres",
        "select * into backup from emendas",
        "select * from emendas for update",
        "with x as (delete from emendas returning *) select * from x",
        "select pg_sleep(10)",
        "select pg_read_file('/etc/passwd')",
        "select lo_import('/etc/passwd')",
        "select current_setting('data_directory')",
        "select * from pg_catalog.pg_user",
        "select * from pg_user",
        "select * from information_schema.tables",
        'select * from "PG_USER"',
        "select * from raw.emendas_parlamentares",
        "select * from staging.emendas",
        "select * from public.emendas",
        "select * from outra_tabela",
        "select * from emendas, pg_class",
        "select (select count(*) from pg_class)",
        "select * from generate_series(1, 1000000)",
        "select * from emendas fetch first 3 rows only",
        "selec * from emendas",
        "select 1",
        "select now()",
    ],
)
def test_anything_else_is_rejected(query):
    with pytest.raises(GuardError):
        guard_sql(query)


def test_error_messages_help_the_model_correct_itself():
    with pytest.raises(GuardError, match="outra_tabela.*emendas"):
        guard_sql("select * from outra_tabela")


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("select * from emendas", "limit 200"),
        ("select * from emendas limit 10", "limit 10"),
        ("select * from emendas limit 5000", "limit 200"),
        ("select * from emendas limit all", "limit 200"),
        ("select ano from emendas union select ano_emenda from convenios", "limit 200"),
    ],
)
def test_row_limit_is_enforced(query, expected):
    assert guard_sql(query).sql.lower().endswith(expected)


def test_limit_is_reported_when_it_was_added_or_lowered():
    assert guard_sql("select * from emendas").row_limit == 200
    assert guard_sql("select * from emendas limit 5000").row_limit == 200
    assert guard_sql("select * from emendas limit 10").row_limit == 10


def test_existing_order_and_filters_survive_the_limit():
    sql = guard_sql("select autor from emendas where ano = 2024 order by autor").sql.lower()
    assert "where ano = 2024" in sql
    assert "order by autor" in sql


def test_tables_lists_real_tables_and_not_ctes():
    guarded = guard_sql(
        "with t as (select * from convenios) select * from t join emendas using (codigo_emenda)"
    )
    assert guarded.tables == ("convenios", "emendas")
