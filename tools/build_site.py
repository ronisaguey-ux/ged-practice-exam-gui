#!/usr/bin/env python3
"""Build the static site for Surge.

Copies web/ into site/, drops the question bank in as data/bank.json, and
refuses to include a robots.txt (the page is noindex via meta tag).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"


def main() -> None:
    if SITE.exists():
        shutil.rmtree(SITE)
    shutil.copytree(ROOT / "web", SITE)
    (SITE / "data").mkdir(exist_ok=True)
    bank = json.loads((ROOT / "data" / "questions.json").read_text())
    (SITE / "data" / "bank.json").write_text(
        json.dumps(bank, separators=(",", ":"), ensure_ascii=False))
    if (SITE / "robots.txt").exists():
        (SITE / "robots.txt").unlink()
    print("site built:", SITE, "files:", sum(1 for _ in SITE.rglob("*") if _.is_file()))


if __name__ == "__main__":
    main()
