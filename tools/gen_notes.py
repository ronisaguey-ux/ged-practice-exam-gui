#!/usr/bin/env python3
"""Generate a 10-30 word note for every multiple-choice option.

Uses the free HY4 model through the same endpoint the tutor uses. Writes
`option_notes` onto each mcq in data/questions.json. Idempotent: questions that
already have four notes are skipped.
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

cfg = json.loads(CFG.read_text())
opts = cfg["provider"]["zenfree"]["options"]
URL = opts["baseURL"].rstrip("/") + "/chat/completions"
KEY = opts["apiKey"]

PROMPT = """You are writing study notes for a GED question.

Question: {prompt}
Options:
A) {a}
B) {b}
C) {c}
D) {d}
Correct answer: {ans}
Why the correct answer is right: {expl}

Write one note per option, 10 to 30 words each, saying why that option is right
or wrong. For the correct option explain what makes it right; for the others say
what specifically is wrong with them.

Reply with JSON only: {{"notes": ["note for A", "note for B", "note for C", "note for D"]}}"""


def call(prompt: str, retries: int = 2) -> list[str] | None:
    body = json.dumps({
        "model": "hy4-flash-free",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 900,
        "temperature": 0.3,
    }).encode()
    for _ in range(retries + 1):
        req = urllib.request.Request(URL, data=body, headers={
            "Authorization": f"Bearer {KEY}", "Content-Type": "application/json",
            "x-opencode-session": "agent-ged-notes",
            "User-Agent": "Mozilla/5.0 ged-notes"})
        try:
            raw = urllib.request.urlopen(req, timeout=120).read().decode()
            data = json.loads(raw)
            msg = data["choices"][0]["message"]
            text = (msg.get("content") or "") + (msg.get("reasoning") or "")
        except Exception as exc:  # noqa: BLE001
            print("call failed:", exc, file=sys.stderr)
            continue
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            continue
        try:
            notes = json.loads(m.group(0))["notes"]
        except Exception:
            continue
        if isinstance(notes, list) and len(notes) == 4 and all(
                8 <= len(n.split()) <= 40 for n in notes):
            return [n.strip() for n in notes]
    return None


def main() -> None:
    bank = json.loads(BANK.read_text())
    mcq = [q for q in bank["questions"] if q["type"] == "mcq"]
    todo = [q for q in mcq if len(q.get("option_notes") or []) != 4]
    print(f"{len(mcq)} mcq, {len(todo)} need notes", flush=True)
    done = 0
    for q in todo:
        o = q["options"]
        if len(o) != 4:
            continue
        notes = call(PROMPT.format(prompt=q["prompt"], a=o[0], b=o[1], c=o[2], d=o[3],
                                   ans=q["answer"], expl=q.get("explanation", "")))
        if not notes:
            print("skip", q["id"], flush=True)
            continue
        q["option_notes"] = notes
        done += 1
        if done % 5 == 0:
            BANK.write_text(json.dumps(bank, separators=(",", ":"), ensure_ascii=False))
            print(f"{done}/{len(todo)}", flush=True)
        time.sleep(0.4)
    BANK.write_text(json.dumps(bank, separators=(",", ":"), ensure_ascii=False))
    print("done", done, flush=True)


if __name__ == "__main__":
    main()
