import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg import Connection, sql

from rastro.agent.sql_guard import MAX_ROWS, guard_sql

MODEL_ROWS = 30
CELL_CHARS = 160

LOOKUPS = {
    "municipio": ("emendas", "municipio"),
    "autor": ("emendas", "autor"),
    "funcao": ("emendas", "funcao"),
    "subfuncao": ("emendas", "subfuncao"),
    "programa": ("emendas", "programa"),
    "tipo_emenda": ("emendas", "tipo_emenda"),
    "convenente": ("convenios", "convenente"),
    "favorecido": ("pagamentos_favorecidos", "nome_favorecido"),
}

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "run_sql",
            "description": (
                "Executa uma consulta SELECT em PostgreSQL sobre as tabelas do esquema mart e "
                "devolve colunas e linhas. Uma única instrução, sem escrever dados."
            ),
            "parameters": {
                "type": "object",
                "properties": {"sql": {"type": "string", "description": "A consulta SELECT."}},
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_values",
            "description": (
                "Procura como um nome está escrito nos dados, sem diferenciar acentos nem "
                "maiúsculas, e devolve até 10 grafias com o número de linhas. Use antes de "
                "filtrar por município, autor, função ou favorecido."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(LOOKUPS)},
                    "text": {"type": "string", "description": "Trecho do nome."},
                },
                "required": ["kind", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_clarification",
            "description": (
                "Pede esclarecimento ao usuário quando a pergunta é ambígua de um jeito que muda "
                "o resultado. Encerra a conversa nesta rodada."
            ),
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "refuse",
            "description": (
                "Recusa com educação um pedido fora do escopo. Encerra a conversa nesta rodada."
            ),
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
]


class QueryError(Exception):
    """A database problem, worded so the model can fix its query."""


@dataclass(frozen=True)
class QueryResult:
    sql: str
    tables: tuple[str, ...]
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    truncated: bool
    elapsed_ms: int


def run_query(conn: Connection, query: str) -> QueryResult:
    """Validate with the guard, then run on the read-only connection."""
    guarded = guard_sql(query)
    started = time.perf_counter()
    try:
        cursor = conn.execute(guarded.sql)
        rows = tuple(cursor.fetchall())
        columns = tuple(column.name for column in cursor.description)
    except psycopg.errors.QueryCanceled as error:
        raise QueryError(
            "The query took too long and was cancelled. Aggregate or filter more."
        ) from error
    except psycopg.Error as error:
        raise QueryError(_describe(error)) from error
    finally:
        conn.rollback()
    return QueryResult(
        sql=guarded.sql,
        tables=guarded.tables,
        columns=columns,
        rows=rows,
        truncated=guarded.row_limit == MAX_ROWS and len(rows) >= MAX_ROWS,
        elapsed_ms=round((time.perf_counter() - started) * 1000),
    )


def find_values(conn: Connection, kind: str, text: str) -> list[tuple[str, int]]:
    if kind not in LOOKUPS:
        raise QueryError(f"Unknown kind '{kind}'. Use one of: {', '.join(LOOKUPS)}.")
    table, column = LOOKUPS[kind]
    pattern = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    query = sql.SQL(
        "select {col}, count(*) as n from mart.{table} "
        "where {col} is not null and unaccent({col}) ilike '%%' || unaccent(%s) || '%%' "
        "group by {col} order by n desc, {col} limit 10"
    ).format(col=sql.Identifier(column), table=sql.Identifier(table))
    try:
        return [(value, n) for value, n in conn.execute(query, (pattern,)).fetchall()]
    finally:
        conn.rollback()


def format_result(result: QueryResult, max_rows: int = MODEL_ROWS) -> str:
    """Compact text rendering of a result for the model."""
    if not result.rows:
        return "0 rows"
    lines = [" | ".join(result.columns)]
    lines += [" | ".join(_cell(value) for value in row) for row in result.rows[:max_rows]]
    if len(result.rows) > max_rows:
        lines.append(f"(showing {max_rows} of {len(result.rows)} rows)")
    if result.truncated:
        lines.append(f"(result cut at {MAX_ROWS} rows)")
    return "\n".join(lines)


def _cell(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date | datetime):
        return value.isoformat()
    text = str(value).replace("\n", " ")
    return text if len(text) <= CELL_CHARS else text[: CELL_CHARS - 1] + "…"


def _describe(error: psycopg.Error) -> str:
    diag = error.diag
    message = diag.message_primary or str(error)
    return f"{message}. {diag.message_hint}" if diag.message_hint else message
