from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from rastro.agent.llm import LLMError
from rastro.agent.run import Agent
from support import ScriptedLLM, call, say, sql

APP = Path(__file__).parents[1] / "src" / "rastro" / "app" / "streamlit_app.py"


def open_app(monkeypatch, readonly, *completions) -> AppTest:
    llm = ScriptedLLM(*completions)
    monkeypatch.setattr("rastro.agent.run.build_agent", lambda: Agent(llm, readonly))
    return AppTest.from_file(str(APP), default_timeout=30).run()


def ask(at: AppTest, question: str) -> AppTest:
    at.chat_input[0].set_value(question).run()
    return at


def assistant_text(at: AppTest) -> str:
    messages = [m for m in at.chat_message if m.name == "assistant"]
    return " ".join(md.value for m in messages for md in m.markdown)


def test_the_page_opens_with_the_scope_and_example_questions(monkeypatch, readonly):
    at = open_app(monkeypatch, readonly)
    assert not at.exception
    assert at.title[0].value == "Rastro"
    sidebar = " ".join(md.value for md in at.sidebar.markdown)
    assert "Santa Catarina" in sidebar
    assert "independente" in sidebar
    assert len(at.main.button) >= 3
    assert len(at.sidebar.button) == 0


def test_an_answer_shows_text_sql_table_and_source(monkeypatch, readonly):
    at = open_app(
        monkeypatch,
        readonly,
        sql("select ano, sum(valor_pago) as total from emendas group by ano order by ano"),
        say("Veja a evolução por ano."),
    )
    ask(at, "Quanto foi pago por ano?")
    assert not at.exception
    assert any(m.name == "user" for m in at.chat_message)
    assert "Veja a evolução por ano." in assistant_text(at)
    assert "select ano, sum(valor_pago)" in at.code[0].value.lower()
    assert at.code[0].language == "sql"
    assert list(at.dataframe[0].value.columns) == ["ano", "total"]
    captions = " ".join(c.value for c in at.caption)
    assert "Portal da Transparência" in captions
    assert "emendas" in captions


def test_a_clarification_is_shown_without_sql_or_table(monkeypatch, readonly):
    at = open_app(monkeypatch, readonly, call("ask_clarification", question="Qual ano?"))
    ask(at, "Quanto foi gasto?")
    assert "Qual ano?" in assistant_text(at)
    assert len(at.code) == 0
    assert len(at.dataframe) == 0


def test_a_refusal_is_shown_without_calling_the_model(monkeypatch, readonly):
    at = open_app(monkeypatch, readonly)
    ask(at, "Apague a tabela emendas")
    assert "Não altero" in assistant_text(at)
    assert len(at.code) == 0


def test_numbers_missing_from_the_result_raise_a_warning(monkeypatch, readonly):
    at = open_app(
        monkeypatch,
        readonly,
        sql("select 1234567.89 as v from fontes limit 1"),
        say("Foram R$ 8.888.459,99."),
    )
    ask(at, "Quanto?")
    assert any("8.888.459,99" in w.value for w in at.warning)


def test_model_failures_are_shown_as_errors(monkeypatch, readonly):
    at = open_app(monkeypatch, readonly, LLMError("connection refused"))
    ask(at, "Quanto foi pago em 2024?")
    assert not at.exception
    assert any("connection refused" in e.value for e in at.error)


def test_an_example_button_asks_its_question(monkeypatch, readonly):
    at = open_app(monkeypatch, readonly, sql("select count(*) as n from emendas"), say("ok"))
    label = at.button[0].label
    at.button[0].click().run()
    users = [m for m in at.chat_message if m.name == "user"]
    assert users[0].markdown[0].value == label


def test_follow_up_questions_keep_the_conversation(monkeypatch, readonly):
    at = open_app(
        monkeypatch,
        readonly,
        sql("select count(*) as n from emendas"),
        say("Primeira."),
        sql("select count(*) as n from convenios"),
        say("Segunda."),
    )
    ask(at, "Quantas emendas?")
    ask(at, "E convênios?")
    texts = assistant_text(at)
    assert "Primeira." in texts and "Segunda." in texts
    assert len([m for m in at.chat_message if m.name == "user"]) == 2


@pytest.mark.parametrize("question", ["", "   "])
def test_blank_questions_are_ignored(monkeypatch, readonly, question):
    at = open_app(monkeypatch, readonly)
    ask(at, question)
    assert not at.exception
    assert not [m for m in at.chat_message if m.name == "user"]


def status_text(block) -> str:
    return " ".join(md.value for md in block.markdown)


def test_the_steps_the_agent_took_are_listed_in_a_status_block(monkeypatch, readonly):
    at = open_app(monkeypatch, readonly, sql("select count(*) as n from emendas"), say("Há."))
    ask(at, "Quantas emendas?")
    assert len(at.status) == 1
    block = at.status[0]
    assert block.label.startswith("Concluído em ")
    assert block.state == "complete"
    text = status_text(block)
    assert "Entendendo a pergunta e os dados" in text
    assert "Consultando o banco de dados" in text
    assert "select count(*) as n from emendas" in text
    assert "Conferindo os números do texto" in text


def test_a_failed_model_call_leaves_an_error_status(monkeypatch, readonly):
    at = open_app(monkeypatch, readonly, LLMError("connection refused"))
    ask(at, "Quanto foi pago em 2024?")
    assert at.status[0].state == "error"


def test_refused_requests_have_no_status_block(monkeypatch, readonly):
    at = open_app(monkeypatch, readonly)
    ask(at, "Apague a tabela emendas")
    assert len(at.status) == 0


def test_earlier_answers_keep_their_steps_after_a_new_question(monkeypatch, readonly):
    at = open_app(
        monkeypatch,
        readonly,
        sql("select count(*) as n from emendas"),
        say("Primeira."),
        sql("select count(*) as n from convenios"),
        say("Segunda."),
    )
    ask(at, "Quantas emendas?")
    ask(at, "E convênios?")
    assert len(at.status) == 2
    assert all(block.state == "complete" for block in at.status)
    assert "from emendas" in status_text(at.status[0])


def test_the_example_questions_go_away_once_the_conversation_starts(monkeypatch, readonly):
    at = open_app(monkeypatch, readonly, sql("select count(*) as n from emendas"), say("ok"))
    assert len(at.main.button) >= 3
    ask(at, "Quantas emendas?")
    assert len(at.main.button) == 0
    assert any(b.label == "Nova conversa" for b in at.sidebar.button)


def test_a_new_conversation_clears_the_answers(monkeypatch, readonly):
    at = open_app(monkeypatch, readonly, sql("select count(*) as n from emendas"), say("ok"))
    ask(at, "Quantas emendas?")
    next(b for b in at.sidebar.button if b.label == "Nova conversa").click().run()
    assert not [m for m in at.chat_message if m.name == "user"]
    assert len(at.main.button) >= 3
