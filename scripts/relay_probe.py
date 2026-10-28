#!/usr/bin/env python3
"""Re-tests the agent-to-agent relay blocker (ADR-0006) against the deployed agents.

    python scripts/relay_probe.py [--project-endpoint URL] [--specialist claims-specialist]
                                  [--member MBR-DEMO-000101]

Uses your `az` login (no secrets). Two calls:
  1. CONTROL   you -> specialist directly with a user token. Must succeed, or the
               test is meaningless (agent down, no access).
  2. RELAY     you -> orchestrator, which makes the same call to the specialist from
               inside its own hosted-agent container with its managed identity
               (the orchestrator's `__relay_probe__` mode, see src/orchestrator/main.py).

Exit codes: 0 = relay works (the blocker is FIXED), 1 = still blocked, 2 = inconclusive.
After a Microsoft fix that needs new packages, bump them in each agent's pyproject.toml
and redeploy the orchestrator and the target specialist before running this.
"""
import argparse
import json
import subprocess
import sys

import httpx

DEFAULT_ENDPOINT = "https://cog-5gj265bjqzp7a.services.ai.azure.com/api/projects/foundry-call-center"


def token() -> str:
    out = subprocess.run(
        ["az", "account", "get-access-token", "--resource", "https://ai.azure.com", "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.exit(f"az login required: {out.stderr.strip()}")
    return out.stdout.strip()


def call(endpoint: str, agent: str, text: str, member: str) -> dict:
    url = f"{endpoint}/agents/{agent}/endpoint/protocols/openai/responses?api-version=v1"
    resp = httpx.post(
        url,
        json={"input": text, "stream": False, "metadata": {"member_id": member}},
        headers={"authorization": f"Bearer {token()}"},
        timeout=180,
    )
    try:
        body = resp.json()
    except ValueError:
        body = {}
    answer = "".join(
        c.get("text", "")
        for o in body.get("output", [])
        if o.get("type") == "message"
        for c in o.get("content", [])
    )
    return {"http": resp.status_code, "error": body.get("error"), "text": answer, "raw": resp.text[:300]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-endpoint", default=DEFAULT_ENDPOINT)
    ap.add_argument("--specialist", default="claims-specialist")
    ap.add_argument("--member", default="MBR-DEMO-000101")
    args = ap.parse_args()

    print(f"1. CONTROL: user token -> {args.specialist}")
    control = call(args.project_endpoint, args.specialist, "hello", args.member)
    if control["http"] != 200 or control["error"] or not control["text"]:
        print(f"   FAILED ({control['http']}): {control['error'] or control['raw']}")
        print("INCONCLUSIVE: the control call must work first.")
        return 2
    print(f"   ok: {control['text'][:80]!r}")

    print(f"2. RELAY: orchestrator (managed identity) -> {args.specialist}")
    relay = call(args.project_endpoint, "orchestrator", f"__relay_probe__ {args.specialist} {args.member}", args.member)
    try:
        result = json.loads(relay["text"])
    except ValueError:
        print(f"   unexpected orchestrator reply ({relay['http']}): {relay['text'] or relay['raw']}")
        print("INCONCLUSIVE: is the orchestrator redeployed with the probe mode?")
        return 2
    if result.get("probe") != "relay":
        print(f"   orchestrator returned a routing decision, not a probe result: {result}")
        print("INCONCLUSIVE: the deployed orchestrator predates the probe mode; redeploy it.")
        return 2
    if result["ok"]:
        print(f"   ok: {result['answer']!r}")
        print("RESULT: relay WORKS - the blocker looks FIXED. Revisit ADR-0006.")
        return 0
    print(f"   blocked (HTTP {result.get('http_status')}): {result.get('error')}")
    print("RESULT: relay still BLOCKED (control works, relay fails).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
