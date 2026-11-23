#!/usr/bin/env python3
"""One-question-at-a-time variant generator for fill-in answers.

The batched generator trips the free tier's rate limit and its multi-item JSON
sometimes comes back malformed, so this version asks for a single question at a
time and writes after every success.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANK = ROOT / "data" / "questions.json"
CFG = Path.home() / ".config/ged-tutor/opencode/opencode.json"
opts = json.loads(CFG.read_text())["provider"]["zenfree"]["options"]
URL = opts["baseURL"].rstrip("/") + "/chat/completions"
KEY = opts["apiKey"]

PROMPT = """GED answer: {ans}
Question: {prompt}

List 5 other correct ways to write that same answer (spacing, units, decimal,
with or without the variable name). JSON only, no prose:
{{"variants": ["...", "...", "...", "...", "..."]}}"""


def ask(prompt: str) -> list[str] | None:
    body = json.dumps({"model": "hy4-flash-free",
                       "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": 3000, "temperature": 0.2}).encode()
    for attempt in range(4):
        req = urllib.request.Request(URL, data=body, headers={
            "Authorization": f"Bearer {KEY}", "Content-Type": "application/json",
            "x-opencode-session": "agent-ged-fib", "User-Agent": "Mozilla/5.0 ged-fib"})
        try:
            raw = json.loads(urllib.request.urlopen(req, timeout=90).read())
            msg = raw["choices"][0]["message"]
            text = (msg.get("content") or "") + (msg.get("reasoning") or "")
        except Exception as exc:  # noqa: BLE001
            print("call failed:", exc, flush=True)
            time.sleep(15 + attempt * 10)
            continue
        m = re.search(r"\{[^{}]*\"variants\"[^{}]*\}", text, re.S)
        if not m:
            m = re.search(r"\{.*\}", text, re.S)
        if not m:
            continue
        try:
            vs = json.loads(m.group(0)).get("variants")
        except Exception:
            continue
        if isinstance(vs, list):
            clean = [str(v).strip() for v in vs if str(v).strip()][:5]
            if len(clean) >= 3:
                return clean
    return None


def extras(q: dict) -> list[str]:
    base = {str(q["answer"]).lower(), str(q["answer"]).replace(" ", "").lower()}
    return [a for a in (q.get("accept") or []) if a not in base]


def main() -> None:
    bank = json.loads(BANK.read_text())
    todo = [q for q in bank["questions"] if q["type"] == "fib" and len(extras(q)) < 5]
    print("todo", len(todo), flush=True)
    done = 0
    for q in todo:
        vs = ask(PROMPT.format(prompt=q["prompt"], ans=q["answer"]))
        if not vs:
            print("skip", q["id"], flush=True)
            continue
        base = {str(q["answer"]).strip().lower(), str(q["answer"]).replace(" ", "").lower()}
        q["accept"] = sorted(base | {v.lower() for v in vs})
        done += 1
        BANK.write_text(json.dumps(bank, separators=(",", ":"), ensure_ascii=False))
        print(f"{done}/{len(todo)}", flush=True)
        time.sleep(3)
    print("done", done, flush=True)


if __name__ == "__main__":
    main()
