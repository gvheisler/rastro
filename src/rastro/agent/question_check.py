import logging
import re
import unicodedata

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

logging.getLogger("sqlglot").setLevel(logging.ERROR)

COMPARISONS = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.In, exp.Between)
COMPARISONS += (exp.Like, exp.ILike, exp.Is)
YEAR_COLUMNS = frozenset({"ano", "ano_emenda", "ano_pagamento", "ano_emissao"})
MUNICIPALITY_COLUMNS = frozenset({"municipio", "codigo_municipio_ibge"})
FIRST_YEAR, LAST_YEAR = 1990, 2100
RELATIVE_YEAR = re.compile(
    r"este ano|neste ano|ano atual|ano corrente|ano passado|ultimo ano|ultimos|recente|"
    r"atualmente|hoje|atual"
)
MENTIONS = {
    "localidade_tipo": re.compile(r"municip|cidade|prefeitura|estad|multipl|localidade"),
    "tipo_emenda": re.compile(r"individua|bancada|comiss|relator|especia|pix|finalidade|tipo"),
    "impedido": re.compile(r"impedi|bloquead"),
}


def unrequested_filters(query: str, asked: str) -> list[str]:
    """Conditions on year, location type, amendment type or the impeded flag that the
    question never mentions. `asked` is the current question plus the earlier ones."""
    try:
        root = sqlglot.parse_one(query, read="postgres")
    except SqlglotError:
        return []
    if root is None:
        return []

    text = _plain(asked)
    columns = {column.name.lower() for column in root.find_all(exp.Column)}
    names_a_place = bool(columns & MUNICIPALITY_COLUMNS)
    found: list[str] = []
    for node in _conditions(root):
        column = _filtered_column(node)
        if column is None or _is_asked(column, node, text, names_a_place):
            continue
        sql = node.sql(dialect="postgres")
        if sql not in found:
            found.append(sql)
    return found


def _conditions(root: exp.Expression) -> list[exp.Expression]:
    conditions = list(root.find_all(*COMPARISONS))
    for where in root.find_all(exp.Where):
        conditions += [c for c in _conjuncts(where.this) if _is_bare_flag(c)]
    return conditions


def _conjuncts(node: exp.Expression) -> list[exp.Expression]:
    if isinstance(node, exp.And):
        return _conjuncts(node.this) + _conjuncts(node.expression)
    if isinstance(node, exp.Paren):
        return _conjuncts(node.this)
    return [node]


def _is_bare_flag(node: exp.Expression) -> bool:
    flag = node.this if isinstance(node, exp.Not) else node
    return isinstance(flag, exp.Column) and flag.name.lower() == "impedido"


def _filtered_column(node: exp.Expression) -> str | None:
    if _is_bare_flag(node):
        return "impedido"
    for operand in (node.this, node.args.get("expression")):
        if isinstance(operand, exp.Extract) and operand.this.name.lower() == "year":
            return "year"
        if isinstance(operand, exp.Column):
            name = operand.name.lower()
            if name in YEAR_COLUMNS:
                return "year"
            if name in MENTIONS:
                return name
    return None


def _is_asked(column: str, node: exp.Expression, text: str, names_a_place: bool) -> bool:
    if column == "year":
        years = _literal_years(node)
        return (
            not years
            or RELATIVE_YEAR.search(text) is not None
            or all(str(year) in text for year in years)
        )
    if column == "localidade_tipo" and names_a_place:
        return True
    return MENTIONS[column].search(text) is not None


def _literal_years(node: exp.Expression) -> set[int]:
    return {
        int(literal.name)
        for literal in node.find_all(exp.Literal)
        if literal.is_int and FIRST_YEAR <= int(literal.name) <= LAST_YEAR
    }


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))
