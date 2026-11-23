#!/usr/bin/env python3
"""GED MCP server (stdio, newline-delimited JSON-RPC 2.0).

Lets the tutor agent read the question bank, answer queued student requests,
edit questions, and search the web. Stdlib only, no dependencies.

Run: python3 mcp/ged_mcp.py
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BANK = DATA / "questions.json"
REQ = DATA / "requests"
REP = DATA / "replies"
SERVER = {"name": "ged", "version": "1.0.0"}

TOOLS = [
    {
        "name": "list_questions",
        "description": "List questions in the GED bank. Optional subject filter (math, science, rla, social_studies) and limit.",
        "inputSchema": {"type": "object", "properties": {
            "subject": {"type": "string"}, "limit": {"type": "integer"}}},
    },
    {
        "name": "get_question",
        "description": "Get one question by id, including passage, options, answer and explanation.",
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}},
                        "required": ["id"]},
    },
    {
        "name": "update_question",
        "description": "Patch a question in the bank (prompt, passage, options, answer, explanation, image).",
        "inputSchema": {"type": "object", "properties": {
            "id": {"type": "string"}, "patch": {"type": "object"}}, "required": ["id", "patch"]},
    },
    {
        "name": "pending_requests",
        "description": "Unanswered student requests, oldest first, with the question inlined.",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
    {
        "name": "reply",
        "description": "Send your answer to the student for a request id.",
        "inputSchema": {"type": "object", "properties": {
            "request_id": {"type": "string"}, "text": {"type": "string"}},
            "required": ["request_id", "text"]},
    },
    {
        "name": "web_search",
        "description": "Search the web (DuckDuckGo) and return the top results.",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}},
                        "required": ["query"]},
    },
    {
        "name": "session_state",
        "description": "The student's live progress: subject, question position, score, answered count, last request.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "variant_jobs",
        "description": "Answered questions waiting for a reworded variant. Returns the source question for each.",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
    {
        "name": "add_variant",
        "description": "Create a reworded variant of a question and schedule it to be re-asked after a random interval.",
        "inputSchema": {"type": "object", "properties": {
            "job_id": {"type": "string"},
            "source_id": {"type": "string"},
            "prompt": {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"}},
            "answer": {"type": "string"},
            "explanation": {"type": "string"},
            "delay_minutes": {"type": "integer"}}, "required": ["job_id", "source_id", "prompt"]},
    },
    {
        "name": "stats",
        "description": "Question counts by subject and type.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def read_bank() -> dict:
    return json.loads(BANK.read_text())


def write_bank(b: dict) -> None:
    BANK.write_text(json.dumps(b, indent=1, ensure_ascii=False))


def text_result(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def call(name: str, args: dict) -> dict:
    if name == "list_questions":
        b = read_bank()
        subj = args.get("subject")
        limit = int(args.get("limit") or 25)
        rows = [q for q in b["questions"] if not subj or q["subject"] == subj][:limit]
        return text_result(json.dumps(
            [{"id": q["id"], "subject": q["subject"], "type": q["type"],
              "prompt": q["prompt"][:160]} for q in rows], indent=1))

    if name == "get_question":
        for q in read_bank()["questions"]:
            if q["id"] == args.get("id"):
                return text_result(json.dumps(q, indent=1, ensure_ascii=False))
        return text_result(f"no question {args.get('id')}")

    if name == "update_question":
        b = read_bank()
        for q in b["questions"]:
            if q["id"] == args.get("id"):
                q.update(args.get("patch") or {})
                write_bank(b)
                return text_result(json.dumps(q, indent=1, ensure_ascii=False))
        return text_result(f"no question {args.get('id')}")

    if name == "pending_requests":
        limit = int(args.get("limit") or 5)
        out = []
        for f in sorted(REQ.glob("*.json"), key=lambda p: p.stat().st_mtime):
            if (REP / f.name).exists():
                continue
            out.append(json.loads(f.read_text()))
            if len(out) >= limit:
                break
        return text_result(json.dumps(out, indent=1, ensure_ascii=False))

    if name == "reply":
        rid = str(args.get("request_id", "")).strip()
        if not re.fullmatch(r"[0-9a-f]{6,32}", rid):
            return text_result("bad request_id")
        REP.mkdir(parents=True, exist_ok=True)
        (REP / f"{rid}.json").write_text(json.dumps(
            {"request_id": rid, "text": args.get("text", ""), "ts": time.time()}, indent=1))
        return text_result("delivered")

    if name == "web_search":
        q = urllib.parse.quote_plus(args.get("query", ""))
        url = f"https://html.duckduckgo.com/html/?q={q}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ged-tutor"})
        try:
            html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            return text_result(f"search failed: {exc}")
        hits = re.findall(
            r'result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?result__snippet"[^>]*>(.*?)</a>',
            html, re.S)[:5]
        rows = [{"url": urllib.parse.unquote(u), "title": re.sub(r"<[^>]+>", "", t).strip(),
                 "snippet": re.sub(r"<[^>]+>", "", s).strip()} for u, t, s in hits]
        return text_result(json.dumps(rows, indent=1, ensure_ascii=False) if rows else "no results")

    if name == "session_state":
        f = DATA / "session.json"
        if not f.exists():
            return text_result("no session yet")
        return text_result(json.dumps(json.loads(f.read_text()), indent=1, ensure_ascii=False))

    if name == "variant_jobs":
        limit = int(args.get("limit") or 5)
        jobs = []
        f = DATA / "variant_jobs.jsonl"
        if f.exists():
            for line in f.read_text().splitlines():
                try:
                    j = json.loads(line)
                except Exception:
                    continue
                if j.get("done"):
                    continue
                src = next((q for q in read_bank()["questions"] if q["id"] == j["question_id"]), None)
                jobs.append({**j, "question": src})
                if len(jobs) >= limit:
                    break
        return text_result(json.dumps(jobs, indent=1, ensure_ascii=False))

    if name == "add_variant":
        import random as _r
        b = read_bank()
        src = next((q for q in b["questions"] if q["id"] == args.get("source_id")), None)
        if not src:
            return text_result(f"no source question {args.get('source_id')}")
        delay = args.get("delay_minutes")
        delay = int(delay) if delay is not None else _r.randint(5, 25)
        n = sum(1 for q in b["questions"] if q.get("variant")) + 1
        opts = args.get("options") or src.get("options") or []
        q = {
            "id": f"var-{n:03d}", "subject": src["subject"], "type": src["type"],
            "set": None, "passage": src.get("passage"), "image": src.get("image"),
            "prompt": args.get("prompt"), "options": opts,
            "answer": args.get("answer") or src.get("answer"),
            "accept": [], "explanation": args.get("explanation") or src.get("explanation", ""),
            "variant": True, "source": src["id"], "due": time.time() + delay * 60,
        }
        b["questions"].append(q)
        write_bank(b)
        # mark the job done
        f = DATA / "variant_jobs.jsonl"
        if f.exists():
            rows = []
            for line in f.read_text().splitlines():
                try:
                    j = json.loads(line)
                except Exception:
                    continue
                if j.get("job_id") == args.get("job_id"):
                    j["done"] = True
                rows.append(json.dumps(j))
            f.write_text("\n".join(rows) + "\n")
        return text_result(f"added {q['id']} (due in {delay} min)")

    if name == "stats":
        b = read_bank()
        by_s, by_t = {}, {}
        for q in b["questions"]:
            by_s[q["subject"]] = by_s.get(q["subject"], 0) + 1
            by_t[q["type"]] = by_t.get(q["type"], 0) + 1
        return text_result(json.dumps({"total": len(b["questions"]), "by_subject": by_s,
                                       "by_type": by_t}, indent=1))

    raise KeyError(name)


def handle(msg: dict) -> dict | None:
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": SERVER}}
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        try:
            res = call(name, params.get("arguments") or {})
        except Exception as exc:  # noqa: BLE001
            res = text_result(f"error: {exc}")
            return {"jsonrpc": "2.0", "id": mid, "result": res, "error": None}
        return {"jsonrpc": "2.0", "id": mid, "result": res}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        out = handle(msg)
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
