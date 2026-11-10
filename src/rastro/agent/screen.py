import re
import unicodedata

MODIFY = (
    "Não altero nem apago dados: só consulto, em modo leitura, as emendas parlamentares federais "
    "com destino a Santa Catarina."
)
PERSONAL = (
    "Não informo CPF nem outros dados pessoais. Posso mostrar valores recebidos por favorecidos "
    "pessoa jurídica e outros números das emendas federais destinadas a Santa Catarina."
)
ACCUSATION = (
    "Não faço julgamentos nem acusações sobre pessoas, empresas ou parlamentares. Posso apresentar "
    "números das emendas federais destinadas a Santa Catarina, como valores empenhados, "
    "liquidados e pagos."
)

_IMPERATIVES = (
    "apague|apagar|exclua|excluir|remova|remover|delete|deletar|drop|truncate|zere|zerar|"
    "altere|alterar|edite|editar|modifique|modificar|insira|inserir|atualize|atualizar"
)
RULES = [
    (re.compile(rf"^(por favor,? |pode |poderia )?({_IMPERATIVES})\b"), MODIFY),
    (re.compile(r"\b(update|delete|insert|drop|truncate)\b"), MODIFY),
    (re.compile(r"\bcpfs?\b"), PERSONAL),
    (
        re.compile(
            r"\b(corrupt[oa]s?|ladra?o|ladroes|criminos[oa]s?|suspeit[oa]s?|fraud\w*|"
            r"desvi(ar|aram|ou|o|os)|propina)\b"
        ),
        ACCUSATION,
    ),
]


def screen(question: str) -> str | None:
    """Refusal text for requests that must never reach the model, or None."""
    text = unicodedata.normalize("NFKD", question).encode("ascii", "ignore").decode().lower()
    text = text.strip()
    for pattern, refusal in RULES:
        if pattern.search(text):
            return refusal
    return None
