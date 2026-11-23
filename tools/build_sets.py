#!/usr/bin/env python3
"""Merge authored passage sets (data/sets/*.json) into the question bank.

Each file is a list of {title, passage, questions:[{prompt, options, answer,
explanation}]}. Sets are appended to data/questions.json as multiple-choice
questions that share one passage, with ids like `ss-p01-q2`.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANK = ROOT / "data" / "questions.json"
SETS = ROOT / "data" / "sets"

PREFIX = {"social_studies": "ss", "rla": "rla", "science": "sci", "math": "mat"}


def main() -> None:
    bank = json.loads(BANK.read_text())
    have = {q["id"] for q in bank["questions"]}
    added = 0
    for path in sorted(SETS.glob("*.json")):
        subject = next((s for s in PREFIX if path.stem.startswith(s)), None)
        if not subject:
            print("skip", path.name, "(no subject in the name)")
            continue
        tag = path.stem.split("_")[-1]
        for n, item in enumerate(json.loads(path.read_text()), 1):
            sid = f"{PREFIX[subject]}-p{tag}{n:02d}"
            for k, q in enumerate(item["questions"], 1):
                qid = f"{sid}-q{k}"
                if qid in have:
                    continue
                opts = q["options"]
                if len(opts) != 4 or q["answer"] not in "ABCD":
                    print("bad question", qid)
                    continue
                bank["questions"].append({
                    "id": qid, "subject": subject, "type": "mcq",
                    "set": item["title"], "passage": item["passage"],
                    "image": None, "prompt": q["prompt"], "options": opts,
                    "answer": q["answer"], "accept": [],
                    "explanation": q.get("explanation", ""),
                })
                have.add(qid)
                added += 1
    BANK.write_text(json.dumps(bank, separators=(",", ":"), ensure_ascii=False))
    words = [len(q["passage"].split()) for q in bank["questions"] if q.get("passage") and q["type"] == "mcq"]
    print("added", added, "| sets in bank:", len({q["set"] for q in bank["questions"] if q.get("set")}))
    if words:
        print("passage words: min", min(words), "max", max(words))


if __name__ == "__main__":
    main()
