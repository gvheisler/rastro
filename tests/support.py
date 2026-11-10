import csv
from decimal import Decimal
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def read_csv(name: str, directory: Path = FIXTURES) -> tuple[list[str], list[list[str]]]:
    with (directory / name).open(encoding="latin-1", newline="") as f:
        reader = csv.reader(f, delimiter=";")
        return next(reader), list(reader)


def column(filename: str, name: str) -> list[str]:
    header, rows = read_csv(filename)
    i = header.index(name)
    return [r[i] for r in rows]


def money(text: str) -> Decimal:
    return Decimal(text.replace(",", "."))


def scalar(conn, query: str, params=None):
    return conn.execute(query, params).fetchone()[0]
