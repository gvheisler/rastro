import json
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from typing import Any

import httpx

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
