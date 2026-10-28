import json
from pathlib import Path

import pytest

from callcenter_tools.logic import dispatch
from callcenter_tools.repo import InMemoryRepo

FIXTURES = Path(__file__).resolve().parents[2] / "seed-data" / "fixtures"


@pytest.fixture()
def repo():
    names = ["members", "providers", "claims", "appointments", "prescriptions"]
    return InMemoryRepo({n: json.loads((FIXTURES / f"{n}.json").read_text()) for n in names})


def call(repo, action, member_id, **params):
    body = {"params": params}
    if member_id:
        body["auth"] = {"member_id": member_id}
    return dispatch(repo, action, body)


def pick(repo, container, **match):
    for item in repo._data[container]:
        if all(item.get(k) == v for k, v in match.items()):
            return item
    pytest.skip(f"no {container} fixture matching {match}")


def other_member(repo, member_id):
    return next(m["member_id"] for m in repo._data["members"] if m["member_id"] != member_id)


def test_unknown_action(repo):
    assert call(repo, "nope", "M1")[0] == 400


def test_member_scoped_action_requires_auth(repo):
    assert call(repo, "search_claims_by_member", None)[0] == 401


def test_provider_info_needs_no_member(repo):
    provider = repo._data["providers"][0]
    status, out = call(repo, "get_provider_info", None, provider_id=provider["provider_id"])
    assert status == 200 and out["found"]


def test_missing_param_is_400(repo):
    assert call(repo, "get_claim_status", "M1")[0] == 400


def test_claim_owner_can_read(repo):
    claim = repo._data["claims"][0]
    status, out = call(repo, "get_claim_status", claim["member_id"], claim_id=claim["claim_id"])
    assert status == 200 and out["found"] and out["claim"]["claim_id"] == claim["claim_id"]


def test_other_members_claim_looks_nonexistent(repo):
    claim = repo._data["claims"][0]
    intruder = other_member(repo, claim["member_id"])
    _, stolen = call(repo, "get_claim_status", intruder, claim_id=claim["claim_id"])
    _, missing = call(repo, "get_claim_status", intruder, claim_id="CLM-DOES-NOT-EXIST")
    assert stolen["found"] is False
    assert stolen["message"].split(" with id")[0] == missing["message"].split(" with id")[0]


def test_search_returns_only_own_claims(repo):
    claim = repo._data["claims"][0]
    _, out = call(repo, "search_claims_by_member", claim["member_id"])
    assert out["count"] >= 1 and all(c["member_id"] == claim["member_id"] for c in out["claims"])


def test_appeal_only_for_denied(repo):
    denied = pick(repo, "claims", status="DENIED")
    _, out = call(repo, "get_appeal_info", denied["member_id"], claim_id=denied["claim_id"])
    assert out["appeal_eligible"] is True and out["appeal_deadline"] == denied["appeal_deadline"]
    other = next(c for c in repo._data["claims"] if c["status"] != "DENIED")
    _, out = call(repo, "get_appeal_info", other["member_id"], claim_id=other["claim_id"])
    assert out["appeal_eligible"] is False


def test_lookup_patient_dob_mismatch(repo):
    m = repo._data["members"][0]
    _, ok = call(repo, "lookup_patient", m["member_id"], dob=m["dob"])
    _, bad = call(repo, "lookup_patient", m["member_id"], dob="1900-01-01")
    assert ok["found"] and not bad["found"]


def test_reschedule_respects_eligibility_and_ownership(repo):
    eligible = pick(repo, "appointments", reschedule_eligible=True)
    intruder = other_member(repo, eligible["member_id"])
    _, out = call(repo, "reschedule_appointment", intruder, appointment_id=eligible["appointment_id"], new_datetime="2030-01-01T09:00:00")
    assert out["found"] is False
    _, out = call(repo, "reschedule_appointment", eligible["member_id"], appointment_id=eligible["appointment_id"], new_datetime="2030-01-01T09:00:00")
    assert out["rescheduled"] is True
    assert repo.get("appointments", eligible["appointment_id"], eligible["member_id"])["scheduled_datetime"] == "2030-01-01T09:00:00"

    locked = pick(repo, "appointments", reschedule_eligible=False)
    _, out = call(repo, "reschedule_appointment", locked["member_id"], appointment_id=locked["appointment_id"], new_datetime="2030-01-01T09:00:00")
    assert out["rescheduled"] is False


def test_refill_rules(repo):
    from callcenter_tools.logic import request_refill

    rx = pick(repo, "prescriptions", status="ACTIVE")
    rx["refills_remaining"] = 0
    repo.upsert("prescriptions", rx)
    assert request_refill(repo, {"prescription_id": rx["prescription_id"]}, rx["member_id"])["refill_approved"] is False

    rx["refills_remaining"] = 2
    rx["next_refill_eligible_date"] = "2030-06-01"
    repo.upsert("prescriptions", rx)
    early = request_refill(repo, {"prescription_id": rx["prescription_id"]}, rx["member_id"], today="2030-05-31")
    ok = request_refill(repo, {"prescription_id": rx["prescription_id"]}, rx["member_id"], today="2030-06-01")
    assert early["refill_approved"] is False and ok["refill_approved"] is True
    assert ok["refills_remaining_after"] == 1
