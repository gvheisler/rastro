import csv
import json
from decimal import Decimal
from pathlib import Path

import httpx

from rastro.agent.llm import Completion, ToolCall

FIXTURES = Path(__file__).parent / "fixtures"
TRANSFEREGOV = FIXTURES / "transferegov"
API_BASE = "https://api.test/especiais"


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


def fake_transferegov(
    data: dict[str, list[dict]], *, honor_filters: bool = True, updated: str = "2026-11-10"
) -> httpx.MockTransport:
    """Serve lists of rows the way the Transferegov API does: pages, totals and equality filters."""

    def handler(request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.rsplit("/", 1)[-1]
        if endpoint == "data-atualizacao":
            return httpx.Response(200, json={"data_ultima_atualizacao": f"{updated}T00:00:00"})
        if endpoint not in data:
            return httpx.Response(404, json={"detail": "Not Found"})
        params = dict(request.url.params)
        number, size = int(params.pop("pagina")), int(params.pop("tamanho_da_pagina"))
        rows = data[endpoint]
        if honor_filters:
            rows = [r for r in rows if all(str(r.get(k)) == v for k, v in params.items())]
        start = (number - 1) * size
        body = {
            "data": rows[start : start + size],
            "page_number": number,
            "page_size": size,
            "total_pages": max(1, -(-len(rows) // size)),
            "total_items": len(rows),
        }
        return httpx.Response(200, text=json.dumps(body, default=float))

    return httpx.MockTransport(handler)


def fixture_transferegov() -> dict[str, list[dict]]:
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
        for path in sorted(TRANSFEREGOV.glob("*.json"))
    }


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
