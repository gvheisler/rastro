import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from psycopg import Connection

from rastro.agent.llm import Completion, LLMClient, LLMError, Message, ToolCall
from rastro.agent.prompt import system_prompt
from rastro.agent.sql_guard import GuardError
from rastro.agent.tools import (
    TOOL_SPECS,
    QueryError,
    QueryResult,
    find_values,
    format_result,
    run_query,
)

NO_RESULTS_TEXT = "Não encontrei registros nos dados para essa consulta."
FAILED_TEXT = "Não consegui obter esses números nos dados. Tente reformular a pergunta."
LLM_DOWN_TEXT = "Não consegui falar com o modelo de linguagem."
EMPTY_TEXT = "Segue o resultado da consulta."
NUDGE = (
    "Você ainda não consultou o banco. Use run_sql para obter os números; se os dados não "
    "puderem responder, use refuse ou ask_clarification."
)

Status = Literal["answered", "no_results", "clarification", "refused", "failed"]


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
    model: str = ""
    steps: int = 0
    guard_blocks: int = 0
    sql_errors: int = 0
    latency_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None

    @property
    def period(self) -> tuple[int, int] | None:
        if not self.sources:
            return None
        return min(s.ano_inicio for s in self.sources), max(s.ano_fim for s in self.sources)


@dataclass
class _Turn:
    result: QueryResult | None = None
    guard_blocks: int = 0
    sql_errors: int = 0
    steps: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    terminal: tuple[Status, str] | None = None
    nudged: bool = False


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

    def ask(self, question: str, history: Sequence[Answer] = ()) -> Answer:
        started = time.perf_counter()
        turn = _Turn()
        try:
            answer = self._run(question, history, turn)
        except LLMError as error:
            answer = Answer(question, "failed", LLM_DOWN_TEXT, error=str(error))
        answer.model = self._llm.model
        answer.steps = turn.steps
        answer.guard_blocks = turn.guard_blocks
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

        while turn.steps < self._max_steps:
            turn.steps += 1
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
                try:
                    found = find_values(self._conn, args["kind"], args["text"])
                except QueryError as error:
                    return str(error)
                if not found:
                    return "No matching values."
                return "\n".join(f"{value} | {count} rows" for value, count in found)
            case "ask_clarification":
                turn.terminal = ("clarification", str(args.get("question", "")).strip())
                return ""
            case "refuse":
                turn.terminal = ("refused", str(args.get("reason", "")).strip())
                return ""
            case _:
                return f"Unknown tool '{call.name}'."

    def _run_sql(self, query: str, turn: _Turn) -> str:
        try:
            turn.result = run_query(self._conn, query)
        except GuardError as error:
            turn.guard_blocks += 1
            return f"Query blocked: {error}"
        except QueryError as error:
            turn.sql_errors += 1
            return f"Query error: {error}"
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
        }
        if _is_empty(result):
            return Answer(question, "no_results", NO_RESULTS_TEXT, **base)
        return Answer(question, "answered", text.strip() or EMPTY_TEXT, **base)

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
            "sql_errors": answer.sql_errors,
            "input_tokens": answer.input_tokens,
            "output_tokens": answer.output_tokens,
            "error": answer.error,
        }
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


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
