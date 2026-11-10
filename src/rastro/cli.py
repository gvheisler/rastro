from pathlib import Path
from typing import Annotated

import typer

from rastro.agent.run import Answer, build_agent
from rastro.agent.tools import format_table
from rastro.config import RAW_DIR, get_settings
from rastro.db import apply_sql, connect
from rastro.ingest.federal import FILES, load_raw
from rastro.ingest.load import SchemaMismatchError
from rastro.ingest.transferegov import (
    TransferegovClient,
    TransferegovError,
    load_raw_transferegov,
)
from rastro.mart import build_mart
from rastro.quality.checks import run_checks

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Rastro data pipeline.")


@app.callback()
def main() -> None:
    """Rastro data pipeline."""


def build_transferegov_client() -> TransferegovClient:
    return TransferegovClient(get_settings().transferegov_base_url)


@app.command()
def ingest(
    raw_dir: Annotated[
        Path, typer.Option(help="Directory with the Portal da Transparência CSVs.")
    ] = RAW_DIR,
    skip_transferegov: Annotated[
        bool,
        typer.Option(
            "--skip-transferegov", help="Do not download Transferegov; keep what is already in raw."
        ),
    ] = False,
) -> None:
    """Load the federal CSVs and Transferegov into raw, then rebuild staging and the mart."""
    missing = [name for name in FILES if not (raw_dir / name).exists()]
    if missing:
        typer.echo(
            f"Missing in {raw_dir}: {', '.join(missing)}. "
            "Run: uv run python scripts/download_federal.py",
            err=True,
        )
        raise typer.Exit(1)

    with connect() as conn:
        apply_sql(conn, "01_raw.sql")
        loaded: dict[str, int] = {}
        if not skip_transferegov:
            try:
                loaded |= load_raw_transferegov(conn, build_transferegov_client())
            except (TransferegovError, SchemaMismatchError) as error:
                typer.echo(
                    f"Transferegov: {error}. Try again later, or use --skip-transferegov "
                    "to rebuild with what is already loaded.",
                    err=True,
                )
                raise typer.Exit(1) from error
        loaded |= load_raw(conn, raw_dir)
        apply_sql(conn, "02_staging.sql")
        build_mart(conn)

    for name, rows in loaded.items():
        typer.echo(f"{name}: {rows:,} rows")


@app.command()
def check() -> None:
    """Run data quality checks on the mart; exit with 1 if any error check fails."""
    with connect() as conn:
        results = run_checks(conn)

    for result in results:
        status = "FAIL" if result.failed else ("info" if result.check.severity == "info" else "ok")
        typer.echo(
            f"{status:<5} {result.check.name:<34} {result.count:>8,}  {result.check.description}"
        )
    if any(r.failed for r in results):
        raise typer.Exit(1)


@app.command()
def ask(question: Annotated[str, typer.Argument(help="Question in Portuguese.")]) -> None:
    """Ask the agent a question about amendments to Santa Catarina."""
    answer = build_agent().ask(question)
    if answer.error:
        typer.echo(f"{answer.text} ({answer.error})", err=True)
        raise typer.Exit(1)
    typer.echo(_render(answer))


def _render(answer: Answer) -> str:
    parts = [answer.text]
    if answer.sql:
        parts.append(f"SQL\n{answer.sql}")
        parts.append("Resultado\n" + format_table(answer.columns, answer.rows, 20))
    for source in answer.sources:
        parts.append(
            f"Fonte: {source.fonte}, {source.arquivo}, {source.ano_inicio} a {source.ano_fim}, "
            f"carregado em {source.carregado_em:%d/%m/%Y}"
        )
    return "\n\n".join(parts)
