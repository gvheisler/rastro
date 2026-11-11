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
VALUE_LABELS = {
    "valor_pago": "o valor pago",
    "valor_empenhado": "o valor empenhado",
    "valor_liquidado": "o valor liquidado",
    "valor_planejado": "o valor planejado",
    "valor_restos_a_pagar_inscritos": "os restos a pagar inscritos",
    "valor_restos_a_pagar_cancelados": "os restos a pagar cancelados",
    "valor_restos_a_pagar_pagos": "os restos a pagar pagos",
}
VALUE_WORDS = re.compile(r"pag|empenh|liquid|planej|previst|resto")
EMENDA_YEAR_COLUMNS = frozenset({"ano", "ano_emenda"})
MENTIONS = {
    "localidade_tipo": re.compile(r"municip|cidade|prefeitura|estad|multipl|localidade"),
    "tipo_emenda": re.compile(r"individua|bancada|comiss|relator|especia|pix|finalidade|tipo"),
    "impedido": re.compile(r"impedi|bloquead"),
}


def unrequested_filters(query: str, asked: str) -> list[str]:
    """Conditions on year, location type, amendment type or the impeded flag that the
    question never mentions. `asked` is the current question plus the earlier ones."""
    root = _parse(query)
    if root is None:
        return []

    text = _plain(asked)
    names_a_place = bool(_column_names(root) & MUNICIPALITY_COLUMNS)
    found: list[str] = []
    for node in _conditions(root):
        column = _filtered_column(node)
        if column is None or _is_asked(column, node, text, names_a_place):
            continue
        sql = node.sql(dialect="postgres")
        if sql not in found:
            found.append(sql)
    return found


def unrequested_values(query: str, asked: str) -> list[str]:
    """Value columns the query uses together, when the question never named a value."""
    used = _unnamed_values(query, asked)
    return used if len(used) > 1 else []


def value_assumption(query: str, asked: str) -> str | None:
    """The sentence that says which value the query used, when the question never named one."""
    used = _unnamed_values(query, asked)
    if not used:
        return None
    labels = [VALUE_LABELS[name] for name in used]
    names = labels[0] if len(labels) == 1 else f"{', '.join(labels[:-1])} e {labels[-1]}"
    return f"Você não disse qual valor queria; usei {names}."


def year_assumption(query: str) -> str | None:
    """Says that a paid value filtered by year follows the year of the emenda, not the payment."""
    root = _parse(query)
    if root is None or "valor_pago" not in _column_names(root):
        return None
    for node in _conditions(root):
        operands = (node.this, node.args.get("expression"))
        if any(
            isinstance(operand, exp.Column) and operand.name.lower() in EMENDA_YEAR_COLUMNS
            for operand in operands
        ):
            return (
                "Considerei o ano da emenda no orçamento, não a data do pagamento "
                f"(`{node.sql(dialect='postgres')}`)."
            )
    return None


def _unnamed_values(query: str, asked: str) -> list[str]:
    root = None if _names_a_value(asked) else _parse(query)
    if root is None:
        return []
    columns = _column_names(root)
    return [name for name in VALUE_LABELS if name in columns]


def _parse(query: str) -> exp.Expression | None:
    try:
        return sqlglot.parse_one(query, read="postgres")
    except SqlglotError:
        return None


def _column_names(root: exp.Expression) -> set[str]:
    return {column.name.lower() for column in root.find_all(exp.Column)}


def _names_a_value(text: str) -> bool:
    return VALUE_WORDS.search(_plain(text)) is not None


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
