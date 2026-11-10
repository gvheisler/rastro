import logging
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

logging.getLogger("sqlglot").setLevel(logging.ERROR)

SCHEMA = "mart"
ALLOWED_TABLES = (
    "convenios",
    "emendas",
    "fontes",
    "pagamentos_favorecidos",
    "transferencias_especiais",
    "transferencias_especiais_empenhos",
)
ALLOWED_FUNCTIONS = frozenset({"unaccent", "similarity", "age", "make_date"})
MAX_ROWS = 200

_FORBIDDEN = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Copy,
    exp.Command,
    exp.Into,
    exp.Lock,
)


class GuardError(ValueError):
    """The query is not allowed; the message is written to be read by the model."""


@dataclass(frozen=True)
class GuardedQuery:
    sql: str
    tables: tuple[str, ...]
    row_limit: int


def guard_sql(query: str) -> GuardedQuery:
    """Validate a model-written query and cap its row count."""
    if not query.strip():
        raise GuardError("The query is empty.")
    try:
        statements = [s for s in sqlglot.parse(query, read="postgres") if s is not None]
    except SqlglotError as error:
        raise GuardError(f"The query is not valid PostgreSQL: {error}") from error
    if len(statements) != 1:
        raise GuardError("Send exactly one SELECT statement.")

    root = statements[0]
    if not isinstance(root, exp.Select | exp.SetOperation) or root.find(*_FORBIDDEN):
        raise GuardError("Only read-only SELECT statements are allowed.")
    if isinstance(root.args.get("limit"), exp.Fetch):
        raise GuardError("Use LIMIT instead of FETCH.")

    tables = _check_tables(root)
    _check_functions(root)
    _check_precedence(root)
    root, row_limit = _apply_limit(root)
    return GuardedQuery(root.sql(dialect="postgres"), tables, row_limit)


def _check_tables(root: exp.Expression) -> tuple[str, ...]:
    ctes = {cte.alias.lower() for cte in root.find_all(exp.CTE)}
    allowed = ", ".join(ALLOWED_TABLES)
    found: set[str] = set()
    for table in root.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise GuardError("Table functions are not allowed.")
        name, schema = table.name.lower(), table.db.lower()
        if not schema and name in ctes:
            continue
        if table.catalog or schema not in ("", SCHEMA):
            raise GuardError(f"Schema '{schema}' is not allowed. Use only: {allowed}.")
        if name not in ALLOWED_TABLES:
            raise GuardError(f"Table '{name}' is not allowed. Allowed tables: {allowed}.")
        found.add(name)
    if not found:
        raise GuardError(f"The query must read from at least one table. Allowed tables: {allowed}.")
    return tuple(sorted(found))


def _check_functions(root: exp.Expression) -> None:
    for function in root.find_all(exp.Anonymous):
        if function.name.lower() not in ALLOWED_FUNCTIONS:
            raise GuardError(f"Function '{function.name}' is not allowed.")


def _check_precedence(root: exp.Expression) -> None:
    for node in root.find_all(exp.Or):
        if isinstance(node.this, exp.And) or isinstance(node.expression, exp.And):
            raise GuardError(
                "Mixing AND with OR without parentheses is ambiguous. "
                "Add parentheses around each group of conditions."
            )


def _requested_limit(node: exp.Expression) -> int | None:
    limit = node.args.get("limit")
    value = limit.expression if limit is not None else None
    if isinstance(value, exp.Literal) and value.is_int:
        return int(value.name)
    return None


def _apply_limit(root: exp.Expression) -> tuple[exp.Expression, int]:
    requested = _requested_limit(root)
    if requested is not None and requested <= MAX_ROWS:
        return root, requested
    if isinstance(root, exp.Select):
        return root.limit(MAX_ROWS), MAX_ROWS
    wrapped = exp.select("*").from_(root.subquery("q")).limit(MAX_ROWS)
    return wrapped, MAX_ROWS
