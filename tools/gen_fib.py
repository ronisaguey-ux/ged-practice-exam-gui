#!/usr/bin/env python3
"""Generate five accepted variants for every fill-in-the-blank answer.

A variant is another spelling or equivalent form a correct student might type:
`0.8 g/mL` also accepts `0.8`, `0.8 g/ml`; `x = 11` also accepts `11`.
Writes `accept` (canonical + variants) onto each fib question.
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

PROMPT = """A GED fill-in-the-blank question has this answer key:

Question: {prompt}
Canonical answer: {ans}
Worked solution: {work}

Give exactly 5 other ways a correct student might type the same answer: different
units, spacing, fractions vs decimals, with or without a variable name, with or
without a dollar sign. They must all be CORRECT answers, never different values.

Reply JSON only: {{"variants": ["...", "...", "...", "...", "..."]}}"""


def call(prompt: str) -> list[str] | None:
    body = json.dumps({"model": "hy4-flash-free",
                       "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": 500, "temperature": 0.2}).encode()
    for _ in range(2):
        req = urllib.request.Request(URL, data=body, headers={
            "Authorization": f"Bearer {KEY}", "Content-Type": "application/json",
            "x-opencode-session": "agent-ged-notes", "User-Agent": "Mozilla/5.0 ged-notes"})
        try:
            text = json.loads(urllib.request.urlopen(req, timeout=90).read())["choices"][0]["message"]
            text = (text.get("content") or "") + (text.get("reasoning") or "")
        except Exception as exc:  # noqa: BLE001
            print("call failed:", exc, file=sys.stderr)
            if "429" in str(exc):
                time.sleep(25)
            continue
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            continue
        try:
            vs = json.loads(m.group(0))["variants"]
        except Exception:
            continue
        vs = [str(v).strip() for v in vs if str(v).strip()][:5]
        if len(vs) >= 3:
            return vs
    return None


def main() -> None:
    bank = json.loads(BANK.read_text())
    fib = [q for q in bank["questions"] if q["type"] == "fib"]
    todo = [q for q in fib if len(q.get("accept") or []) < 6]
    print(f"{len(fib)} fib, {len(todo)} need variants", flush=True)
    done = 0
    for q in todo:
        vs = call(PROMPT.format(prompt=q["prompt"], ans=q["answer"],
                                work=q.get("explanation", "")[:300]))
        if not vs:
            print("skip", q["id"], flush=True)
            continue
        base = {str(q["answer"]).strip().lower(), str(q["answer"]).replace(" ", "").lower()}
        q["accept"] = sorted(base | {v.lower() for v in vs})
        done += 1
        if done % 5 == 0:
            BANK.write_text(json.dumps(bank, separators=(",", ":"), ensure_ascii=False))
            print(f"{done}/{len(todo)}", flush=True)
        time.sleep(1.4)
    BANK.write_text(json.dumps(bank, separators=(",", ":"), ensure_ascii=False))
    print("done", done, flush=True)


if __name__ == "__main__":
    main()
