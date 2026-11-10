from datetime import date

from rastro.agent.prompt import coverage_text, schema_text, system_prompt
from rastro.agent.sql_guard import ALLOWED_TABLES

TODAY = date(2026, 11, 10)


def test_schema_lists_allowed_tables_with_columns_types_and_comments(readonly):
    text = schema_text(readonly)
    for table in ALLOWED_TABLES:
        assert f"Tabela {table}" in text
    assert "valor_pago (numeric" in text
    assert "ano (smallint" in text
    assert "Ano da emenda no orçamento" in text
    assert "localidade_tipo" in text


def test_schema_does_not_leak_upstream_layers(readonly):
    text = schema_text(readonly)
    assert "staging" not in text
    assert "raw." not in text


def test_coverage_reports_years_and_load_date(readonly):
    text = coverage_text(readonly, TODAY)
    assert "emendas" in text
    assert "pagamentos_favorecidos" in text
    assert "2014" in text
    assert "carregados em" in text


def test_prompt_names_the_tools_and_the_rules(readonly):
    prompt = system_prompt(readonly, TODAY)
    for name in ("run_sql", "find_values", "ask_clarification", "refuse"):
        assert name in prompt
    assert "10/11/2026" in prompt
    assert "count(distinct codigo_emenda)" in prompt
    assert "Tabela emendas" in prompt


def test_prompt_is_deterministic_and_fits_a_small_context(readonly):
    assert system_prompt(readonly, TODAY) == system_prompt(readonly, TODAY)
    assert len(system_prompt(readonly, TODAY)) < 16000


def test_prompt_states_how_to_read_ambiguous_terms(readonly):
    prompt = system_prompt(readonly, TODAY)
    assert "like 'Emenda Individual%'" in prompt
    assert "having sum(valor_pago) = 0" in prompt
    assert "parênteses" in prompt
    assert "use valor_pago" in prompt
