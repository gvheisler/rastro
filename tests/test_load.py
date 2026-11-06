import pytest

from rastro.ingest.load import normalize_column


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Código da Emenda", "codigo_da_emenda"),
        ("Número da emenda", "numero_da_emenda"),
        ("Localidade de aplicação do recurso", "localidade_de_aplicacao_do_recurso"),
        ("Valor Restos A Pagar Inscritos", "valor_restos_a_pagar_inscritos"),
        ("Ano/Mês", "ano_mes"),
    ],
)
def test_normalize_column(header, expected):
    assert normalize_column(header) == expected
