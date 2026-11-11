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


def test_llm_defaults_point_to_local_ollama(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "segredo")
    monkeypatch.setenv("READONLY_PASSWORD", "leitura")
    settings = Settings(_env_file=None)
    assert settings.llm_base_url == "http://localhost:11434/v1"
    assert settings.llm_model == "rastro-sql"
    assert settings.llm_api_key is None
    assert settings.llm_extra_body == {"reasoning_effort": "none"}


def test_llm_can_point_to_another_server(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "segredo")
    monkeypatch.setenv("READONLY_PASSWORD", "leitura")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("LLM_EXTRA_BODY", '{"chat_template_kwargs": {"enable_thinking": false}}')
    settings = Settings(_env_file=None)
    assert settings.llm_base_url == "http://localhost:8000/v1"
    assert settings.llm_extra_body == {"chat_template_kwargs": {"enable_thinking": False}}


def test_transferegov_defaults_to_the_current_public_api(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "segredo")
    monkeypatch.setenv("READONLY_PASSWORD", "leitura")
    monkeypatch.delenv("TRANSFEREGOV_BASE_URL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.transferegov_base_url == (
        "https://api-publica.transferegov.gestao.gov.br/especiais"
    )


def test_transferegov_base_url_can_be_changed(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "segredo")
    monkeypatch.setenv("READONLY_PASSWORD", "leitura")
    monkeypatch.setenv("TRANSFEREGOV_BASE_URL", "http://localhost:9000/especiais")
    assert Settings(_env_file=None).transferegov_base_url == "http://localhost:9000/especiais"


def base(monkeypatch, **env) -> Settings:
    monkeypatch.setenv("POSTGRES_PASSWORD", "segredo")
    monkeypatch.setenv("READONLY_PASSWORD", "leitura")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return Settings(_env_file=None)


def test_provider_defaults_to_the_openai_compatible_client(monkeypatch):
    settings = base(monkeypatch)
    assert settings.llm_provider == "openai"
    assert settings.llm_temperature == 0


def test_anthropic_provider_gets_its_own_default_model(monkeypatch):
    settings = base(monkeypatch, LLM_PROVIDER="anthropic")
    assert settings.llm_model == "claude-opus-5-5"
    assert settings.anthropic_base_url is None


def test_an_explicit_model_wins_over_the_provider_default(monkeypatch):
    settings = base(monkeypatch, LLM_PROVIDER="anthropic", LLM_MODEL="claude-haiku-5-5")
    assert settings.llm_model == "claude-haiku-5-5"


def test_anthropic_key_falls_back_to_the_sdk_variable(monkeypatch):
    assert base(monkeypatch, ANTHROPIC_API_KEY="sk-a").anthropic_key == "sk-a"
    assert base(monkeypatch, ANTHROPIC_API_KEY="sk-a", LLM_API_KEY="sk-b").anthropic_key == "sk-b"


def test_unknown_provider_is_rejected(monkeypatch):
    with pytest.raises(ValidationError):
        base(monkeypatch, LLM_PROVIDER="outro")


def test_blank_optional_values_count_as_unset(monkeypatch):
    settings = base(monkeypatch, LLM_TEMPERATURE="", LLM_EFFORT="", LLM_API_KEY="")
    assert settings.llm_temperature is None
    assert settings.llm_effort is None
    assert settings.llm_api_key is None
