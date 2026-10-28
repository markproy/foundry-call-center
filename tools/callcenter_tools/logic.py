"""Tool actions for the simulated enterprise systems.

Contract: the caller sends
{"auth": {"member_id": ...}, "params": {...}}. The member is taken only from
`auth`, which the specialist binds from the session before the model runs;
`params` is whatever the model chose and is never trusted for identity.
"""
from __future__ import annotations

import datetime
from typing import Callable, Dict, Optional, Tuple

from .repo import Repo


def _not_found(kind: str, item_id: str) -> dict:
    # Same answer for "missing" and "not yours" so ids can't be enumerated.
    return {"found": False, "message": f"No {kind} found with id {item_id}"}


def get_claim_status(repo: Repo, params: dict, member_id: str) -> dict:
    item = repo.get("claims", params["claim_id"], member_id)
    if not item:
        return _not_found("claim", params["claim_id"])
    return {"found": True, "claim": item}


def search_claims_by_member(repo: Repo, params: dict, member_id: str) -> dict:
    items = repo.query_by_member("claims", member_id)
    return {"count": len(items), "claims": items}


def get_appeal_info(repo: Repo, params: dict, member_id: str) -> dict:
    claim_id = params["claim_id"]
    item = repo.get("claims", claim_id, member_id)
    if not item:
        return _not_found("claim", claim_id)
    if item.get("status") != "DENIED":
        return {
            "found": True,
            "appeal_eligible": False,
            "message": "This claim was not denied, so there is nothing to appeal.",
        }
    return {
        "found": True,
        "appeal_eligible": True,
        "claim_id": claim_id,
        "denial_reason_code": item.get("denial_reason_code"),
        "denial_reason_text": item.get("denial_reason_text"),
        "appeal_deadline": item.get("appeal_deadline"),
        "appeal_status": item.get("appeal_status"),
    }


def check_eligibility(repo: Repo, params: dict, member_id: str) -> dict:
    item = repo.get("members", member_id, member_id)
    if not item:
        return {"found": False, "message": f"No member found with id {member_id}"}
    return {
        "found": True,
        "member_id": member_id,
        "enrollment_status": item.get("enrollment_status"),
        "plan_id": item.get("plan_id"),
        "plan_name": item.get("plan_name"),
        "eligible": item.get("enrollment_status") == "ACTIVE",
    }


def get_provider_info(repo: Repo, params: dict, member_id: Optional[str]) -> dict:
    # Directory data, identical for every member: not member-scoped.
    provider_id = params["provider_id"]
    item = repo.get("providers", provider_id, provider_id)
    if not item:
        return _not_found("provider", provider_id)
    return {"found": True, "provider": item}


def lookup_patient(repo: Repo, params: dict, member_id: str) -> dict:
    item = repo.get("members", member_id, member_id)
    if not item:
        return {"found": False, "message": f"No member found with id {member_id}"}
    dob = params.get("dob")
    if dob and item.get("dob") != dob:
        return {"found": False, "message": "Member ID and date of birth do not match our records."}
    return {
        "found": True,
        "member_id": member_id,
        "first_name": item.get("first_name"),
        "last_name": item.get("last_name"),
        "enrollment_status": item.get("enrollment_status"),
        "pcp_provider_id": item.get("pcp_provider_id"),
    }


def get_upcoming_appointments(repo: Repo, params: dict, member_id: str) -> dict:
    items = [i for i in repo.query_by_member("appointments", member_id) if i.get("status") == "SCHEDULED"]
    if not items:
        return {
            "count": 0,
            "appointments": [],
            "message": "This member has no upcoming scheduled appointments. "
            "Booking a brand-new appointment isn't supported by this "
            "tool — the member should call their provider's office directly.",
        }
    return {"count": len(items), "appointments": items}


def reschedule_appointment(repo: Repo, params: dict, member_id: str) -> dict:
    appointment_id = params["appointment_id"]
    new_datetime = params.get("new_datetime")
    item = repo.get("appointments", appointment_id, member_id)
    if not item:
        return _not_found("appointment", appointment_id)
    if not item.get("reschedule_eligible", True):
        return {
            "found": True,
            "rescheduled": False,
            "reason": item.get("reschedule_notes")
            or "This appointment is not eligible for self-service rescheduling per policy.",
        }
    item["scheduled_datetime"] = new_datetime
    repo.upsert("appointments", item)
    return {"found": True, "rescheduled": True, "appointment_id": appointment_id, "new_datetime": new_datetime}


def get_prescription_status(repo: Repo, params: dict, member_id: str) -> dict:
    item = repo.get("prescriptions", params["prescription_id"], member_id)
    if not item:
        return _not_found("prescription", params["prescription_id"])
    return {"found": True, "prescription": item}


def search_prescriptions_by_member(repo: Repo, params: dict, member_id: str) -> dict:
    items = repo.query_by_member("prescriptions", member_id)
    return {"count": len(items), "prescriptions": items}


def request_refill(repo: Repo, params: dict, member_id: str, today: Optional[str] = None) -> dict:
    """Refill rule from kb-documents/pharmacy/refill-policy-faq.md: refills
    remaining > 0 and today >= next_refill_eligible_date. Both come from the
    record, never from the model's general knowledge."""
    prescription_id = params["prescription_id"]
    item = repo.get("prescriptions", prescription_id, member_id)
    if not item:
        return _not_found("prescription", prescription_id)
    if item.get("status") == "PENDING_PRIOR_AUTH":
        return {
            "found": True,
            "refill_approved": False,
            "reason": "This prescription is still awaiting prior authorization and cannot be filled yet.",
        }
    if item.get("status") == "PRIOR_AUTH_DENIED":
        return {
            "found": True,
            "refill_approved": False,
            "reason": "Prior authorization for this prescription was denied, so it cannot be filled without a new authorization decision.",
        }
    refills_remaining = int(item.get("refills_remaining", 0))
    if refills_remaining <= 0:
        return {
            "found": True,
            "refill_approved": False,
            "reason": "No refills remain on file. The prescribing provider needs to send a new prescription before this can be filled again.",
        }
    next_eligible = item.get("next_refill_eligible_date")
    today = today or datetime.date.today().isoformat()
    if next_eligible and today < next_eligible:
        return {
            "found": True,
            "refill_approved": False,
            "reason": f"This prescription isn't eligible for refill until {next_eligible}. An earlier refill needs pharmacy review.",
            "next_refill_eligible_date": next_eligible,
        }
    return {
        "found": True,
        "refill_approved": True,
        "prescription_id": prescription_id,
        "drug_name": item.get("drug_name"),
        "refills_remaining_after": refills_remaining - 1,
        "pharmacy_name": item.get("pharmacy_name"),
        "pharmacy_phone": item.get("pharmacy_phone"),
    }


def check_prior_authorization(repo: Repo, params: dict, member_id: str) -> dict:
    prescription_id = params["prescription_id"]
    item = repo.get("prescriptions", prescription_id, member_id)
    if not item:
        return _not_found("prescription", prescription_id)
    if not item.get("prior_authorization_required"):
        return {
            "found": True,
            "prior_authorization_required": False,
            "message": "This medication does not require prior authorization.",
        }
    return {
        "found": True,
        "prior_authorization_required": True,
        "prior_authorization_status": item.get("prior_authorization_status"),
        "drug_name": item.get("drug_name"),
    }


ACTIONS: Dict[str, Callable[..., dict]] = {
    "get_claim_status": get_claim_status,
    "search_claims_by_member": search_claims_by_member,
    "get_appeal_info": get_appeal_info,
    "check_eligibility": check_eligibility,
    "get_provider_info": get_provider_info,
    "lookup_patient": lookup_patient,
    "get_upcoming_appointments": get_upcoming_appointments,
    "reschedule_appointment": reschedule_appointment,
    "get_prescription_status": get_prescription_status,
    "search_prescriptions_by_member": search_prescriptions_by_member,
    "request_refill": request_refill,
    "check_prior_authorization": check_prior_authorization,
}

# Everything except provider directory data requires an authenticated member.
NOT_MEMBER_SCOPED = {"get_provider_info"}


def dispatch(repo: Repo, action: str, body: dict) -> Tuple[int, dict]:
    if action not in ACTIONS:
        return 400, {"error": f"Unknown or missing action: {action!r}"}
    member_id = (body.get("auth") or {}).get("member_id")
    if not member_id and action not in NOT_MEMBER_SCOPED:
        return 401, {"error": "Missing authenticated member_id in the request's auth envelope"}
    params = body.get("params") or {}
    try:
        return 200, ACTIONS[action](repo, params, member_id)
    except KeyError as e:
        return 400, {"error": f"Missing required parameter: {e.args[0]}"}
