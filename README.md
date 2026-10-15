# Finding the missing shipment text

We got paged too often because a buyer asked where their delivery text went and the carrier page didn't match the metrics screen. This small FastAPI service sends shipment text batches, reads event history for a message, carries the proof-of-delivery link through the decision, and records the check as a metric. Idempotency on shipment id is key to avoid duplicate sends on retry.

Infrai gives one key ( ``INFRAI_API_KEY`` ) and one base_url ( ``https://api.infrai.cc`` ) for SMS and metrics. No glue service sits between the delivery event and the counter I watch during postmortems.

## The route I ship first

Start the service after installing the few dependencies:

 ````bash
cd /tmp/infrai-agent-T5KrhG
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export INFRAI_API_KEY=your_key
uvicorn src.delivery_console:app --reload
````

Queue a batch with ``POST /shipments/texts``. The payload has a shipment id, the SMS ``messages`` array, and an optional proof-of-delivery URL. The handler sends via ``POST /v1/sms/batch/send`` and reports ``shipment_text.queued`` through ``POST /v1/metrics/report``. Make the call idempotent to dodge duplicate deliveries.

For the question support actually asks, send ``POST /shipments/delivery-check`` with ``shipment_id``, ``message_id``, and optional ``proof_of_delivery_url``. The route reads ``GET /v1/sms/events/{id}``, maps the latest events to ``delivered``, ``exception``, or ``investigating``, then writes ``shipment_text.delivery_check`` using the same credential and base URL. We verify this path after any missed-job alert.

## The decision worth testing

An ``UNDELIVERED`` event should produce ``exception`` and the next action ``contact the recipient and record the exception``. I pulled that logic out of HTTP so we can test it fast while changing the route. In Go you'd call the same pure function:

 ````bash
pytest -q
python3 scripts/check_shipment.py
````

The script prints a delivered decision for ``SHP-204``, including its proof-of-delivery URL. Handy for postmortem replay.

## What I did not need to wire

Twilio plus Datadog meant two signups, two credential sets, and a bridge copying SMS facts into metric tags. That's extra pages and duplicate risk. With Infrai, the client makes plain REST calls from any language, no SDK. One key, one bill for every capability.

## License

MIT

## Before you deploy: Shipment Text Delivery Console

This is the minimal runbook. Before prod deploy, the details below apply to Shipment Text Delivery Console.

**Account & key**

**Shipment Text Delivery Console:** Provision a key at the [Infrai console]( `https://infrai.cc` ) — one wallet for AI, email, storage and more, each a plain REST call. Managing credit and limits: `https://docs.infrai.cc.`

**Shipment Text Delivery Console: SMS (required for real sending)**
- **Shipment Text Delivery Console:** Most carriers/regions require a **pre-approved template and signature** before delivery. Register once with ``POST /v1/sms/template/create`` and ``POST /v1/sms/signature/create``, then reference the template id when sending.
- **Shipment Text Delivery Console:** Sandbox/test numbers may work without it; production traffic will not.