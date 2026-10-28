"""Replays eval/eval_set.yaml against the deployed chat backend and gates on pass rate.

    python eval/run_eval.py --url https://<chat-app> [--threshold 0.9] [--workers 4]

Checks per turn: intent (a guardrail block counts as out_of_scope), answer
contains / excludes (case-insensitive; a nested list means any-of), and, where
`expected_citation_required` is set, that the specialist called
`search_knowledge_base`. Writes eval/results/<timestamp>.json and exits 1 when
the pass rate is below the threshold.
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).parent


def substitute_dates(text: str) -> str:
    """Replaces {{today+N}} with an ISO date; offsets match seed-data/load_seed_data.py."""
    def day(m: re.Match) -> str:
        return (datetime.date.today() + datetime.timedelta(days=int(m.group(1)))).isoformat()
    return re.sub(r"\{\{today\+(\d+)\}\}", day, text)


def load_items(path: Path) -> list[dict]:
    """Flattens cases and conversations into sessions: a list of turn dicts each."""
    data = yaml.safe_load(substitute_dates(path.read_text()))
    sessions = []
    for c in data.get("cases", []):
        sessions.append({"id": c["id"], "member_id": c["member_id"], "turns": [{**c, "id": c["id"]}]})
    for conv in data.get("conversations", []):
        turns = [{**t, "id": f"{conv['id']}-t{i + 1}"} for i, t in enumerate(conv["turns"])]
        sessions.append({"id": conv["id"], "member_id": conv["member_id"], "turns": turns})
    return sessions


def chat(client: httpx.Client, url: str, member_id: str, messages: list[dict], secret: str) -> dict:
    text, done = [], {}
    headers = {"x-demo-secret": secret} if secret else {}
    with client.stream("POST", f"{url}/api/chat", json={"member_id": member_id, "messages": messages},
                       headers=headers) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line.startswith("data:"):
                continue
            ev = json.loads(line[5:])
            if ev["type"] == "text_delta":
                text.append(ev["text"])
            elif ev["type"] == "replace":
                text = [ev["text"]]
            elif ev["type"] == "done":
                done = ev
            elif ev["type"] == "error":
                raise RuntimeError(ev["error"])
    return {"text": "".join(text), **done}


def _has(answer: str, want) -> bool:
    if isinstance(want, list):
        return any(_has(answer, w) for w in want)
    return str(want).lower() in answer.lower()


def score(turn: dict, got: dict) -> list[str]:
    fails = []
    expected = turn.get("expected_intent")
    actual = got.get("intent")
    if expected and actual != expected and not (expected == "out_of_scope" and actual == "blocked"):
        fails.append(f"intent: expected {expected}, got {actual}")
    answer = got.get("text", "")
    for want in turn.get("expected_answer_contains", []):
        if not _has(answer, want):
            fails.append(f"missing: {want}")
    for bad in turn.get("expected_answer_excludes", []):
        if _has(answer, bad):
            fails.append(f"leaked: {bad}")
    if turn.get("expected_citation_required") and "search_knowledge_base" not in got.get("tools", []):
        fails.append("no knowledge-base lookup")
    return fails


def run_session(url: str, secret: str, session: dict) -> list[dict]:
    results, messages = [], []
    with httpx.Client(timeout=httpx.Timeout(180, connect=15)) as client:
        for turn in session["turns"]:
            messages.append({"role": "user", "content": turn["message"]})
            try:
                got = chat(client, url, session["member_id"], messages, secret)
            except Exception as exc:  # noqa: BLE001
                results.append({"id": turn["id"], "message": turn["message"], "passed": False,
                                "failures": [f"error: {exc!r}"]})
                break
            fails = score(turn, got)
            results.append({"id": turn["id"], "message": turn["message"], "passed": not fails, "failures": fails,
                            "member_id": session["member_id"], "expected_intent": turn.get("expected_intent"),
                            "intent": got.get("intent"), "tools": got.get("tools"), "total_ms": got.get("total_ms"),
                            "answer": got["text"]})
            messages.append({"role": "assistant", "content": got["text"]})
    return results


def upload(doc: dict) -> None:
    """Stores the run in Cosmos for the admin dashboard when COSMOS_ENDPOINT is set."""
    endpoint = os.environ.get("COSMOS_ENDPOINT")
    if not endpoint:
        return
    try:
        from azure.cosmos import CosmosClient
        from azure.identity import DefaultAzureCredential

        client = CosmosClient(endpoint, credential=DefaultAzureCredential())
        client.get_database_client("callcenter").get_container_client("evalruns").upsert_item(doc)
        print(f"uploaded run {doc['id']} to Cosmos")
    except Exception as exc:  # noqa: BLE001
        print(f"warning: could not upload run to Cosmos: {exc!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("CHAT_URL"), required=not os.environ.get("CHAT_URL"))
    ap.add_argument("--threshold", type=float, default=0.9)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--eval-set", default=str(HERE / "eval_set.yaml"))
    args = ap.parse_args()
    secret = os.environ.get("DEMO_SHARED_SECRET", "")
    sessions = load_items(Path(args.eval_set))
    # The backend reuses one agent session per member and a session handles one
    # request at a time, so a member's cases run in order; members run in parallel.
    by_member: dict[str, list[dict]] = {}
    for s in sessions:
        by_member.setdefault(s["member_id"], []).append(s)

    def run_member(group: list[dict]) -> list[dict]:
        return [r for s in group for r in run_session(args.url.rstrip("/"), secret, s)]

    with ThreadPoolExecutor(args.workers) as pool:
        results = [r for rs in pool.map(run_member, by_member.values()) for r in rs]
    passed = sum(r["passed"] for r in results)
    rate = passed / len(results)
    for r in results:
        if not r["passed"]:
            print(f"FAIL {r['id']}: {r['message']!r}\n     " + "; ".join(r["failures"]))
    print(f"\n{passed}/{len(results)} passed ({rate:.0%}), threshold {args.threshold:.0%}")
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    run_id = time.strftime("%Y%m%d-%H%M%S")
    doc = {"id": run_id, "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
           "chat_url": args.url, "pass_rate": rate, "threshold": args.threshold,
           "total": len(results), "passed": passed, "results": results}
    (out / f"{run_id}.json").write_text(json.dumps(doc, indent=2))
    upload(doc)
    return 0 if rate >= args.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
