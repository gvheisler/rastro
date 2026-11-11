from decimal import Decimal
from typing import Any

import pandas as pd
import psycopg
import streamlit as st

from rastro.agent.run import Answer, Step, StepKind, build_agent

EXAMPLES = [
    "Quanto foi pago em emendas para Santa Catarina em cada ano?",
    "Quais municípios tiveram mais valor pago em emendas em 2023?",
    "Quais autores destinaram mais valor empenhado em 2024?",
    "Quanto foi empenhado em transferências especiais em cada ano?",
]
CONTEXT_TURNS = 3
ASSISTANT_AVATAR = ":material/travel_explore:"
USER_AVATAR = ":material/person:"
STYLE = """
<style>
.st-key-examples button {
    min-height: 4.5rem;
    padding: 0.75rem 1rem;
}
.st-key-examples button > div,
.st-key-examples button span {
    display: block !important;
    width: 100%;
    text-align: left !important;
}
.st-key-examples button p {
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: clip !important;
    text-align: left !important;
}
[data-testid="stExpanderDetails"] pre,
[data-testid="stExpanderDetails"] code {
    white-space: pre-wrap !important;
    word-break: break-word;
}
</style>
"""

STEP_TEXT: dict[StepKind, tuple[str, str]] = {
    "understand": ("psychology", "Entendendo a pergunta e os dados"),
    "lookup": ("search", "Conferindo como o nome aparece nos dados"),
    "plan": ("edit_note", "Montando a consulta"),
    "query": ("database", "Consultando o banco de dados"),
    "blocked": ("shield", "Consulta barrada pela verificação de segurança, ajustando"),
    "unrequested_filter": (
        "filter_alt_off",
        "A consulta tem um filtro que a pergunta não pediu, ajustando",
    ),
    "sql_error": ("build", "A consulta deu erro, corrigindo"),
    "answer": ("article", "Lendo o resultado e escrevendo a resposta"),
    "verify": ("fact_check", "Conferindo os números do texto"),
}
FINAL_LABEL = {
    "answered": "Concluído em {seconds}",
    "no_results": "Concluído em {seconds}",
    "clarification": "Falta um detalhe na pergunta",
    "refused": "Pedido recusado",
    "failed": "Não foi possível concluir",
}


def main() -> None:
    st.set_page_config(page_title="Rastro", page_icon=":material/travel_explore:")
    if "answers" not in st.session_state:
        st.session_state.answers = []
    answers: list[Answer] = st.session_state.answers

    st.title("Rastro")
    st.caption(
        "Pergunte em português para onde foi o dinheiro das emendas parlamentares "
        "destinadas a Santa Catarina."
    )

    question = st.chat_input("Pergunte sobre as emendas para Santa Catarina")
    question = question or st.session_state.pop("pending", None)
    question = question.strip() if question else None

    if not answers and not question:
        render_examples()
    for answer in answers:
        with st.chat_message("user", avatar=USER_AVATAR):
            st.markdown(answer.question)
        with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
            render_answer(answer)
    if question:
        ask(question)
    render_sidebar(bool(answers))
    st.html(STYLE)


def choose(question: str) -> None:
    st.session_state.pending = question


def reset() -> None:
    st.session_state.answers = []


def render_examples() -> None:
    st.markdown("#### Comece por uma destas perguntas")
    with st.container(key="examples"):
        for start in range(0, len(EXAMPLES), 2):
            for column, example in zip(st.columns(2), EXAMPLES[start : start + 2], strict=False):
                column.button(
                    example,
                    key=f"example{EXAMPLES.index(example)}",
                    on_click=choose,
                    args=(example,),
                    width="stretch",
                )


def render_sidebar(has_conversation: bool) -> None:
    with st.sidebar:
        if has_conversation:
            st.button("Nova conversa", icon=":material/add:", on_click=reset, width="stretch")
        st.markdown("### Como funciona")
        st.markdown(
            "Sua pergunta vira uma consulta SQL somente leitura sobre dados públicos de emendas "
            "parlamentares federais com destino a Santa Catarina e das transferências especiais "
            "do Transferegov. A resposta mostra a tabela com o resultado, a fonte e o SQL "
            "executado."
        )
        st.markdown("### Aviso")
        st.markdown(
            "Projeto independente, sem vínculo com o TCE/SC, a ALESC, a CGU ou qualquer outro "
            "órgão público. Os números vêm do Portal da Transparência e do Transferegov e não "
            "implicam juízo sobre pessoas, empresas ou parlamentares."
        )


class LiveTrace:
    """Shows what the agent is doing while it works, one line per step."""

    def __init__(self) -> None:
        self._steps: list[Step] = []
        self._status: Any = None
        self._log: Any = None

    def show(self, step: Step) -> None:
        self._steps.append(step)
        if self._status is None:
            self._status = st.status(step_label(step), expanded=True)
            self._log = self._status.empty()
        self._status.update(label=step_label(step) + "…", expanded=True)
        self._log.markdown(trace_markdown(self._steps, running=True))

    def finish(self, answer: Answer) -> None:
        if self._status is None:
            return
        self._status.update(
            label=final_label(answer),
            state="error" if answer.error else "complete",
            expanded=False,
        )
        self._log.markdown(trace_markdown(self._steps, running=False))


def step_label(step: Step) -> str:
    return STEP_TEXT[step.kind][1]


def final_label(answer: Answer) -> str:
    return FINAL_LABEL[answer.status].format(seconds=seconds_text(answer.latency_s))


def seconds_text(seconds: float) -> str:
    return f"{seconds:.1f} s".replace(".", ",")


def trace_markdown(steps: list[Step], *, running: bool) -> str:
    lines = []
    for index, step in enumerate(steps):
        icon, label = STEP_TEXT[step.kind]
        current = running and index == len(steps) - 1
        color = "green" if current else "gray"
        text = f"**{label}**" if current else label
        if step.kind == "lookup" and step.detail:
            text += f": *{step.detail}*"
        if step.kind == "answer" and step.rows is not None:
            text += f" ({step.rows} {'linha' if step.rows == 1 else 'linhas'})"
        if step.seconds >= 0.1:
            text += f" `{seconds_text(step.seconds)}`"
        lines.append(f":{color}[:material/{icon}:] {text}")
        if step.kind == "query" and step.detail:
            lines.append(f"```sql\n{step.detail}\n```")
    return "\n\n".join(lines)


def ask(question: str) -> None:
    with st.chat_message("user", avatar=USER_AVATAR):
        st.markdown(question)
    with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
        live = LiveTrace()
        try:
            if "agent" not in st.session_state:
                st.session_state.agent = build_agent()
            history = [a for a in st.session_state.answers if a.status == "answered"]
            answer = st.session_state.agent.ask(
                question, history[-CONTEXT_TURNS:], on_step=live.show
            )
        except psycopg.OperationalError as error:
            st.error(f"Não consegui conectar ao banco. Rode `make up`. ({error})")
            return
        live.finish(answer)
        render_body(answer)
    st.session_state.answers.append(answer)


def render_answer(answer: Answer) -> None:
    if answer.trace:
        with st.status(
            final_label(answer), state="error" if answer.error else "complete", expanded=False
        ):
            st.markdown(trace_markdown(list(answer.trace), running=False))
    render_body(answer)


def render_body(answer: Answer) -> None:
    if answer.error:
        st.error(f"{answer.text} ({answer.error})")
        return
    st.markdown(answer.text)
    if answer.unverified_numbers:
        st.warning(
            "Estes valores do texto não aparecem no resultado da consulta, confira na tabela: "
            + ", ".join(answer.unverified_numbers)
        )
    if answer.unrequested_filters:
        st.warning(
            "A consulta aplicou filtros que a pergunta não pediu, então os valores podem estar "
            "incompletos: "
            + ", ".join(f"`{condition}`" for condition in answer.unrequested_filters)
        )
    if answer.assumptions:
        st.info(
            "**Como interpretei a pergunta**\n\n" + "\n".join(f"- {a}" for a in answer.assumptions),
            icon=":material/lightbulb:",
        )
    if not answer.sql:
        return

    frame, config = table(answer)
    st.dataframe(frame, hide_index=True, column_config=config)
    for line in caption_lines(answer):
        st.caption(line)
    with st.expander("SQL executado"):
        st.code(answer.sql, language="sql")


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


def caption_lines(answer: Answer) -> list[str]:
    lines = [
        f"Fonte: {source.fonte}, {source.arquivo} ({source.ano_inicio} a {source.ano_fim}), "
        f"carregado em {source.carregado_em:%d/%m/%Y}"
        for source in answer.sources
    ]
    if answer.truncated:
        lines.append("Resultado limitado às primeiras 200 linhas.")
    lines.append(
        f"Tabelas consultadas: {', '.join(answer.tables)}. "
        f"Modelo: {answer.model}, {seconds_text(answer.latency_s)}."
    )
    return lines


main()
