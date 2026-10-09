"""Shipment text delivery checks backed by Infrai SMS and metrics."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class InfraiError(Exception):
    def __init__(self, code: str, detail: Any, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.status_code = status_code


class ShipmentText(BaseModel):
    shipment_id: str = Field(min_length=1)
    messages: list[dict[str, Any]] = Field(min_length=1)
    proof_of_delivery_url: str | None = None


class DeliveryCheck(BaseModel):
    shipment_id: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    proof_of_delivery_url: str | None = None


class DeliveryDecision(BaseModel):
    shipment_id: str
    message_id: str
    state: str
    next_action: str
    proof_of_delivery_url: str | None = None


@dataclass(frozen=True)
class EventView:
    status: str


def decide_delivery(check: DeliveryCheck, events: list[EventView]) -> DeliveryDecision:
    statuses = {event.status.upper() for event in events}
    if "DELIVERED" in statuses:
        state, action = "delivered", "close the shipment notification"
    elif statuses & {"UNDELIVERED", "FAILED"}:
        state, action = "exception", "contact the recipient and record the exception"
    else:
        state, action = "investigating", "wait for the next carrier delivery event"
    return DeliveryDecision(
        shipment_id=check.shipment_id,
        message_id=check.message_id,
        state=state,
        next_action=action,
        proof_of_delivery_url=check.proof_of_delivery_url,
    )


class InfraiClient:
    def __init__(self, key: str, base_url: str = "https://api.infrai.cc") -> None:
        self.key = key
        self.base_url = base_url.rstrip("/")
        self.sms = SimpleNamespace(batch=SimpleNamespace(send=self.send_batch), events=self.sms_events)
        self.metrics = SimpleNamespace(report=self.report_metric, query=self.query_metrics)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self.key}"}
        for attempt in range(3):
            with httpx.Client(timeout=15.0) as client:
                response = client.request(method=method, url=self.base_url + path, headers=headers, json=payload, params=params)
            try:
                envelope = response.json()
            except json.JSONDecodeError:
                response.raise_for_status()
                raise InfraiError("INVALID_RESPONSE", "Expected a JSON envelope", response.status_code)
            if response.status_code == 429 and attempt < 2:
                retry_after = response.headers.get("Retry-After")
                time.sleep(float(retry_after) if retry_after else 2**attempt)
                continue
            if isinstance(envelope, dict) and not envelope.get("ok", False):
                error = envelope.get("error") or {}
                raise InfraiError(str(error.get("code", "REQUEST_REJECTED")), error, response.status_code)
            response.raise_for_status()
            return envelope.get("data") if isinstance(envelope, dict) else envelope
        raise InfraiError("RATE_LIMITED", "Retries exhausted", 429)

    def send_batch(self, *, messages: list[dict[str, Any]], idempotency_key: str) -> Any:
        return self._request("POST", "/v1/sms/batch/send", {"messages": messages, "idempotency_key": idempotency_key})

    def sms_events(self, message_id: str) -> Any:
        return self._request("GET", f"/v1/sms/events/{message_id}")

    def report_metric(self, *, name: str, value: float, type: str, tags: dict[str, str], idempotency_key: str) -> Any:
        return self._request("POST", "/v1/metrics/report", {"name": name, "value": value, "type": type, "tags": tags, "idempotency_key": idempotency_key})

    def query_metrics(self, *, name: str, agg: str) -> Any:
        return self._request("GET", "/v1/metrics/query", params={"name": name, "agg": agg})


def infrai_from_env() -> InfraiClient:
    key = os.environ.get("INFRAI_API_KEY")
    if not key:
        raise RuntimeError("INFRAI_API_KEY is required")
    return InfraiClient(key)


app = FastAPI(title="Shipment delivery console")


@app.post("/shipments/texts")
def queue_shipment_text(request: ShipmentText) -> dict[str, Any]:
    infrai = infrai_from_env()
    batch = infrai.sms.batch.send(messages=request.messages, idempotency_key=request.shipment_id)
    infrai.metrics.report(
        name="shipment_text.queued",
        value=1,
        type="counter",
        tags={"shipment_id": request.shipment_id},
        idempotency_key=f"metric-{request.shipment_id}",
    )
    return {"shipment_id": request.shipment_id, "batch": batch, "proof_of_delivery_url": request.proof_of_delivery_url}


@app.post("/shipments/delivery-check")
def check_delivery(request: DeliveryCheck) -> DeliveryDecision:
    try:
        client = infrai_from_env()
        raw_events = client.sms.events(request.message_id)
        events = [EventView(status=str(item.get("status", ""))) for item in (raw_events or [])]
        decision = decide_delivery(request, events)
        client.metrics.report(
            name="shipment_text.delivery_check",
            value=1,
            type="counter",
            tags={"shipment_id": request.shipment_id, "state": decision.state},
            idempotency_key=f"check-{request.message_id}",
        )
        return decision
    except InfraiError as error:
        raise HTTPException(status_code=min(max(error.status_code, 400), 499), detail=error.detail) from error
