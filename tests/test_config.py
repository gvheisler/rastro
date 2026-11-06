import pytest
from pydantic import ValidationError

from rastro.config import Settings


def test_dsn_uses_environment(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "segredo")
    monkeypatch.setenv("POSTGRES_PORT", "5544")
    settings = Settings(_env_file=None)
    assert settings.dsn == ("host=localhost port=5544 dbname=rastro user=rastro password=segredo")


def test_password_is_required(monkeypatch):
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
