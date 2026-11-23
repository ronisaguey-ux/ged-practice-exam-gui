#!/usr/bin/env python3
"""Build the static site for Surge.

Copies web/ into site/, drops the question bank in as data/bank.json, and
refuses to include a robots.txt (the page is noindex via meta tag).
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"


def main() -> None:
    if SITE.exists():
        shutil.rmtree(SITE)
    shutil.copytree(ROOT / "web", SITE)
    (SITE / "data").mkdir(exist_ok=True)
    api = os.environ.get("GED_API", "")
    index = (SITE / "index.html").read_text()
    index = index.replace("</head>", f'<script>window.GED_API = "{api}";</script>\n</head>')
    (SITE / "index.html").write_text(index)
    if (SITE / "robots.txt").exists():
        (SITE / "robots.txt").unlink()
    print("site built:", SITE, "files:", sum(1 for _ in SITE.rglob("*") if _.is_file()))


if __name__ == "__main__":
    main()
