import pytest
from typer.testing import CliRunner

from rastro.cli import app
from rastro.ingest.transferegov import TransferegovError
from support import FIXTURES, read_csv

runner = CliRunner()


@pytest.fixture(autouse=True)
def fake_transferegov(monkeypatch, transferegov_client):
    monkeypatch.setattr("rastro.cli.build_transferegov_client", lambda: transferegov_client)


def test_ingest_loads_raw_and_builds_staging(db, monkeypatch):
    monkeypatch.setenv("POSTGRES_DB", db.info.dbname)
    result = runner.invoke(app, ["ingest", "--raw-dir", str(FIXTURES)])
    assert result.exit_code == 0, result.output
    rows = len(read_csv("EmendasParlamentares.csv")[1])
    assert f"EmendasParlamentares.csv: {rows:,} rows" in result.output
    assert db.execute("select count(*) from staging.emendas").fetchone()[0] == rows


def test_ingest_loads_santa_catarina_from_transferegov(db, monkeypatch):
    monkeypatch.setenv("POSTGRES_DB", db.info.dbname)
    result = runner.invoke(app, ["ingest", "--raw-dir", str(FIXTURES)])
    assert result.exit_code == 0, result.output
    assert "transferegov_planos_acao:" in result.output
    assert db.execute("select count(*) from staging.transferegov_planos_acao").fetchone()[0] > 0


def test_ingest_can_skip_transferegov(db, monkeypatch):
    def unavailable():
        raise AssertionError("the API must not be contacted")

    monkeypatch.setattr("rastro.cli.build_transferegov_client", unavailable)
    monkeypatch.setenv("POSTGRES_DB", db.info.dbname)
    result = runner.invoke(app, ["ingest", "--raw-dir", str(FIXTURES), "--skip-transferegov"])
    assert result.exit_code == 0, result.output
    assert "transferegov" not in result.output
    assert db.execute("select count(*) from staging.transferegov_planos_acao").fetchone()[0] == 0


def test_ingest_stops_before_loading_anything_when_the_api_fails(db, monkeypatch):
    class Broken:
        def rows(self, *args, **kwargs):
            raise TransferegovError("beneficiarios-especiais: gave up after 6 attempts (HTTP 500)")

    monkeypatch.setattr("rastro.cli.build_transferegov_client", lambda: Broken())
    monkeypatch.setenv("POSTGRES_DB", db.info.dbname)
    result = runner.invoke(app, ["ingest", "--raw-dir", str(FIXTURES)])
    assert result.exit_code == 1
    assert "gave up after 6 attempts" in result.output
    assert "--skip-transferegov" in result.output
    assert db.execute("select count(*) from raw.emendas_parlamentares").fetchone()[0] == 0


def test_ingest_explains_how_to_get_missing_files(db, monkeypatch, tmp_path):
    monkeypatch.setenv("POSTGRES_DB", db.info.dbname)
    result = runner.invoke(app, ["ingest", "--raw-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "download_federal.py" in result.output


def test_ingest_builds_the_mart(db, monkeypatch):
    monkeypatch.setenv("POSTGRES_DB", db.info.dbname)
    result = runner.invoke(app, ["ingest", "--raw-dir", str(FIXTURES)])
    assert result.exit_code == 0, result.output
    assert db.execute("select count(*) from mart.emendas").fetchone()[0] > 0


def test_ask_prints_answer_sql_rows_and_sources(readonly, monkeypatch):
    from rastro.agent.run import Agent
    from support import ScriptedLLM, say, sql

    llm = ScriptedLLM(sql("select count(*) as linhas from emendas"), say("Há linhas de sobra."))
    monkeypatch.setattr("rastro.cli.build_agent", lambda: Agent(llm, readonly))
    result = runner.invoke(app, ["ask", "Quantas linhas?"])
    assert result.exit_code == 0, result.output
    assert "Há linhas de sobra." in result.output
    assert "select count(*)" in result.output.lower()
    assert "linhas" in result.output
    assert "Portal da Transparência (CGU)" in result.output


def test_ask_exits_with_error_when_the_model_is_unavailable(readonly, monkeypatch):
    from rastro.agent.llm import LLMError
    from rastro.agent.run import Agent
    from support import ScriptedLLM

    llm = ScriptedLLM(LLMError("connection refused"))
    monkeypatch.setattr("rastro.cli.build_agent", lambda: Agent(llm, readonly))
    result = runner.invoke(app, ["ask", "Quanto?"])
    assert result.exit_code == 1
    assert "connection refused" in result.output
