#!/usr/bin/env python3
"""Smoke test: server, grading, MCP tools, tutor round-trip.

  python3 tools/smoke.py            # everything except the live tutor
  python3 tools/smoke.py --tutor    # also queue one request and wait for Jarvis
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8765"
fails: list[str] = []


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read())


def post(path: str, body: dict):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("ok   " if cond else "FAIL ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def mcp_call(tool: str, args: dict) -> dict:
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool, "arguments": args}},
    ]
    out = subprocess.run([sys.executable, str(ROOT / "mcp/ged_mcp.py")],
                         input="\n".join(json.dumps(x) for x in lines) + "\n",
                         capture_output=True, text=True, timeout=60).stdout.strip().splitlines()
    return json.loads(out[-1])["result"]["content"][0]["text"]


def main() -> None:
    stats = get("/api/stats")
    check("bank loaded", stats["total"] >= 300, str(stats))
    for subj in ("math", "science", "rla", "social_studies"):
        check(f"{subj} has questions", stats["by_subject"].get(subj, 0) >= 20, str(stats["by_subject"]))

    bank = get("/api/questions?subject=science")
    mcq = next(q for q in bank["questions"] if q["type"] == "mcq")
    check("mcq right answer accepted", post("/api/answer", {"id": mcq["id"], "answer": mcq["answer"]})["correct"] is True)
    check("mcq wrong answer rejected", post("/api/answer", {"id": mcq["id"], "answer": "Z"})["correct"] is False)
    check("passage sets exist", any(q.get("passage") for q in bank["questions"]))
    check("images attached", any(q.get("image") for q in bank["questions"]))

    math = get("/api/questions?subject=math")["questions"]
    fib = next(q for q in math if q["type"] == "fib")
    check("fib answer accepted", post("/api/answer", {"id": fib["id"], "answer": fib["answer"]})["correct"] is True)

    check("fib ignores stray spaces", post("/api/answer", {"id": fib["id"], "answer": " " + fib["answer"] + " "})["correct"] is True)
    notes = [q for q in bank["questions"] if q.get("option_notes")]
    print(f"     option notes present on {len(notes)} mcq")
    variants = [q for q in get("/api/questions")["questions"] if q.get("variant")]
    print(f"     variants due now: {len(variants)}")

    check("mcp stats", '"total"' in mcp_call("stats", {}))
    check("mcp get_question", mcq["id"] in mcp_call("get_question", {"id": mcq["id"]}))
    check("mcp pending_requests", isinstance(json.loads(mcp_call("pending_requests", {})), list))

    if "--tutor" in sys.argv:
        rid = post("/api/help", {"id": mcq["id"], "kind": "hint", "answer": mcq["answer"],
                                 "text": "smoke test: give me a one-line hint"})["request_id"]
        print("queued", rid, "— waiting for Jarvis…")
        for _ in range(40):
            r = get(f"/api/help/{rid}")
            if r["status"] == "done":
                check("tutor replied", bool(r["reply"]), r["reply"][:120])
                print("reply:", r["reply"][:300])
                break
            if r["status"] == "timeout":
                check("tutor replied", False, "timeout")
                break
            time.sleep(3)

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
