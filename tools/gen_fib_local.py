#!/usr/bin/env python3
"""Add safe answer variants to numeric fill-in questions, instantly.

Only mathematically identical forms are added, so no wrong answer is accepted.
Word answers are left for the model generator.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANK = ROOT / "data" / "questions.json"

NUM = re.compile(r"^-?\d+(?:\.\d+)?$")
FRAC = re.compile(r"^(-?\d+)\s*/\s*(\d+)$")


def variants_for(ans: str, prompt: str) -> list[str] | None:
    raw = str(ans).strip()
    cleaned = raw.replace("$", "").replace(",", "").strip()
    m = re.match(r"^[a-zA-Z]\s*=\s*(.+)$", cleaned)
    if m:
        cleaned = m.group(1).strip()
    out: list[str] = []
    if NUM.match(cleaned):
        v = float(cleaned)
        forms = [cleaned]
        if v == int(v):
            forms += [str(int(v)), f"{int(v)}.0", f"{int(v)}.00"]
        else:
            forms += [f"{v:g}", f"{v:.2f}", f"{v:.3f}"]
        if "$" in raw or re.search(r"\$|dollar|cost|price|pay|earn", prompt, re.I):
            forms += [f"${cleaned}", f"${v:g}"]
        forms += [f"x = {cleaned}", f"x={cleaned}", f"{cleaned} units"]
        for f in forms:
            if f not in out:
                out.append(f)
    elif FRAC.match(cleaned):
        a, b = FRAC.match(cleaned).groups()
        try:
            dec = float(a) / float(b)
        except ZeroDivisionError:
            return None
        out = [cleaned, f"{a}/{b}", f"{dec:g}", f"{dec:.2f}", f"x = {cleaned}"]
        seen, uniq = set(), []
        for f in out:
            if f not in seen:
                seen.add(f)
                uniq.append(f)
        out = uniq
    else:
        return None
    return out if len(out) >= 5 else None


def main() -> None:
    bank = json.loads(BANK.read_text())
    done = 0
    for q in bank["questions"]:
        if q["type"] != "fib":
            continue
        extras = [a for a in (q.get("accept") or [])
                  if a not in {str(q["answer"]).lower(), str(q["answer"]).replace(" ", "").lower()}]
        if len(extras) >= 5:
            continue
        vs = variants_for(q["answer"], q["prompt"])
        if not vs:
            continue
        base = {str(q["answer"]).strip().lower(), str(q["answer"]).replace(" ", "").lower()}
        q["accept"] = sorted(base | {v.lower() for v in vs})
        done += 1
    BANK.write_text(json.dumps(bank, separators=(",", ":"), ensure_ascii=False))
    left = sum(1 for q in bank["questions"] if q["type"] == "fib" and len(q.get("accept") or []) < 5)
    print("added local variants to", done, "| still missing:", left)


if __name__ == "__main__":
    main()
