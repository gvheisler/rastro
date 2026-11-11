import pytest

from rastro.agent.question_check import (
    unrequested_filters,
    unrequested_values,
    value_assumption,
    year_assumption,
)

BY_FUNCTION = "select funcao, sum(valor_pago) from emendas where {where} group by funcao"


@pytest.mark.parametrize(
    ("question", "where", "expected"),
    [
        (
            "Quais funções tiveram mais valor pago em 2024?",
            "ano = 2024 and localidade_tipo = 'municipio'",
            ["localidade_tipo = 'municipio'"],
        ),
        (
            "Quais funções tiveram mais valor pago nos municípios em 2024?",
            "ano = 2024 and localidade_tipo = 'municipio'",
            [],
        ),
        ("Quanto o estado recebeu em 2024?", "ano = 2024 and localidade_tipo = 'estado'", []),
        ("Quanto foi pago em 2024?", "ano = 2024", []),
        ("Quanto foi pago?", "ano = 2024", ["ano = 2024"]),
        ("Quanto foi pago em 2024?", "ano in (2023, 2024)", ["ano IN (2023, 2024)"]),
        ("Quanto foi pago em 2023 e 2024?", "ano in (2023, 2024)", []),
        ("Quanto foi pago entre 2020 e 2023?", "ano between 2020 and 2023", []),
        ("Quanto foi pago este ano?", "ano = 2026", []),
        ("Quanto foi pago no ano passado?", "ano = 2025", []),
        ("Quanto foi pago nos últimos 3 anos?", "ano >= 2024", []),
        ("Quanto foi pago?", "ano = extract(year from current_date)", []),
        (
            "Quanto foi pago?",
            "tipo_emenda like 'Emenda Individual%'",
            ["tipo_emenda LIKE 'Emenda Individual%'"],
        ),
        ("Quanto foi pago em emendas individuais?", "tipo_emenda like 'Emenda Individual%'", []),
        ("Quanto veio das emendas de bancada?", "tipo_emenda = 'Emenda de Bancada'", []),
        ("Quanto foi pago?", "valor_pago > 0", []),
    ],
)
def test_filters_the_question_did_not_ask_for_are_reported(question, where, expected):
    sql = BY_FUNCTION.format(where=where)
    assert unrequested_filters(sql, question) == expected


def test_a_year_filter_on_a_date_column_needs_the_year_in_the_question():
    sql = "select count(*) from convenios where extract(year from data_publicacao) = 2023"
    assert unrequested_filters(sql, "Quantos convênios foram publicados?") == [
        "EXTRACT(YEAR FROM data_publicacao) = 2023"
    ]
    assert unrequested_filters(sql, "Quantos convênios foram publicados em 2023?") == []


def test_a_city_in_the_query_justifies_the_municipal_location_filter():
    sql = (
        "select sum(valor_pago) from emendas "
        "where municipio = 'JOINVILLE' and localidade_tipo = 'municipio' and ano = 2024"
    )
    assert unrequested_filters(sql, "Quanto Joinville recebeu em 2024?") == []


def test_years_from_earlier_questions_count_as_asked():
    sql = "select sum(valor_pago) from convenios where ano_emenda = 2023"
    assert unrequested_filters(sql, "E de convênios?") == ["ano_emenda = 2023"]
    assert unrequested_filters(sql, "Quanto foi pago em 2023? E de convênios?") == []


def test_only_comparisons_count_not_columns_that_are_merely_selected_or_grouped():
    sql = "select ano, localidade_tipo, sum(valor_pago) from emendas group by ano, localidade_tipo"
    assert unrequested_filters(sql, "Quanto foi pago?") == []


def test_a_filter_on_the_impeded_flag_needs_the_question_to_mention_it():
    sql = "select count(*) from transferencias_especiais where impedido = true"
    assert unrequested_filters(sql, "Quantos planos há?") == ["impedido = TRUE"]
    assert unrequested_filters(sql, "Quantos planos estão impedidos?") == []


@pytest.mark.parametrize(
    ("where", "flagged"),
    [
        ("impedido", "impedido"),
        ("not impedido", "NOT impedido"),
        ("impedido is true", "impedido IS TRUE"),
    ],
)
def test_the_impeded_flag_is_caught_even_without_a_comparison(where, flagged):
    sql = f"select count(*) from transferencias_especiais where {where}"
    assert unrequested_filters(sql, "Quantos planos há?") == [flagged]
    assert unrequested_filters(sql, "Quantos planos estão impedidos?") == []


@pytest.mark.parametrize("sql", ["", "selec nada", "select 1 from", "delete from emendas"])
def test_queries_that_cannot_be_read_are_left_to_the_sql_guard(sql):
    assert unrequested_filters(sql, "Quanto foi pago?") == []


@pytest.mark.parametrize(
    ("query", "question", "expected"),
    [
        (
            "select sum(valor_pago) from emendas where ano >= 2020",
            "Quanto foi gasto desde 2020?",
            "Você não disse qual valor queria; usei o valor pago.",
        ),
        (
            "select sum(valor_empenhado) from transferencias_especiais",
            "Quanto Joinville recebeu?",
            "Você não disse qual valor queria; usei o valor empenhado.",
        ),
        (
            "select sum(valor_planejado) from transferencias_especiais",
            "Quanto Joinville tem?",
            "Você não disse qual valor queria; usei o valor planejado.",
        ),
        ("select sum(valor_pago) from emendas", "Quanto foi pago?", None),
        ("select sum(valor_empenhado) from emendas", "Quanto foi empenhado?", None),
        ("select sum(valor_liquidado) from emendas", "Quanto já foi liquidado?", None),
        ("select sum(valor_planejado) from transferencias_especiais", "Quanto foi previsto?", None),
        ("select sum(valor_pago) from emendas", "Quanto foi empenhado?", None),
        ("select count(*) from convenios", "Quantos convênios há?", None),
        ("select sum(valor_recebido) from pagamentos_favorecidos", "Quanto cada um recebeu?", None),
        (
            "select sum(valor_empenhado), sum(valor_pago) from emendas",
            "Quanto foi gasto?",
            "Você não disse qual valor queria; usei o valor pago e o valor empenhado.",
        ),
        (
            "select sum(valor_liquidado), sum(valor_empenhado), sum(valor_pago) from emendas",
            "Quanto foi gasto?",
            "Você não disse qual valor queria; usei o valor pago, o valor empenhado e o valor "
            "liquidado.",
        ),
        ("select sum(valor_pago) from", "Quanto foi gasto?", None),
    ],
)
def test_the_value_the_query_used_is_reported_when_the_question_did_not_name_one(
    query, question, expected
):
    assert value_assumption(query, question) == expected


@pytest.mark.parametrize(
    ("query", "question", "expected"),
    [
        (
            "select sum(valor_pago) as p, sum(valor_liquidado) as l from emendas",
            "Quais os valores de emendas?",
            ["valor_pago", "valor_liquidado"],
        ),
        (
            "select sum(valor_pago) - sum(valor_liquidado) from emendas",
            "Quanto foi gasto?",
            ["valor_pago", "valor_liquidado"],
        ),
        (
            "select sum(valor_pago), sum(valor_restos_a_pagar_inscritos) from emendas",
            "Quanto foi gasto?",
            ["valor_pago", "valor_restos_a_pagar_inscritos"],
        ),
        ("select sum(valor_pago) from emendas", "Quanto foi gasto?", []),
        (
            "select sum(valor_pago), sum(valor_empenhado) from emendas",
            "Quanto foi pago e quanto foi empenhado?",
            [],
        ),
        ("select sum(valor_pago) / sum(valor_empenhado) from emendas", "Qual o % pago?", []),
        ("select count(*) from convenios", "Quantos convênios há?", []),
        ("select sum(valor_pago), sum(valor_empenhado) from", "Quanto foi gasto?", []),
    ],
)
def test_several_values_in_one_query_are_reported_when_the_question_named_none(
    query, question, expected
):
    assert unrequested_values(query, question) == expected


def test_a_value_named_in_an_earlier_question_counts_as_named():
    query = "select sum(valor_pago) from emendas where ano = 2023"
    assert value_assumption(query, "E em 2023?") is not None
    assert value_assumption(query, "Quanto foi pago em 2024? E em 2023?") is None


@pytest.mark.parametrize(
    ("query", "fragment"),
    [
        ("select sum(valor_pago) from emendas where ano >= 2020", "ano >= 2020"),
        ("select sum(valor_pago) from emendas where ano in (2023, 2024)", "ano IN (2023, 2024)"),
        (
            "select sum(valor_pago) from emendas where tipo_emenda = 'Emenda de Bancada' "
            "and ano between 2020 and 2022",
            "ano BETWEEN 2020 AND 2022",
        ),
        ("select sum(valor_pago) from convenios where ano_emenda = 2023", "ano_emenda = 2023"),
    ],
)
def test_a_paid_value_by_the_year_of_the_emenda_says_it_is_not_the_payment_date(query, fragment):
    assert year_assumption(query) == (
        f"Considerei o ano da emenda no orçamento, não a data do pagamento (`{fragment}`)."
    )


@pytest.mark.parametrize(
    "query",
    [
        "select sum(valor_empenhado) from emendas where ano >= 2020",
        "select sum(valor_pago) from emendas",
        "select sum(valor_recebido) from pagamentos_favorecidos where ano_pagamento = 2024",
        "select sum(valor_pago) from emendas where extract(year from current_date) = 2024",
        "select sum(valor_pago) from",
    ],
)
def test_no_year_note_without_a_paid_value_filtered_by_the_year_of_the_emenda(query):
    assert year_assumption(query) is None
