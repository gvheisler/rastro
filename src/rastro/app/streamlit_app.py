from decimal import Decimal
from typing import Any

import pandas as pd
import psycopg
import streamlit as st

from rastro.agent.run import Answer, build_agent

EXAMPLES = [
    "Quanto foi pago em emendas para Santa Catarina em cada ano?",
    "Quais municípios receberam mais recursos em 2023?",
    "Quais autores destinaram mais valor empenhado em 2024?",
    "Em quais funções as emendas concentram mais recursos?",
]
CONTEXT_TURNS = 3


def main() -> None:
    st.set_page_config(page_title="Rastro", layout="centered")
    st.title("Rastro")
    st.caption(
        "Pergunte em português para onde foi o dinheiro das emendas parlamentares "
        "destinadas a Santa Catarina."
    )
    render_sidebar()

    if "answers" not in st.session_state:
        st.session_state.answers = []
    for answer in st.session_state.answers:
        with st.chat_message("user"):
            st.markdown(answer.question)
        with st.chat_message("assistant"):
            render_answer(answer)

    question = st.chat_input("Pergunte sobre as emendas para Santa Catarina")
    question = question or st.session_state.pop("pending", None)
    if question and question.strip():
        ask(question.strip())


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### Como funciona")
        st.markdown(
            "Sua pergunta vira uma consulta SQL somente leitura sobre dados públicos de emendas "
            "parlamentares federais com destino a Santa Catarina. A resposta mostra o SQL, a "
            "tabela com o resultado e a fonte."
        )
        st.markdown("### Exemplos")
        for example in EXAMPLES:
            if st.button(example, width="stretch"):
                st.session_state.pending = example
        st.markdown("### Aviso")
        st.markdown(
            "Projeto independente, sem vínculo com o TCE/SC, a ALESC, a CGU ou qualquer outro "
            "órgão público. Os números vêm do Portal da Transparência e não implicam juízo sobre "
            "pessoas, empresas ou parlamentares."
        )


def ask(question: str) -> None:
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        try:
            if "agent" not in st.session_state:
                st.session_state.agent = build_agent()
            history = [a for a in st.session_state.answers if a.status == "answered"]
            with st.spinner("Consultando os dados..."):
                answer = st.session_state.agent.ask(question, history[-CONTEXT_TURNS:])
        except psycopg.OperationalError as error:
            st.error(f"Não consegui conectar ao banco. Rode `make up`. ({error})")
            return
        render_answer(answer)
    st.session_state.answers.append(answer)


def render_answer(answer: Answer) -> None:
    if answer.error:
        st.error(f"{answer.text} ({answer.error})")
        return
    st.markdown(answer.text)
    if answer.unverified_numbers:
        st.warning(
            "Estes valores do texto não aparecem no resultado da consulta, confira na tabela: "
            + ", ".join(answer.unverified_numbers)
        )
    if not answer.sql:
        return

    with st.expander("SQL executado"):
        st.code(answer.sql, language="sql")
    frame, config = table(answer)
    st.dataframe(frame, hide_index=True, column_config=config)
    st.caption(caption(answer))


def table(answer: Answer) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = pd.DataFrame(answer.rows, columns=list(answer.columns))
    config = {}
    for name in frame.columns:
        values = frame[name].dropna()
        if values.empty:
            continue
        if isinstance(values.iloc[0], Decimal):
            frame[name] = frame[name].astype(float)
            config[name] = st.column_config.NumberColumn(format="localized")
        elif isinstance(values.iloc[0], int):
            config[name] = st.column_config.NumberColumn(format="%d")
    return frame, config


def caption(answer: Answer) -> str:
    parts = []
    for source in answer.sources:
        parts.append(
            f"Fonte: {source.fonte}, {source.arquivo} ({source.ano_inicio} a {source.ano_fim}), "
            f"carregado em {source.carregado_em:%d/%m/%Y}"
        )
    parts.append("Tabelas: " + ", ".join(answer.tables))
    if answer.truncated:
        parts.append("Resultado limitado às primeiras 200 linhas")
    parts.append(f"Modelo: {answer.model}, {answer.latency_s:.1f} s")
    return " · ".join(parts)


main()
