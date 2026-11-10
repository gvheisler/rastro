import csv
from decimal import Decimal
from pathlib import Path

from rastro.agent.llm import Completion, ToolCall

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


class ScriptedLLM:
    """Replays prepared completions and records the messages it was sent."""

    model = "scripted"

    def __init__(self, *completions):
        self.completions = list(completions)
        self.calls = []

    def complete(self, messages, tools):
        self.calls.append([dict(m) for m in messages])
        item = self.completions.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def call(name, **arguments):
    return Completion("", (ToolCall(f"id{name}", name, arguments),), 10, 5)


def say(text):
    return Completion(text, (), 10, 5)


def sql(query):
    return call("run_sql", sql=query)
