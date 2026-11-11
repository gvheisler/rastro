import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from psycopg import Connection

from rastro.agent.llm import Completion, LLMClient, LLMError, Message, ToolCall, build_llm
from rastro.agent.prompt import system_prompt
from rastro.agent.question_check import (
    unrequested_filters,
    unrequested_values,
    value_assumption,
    year_assumption,
)
from rastro.agent.screen import screen
from rastro.agent.sql_guard import GuardError
from rastro.agent.tools import (
    TOOL_SPECS,
    QueryError,
    QueryResult,
    find_values,
    format_result,
    run_query,
)
from rastro.config import LOG_DIR, get_settings
from rastro.db import connect_readonly

NO_RESULTS_TEXT = "Não encontrei registros nos dados para essa consulta."
FAILED_TEXT = "Não consegui obter esses números nos dados. Tente reformular a pergunta."
LLM_DOWN_TEXT = "Não consegui falar com o modelo de linguagem."
EMPTY_TEXT = "Segue o resultado da consulta."
NUDGE = (
    "Você ainda não consultou o banco. Use run_sql para obter os números; se os dados não "
    "puderem responder, use refuse ou ask_clarification."
)
CLARIFICATION_PUSHBACK = (
    "Do not ask the user yet. Doubt about which value, year or table is not a reason to ask: "
    "pick the default from the rules and run the query with run_sql. Call ask_clarification "
    "again only if the request has nothing to measure or list."
)

Status = Literal["answered", "no_results", "clarification", "refused", "failed"]
StepKind = Literal[
    "understand",
    "lookup",
    "plan",
    "query",
    "blocked",
    "unrequested_filter",
    "sql_error",
    "answer",
    "verify",
]
Phase = Literal["start", "lookup", "result", "blocked", "sql_error"]


@dataclass
class Step:
    """One thing the agent did while answering; `seconds` is set when the next step begins."""

    kind: StepKind
    detail: str | None = None
    rows: int | None = None
    seconds: float = 0.0


@dataclass(frozen=True)
class Source:
    tabela: str
    fonte: str
    arquivo: str
    ano_inicio: int
    ano_fim: int
    carregado_em: datetime


@dataclass
class Answer:
    question: str
    status: Status
    text: str
    sql: str | None = None
    tables: tuple[str, ...] = ()
    columns: tuple[str, ...] = ()
    rows: tuple[tuple[Any, ...], ...] = ()
    truncated: bool = False
    sources: tuple[Source, ...] = ()
    unverified_numbers: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    model: str = ""
    steps: int = 0
    guard_blocks: int = 0
    filter_blocks: int = 0
    unrequested_filters: tuple[str, ...] = ()
    sql_errors: int = 0
    latency_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    trace: tuple[Step, ...] = ()

    @property
    def period(self) -> tuple[int, int] | None:
        if not self.sources:
            return None
        return min(s.ano_inicio for s in self.sources), max(s.ano_fim for s in self.sources)


@dataclass
class _Turn:
    result: QueryResult | None = None
    guard_blocks: int = 0
    filter_blocks: int = 0
    flagged: set[str] = field(default_factory=set)
    values_flagged: bool = False
    asked: str = ""
    sql_errors: int = 0
    pushed_back: bool = False
    steps: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    terminal: tuple[Status, str] | None = None
    nudged: bool = False
    on_step: Callable[[Step], None] | None = None
    trace: list[Step] = field(default_factory=list)
    phase: Phase = "start"
    step_started: float = 0.0

    def begin(self, kind: StepKind, detail: str | None = None, rows: int | None = None) -> None:
        self.end()
        step = Step(kind, detail, rows)
        self.trace.append(step)
        if self.on_step:
            self.on_step(step)

    def end(self) -> None:
        now = time.perf_counter()
        if self.trace:
            self.trace[-1].seconds = round(now - self.step_started, 2)
        self.step_started = now


class Agent:
    """Tool-calling loop: the model writes SQL, the guard and the read-only role contain it."""

    def __init__(
        self,
        llm: LLMClient,
        conn: Connection,
        *,
        max_steps: int = 6,
        log_path: Path | None = None,
        today: date | None = None,
    ) -> None:
        self._llm = llm
        self._conn = conn
        self._max_steps = max_steps
        self._log_path = log_path
        self._system_prompt = system_prompt(conn, today)

    def ask(
        self,
        question: str,
        history: Sequence[Answer] = (),
        on_step: Callable[[Step], None] | None = None,
    ) -> Answer:
        started = time.perf_counter()
        turn = _Turn(on_step=on_step)
        try:
            refusal = screen(question)
            answer = (
                Answer(question, "refused", refusal)
                if refusal
                else self._run(question, history, turn)
            )
        except LLMError as error:
            answer = Answer(question, "failed", LLM_DOWN_TEXT, error=str(error))
        turn.end()
        answer.trace = tuple(turn.trace)
        answer.model = self._llm.model
        answer.steps = turn.steps
        answer.guard_blocks = turn.guard_blocks
        answer.filter_blocks = turn.filter_blocks
        answer.sql_errors = turn.sql_errors
        answer.input_tokens = turn.input_tokens
        answer.output_tokens = turn.output_tokens
        answer.latency_s = round(time.perf_counter() - started, 2)
        self._log(answer)
        return answer

    def _run(self, question: str, history: Sequence[Answer], turn: _Turn) -> Answer:
        messages: list[Message] = [{"role": "system", "content": self._system_prompt}]
        for previous in history:
            messages += _history_messages(previous)
        messages.append({"role": "user", "content": question})
        turn.asked = " ".join([previous.question for previous in history] + [question])

        while turn.steps < self._max_steps:
            turn.steps += 1
            self._announce(turn)
            completion = self._llm.complete(messages, TOOL_SPECS)
            turn.input_tokens += completion.input_tokens
            turn.output_tokens += completion.output_tokens
            messages.append(_assistant_message(completion))

            if not completion.tool_calls:
                if turn.result is None and not turn.nudged:
                    turn.nudged = True
                    messages.append({"role": "user", "content": NUDGE})
                    continue
                return self._finish(question, turn, completion.text)

            for tool_call in completion.tool_calls:
                content = self._dispatch(tool_call, turn)
                if turn.terminal:
                    status, text = turn.terminal
                    return Answer(question, status, text)
                messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": content})
        return Answer(question, "failed", FAILED_TEXT)

    def _announce(self, turn: _Turn) -> None:
        match turn.phase:
            case "start":
                kind, rows = "understand", None
            case "lookup":
                kind, rows = "plan", None
            case "result" if turn.result is not None:
                kind, rows = "answer", len(turn.result.rows)
            case _:
                return
        if not turn.trace or turn.trace[-1].kind != kind:
            turn.begin(kind, rows=rows)

    def _dispatch(self, call: ToolCall, turn: _Turn) -> str:
        if call.error:
            return f"Invalid arguments for {call.name}: {call.error} Send a JSON object."
        args = call.arguments
        match call.name:
            case "run_sql":
                if not isinstance(args.get("sql"), str):
                    return "Missing argument 'sql' (string)."
                return self._run_sql(args["sql"], turn)
            case "find_values":
                if not isinstance(args.get("kind"), str) or not isinstance(args.get("text"), str):
                    return "Missing arguments 'kind' and 'text' (strings)."
                turn.begin("lookup", args["text"])
                turn.phase = "lookup"
                try:
                    found = find_values(self._conn, args["kind"], args["text"])
                except QueryError as error:
                    return str(error)
                if not found:
                    return "No matching values."
                return "\n".join(f"{value} | {count} rows" for value, count in found)
            case "ask_clarification":
                if not turn.pushed_back:
                    turn.pushed_back = True
                    return CLARIFICATION_PUSHBACK
                turn.terminal = ("clarification", str(args.get("question", "")).strip())
                return ""
            case "refuse":
                turn.terminal = ("refused", str(args.get("reason", "")).strip())
                return ""
            case _:
                return f"Unknown tool '{call.name}'."

    def _run_sql(self, query: str, turn: _Turn) -> str:
        turn.begin("query", query)
        unasked = [f for f in unrequested_filters(query, turn.asked) if f not in turn.flagged]
        values = [] if turn.values_flagged else unrequested_values(query, turn.asked)
        if unasked or values:
            turn.flagged.update(unasked)
            turn.values_flagged = turn.values_flagged or bool(values)
            turn.filter_blocks += 1
            turn.begin("unrequested_filter")
            turn.phase = "blocked"
            return _unrequested_message(unasked, values)
        try:
            turn.result = run_query(self._conn, query)
        except GuardError as error:
            turn.guard_blocks += 1
            turn.begin("blocked")
            turn.phase = "blocked"
            return f"Query blocked: {error}"
        except QueryError as error:
            turn.sql_errors += 1
            turn.begin("sql_error")
            turn.phase = "sql_error"
            return f"Query error: {error}"
        turn.phase = "result"
        return format_result(turn.result)

    def _finish(self, question: str, turn: _Turn, text: str) -> Answer:
        result = turn.result
        if result is None:
            return Answer(question, "failed", FAILED_TEXT)
        base = {
            "sql": result.sql,
            "tables": result.tables,
            "columns": result.columns,
            "rows": result.rows,
            "truncated": result.truncated,
            "sources": self._sources(result.tables),
            "assumptions": _assumptions(result.sql, turn.asked),
        }
        if _is_empty(result):
            return Answer(question, "no_results", NO_RESULTS_TEXT, **base)
        turn.begin("verify")
        text = text.strip() or EMPTY_TEXT
        return Answer(
            question,
            "answered",
            text,
            unverified_numbers=unverified_numbers(text, result.rows),
            unrequested_filters=tuple(unrequested_filters(result.sql, turn.asked)),
            **base,
        )

    def _sources(self, tables: Sequence[str]) -> tuple[Source, ...]:
        rows = self._conn.execute(
            "select tabela, fonte, arquivo, ano_inicio, ano_fim, carregado_em "
            "from mart.fontes where tabela = any(%s) order by tabela",
            (list(tables),),
        ).fetchall()
        self._conn.rollback()
        return tuple(Source(*row) for row in rows)

    def _log(self, answer: Answer) -> None:
        if self._log_path is None:
            return
        record = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "question": answer.question,
            "status": answer.status,
            "sql": answer.sql,
            "rows": len(answer.rows),
            "model": answer.model,
            "latency_s": answer.latency_s,
            "steps": answer.steps,
            "guard_blocks": answer.guard_blocks,
            "filter_blocks": answer.filter_blocks,
            "unrequested_filters": list(answer.unrequested_filters),
            "assumptions": list(answer.assumptions),
            "sql_errors": answer.sql_errors,
            "input_tokens": answer.input_tokens,
            "output_tokens": answer.output_tokens,
            "error": answer.error,
        }
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


NUMBER = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?")
CENTS = Decimal("0.01")


def unverified_numbers(text: str, rows: Sequence[Sequence[Any]]) -> tuple[str, ...]:
    """Numbers written in the answer that do not appear in the query result.

    Small integers and years are ignored; derived values, such as a difference
    the model computed itself, are reported too.
    """
    known = {
        Decimal(value).quantize(CENTS)
        for row in rows
        for value in row
        if isinstance(value, int | Decimal) and not isinstance(value, bool)
    }
    missing = []
    for token in NUMBER.findall(text):
        value = Decimal(token.replace(".", "").replace(",", "."))
        plain = token.isdigit() and (value <= 31 or 1900 <= value <= 2100)
        if not plain and value.quantize(CENTS) not in known:
            missing.append(token)
    return tuple(missing)


def _unrequested_message(filters: Sequence[str], values: Sequence[str]) -> str:
    parts = []
    if filters:
        parts.append(
            "the question does not ask for these conditions: "
            + "; ".join(filters)
            + ". Remove them."
        )
    if values:
        parts.append(
            "the question does not name a value, yet the query uses several: "
            + ", ".join(values)
            + ". Use only the single value the rules give for this question (valor_pago for "
            "emendas, valor_empenhado for transferencias_especiais), with no arithmetic "
            "between values."
        )
    return "Query not run: " + " ".join(parts) + " Run the query again."


def _assumptions(query: str, asked: str) -> tuple[str, ...]:
    """What the answer tells the user about how the question was read, from the query itself."""
    notes = (value_assumption(query, asked), year_assumption(query))
    return tuple(note for note in notes if note)


def _is_empty(result: QueryResult) -> bool:
    return not result.rows or all(value is None for row in result.rows for value in row)


def _assistant_message(completion: Completion) -> Message:
    message: Message = {"role": "assistant", "content": completion.text}
    if completion.tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
            }
            for call in completion.tool_calls
        ]
    return message


def _history_messages(previous: Answer) -> list[Message]:
    reply = previous.text + (f"\n[SQL usado: {previous.sql}]" if previous.sql else "")
    return [
        {"role": "user", "content": previous.question},
        {"role": "assistant", "content": reply},
    ]


def build_agent() -> Agent:
    """An agent wired to the configured model and the read-only database role."""
    settings = get_settings()
    return Agent(build_llm(settings), connect_readonly(), log_path=LOG_DIR / "agent.jsonl")
