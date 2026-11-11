import pytest

from rastro.agent.question_check import unrequested_filters

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
