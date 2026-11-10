import pytest

from rastro.ingest.transferegov import TransferegovClient, TransferegovError, fetch_santa_catarina
from support import API_BASE, fake_transferegov


def api(**overrides):
    data = {
        "beneficiarios-especiais": [
            {"id_beneficiario": 1, "uf_beneficiario": "SC"},
            {"id_beneficiario": 2, "uf_beneficiario": "SC"},
            {"id_beneficiario": 3, "uf_beneficiario": "PR"},
        ],
        "planos-acao-especiais": [
            {"id_plano_acao": 12, "id_beneficiario": 2},
            {"id_plano_acao": 11, "id_beneficiario": 1},
            {"id_plano_acao": 13, "id_beneficiario": 3},
        ],
        "executores-especiais": [
            {"id_executor": 1, "id_plano_acao": 11},
            {"id_executor": 2, "id_plano_acao": 13},
        ],
        "planos-trabalho-especiais": [{"id_plano_trabalho": 1, "id_plano_acao": 12}],
        "empenhos-especiais": [
            {"id_empenho": 2, "id_plano_acao": 12},
            {"id_empenho": 1, "id_plano_acao": 11},
            {"id_empenho": 3, "id_plano_acao": 13},
        ],
    }
    data.update(overrides)
    return data


def client(data, **options):
    return TransferegovClient(API_BASE, transport=fake_transferegov(data, **options))


def ids(rows, key):
    return [r[key] for r in rows]


def test_keeps_only_santa_catarina_beneficiaries_and_what_hangs_from_them():
    result = fetch_santa_catarina(client(api()))
    assert ids(result["transferegov_beneficiarios"], "id_beneficiario") == [1, 2]
    assert ids(result["transferegov_planos_acao"], "id_plano_acao") == [11, 12]
    assert ids(result["transferegov_executores"], "id_executor") == [1]
    assert ids(result["transferegov_planos_trabalho"], "id_plano_trabalho") == [1]
    assert ids(result["transferegov_empenhos"], "id_empenho") == [1, 2]


def test_filters_santa_catarina_locally_when_the_api_ignores_the_uf_filter():
    result = fetch_santa_catarina(client(api(), honor_filters=False))
    assert ids(result["transferegov_beneficiarios"], "id_beneficiario") == [1, 2]


def test_a_missing_endpoint_is_an_error():
    data = api()
    del data["empenhos-especiais"]
    with pytest.raises(TransferegovError, match="empenhos-especiais.*404"):
        fetch_santa_catarina(client(data))
