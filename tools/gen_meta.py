#!/usr/bin/env python3
"""Batch-generate study metadata for the bank.

  --notes   four 10-30 word notes per multiple-choice question
  --fib     five accepted variants per fill-in answer

Batches four questions per request to stay under the free tier's rate limit,
backs off on 429, and is resumable (finished items are skipped).
"""
from __future__ import annotations

import argparse
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

NOTES_PROMPT = """For each GED question below write four option notes, 10 to 30 words
each, saying why that option is right or wrong. The correct option's note explains
what makes it right; the others say what is specifically wrong.

{items}

Reply JSON only:
{{"results": [{{"id": "...", "notes": ["A note", "B note", "C note", "D note"]}}]}}"""

FIB_PROMPT = """For each GED fill-in-the-blank below give five other ways a correct student
might type the same answer: units, spacing, fraction vs decimal, with or without
the variable or dollar sign. Every variant must be CORRECT.

{items}

Reply JSON only:
{{"results": [{{"id": "...", "variants": ["v1", "v2", "v3", "v4", "v5"]}}]}}"""


def ask(prompt: str) -> str | None:
    body = json.dumps({"model": "hy4-flash-free",
                       "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": 2200, "temperature": 0.2}).encode()
    for attempt in range(5):
        req = urllib.request.Request(URL, data=body, headers={
            "Authorization": f"Bearer {KEY}", "Content-Type": "application/json",
            "x-opencode-session": "agent-ged-meta", "User-Agent": "Mozilla/5.0 ged-meta"})
        try:
            raw = json.loads(urllib.request.urlopen(req, timeout=150).read())
            msg = raw["choices"][0]["message"]
            return (msg.get("content") or "") + (msg.get("reasoning") or "")
        except Exception as exc:  # noqa: BLE001
            print("call failed:", exc, file=sys.stderr, flush=True)
            time.sleep(20 + attempt * 15)
    return None


def json_block(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def run_notes(bank: dict) -> int:
    todo = [q for q in bank["questions"]
            if q["type"] == "mcq" and len(q.get("option_notes") or []) != 4 and len(q["options"]) == 4]
    print(f"notes: {len(todo)} to do", flush=True)
    done = 0
    for i in range(0, len(todo), 4):
        batch = todo[i:i + 4]
        items = "\n\n".join(
            f"id: {q['id']}\nQuestion: {q['prompt']}\nA) {q['options'][0]}\nB) {q['options'][1]}\n"
            f"C) {q['options'][2]}\nD) {q['options'][3]}\nCorrect: {q['answer']}\n"
            f"Why right: {q.get('explanation', '')[:220]}" for q in batch)
        text = ask(NOTES_PROMPT.format(items=items))
        data = json_block(text) if text else None
        got = {r["id"]: r["notes"] for r in (data or {}).get("results", [])
               if isinstance(r.get("notes"), list) and len(r["notes"]) == 4}
        for q in batch:
            notes = got.get(q["id"])
            if not notes:
                continue
            if all(8 <= len(n.split()) <= 45 for n in notes):
                q["option_notes"] = [n.strip() for n in notes]
                done += 1
        BANK.write_text(json.dumps(bank, separators=(",", ":"), ensure_ascii=False))
        print(f"{done}/{len(todo)}", flush=True)
        time.sleep(2)
    return done


def run_fib(bank: dict) -> int:
    def extras(q):
        base = {str(q["answer"]).lower(), str(q["answer"]).replace(" ", "").lower()}
        return [a for a in (q.get("accept") or []) if a not in base]
    todo = [q for q in bank["questions"] if q["type"] == "fib" and len(extras(q)) < 5]
    print(f"fib: {len(todo)} to do", flush=True)
    done = 0
    for i in range(0, len(todo), 4):
        batch = todo[i:i + 4]
        items = "\n\n".join(f"id: {q['id']}\nQuestion: {q['prompt']}\nAnswer: {q['answer']}\n"
                            f"Work: {q.get('explanation', '')[:160]}" for q in batch)
        text = ask(FIB_PROMPT.format(items=items))
        data = json_block(text) if text else None
        got = {r["id"]: r["variants"] for r in (data or {}).get("results", [])
               if isinstance(r.get("variants"), list)}
        for q in batch:
            vs = [str(v).strip() for v in got.get(q["id"], []) if str(v).strip()][:5]
            if len(vs) < 3:
                continue
            base = {str(q["answer"]).strip().lower(), str(q["answer"]).replace(" ", "").lower()}
            q["accept"] = sorted(base | {v.lower() for v in vs})
            done += 1
        BANK.write_text(json.dumps(bank, separators=(",", ":"), ensure_ascii=False))
        print(f"{done}/{len(todo)}", flush=True)
        time.sleep(2)
    return done


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--notes", action="store_true")
    ap.add_argument("--fib", action="store_true")
    a = ap.parse_args()
    if not (a.notes or a.fib):
        a.notes = a.fib = True
    bank = json.loads(BANK.read_text())
    if a.notes:
        print("notes done:", run_notes(bank), flush=True)
    if a.fib:
        print("fib done:", run_fib(bank), flush=True)
    BANK.write_text(json.dumps(bank, separators=(",", ":"), ensure_ascii=False))


if __name__ == "__main__":
    main()
