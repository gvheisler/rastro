import csv
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def read_csv(name: str, directory: Path = FIXTURES) -> tuple[list[str], list[list[str]]]:
    with (directory / name).open(encoding="latin-1", newline="") as f:
        reader = csv.reader(f, delimiter=";")
        return next(reader), list(reader)
