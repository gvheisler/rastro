import json
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import psycopg

from rastro.ingest.load import SchemaMismatchError, load_raw_rows

PAGE_SIZE = 200
RETRYABLE = {429, 500, 502, 503, 504}


class TransferegovError(Exception):
    """The Transferegov API did not return a complete, well-formed answer."""


class TransferegovClient:
    """Reads the paginated open-data API of the Transferegov special-transfers module."""

    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.BaseTransport | None = None,
        retries: int = 5,
        backoff: float = 0.5,
        workers: int = 4,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = httpx.Client(base_url=base_url.rstrip("/"), transport=transport, timeout=90)
        self._retries = retries
        self._backoff = backoff
        self._workers = workers
        self._sleep = sleep

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        last = ""
        for attempt in range(self._retries + 1):
            if attempt:
                self._sleep(self._backoff * 2 ** (attempt - 1))
            try:
                response = self._http.get(f"/{endpoint}", params=params)
            except httpx.TransportError as error:
                last = type(error).__name__
                continue
            if response.status_code in RETRYABLE:
                last = f"HTTP {response.status_code}"
                continue
            if response.status_code != 200:
                raise TransferegovError(f"{endpoint}: HTTP {response.status_code}")
            return json.loads(response.text, parse_float=Decimal)
        raise TransferegovError(f"{endpoint}: gave up after {self._retries + 1} attempts ({last})")

    def last_update(self) -> date:
        """Date of the last update of the source, as reported by the API."""
        body = self._get("data-atualizacao")
        return date.fromisoformat(body["data_ultima_atualizacao"][:10])

    def _page(self, endpoint: str, number: int, filters: dict[str, str]) -> dict[str, Any]:
        body = self._get(endpoint, {"pagina": number, "tamanho_da_pagina": PAGE_SIZE, **filters})
        if not isinstance(body, dict) or not {"data", "total_pages", "total_items"} <= body.keys():
            raise TransferegovError(f"{endpoint}: unexpected response shape")
        return body

    def rows(self, endpoint: str, **filters: str) -> Iterator[dict[str, Any]]:
        """Yield every row of an endpoint, in page order.

        The first page says how many pages there are; the rest are fetched by a few workers.
        Raises when the rows received do not add up to the total the API announced, so a
        partial download is never mistaken for a complete one.
        """
        first = self._page(endpoint, 1, filters)
        received = len(first["data"])
        yield from first["data"]
        with ThreadPoolExecutor(self._workers) as pool:
            later = pool.map(
                lambda n: self._page(endpoint, n, filters), range(2, first["total_pages"] + 1)
            )
            for body in later:
                received += len(body["data"])
                yield from body["data"]
        if received != first["total_items"]:
            raise TransferegovError(
                f"{endpoint}: received {received} of {first['total_items']} rows"
            )


@dataclass(frozen=True)
class Resource:
    """An API endpoint, the raw table that receives it and the fields kept from each row."""

    endpoint: str
    table: str
    key: str
    columns: tuple[str, ...]


BENEFICIARIOS = Resource(
    "beneficiarios-especiais",
    "transferegov_beneficiarios",
    "id_beneficiario",
    ("id_beneficiario", "uf_beneficiario", "nome_beneficiario", "cnpj_beneficiario"),
)

PLANOS_ACAO = Resource(
    "planos-acao-especiais",
    "transferegov_planos_acao",
    "id_plano_acao",
    (
        "id_plano_acao",
        "codigo_plano_acao",
        "ano_plano_acao",
        "situacao_plano_acao",
        "data_aceite_plano_acao",
        "motivo_impedimento_plano_acao",
        "nome_parlamentar_emenda_plano_acao",
        "ano_emenda_parlamentar_plano_acao",
        "numero_emenda_parlamentar_plano_acao",
        "valor_custeio_plano_acao",
        "valor_investimento_plano_acao",
        "categoria_despesa_plano_acao",
        "codigo_descricao_areas_politicas_publicas_plano_acao",
        "nome_objeto",
        "detalhamento_objeto",
        "id_beneficiario",
    ),
)

EXECUTORES = Resource(
    "executores-especiais",
    "transferegov_executores",
    "id_executor",
    ("id_executor", "id_plano_acao", "cnpj_executor", "nome_executor", "objeto_executor"),
)

PLANOS_TRABALHO = Resource(
    "planos-trabalho-especiais",
    "transferegov_planos_trabalho",
    "id_plano_trabalho",
    (
        "id_plano_trabalho",
        "id_plano_acao",
        "situacao_plano_trabalho",
        "data_inicio_execucao_plano_trabalho",
        "data_fim_execucao_plano_trabalho",
        "prazo_execucao_meses_plano_trabalho",
    ),
)

EMPENHOS = Resource(
    "empenhos-especiais",
    "transferegov_empenhos",
    "id_empenho",
    (
        "id_empenho",
        "id_plano_acao",
        "numero_empenho",
        "situacao_empenho",
        "descricao_situacao_empenho",
        "descricao_tipo_documento_empenho",
        "data_emissao_empenho",
        "categoria_despesa_empenho",
        "valor_empenho",
    ),
)

RESOURCES = (BENEFICIARIOS, PLANOS_ACAO, EXECUTORES, PLANOS_TRABALHO, EMPENHOS)


def fetch_santa_catarina(client: TransferegovClient) -> dict[str, list[dict[str, Any]]]:
    """Download what hangs from Santa Catarina beneficiaries, keyed by raw table name.

    The API has no UF filter on plans or on the tables below them, so beneficiaries come
    first, then the plans of those beneficiaries, then the rows tied to those plans. Rows
    are sorted by their id so that the same source state always yields the same load.
    """
    beneficiarios = [
        row
        for row in client.rows(BENEFICIARIOS.endpoint, uf_beneficiario="SC")
        if row["uf_beneficiario"] == "SC"
    ]
    beneficiary_ids = {row["id_beneficiario"] for row in beneficiarios}
    planos = [
        row
        for row in client.rows(PLANOS_ACAO.endpoint)
        if row["id_beneficiario"] in beneficiary_ids
    ]
    plan_ids = {row["id_plano_acao"] for row in planos}
    result = {BENEFICIARIOS.table: beneficiarios, PLANOS_ACAO.table: planos}
    for resource in (EXECUTORES, PLANOS_TRABALHO, EMPENHOS):
        result[resource.table] = [
            row for row in client.rows(resource.endpoint) if row["id_plano_acao"] in plan_ids
        ]
    for resource in RESOURCES:
        result[resource.table].sort(key=lambda row, key=resource.key: row[key])
    return result


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _as_rows(resource: Resource, rows: list[dict[str, Any]]) -> list[tuple[str | None, ...]]:
    """Pick the loaded fields of each row; fields the API no longer sends are an error."""
    wanted = set(resource.columns)
    for row in rows:
        if missing := sorted(wanted - row.keys()):
            raise SchemaMismatchError(
                f"{resource.endpoint}: the API rows lack the fields {missing}, "
                f"which raw.{resource.table} expects"
            )
    return [tuple(_text(row[c]) for c in resource.columns) for row in rows]


def load_raw_transferegov(conn: psycopg.Connection, client: TransferegovClient) -> dict[str, int]:
    """Download Santa Catarina from the API and replace the raw Transferegov tables.

    Everything is downloaded and checked before the database is touched, and the tables are
    replaced in one transaction, so a failure leaves the previous load in place.
    """
    data = fetch_santa_catarina(client)
    updated = client.last_update()
    tables = {resource: _as_rows(resource, data[resource.table]) for resource in RESOURCES}
    with conn.transaction():
        return {
            resource.table: load_raw_rows(
                conn,
                resource.table,
                resource.columns,
                rows,
                arquivo=f"especiais/{resource.endpoint}",
                atualizado_na_fonte=updated,
            )
            for resource, rows in tables.items()
        }
