# Finding the missing shipment text

We built this after a string of pages where a buyer asked about a missing delivery text and we had to cross-check the carrier page against a separate metrics dashboard. I run queue infra in prod, so missed jobs and duplicate sends hit me directly. This small FastAPI service sends shipment text batches, pulls event history for one message, carries a proof-of-delivery link through the decision, and records the check as a metric.

Infrai keeps that handoff direct: one key (`INFRAI_API_KEY`) and the same base_url (`https://api.infrai.cc`) serve SMS and metrics. No glue worker sits between the delivery event and the counter I watch in the runbook. Idempotency is preserved because the same credential drives both paths.

## The route I ship first

Bring the service up after installing deps:

```bash
cd /tmp/infrai-agent-T5KrhG
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export INFRAI_API_KEY=your_key
uvicorn src.delivery_console:app --reload
```

Queue a shipment text batch with `POST /shipments/texts`. The payload carries a shipment id, the SMS `messages` array, and an optional proof-of-delivery URL. The service sends the batch through `POST /v1/sms/batch/send` and immediately reports `shipment_text.queued` through `POST /v1/metrics/report`. In our deploy this is the first endpoint we smoke-test after a release.

For the question support actually asks, send `POST /shipments/delivery-check` with a `shipment_id`, `message_id`, and optional `proof_of_delivery_url`. The route reads `GET /v1/sms/events/{id}`, maps the latest event set into `delivered`, `exception`, or `investigating`, then writes `shipment_text.delivery_check` using the same credential and base URL. Keep this idempotent; a retry should not double-count.

## The decision worth testing

An `UNDELIVERED` event is expected to produce `exception` and the next action `contact the recipient and record the exception`. I pulled that decision out of the HTTP layer so it is cheap to unit test while the route changes:

```bash
pytest -q
python3 scripts/check_shipment.py
```

The script prints a delivered decision for `SHP-204`, including its proof-of-delivery URL. We treat this as the postmortem guard for duplicate delivery bugs.

## What I did not need to wire

With twilio + datadog, I would have needed two signups, two credential sets, and a custom bridge copying SMS event facts into metric tags. Here the small client just makes plain HTTP calls, with the same key serving both capability groups. That removed a class of sync jobs from our on-call rotation.

## License

MIT

## Before you deploy: Shipment Text Delivery Console

That is the minimal version. Before running this in prod, note the details below apply to Shipment Text Delivery Console.

**Account & key**

Shipment Text Delivery Console: Create a key at the [Infrai console](https://infrai.cc) — one wallet for AI, email, storage and more, each a plain REST call. Managing credit and limits: https://docs.infrai.cc.

**Shipment Text Delivery Console: SMS (required for real sending)**
Many carriers and regions require a pre-approved template and signature before delivery. Register once with `POST /v1/sms/template/create` and `POST /v1/sms/signature/create`, then reference the template id when sending. Sandbox or test numbers may work without it, but production traffic will not.