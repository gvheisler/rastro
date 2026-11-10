from pathlib import Path
from typing import Annotated

import typer

from rastro.config import RAW_DIR
from rastro.db import apply_sql, connect
from rastro.ingest.federal import FILES, load_raw
from rastro.mart import build_mart

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Rastro data pipeline.")


@app.callback()
def main() -> None:
    """Rastro data pipeline."""


@app.command()
def ingest(
    raw_dir: Annotated[
        Path, typer.Option(help="Directory with the Portal da Transparência CSVs.")
    ] = RAW_DIR,
) -> None:
    """Load the federal CSVs into raw, then rebuild staging and the mart."""
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
        loaded = load_raw(conn, raw_dir)
        apply_sql(conn, "02_staging.sql")
        build_mart(conn)

    for name, rows in loaded.items():
        typer.echo(f"{name}: {rows:,} rows")
