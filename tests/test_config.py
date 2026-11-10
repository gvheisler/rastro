import pytest
from pydantic import ValidationError

from rastro.config import Settings


def test_dsn_uses_environment(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "segredo")
    monkeypatch.setenv("READONLY_PASSWORD", "leitura")
    monkeypatch.setenv("POSTGRES_PORT", "5544")
    settings = Settings(_env_file=None)
    assert settings.dsn == ("host=localhost port=5544 dbname=rastro user=rastro password=segredo")


def test_readonly_dsn_uses_the_readonly_credentials(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "segredo")
    monkeypatch.setenv("READONLY_PASSWORD", "leitura")
    settings = Settings(_env_file=None)
    assert settings.readonly_dsn == (
        "host=localhost port=5433 dbname=rastro user=rastro_ro password=leitura"
    )


@pytest.mark.parametrize("missing", ["POSTGRES_PASSWORD", "READONLY_PASSWORD"])
def test_passwords_are_required(monkeypatch, missing):
    monkeypatch.setenv("POSTGRES_PASSWORD", "segredo")
    monkeypatch.setenv("READONLY_PASSWORD", "leitura")
    monkeypatch.delenv(missing)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
