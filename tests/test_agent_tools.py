from decimal import Decimal

import pytest

from rastro.agent.sql_guard import GuardError
from rastro.agent.tools import QueryError, QueryResult, find_values, format_result, run_query


def test_run_query_returns_columns_rows_and_tables(readonly):
    result = run_query(
        readonly, "select ano, sum(valor_pago) as total from emendas group by ano order by ano"
    )
    assert result.columns == ("ano", "total")
    assert result.tables == ("emendas",)
    assert result.rows[0][0] == 2014
    assert isinstance(result.rows[0][1], Decimal)
    assert result.sql.lower().endswith("limit 200")
    assert result.elapsed_ms >= 0


def test_run_query_matches_a_direct_query(readonly):
    direct = readonly.execute("select sum(valor_pago) from mart.emendas").fetchone()[0]
    result = run_query(readonly, "select sum(valor_pago) from emendas")
    assert result.rows == ((direct,),)


def test_run_query_marks_truncated_results(readonly):
    result = run_query(readonly, "select * from pagamentos_favorecidos")
    assert len(result.rows) == 200
    assert result.truncated


def test_run_query_does_not_mark_small_results_as_truncated(readonly):
    assert not run_query(readonly, "select * from fontes").truncated


def test_run_query_rejects_what_the_guard_rejects(readonly):
    with pytest.raises(GuardError):
        run_query(readonly, "delete from emendas")


def test_run_query_turns_database_errors_into_messages_for_the_model(readonly):
    with pytest.raises(QueryError, match="coluna_que_nao_existe"):
        run_query(readonly, "select coluna_que_nao_existe from emendas")
    assert readonly.execute("select 1").fetchone() == (1,)


def test_run_query_stops_slow_queries(readonly):
    readonly.execute("set statement_timeout = '50ms'")
    with pytest.raises(QueryError, match="too long"):
        run_query(
            readonly,
            "select count(*) from pagamentos_favorecidos a, pagamentos_favorecidos b, emendas c",
        )


def test_format_result_is_compact_and_limits_rows(readonly):
    result = run_query(readonly, "select autor, ano, valor_pago from emendas order by ano")
    text = format_result(result, max_rows=3)
    lines = text.splitlines()
    assert lines[0] == "autor | ano | valor_pago"
    assert len([line for line in lines if " | " in line]) == 4
    assert "showing 3 of 200 rows" in text


def test_format_result_says_when_there_are_no_rows(readonly):
    result = run_query(readonly, "select * from emendas where ano = 1900")
    assert "0 rows" in format_result(result)


def test_find_values_ignores_case_and_accents(readonly):
    name = readonly.execute(
        "select municipio from mart.emendas where municipio like '%Ó%' limit 1"
    ).fetchone()[0]
    plain = name.encode("ascii", "ignore").decode().lower()
    found = [value for value, _ in find_values(readonly, "municipio", plain)]
    assert name in found


def test_find_values_counts_occurrences_and_orders_by_frequency(readonly):
    found = find_values(readonly, "funcao", "")
    counts = [n for _, n in found]
    assert counts == sorted(counts, reverse=True)
    assert len(found) <= 10


def test_find_values_treats_wildcards_literally(readonly):
    assert find_values(readonly, "municipio", "%") == []


def test_find_values_rejects_unknown_kinds(readonly):
    with pytest.raises(QueryError, match="municipio"):
        find_values(readonly, "cpf", "123")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("888845998.75"), "888.845.998,75"),
        (Decimal("1234567.5"), "1.234.567,50"),
        (Decimal("0"), "0,00"),
        (Decimal("-15.3"), "-15,30"),
        (Decimal("33.3333333333"), "33,33"),
        (2024, "2024"),
        (1234567, "1234567"),
        (None, "NULL"),
    ],
)
def test_numbers_are_written_in_brazilian_format_for_the_model(value, expected):
    result = QueryResult("", (), ("v",), ((value,),), False, 0)
    assert format_result(result).splitlines()[1] == expected
