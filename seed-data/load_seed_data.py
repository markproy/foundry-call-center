#!/usr/bin/env python3
"""Loads seed-data/fixtures/*.json into the Cosmos DB containers created by
infra/tools.bicep. Idempotent (upsert by id + partition key).

    COSMOS_ENDPOINT=https://<account>.documents.azure.com:443/ python seed-data/load_seed_data.py

Requires the Cosmos DB data-plane role (granted to the deploying principal by
the Bicep template) and `az login`.
"""
import datetime
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "tools"))

from callcenter_tools.repo import CONTAINERS, CosmosRepo  # noqa: E402

FIXTURES_DIR = ROOT / "fixtures"

# Fixtures hold absolute dates, but the scenarios are relative to "now" (upcoming
# appointments, open appeal windows, refills that are or are not yet eligible).
# Forward-looking fields are therefore re-dated at load time: days from today,
# negative = in the past. Re-run this loader to refresh them; the eval set uses
# the same offsets via {{today+N}} tokens (appeal deadline of MBR-DEMO-000106 is +10).
ID_FIELD = {"appointments": "appointment_id", "claims": "claim_id", "prescriptions": "prescription_id"}
RELATIVE_DATES = {
    "appointments": {  # scheduled_datetime (time of day is kept)
        "APT-DEMO-5001": 3, "APT-DEMO-5002": 4, "APT-DEMO-5003": 5,
        "APT-DEMO-5004": 6, "APT-DEMO-5005": 7, "APT-DEMO-5006": 8, "APT-DEMO-5007": 9,
        "APT-DEMO-5008": 14, "APT-DEMO-5009": 15,  # need a reschedule, still reschedulable
        "APT-DEMO-5010": 0,  # same-day: reschedule blocked by policy
    },
    "claims": {  # appeal_deadline
        "CLM-DEMO-10005": 10, "CLM-DEMO-10006": 25, "CLM-DEMO-10007": 15,
        "CLM-DEMO-10011": 42, "CLM-DEMO-10013": 42,
    },
    "prescriptions": {  # next_refill_eligible_date
        "RX-DEMO-50000": -15, "RX-DEMO-50001": 20, "RX-DEMO-50004": -19, "RX-DEMO-50005": -46,
        "RX-DEMO-50007": -10, "RX-DEMO-50008": 5, "RX-DEMO-50009": -12,
    },
}
DATE_FIELD = {"appointments": "scheduled_datetime", "claims": "appeal_deadline",
              "prescriptions": "next_refill_eligible_date"}


def redate(container: str, item: dict) -> dict:
    days = RELATIVE_DATES.get(container, {}).get(item.get(ID_FIELD.get(container, "")))
    if days is None:
        return item
    day = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
    field = DATE_FIELD[container]
    if container == "appointments":
        time_part = item[field].split("T", 1)[1]
        hour, rest = time_part.split(":", 1)
        item[field] = f"{day}T{int(hour):02d}:{rest}"
    else:
        item[field] = day
    return item


def main():
    repo = CosmosRepo(os.environ["COSMOS_ENDPOINT"])
    for container in CONTAINERS:
        items = json.loads((FIXTURES_DIR / f"{container}.json").read_text())
        for item in items:
            repo.upsert(container, redate(container, item))
        print(f"Loaded {len(items)} items into {container}")


if __name__ == "__main__":
    main()
