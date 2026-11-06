from pathlib import Path

import psycopg

from rastro.ingest.load import load_raw_csv

FILES = {
    "EmendasParlamentares.csv": "emendas_parlamentares",
    "EmendasParlamentares_Convenios.csv": "emendas_convenios",
    "EmendasParlamentares_PorFavorecido.csv": "emendas_por_favorecido",
}


def load_raw(conn: psycopg.Connection, raw_dir: Path) -> dict[str, int]:
    """Load the three federal files into the raw schema in one transaction."""
    with conn.transaction():
        return {name: load_raw_csv(conn, table, raw_dir / name) for name, table in FILES.items()}
