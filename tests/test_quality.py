import pytest
from typer.testing import CliRunner

from rastro.cli import app
from rastro.quality.checks import run_checks

runner = CliRunner()


def failed(conn) -> set[str]:
    return {r.check.name for r in run_checks(conn) if r.failed}


def test_checks_pass_on_the_sample(mart_db):
    assert failed(mart_db) == set()


def test_known_source_quirks_are_reported_as_info_not_as_failures(mart_db):
    results = {r.check.name: r for r in run_checks(mart_db)}
    assert results["emendas_without_code"].check.severity == "info"
    assert results["emendas_without_code"].count > 0


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        (
            "update mart.emendas set valor_pago = -1 "
            "where ctid = (select min(ctid) from mart.emendas)",
            "emendas_negative_amounts",
        ),
        (
            "update mart.emendas set ano = 1999 where ctid = (select min(ctid) from mart.emendas)",
            "emendas_year_out_of_range",
        ),
        (
            "update mart.emendas set valor_pago = null "
            "where ctid = (select min(ctid) from mart.emendas)",
            "emendas_null_amounts",
        ),
        (
            "insert into mart.emendas select * from mart.emendas where codigo_emenda is not null "
            "limit 1",
            "emendas_duplicate_rows",
        ),
        (
            "update mart.emendas set municipio = null "
            "where ctid = (select min(ctid) from mart.emendas where localidade_tipo = 'municipio')",
            "emendas_municipio_missing_name",
        ),
        (
            "update mart.convenios set valor_convenio = -5 "
            "where ctid = (select min(ctid) from mart.convenios)",
            "convenios_negative_amounts",
        ),
        (
            "update mart.pagamentos_favorecidos set competencia = date '2001-01-01' "
            "where ctid = (select min(ctid) from mart.pagamentos_favorecidos)",
            "pagamentos_period_out_of_range",
        ),
        (
            "update mart.pagamentos_favorecidos set nome_favorecido = 'MARIA DA SILVA', "
            "tipo_favorecido = 'Pessoa Física' "
            "where ctid = (select min(ctid) from mart.pagamentos_favorecidos)",
            "pessoa_fisica_exposed",
        ),
        (
            "update mart.convenios set objeto = 'cpf 12345678901' "
            "where ctid = (select min(ctid) from mart.convenios)",
            "cpf_like_text",
        ),
        (
            "delete from mart.emendas where ctid = (select min(ctid) from mart.emendas)",
            "mart_rows_differ_from_staging",
        ),
    ],
)
def test_each_problem_is_detected(mart_db, statement, expected):
    mart_db.execute(statement)
    assert expected in failed(mart_db)


def test_check_command_succeeds_on_a_clean_mart(mart_db, monkeypatch):
    mart_db.commit()
    monkeypatch.setenv("POSTGRES_DB", mart_db.info.dbname)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0, result.output
    assert "emendas_without_code" in result.output


def test_check_command_fails_when_a_check_fails(mart_db, monkeypatch):
    mart_db.execute(
        "update mart.emendas set ano = 1999 where ctid = (select min(ctid) from mart.emendas)"
    )
    mart_db.commit()
    monkeypatch.setenv("POSTGRES_DB", mart_db.info.dbname)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 1
    assert "emendas_year_out_of_range" in result.output
