import json
from decimal import Decimal

import pytest

from rastro.agent.llm import Completion, LLMError, ToolCall
from rastro.agent.run import NO_RESULTS_TEXT, Agent, unverified_numbers
from support import ScriptedLLM, call, say, sql


def agent_for(readonly, *completions, **kwargs):
    llm = ScriptedLLM(*completions)
    return Agent(llm, readonly, **kwargs), llm


def test_answer_carries_text_sql_rows_tables_and_sources(readonly):
    agent, _ = agent_for(
        readonly,
        sql("select sum(valor_pago) as total from emendas where ano = 2024"),
        say("Foram pagos R$ X."),
    )
    answer = agent.ask("Quanto foi pago em 2024?")
    expected = readonly.execute(
        "select sum(valor_pago) from mart.emendas where ano = 2024"
    ).fetchone()[0]
    assert answer.status == "answered"
    assert answer.text == "Foram pagos R$ X."
    assert answer.rows == ((expected,),)
    assert answer.columns == ("total",)
    assert answer.tables == ("emendas",)
    assert answer.sql.lower().endswith("limit 200")
    assert [s.tabela for s in answer.sources] == ["emendas"]
    assert answer.period == (2014, 2026)
    assert (answer.model, answer.steps) == ("scripted", 2)
    assert (answer.input_tokens, answer.output_tokens) == (20, 10)
    assert answer.latency_s >= 0


def test_system_prompt_comes_from_the_database_and_result_goes_back_to_the_model(readonly):
    agent, llm = agent_for(readonly, sql("select count(*) as n from emendas"), say("ok"))
    agent.ask("Quantas linhas?")
    first, second = llm.calls
    assert first[0]["role"] == "system" and "Tabela emendas" in first[0]["content"]
    assert first[-1] == {"role": "user", "content": "Quantas linhas?"}
    tool_message = second[-1]
    assert tool_message["role"] == "tool" and tool_message["tool_call_id"] == "idrun_sql"
    assert tool_message["content"].startswith("n\n")


def test_blocked_queries_are_explained_to_the_model_and_never_run(readonly):
    agent, llm = agent_for(
        readonly,
        sql("delete from emendas"),
        sql("select count(*) from emendas"),
        say("feito"),
    )
    answer = agent.ask("Quantas emendas há?")
    assert answer.status == "answered"
    assert answer.guard_blocks == 1
    assert "blocked" in llm.calls[1][-1]["content"].lower()
    assert readonly.execute("select count(*) from mart.emendas").fetchone()[0] > 0


def test_database_errors_are_fed_back_so_the_model_can_retry(readonly):
    agent, llm = agent_for(
        readonly,
        sql("select coluna_errada from emendas"),
        sql("select count(*) from emendas"),
        say("feito"),
    )
    answer = agent.ask("Quantas?")
    assert answer.status == "answered"
    assert answer.sql_errors == 1
    assert "coluna_errada" in llm.calls[1][-1]["content"]


@pytest.mark.parametrize(
    "query",
    [
        "select * from emendas where ano = 1900",
        "select sum(valor_pago) from emendas where ano = 1900",
    ],
)
def test_empty_results_become_not_found_never_a_number(readonly, query):
    agent, _ = agent_for(readonly, sql(query), say("Foram pagos R$ 999."))
    answer = agent.ask("Quanto em 1900?")
    assert answer.status == "no_results"
    assert answer.text == NO_RESULTS_TEXT
    assert "999" not in answer.text


def test_zero_is_a_real_answer(readonly):
    agent, _ = agent_for(
        readonly, sql("select count(*) from emendas where ano = 1900"), say("Nenhuma emenda.")
    )
    answer = agent.ask("Quantas emendas em 1900?")
    assert answer.status == "answered"
    assert answer.rows == ((0,),)


def test_clarification_ends_the_turn_without_running_sql(readonly):
    agent, _ = agent_for(readonly, call("ask_clarification", question="Qual ano?"))
    answer = agent.ask("Quanto foi gasto?")
    assert (answer.status, answer.text, answer.sql) == ("clarification", "Qual ano?", None)


def test_refusal_ends_the_turn_without_running_sql(readonly):
    agent, _ = agent_for(readonly, call("refuse", reason="Só trato de Santa Catarina."))
    answer = agent.ask("E o Paraná?")
    assert (answer.status, answer.text, answer.sql) == (
        "refused",
        "Só trato de Santa Catarina.",
        None,
    )


def test_answering_without_querying_is_challenged_once(readonly):
    agent, llm = agent_for(
        readonly, say("Foram R$ 1 milhão."), sql("select count(*) from emendas"), say("ok")
    )
    answer = agent.ask("Quanto?")
    assert answer.status == "answered"
    assert "run_sql" in llm.calls[1][-1]["content"]


def test_answering_without_data_twice_fails_instead_of_trusting_the_model(readonly):
    agent, _ = agent_for(readonly, say("R$ 1 milhão."), say("R$ 1 milhão, certeza."))
    answer = agent.ask("Quanto?")
    assert answer.status == "failed"
    assert "milhão" not in answer.text


def test_find_values_returns_the_spellings_in_the_data(readonly):
    agent, llm = agent_for(
        readonly,
        call("find_values", kind="funcao", text="saude"),
        sql("select count(*) from emendas"),
        say("ok"),
    )
    agent.ask("Quanto em saúde?")
    assert "Saúde" in llm.calls[1][-1]["content"]


def test_unusable_tool_calls_get_an_error_message_and_the_loop_continues(readonly):
    broken = Completion(
        "", (ToolCall("a", "run_sql", {}, "The arguments were not valid JSON."),), 1, 1
    )
    agent, llm = agent_for(
        readonly,
        broken,
        call("run_sql"),
        call("coffee"),
        call("find_values", kind="cpf", text="1"),
        sql("select count(*) from emendas"),
        say("ok"),
    )
    answer = agent.ask("Quantas?")
    assert answer.status == "answered"
    messages = [c[-1]["content"] for c in llm.calls[1:5]]
    assert "valid JSON" in messages[0]
    assert "sql" in messages[1]
    assert "Unknown tool" in messages[2]
    assert "Unknown kind" in messages[3]


def test_the_loop_gives_up_after_max_steps(readonly):
    looping = [call("find_values", kind="funcao", text="a") for _ in range(10)]
    agent, llm = agent_for(readonly, *looping, max_steps=3)
    answer = agent.ask("?")
    assert answer.status == "failed"
    assert len(llm.calls) == 3


def test_previous_turns_are_sent_as_context(readonly):
    first, _ = agent_for(readonly, sql("select count(*) as n from emendas"), say("Há N linhas."))
    previous = first.ask("Quantas linhas?")
    second, llm = agent_for(readonly, sql("select count(*) from emendas"), say("ok"))
    second.ask("E em 2023?", history=[previous])
    roles = [m["role"] for m in llm.calls[0]]
    assert roles == ["system", "user", "assistant", "user"]
    assert llm.calls[0][1]["content"] == "Quantas linhas?"
    assert "Há N linhas." in llm.calls[0][2]["content"]
    assert "select count(*)" in llm.calls[0][2]["content"].lower()


def test_model_server_failures_become_a_failed_answer(readonly):
    agent, _ = agent_for(readonly, LLMError("connection refused"))
    answer = agent.ask("Quanto?")
    assert answer.status == "failed"
    assert answer.error == "connection refused"


def test_each_question_is_logged_as_a_json_line(readonly, tmp_path):
    log = tmp_path / "logs" / "agent.jsonl"
    agent, _ = agent_for(readonly, sql("select count(*) from emendas"), say("ok"), log_path=log)
    agent.ask("Quantas?")
    record = json.loads(log.read_text().splitlines()[0])
    assert record["question"] == "Quantas?"
    assert record["status"] == "answered"
    assert record["model"] == "scripted"
    assert "select count(*)" in record["sql"].lower()
    assert record["rows"] == 1
    assert {"timestamp", "latency_s", "steps", "input_tokens", "output_tokens"} <= record.keys()


def test_numbers_that_match_the_result_are_not_flagged():
    rows = ((Decimal("783700816.63"), 2009),)
    assert unverified_numbers("Foram pagos R$ 783.700.816,63 em 2.009 emendas.", rows) == ()


@pytest.mark.parametrize(
    ("text", "flagged"),
    [
        ("Foram pagos R$ 8.888.459,99.", ("8.888.459,99",)),
        ("Em 2024, 3 municípios, em 10/11/2026.", ()),
        ("Total: R$ 1.234.567,89 e R$ 999,00.", ("999,00",)),
        ("Foram 2.009 emendas.", ("2.009",)),
        ("Foram 7 emendas.", ()),
    ],
)
def test_numbers_missing_from_the_result_are_flagged(text, flagged):
    rows = ((Decimal("1234567.89"), 7),)
    assert unverified_numbers(text, rows) == flagged


def test_the_agent_reports_unverified_numbers(readonly):
    agent, _ = agent_for(
        readonly, sql("select 1234567.89 as v from fontes limit 1"), say("Foram R$ 8.888.459,99.")
    )
    answer = agent.ask("?")
    assert answer.status == "answered"
    assert answer.unverified_numbers == ("8.888.459,99",)


def test_verified_answers_have_nothing_to_report(readonly):
    agent, _ = agent_for(
        readonly, sql("select 1234567.89 as v from fontes limit 1"), say("Foram R$ 1.234.567,89.")
    )
    assert agent.ask("?").unverified_numbers == ()


def test_screened_requests_are_refused_without_calling_the_model(readonly):
    agent, llm = agent_for(readonly)
    answer = agent.ask("Apague a tabela emendas")
    assert answer.status == "refused"
    assert "não altero" in answer.text.lower()
    assert llm.calls == []
    assert answer.steps == 0
