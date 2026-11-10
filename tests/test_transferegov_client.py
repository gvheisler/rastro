import json
import threading
import time
from decimal import Decimal

import httpx
import pytest

from rastro.ingest.transferegov import PAGE_SIZE, TransferegovClient, TransferegovError

BASE = "https://api.test/especiais"


def page(rows, number, total_pages, total_items):
    return {
        "data": rows,
        "page_number": number,
        "page_size": PAGE_SIZE,
        "total_pages": total_pages,
        "total_items": total_items,
    }


def client_for(handler, retries=3):
    waits = []
    client = TransferegovClient(
        BASE,
        transport=httpx.MockTransport(handler),
        retries=retries,
        sleep=waits.append,
    )
    return client, waits


def test_rows_follow_the_pages_until_the_last_one():
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        number = int(request.url.params["pagina"])
        rows = {1: [{"id": 1}, {"id": 2}], 2: [{"id": 3}]}[number]
        return httpx.Response(200, json=page(rows, number, 2, 3))

    client, _ = client_for(handler)
    assert [r["id"] for r in client.rows("planos")] == [1, 2, 3]
    assert [p["pagina"] for p in seen] == ["1", "2"]
    assert all(p["tamanho_da_pagina"] == str(PAGE_SIZE) for p in seen)


def test_later_pages_are_fetched_in_parallel_and_returned_in_order():
    lock = threading.Lock()
    state = {"active": 0, "peak": 0}

    def handler(request):
        number = int(request.url.params["pagina"])
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        time.sleep(0.02 * (6 - number))
        with lock:
            state["active"] -= 1
        return httpx.Response(200, json=page([{"id": number}], number, 5, 5))

    client, _ = client_for(handler)
    assert [r["id"] for r in client.rows("planos")] == [1, 2, 3, 4, 5]
    assert state["peak"] > 1


def test_a_failed_page_stops_the_remaining_downloads():
    requested = []

    def handler(request):
        number = int(request.url.params["pagina"])
        requested.append(number)
        if number == 3:
            return httpx.Response(404, json={"detail": "Not Found"})
        time.sleep(0.01)
        return httpx.Response(200, json=page([{"id": number}], number, 60, 60))

    client, _ = client_for(handler)
    with pytest.raises(TransferegovError, match="404"):
        list(client.rows("planos"))
    assert len(requested) < 30


def test_filters_are_sent_as_query_parameters():
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=page([], 1, 1, 0))

    client, _ = client_for(handler)
    list(client.rows("beneficiarios", uf_beneficiario="SC"))
    assert seen[0]["uf_beneficiario"] == "SC"


def test_decimal_values_keep_their_exact_text():
    body = '{"data": [{"valor": 990000.10}], "total_pages": 1, "total_items": 1}'

    client, _ = client_for(lambda request: httpx.Response(200, text=body))
    (row,) = client.rows("planos")
    assert row["valor"] == Decimal("990000.10")
    assert str(row["valor"]) == "990000.10"


def test_server_errors_are_retried_with_growing_waits():
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(500, text="Internal Server Error")
        return httpx.Response(200, json=page([{"id": 1}], 1, 1, 1))

    client, waits = client_for(handler)
    assert list(client.rows("planos")) == [{"id": 1}]
    assert len(attempts) == 3
    assert len(waits) == 2 and waits[0] < waits[1]


def test_network_errors_are_retried():
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ConnectTimeout("slow", request=request)
        return httpx.Response(200, json=page([{"id": 1}], 1, 1, 1))

    client, _ = client_for(handler)
    assert list(client.rows("planos")) == [{"id": 1}]


def test_gives_up_after_the_configured_retries():
    attempts = []

    def handler(request):
        attempts.append(1)
        return httpx.Response(500, text="Internal Server Error")

    client, _ = client_for(handler, retries=2)
    with pytest.raises(TransferegovError, match="planos.*500"):
        list(client.rows("planos"))
    assert len(attempts) == 3


def test_client_errors_are_not_retried():
    attempts = []

    def handler(request):
        attempts.append(1)
        return httpx.Response(404, json={"detail": "Not Found"})

    client, _ = client_for(handler)
    with pytest.raises(TransferegovError, match="404"):
        list(client.rows("planos"))
    assert len(attempts) == 1


def test_fewer_rows_than_the_reported_total_is_an_error():
    def handler(request):
        return httpx.Response(200, json=page([{"id": 1}], 1, 1, 5))

    client, _ = client_for(handler)
    with pytest.raises(TransferegovError, match="1 of 5"):
        list(client.rows("planos"))


def test_response_without_the_expected_shape_is_an_error():
    client, _ = client_for(lambda request: httpx.Response(200, json={"unexpected": True}))
    with pytest.raises(TransferegovError, match="planos"):
        list(client.rows("planos"))


def test_last_update_is_the_date_reported_by_the_api():
    def handler(request):
        assert request.url.path == "/especiais/data-atualizacao"
        return httpx.Response(
            200, content=json.dumps({"data_ultima_atualizacao": "2026-11-10T00:00:00"})
        )

    client, _ = client_for(handler)
    assert client.last_update().isoformat() == "2026-11-10"
