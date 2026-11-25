#!/usr/bin/env python3
"""websearch MCP for the GED tutor (stdlib only).

Wraps the keyless search chain that was proven on the water bot: Google News
RSS -> Bing HTML (redirect-decoded) -> Marginalia -> DuckDuckGo, with the
relevance guard that rejects an answer set which does not match the query.

Tools:
  web_search(query, limit=6)      -> numbered hits: title / url / source / snippet
  web_read(url, max_chars=4000)   -> readable text of one page
"""
from __future__ import annotations

import json
import sys
import os

WATER_DIR = "/home/roni/Roni_workspace/water-bot"
sys.path.insert(0, WATER_DIR)

try:
    from water import tools_web as TW  # type: ignore
except Exception:  # pragma: no cover - fallback to direct file import
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "tools_web", os.path.join(WATER_DIR, "water", "tools_web.py"))
    TW = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(TW)  # type: ignore


TOOLS = [
    {
        "name": "web_search",
        "description": "Search the live web. Returns dated headlines and pages with URLs; "
                       "use it for anything current (news, dates, prices, rules, definitions that changed).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for."},
                "limit": {"type": "integer", "description": "Max hits (default 6).", "default": 6},
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_read",
        "description": "Fetch one page and return its readable text (use after web_search).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "max_chars": {"type": "integer", "default": 4000},
            },
            "required": ["url"],
        },
    },
]


def _search(args: dict) -> str:
    q = str(args.get("query") or "").strip()
    if not q:
        return "error: empty query"
    limit = int(args.get("limit") or 6)
    hits = TW.search(q, limit=limit)
    if not hits:
        return f"no results for {q!r}"
    lines = [f"{len(hits)} results for {q!r}:"]
    for i, h in enumerate(hits, 1):
        lines.append(f"{i}. {h.get('title', '').strip()}")
        if h.get("url"):
            lines.append(f"   {h['url']}")
        if h.get("source"):
            lines.append(f"   source: {h['source']}")
        if h.get("snippet"):
            lines.append(f"   {h['snippet'][:300]}")
    return "\n".join(lines)


def _read(args: dict) -> str:
    url = str(args.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return "error: url must start with http(s)://"
    text = TW.read(url, limit_chars=int(args.get("max_chars") or 4000))
    return text or "empty page"


def handle(req: dict) -> dict | None:
    method = req.get("method")
    rid = req.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": req.get("params", {}).get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ged-websearch", "version": "1.0.0"},
        }}
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            if name == "web_search":
                out = _search(args)
            elif name == "web_read":
                out = _read(args)
            else:
                return {"jsonrpc": "2.0", "id": rid,
                        "error": {"code": -32602, "message": f"unknown tool {name}"}}
            return {"jsonrpc": "2.0", "id": rid,
                    "result": {"content": [{"type": "text", "text": out}]}}
        except Exception as exc:  # a search failure must not kill the server
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": f"search failed: {exc}"}], "isError": True}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if rid is None:
        return None
    return {"jsonrpc": "2.0", "id": rid,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        resp = handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
