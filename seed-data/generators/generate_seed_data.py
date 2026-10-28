#!/usr/bin/env python3
"""Deterministic synthetic data generator for the agentic call center demo.

Produces members.json, claims.json, appointments.json, providers.json in
seed-data/fixtures/. Every record is tagged synthetic=true / data_source so
nothing here can be confused with real member data. Re-run any time to
regenerate fixtures from scratch (output is deterministic given SEED).
"""
import json
import random
from pathlib import Path

SEED = 20260904
DATA_SOURCE = "call-center-demo-synth-v1"
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

random.seed(SEED)

FIRST_NAMES = [
    "Alicia", "Marcus", "Priya", "Devon", "Sofia", "Wei", "Grace", "Omar",
    "Nadia", "Ethan", "Renata", "Kwame", "Ines", "Julian", "Farah", "Tobias",
    "Amara", "Leo", "Simone", "Hiro", "Delia", "Anders",
]
LAST_NAMES = [
    "Renner", "Okafor", "Deshmukh", "Marsh", "Alvarez", "Chen", "Whitfield",
    "Haddad", "Kessler", "Boone", "Ferreira", "Nakamura", "Voss", "Larkin",
    "Aziz", "Petrov", "Nwosu", "Byrne", "Kaur", "Solis",
]

SPECIALTIES = [
    "Internal Medicine", "Orthopedics", "Cardiology", "Dermatology",
    "Physical Therapy", "OB/GYN", "Behavioral Health", "Endocrinology",
]

PLANS = [
    ("PLAN-PPO-GOLD-01", "Gold PPO"),
    ("PLAN-HMO-SILVER-02", "Silver HMO"),
    ("PLAN-PPO-BRONZE-03", "Bronze PPO"),
]


def make_providers(n=9):
    providers = []
    for i in range(n):
        pid = f"PRV-DEMO-{2001 + i}"
        providers.append({
            "provider_id": pid,
            "synthetic": True,
            "data_source": DATA_SOURCE,
            "name": f"Dr. {random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}",
            "npi": f"99999{i:05d}",
            "specialty": SPECIALTIES[i % len(SPECIALTIES)],
            "network_status": "OUT_OF_NETWORK" if i == 4 else "IN_NETWORK",
            "accepting_new_patients": i % 3 != 0,
            "locations": [{
                "name": f"{random.choice(['Riverside', 'Lakeview', 'Cedar Hill', 'Harborview', 'Midtown'])} Medical Plaza",
                "address": f"{100 + i * 7} Demo Ave, Springfield, ST 5{i:04d}",
            }],
        })
    return providers


def new_member(idx, first, last, plan, status="ACTIVE", pcp=None):
    dob_year = 1955 + (idx * 7) % 55
    dob_month = 1 + (idx * 3) % 12
    dob_day = 1 + (idx * 5) % 28
    mid = f"MBR-DEMO-{100 + idx:06d}"
    return {
        "member_id": mid,
        "synthetic": True,
        "data_source": DATA_SOURCE,
        "first_name": first,
        "last_name": last,
        "dob": f"{dob_year:04d}-{dob_month:02d}-{dob_day:02d}",
        "plan_id": plan[0],
        "plan_name": plan[1],
        "enrollment_status": status,
        "pcp_provider_id": pcp,
        "contact": {
            "phone": f"555-01{idx:02d}-0{idx:03d}",
            "email": f"{first.lower()}.demo{idx}@example-demo.test",
        },
    }


def main():
    providers = make_providers()
    provider_ids = [p["provider_id"] for p in providers]

    members = []
    claims = []
    appointments = []

    def pid(i):
        return provider_ids[i % len(provider_ids)]

    idx = 1
    scenario_notes = {}

    def add_member(status="ACTIVE"):
        nonlocal idx
        first = FIRST_NAMES[(idx - 1) % len(FIRST_NAMES)]
        last = LAST_NAMES[(idx - 1) % len(LAST_NAMES)]
        plan = PLANS[(idx - 1) % len(PLANS)]
        m = new_member(idx, first, last, plan, status=status, pcp=pid(idx))
        members.append(m)
        idx += 1
        return m

    # --- 5 members: clean paid claim (first 3 also get an upcoming appointment for cross-domain overlap) ---
    for i in range(5):
        m = add_member()
        claims.append({
            "claim_id": f"CLM-DEMO-{10000 + len(claims)}",
            "synthetic": True, "data_source": DATA_SOURCE,
            "member_id": m["member_id"], "provider_id": m["pcp_provider_id"],
            "date_of_service": f"2026-0{2 + i % 6}-1{i}",
            "status": "PAID",
            "denial_reason_code": None, "denial_reason_text": None,
            "billed_amount": 220.0 + i * 15, "allowed_amount": 180.0 + i * 12,
            "member_responsibility": 25.0 + i * 3,
            "service_description": random.choice(["Annual wellness visit", "Follow-up consultation", "Lab panel", "Physical therapy session"]),
            "appeal_deadline": None, "appeal_status": None,
        })
        if i < 3:
            appointments.append({
                "appointment_id": f"APT-DEMO-{5001 + len(appointments)}",
                "synthetic": True, "data_source": DATA_SOURCE,
                "member_id": m["member_id"], "provider_id": m["pcp_provider_id"],
                "scheduled_datetime": f"2026-10-{10 + i:02d}T{9 + i}:00:00-04:00",
                "type": "Follow-up", "modality": "in_person", "status": "SCHEDULED",
                "location": next(p for p in providers if p["provider_id"] == m["pcp_provider_id"])["locations"][0]["name"],
                "reschedule_eligible": True, "reschedule_notes": None,
            })
    scenario_notes["clean_paid_claim"] = [m["member_id"] for m in members[-5:]]

    # --- 3 members: denied claim needing appeal (varied reasons) ---
    denial_reasons = [
        ("CO-197", "Precertification/authorization absent", "2026-09-30"),
        ("CO-B7", "Provider not certified/eligible to bill for this service (out-of-network)", "2026-10-15"),
        ("CO-96", "Non-covered charge under member's current plan", "2026-10-05"),
    ]
    for reason_code, reason_text, deadline in denial_reasons:
        m = add_member()
        claims.append({
            "claim_id": f"CLM-DEMO-{10000 + len(claims)}",
            "synthetic": True, "data_source": DATA_SOURCE,
            "member_id": m["member_id"], "provider_id": m["pcp_provider_id"],
            "date_of_service": "2026-06-02",
            "status": "DENIED",
            "denial_reason_code": reason_code, "denial_reason_text": reason_text,
            "billed_amount": 480.0, "allowed_amount": 0.0, "member_responsibility": 480.0,
            "service_description": "Specialist consultation",
            "appeal_deadline": deadline, "appeal_status": "NOT_FILED",
        })
    scenario_notes["denied_needs_appeal"] = [m["member_id"] for m in members[-3:]]

    # --- 2 members: claim in review ---
    for i in range(2):
        m = add_member()
        claims.append({
            "claim_id": f"CLM-DEMO-{10000 + len(claims)}",
            "synthetic": True, "data_source": DATA_SOURCE,
            "member_id": m["member_id"], "provider_id": m["pcp_provider_id"],
            "date_of_service": "2026-08-20",
            "status": "IN_REVIEW",
            "denial_reason_code": None, "denial_reason_text": None,
            "billed_amount": 610.0, "allowed_amount": None, "member_responsibility": None,
            "service_description": "Outpatient procedure",
            "appeal_deadline": None, "appeal_status": None,
        })
    scenario_notes["in_review"] = [m["member_id"] for m in members[-2:]]

    # --- 2 members: multiple claims, mixed statuses (forces clarification) ---
    for i in range(2):
        m = add_member()
        base = len(claims)
        claims.append({
            "claim_id": f"CLM-DEMO-{10000 + base}", "synthetic": True, "data_source": DATA_SOURCE,
            "member_id": m["member_id"], "provider_id": m["pcp_provider_id"],
            "date_of_service": "2026-05-10", "status": "PAID",
            "denial_reason_code": None, "denial_reason_text": None,
            "billed_amount": 150.0, "allowed_amount": 120.0, "member_responsibility": 15.0,
            "service_description": "Office visit", "appeal_deadline": None, "appeal_status": None,
        })
        claims.append({
            "claim_id": f"CLM-DEMO-{10001 + base}", "synthetic": True, "data_source": DATA_SOURCE,
            "member_id": m["member_id"], "provider_id": m["pcp_provider_id"],
            "date_of_service": "2026-07-22", "status": "DENIED",
            "denial_reason_code": "CO-96", "denial_reason_text": "Non-covered charge under member's current plan",
            "billed_amount": 340.0, "allowed_amount": 0.0, "member_responsibility": 340.0,
            "service_description": "Imaging (MRI)", "appeal_deadline": "2026-11-01", "appeal_status": "NOT_FILED",
        })
    scenario_notes["multiple_claims_mixed"] = [m["member_id"] for m in members[-2:]]

    # --- 4 members: upcoming appointment (straightforward) ---
    for i in range(4):
        m = add_member()
        appointments.append({
            "appointment_id": f"APT-DEMO-{5001 + len(appointments)}",
            "synthetic": True, "data_source": DATA_SOURCE,
            "member_id": m["member_id"], "provider_id": m["pcp_provider_id"],
            "scheduled_datetime": f"2026-10-{15 + i:02d}T{10 + i}:30:00-04:00",
            "type": random.choice(["Annual physical", "Follow-up", "New patient visit"]),
            "modality": "telehealth" if i % 2 == 0 else "in_person", "status": "SCHEDULED",
            "location": next(p for p in providers if p["provider_id"] == m["pcp_provider_id"])["locations"][0]["name"],
            "reschedule_eligible": True, "reschedule_notes": None,
        })
    scenario_notes["upcoming_appointment"] = [m["member_id"] for m in members[-4:]]

    # --- 3 members: appointment needing reschedule (one same-day policy violation) ---
    for i in range(3):
        m = add_member()
        same_day = (i == 2)
        appointments.append({
            "appointment_id": f"APT-DEMO-{5001 + len(appointments)}",
            "synthetic": True, "data_source": DATA_SOURCE,
            "member_id": m["member_id"], "provider_id": m["pcp_provider_id"],
            "scheduled_datetime": "2026-09-04T15:00:00-04:00" if same_day else f"2026-09-{20 + i:02d}T13:00:00-04:00",
            "type": "Follow-up", "modality": "in_person", "status": "SCHEDULED",
            "location": next(p for p in providers if p["provider_id"] == m["pcp_provider_id"])["locations"][0]["name"],
            "reschedule_eligible": not same_day,
            "reschedule_notes": (
                "Same-day reschedule requests are not eligible per scheduling policy; member must call the office directly."
                if same_day else None
            ),
        })
    scenario_notes["needs_reschedule"] = [m["member_id"] for m in members[-3:]]

    # --- 2 members: no upcoming appointments ---
    for i in range(2):
        add_member()
    scenario_notes["no_upcoming_appointments"] = [m["member_id"] for m in members[-2:]]

    # --- 1 member: lapsed enrollment ---
    m = add_member(status="LAPSED")
    scenario_notes["lapsed_enrollment"] = [m["member_id"]]

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    (FIXTURES_DIR / "providers.json").write_text(json.dumps(providers, indent=2) + "\n")
    (FIXTURES_DIR / "members.json").write_text(json.dumps(members, indent=2) + "\n")
    (FIXTURES_DIR / "claims.json").write_text(json.dumps(claims, indent=2) + "\n")
    (FIXTURES_DIR / "appointments.json").write_text(json.dumps(appointments, indent=2) + "\n")
    (FIXTURES_DIR / "scenario_index.json").write_text(json.dumps(scenario_notes, indent=2) + "\n")

    print(f"Generated {len(members)} members, {len(claims)} claims, "
          f"{len(appointments)} appointments, {len(providers)} providers.")
    print(f"Scenario index written to {FIXTURES_DIR / 'scenario_index.json'}")


if __name__ == "__main__":
    main()
