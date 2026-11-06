from typer.testing import CliRunner

from rastro.cli import app
from support import FIXTURES, read_csv

runner = CliRunner()


def test_ingest_loads_raw_and_builds_staging(db, monkeypatch):
    monkeypatch.setenv("POSTGRES_DB", db.info.dbname)
    result = runner.invoke(app, ["ingest", "--raw-dir", str(FIXTURES)])
    assert result.exit_code == 0, result.output
    rows = len(read_csv("EmendasParlamentares.csv")[1])
    assert f"EmendasParlamentares.csv: {rows:,} rows" in result.output
    assert db.execute("select count(*) from staging.emendas").fetchone()[0] == rows


def test_ingest_explains_how_to_get_missing_files(db, monkeypatch, tmp_path):
    monkeypatch.setenv("POSTGRES_DB", db.info.dbname)
    result = runner.invoke(app, ["ingest", "--raw-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "download_federal.py" in result.output
