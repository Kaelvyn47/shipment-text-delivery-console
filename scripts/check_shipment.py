"""Run the local decision rule with a shipment event timeline."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.delivery_console import DeliveryCheck, EventView, decide_delivery


check = DeliveryCheck(
    shipment_id="SHP-204",
    message_id="message-204",
    proof_of_delivery_url="https://proof.example/SHP-204",
)
decision = decide_delivery(check, [EventView(status="DELIVERED")])
print(decision.model_dump_json(indent=2))
