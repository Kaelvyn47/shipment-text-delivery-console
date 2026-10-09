import httpx

from src.delivery_console import DeliveryCheck, EventView, InfraiClient, decide_delivery


def test_undelivered_event_becomes_recipient_exception() -> None:
    check = DeliveryCheck(shipment_id="SHP-9", message_id="message-9")

    decision = decide_delivery(check, [EventView(status="UNDELIVERED")])

    assert decision.state == "exception"
    assert decision.next_action == "contact the recipient and record the exception"


def test_metrics_query_sends_required_query_fields(monkeypatch) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/metrics/query"
        assert dict(request.url.params) == {"name": "shipment_text.queued", "agg": "sum"}
        return httpx.Response(200, json={"ok": True, "data": []})

    transport = httpx.MockTransport(handle)
    original_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(transport=transport, **kwargs))

    assert InfraiClient("test-key").metrics.query(name="shipment_text.queued", agg="sum") == []
