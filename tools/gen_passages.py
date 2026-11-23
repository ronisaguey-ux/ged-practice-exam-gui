#!/usr/bin/env python3
"""Write a short GED-style stimulus for questions that have no passage.

Social studies questions in the source file are bare knowledge questions; the
real test wraps them in a document, quote or data description. This generates
that context, one question at a time, and is resumable.
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

PROMPT = """Write a GED-style stimulus for this question.

Question: {prompt}
Answer: {ans}

The stimulus is what the student reads first: a short document excerpt, a quote,
a law or speech passage, or a description of a chart or map. Three to five
sentences, plain text, no title, no questions. It must give realistic context
for the question WITHOUT stating the answer outright.

Reply with the stimulus text only."""


def ask(prompt: str) -> str | None:
    body = json.dumps({"model": "hy4-flash-free",
                       "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": 3000, "temperature": 0.4}).encode()
    for attempt in range(3):
        req = urllib.request.Request(URL, data=body, headers={
            "Authorization": f"Bearer {KEY}", "Content-Type": "application/json",
            "x-opencode-session": "agent-ged-passage", "User-Agent": "Mozilla/5.0 ged-passage"})
        try:
            raw = json.loads(urllib.request.urlopen(req, timeout=90).read())
            msg = raw["choices"][0]["message"]
            text = (msg.get("content") or "").strip()
        except Exception as exc:  # noqa: BLE001
            print("call failed:", exc, flush=True)
            time.sleep(15 + attempt * 10)
            continue
        text = re.sub(r"^```.*?\n|```$", "", text).strip()
        if 120 <= len(text) <= 1200 and text.count(".") >= 2:
            return " ".join(text.split())
    return None


def main() -> None:
    bank = json.loads(BANK.read_text())
    todo = [q for q in bank["questions"]
            if not q.get("passage") and q["subject"] in ("social_studies", "rla", "math")]
    print("todo", len(todo), flush=True)
    done = 0
    for q in todo:
        text = ask(PROMPT.format(prompt=q["prompt"], ans=str(q.get("answer") or "")[:200]))
        if not text:
            print("skip", q["id"], flush=True)
            continue
        q["passage"] = text
        done += 1
        BANK.write_text(json.dumps(bank, separators=(",", ":"), ensure_ascii=False))
        print(f"{done}/{len(todo)}", flush=True)
        time.sleep(3)
    print("done", done, flush=True)


if __name__ == "__main__":
    main()
