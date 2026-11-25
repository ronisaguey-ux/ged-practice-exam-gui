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
        "description": ("Change any question in the bank on the fly: prompt, passage, options, answer, "
                        "accept list, explanation, image, type, subject, skill, set, due. Give the id "
                        "and the fields to change; `reason` is recorded in data/bank_changes.jsonl so "
                        "every edit is traceable. Returns the question after the change."),
        "inputSchema": {"type": "object", "properties": {
            "id": {"type": "string"}, "patch": {"type": "object"},
            "reason": {"type": "string"}}, "required": ["id", "patch"]},
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
    {
        "name": "regrade",
        "description": ("Re-grade any attempt, on request and with a stated justification. Finds the "
                        "attempt for a question (newest by default, `attempt` counts back: 2 = the one "
                        "before, or `ts` picks one by timestamp) and grades it again with the same grader "
                        "the app uses, optionally with a corrected student answer and/or a corrected "
                        "answer key (`answer_key` also fixes the bank). With no recorded attempt it "
                        "grades a supplied answer against the key, for 'would this have counted?'. "
                        "`reason` is mandatory: the regrade row carries it, and the original row is "
                        "never rewritten - a `regraded: true` row is appended."),
        "inputSchema": {"type": "object", "properties": {
            "id": {"type": "string", "description": "question id, e.g. math-014"},
            "attempt": {"type": "integer", "description": "1 = newest (default), 2 = the one before, ..."},
            "ts": {"type": "number", "description": "pick the attempt nearest this timestamp instead"},
            "given": {"type": "string", "description": "the answer to grade (default: what they gave)"},
            "answer_key": {"type": "string", "description": "corrected expected answer, also written to the bank"},
            "reason": {"type": "string", "description": "why this regrade is justified (required)"}},
            "required": ["id", "reason"]},
    },
    {
        "name": "award_points",
        "description": ("Give the student points by hand (streak recoveries, good explanations, a "
                        "question they got right that was marked wrong). Writes to the session "
                        "counter and to an append-only ledger; returns the new total."),
        "inputSchema": {"type": "object", "properties": {
            "points": {"type": "integer", "description": "how many points to add (positive)"},
            "subject": {"type": "string", "description": "session to credit (default: the live session)"},
            "as_if_correct": {"type": "boolean", "description": "award exactly what the app's scoring would give: 1 + the current streak"},
            "reason": {"type": "string"}},
            "required": ["reason"]},
    },
    {
        "name": "deduct_points",
        "description": ("Take points away by hand (a question answered off the key, a duplicate "
                        "attempt). Never goes below zero. Writes to the session counter and the "
                        "append-only ledger; returns the new total."),
        "inputSchema": {"type": "object", "properties": {
            "points": {"type": "integer", "description": "how many points to remove (positive number)"},
            "subject": {"type": "string", "description": "session to debit (default: the live session)"},
            "as_if_miss": {"type": "boolean", "description": "deduct exactly what a miss costs: 1 + the current streak, streak reset to 0"},
            "reason": {"type": "string"}},
            "required": ["reason"]},
    },
    {
        "name": "point_ledger",
        "description": "Recent manual point adjustments (newest last): points, reason, subject, resulting total.",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
    {
        "name": "reorder_questions",
        "description": ("Put questions in an explicit order. Give a list of ids (optionally filtered to "
                        "one subject or set) and they are moved to the front in exactly that order; the "
                        "rest keep their relative order. Use it to fix a bad sequence or to line up a "
                        "lesson. `reason` is logged."),
        "inputSchema": {"type": "object", "properties": {
            "order": {"type": "array", "items": {"type": "string"}},
            "subject": {"type": "string"}, "set": {"type": "string"},
            "reason": {"type": "string"}}, "required": ["order"]},
    },
    {
        "name": "move_question",
        "description": "Move one question to a 0-based position in the bank order.",
        "inputSchema": {"type": "object", "properties": {
            "id": {"type": "string"}, "position": {"type": "integer"},
            "reason": {"type": "string"}}, "required": ["id", "position"]},
    },
    {
        "name": "shuffle_questions",
        "description": ("Shuffle the order questions are served in. A `seed` makes it repeatable (same "
                        "seed, same order); `keep_sets` (default true) keeps a passage set together, "
                        "exactly like the app's own random mode. Scope with `subject` or `set`, or "
                        "shuffle the whole bank. Returns the first 10 ids of the new order."),
        "inputSchema": {"type": "object", "properties": {
            "subject": {"type": "string"}, "set": {"type": "string"},
            "seed": {"type": "integer"}, "keep_sets": {"type": "boolean"},
            "reason": {"type": "string"}}},
    },
]


def read_bank() -> dict:
    return json.loads(BANK.read_text())


def write_bank(b: dict) -> None:
    BANK.write_text(json.dumps(b, indent=1, ensure_ascii=False))


HISTORY = DATA / "history.jsonl"
SESSIONS = DATA / "sessions"
SESSIONS.mkdir(parents=True, exist_ok=True)
LEDGER = DATA / "adjustments.jsonl"


def _grade(q: dict, given: str) -> tuple[bool | None, str]:
    """One grader, owned by the app. Imported rather than re-implemented so a
    correction can never disagree with the verdict the student was shown."""
    sys.path.insert(0, str(ROOT))
    import server as S  # noqa: PLC0415 - local by design, server owns the rules

    return S.grade(q, given)


def _history_rows() -> list[dict]:
    rows: list[dict] = []
    if not HISTORY.exists():
        return rows
    for line in HISTORY.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def _session_path(subject: str | None) -> Path:
    if subject:
        return SESSIONS / f"{subject}.json"
    return DATA / "session.json"


def _apply_points(subject: str | None, delta: int, reason: str, streak: int | None = None) -> dict:
    """Move a session's point counter and record the move. Points never go
    below zero: a deduction larger than the balance takes what is there.
    `streak` (optional) also writes the session's streak counter, which is what
    the app's own award() does on a hit or a miss."""
    path = _session_path(subject)
    doc: dict = {}
    if path.exists():
        try:
            doc = json.loads(path.read_text())
        except Exception:
            doc = {}
    prog = dict(doc.get("progress") or {})
    before = int(prog.get("points") or 0)
    after = max(0, before + int(delta))
    applied = after - before
    prog["points"] = after
    if streak is not None:
        prog["streak"] = int(streak)
    doc["progress"] = prog
    doc["updated"] = time.time()
    path.write_text(json.dumps(doc, indent=1))
    entry = {"ts": round(time.time(), 3), "subject": subject or prog.get("subject") or "live",
             "requested": int(delta), "applied": applied, "before": before, "after": after,
             "reason": str(reason)[:300]}
    if streak is not None:
        entry["streak_after"] = int(streak)
    with LEDGER.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")
    return entry


def _read_progress(subject: str | None) -> dict:
    path = _session_path(subject)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text()).get("progress") or {}
    except Exception:
        return {}


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
        patch = args.get("patch") or {}
        allowed = {"prompt", "passage", "options", "answer", "accept", "explanation", "image",
                   "type", "subject", "skill", "set", "due"}
        unknown = [k for k in patch if k not in allowed]
        if unknown:
            return text_result(f"unknown field(s): {', '.join(unknown)}; allowed: {', '.join(sorted(allowed))}")
        b = read_bank()
        for q in b["questions"]:
            if q["id"] == args.get("id"):
                before = {k: q.get(k) for k in patch}
                q.update(patch)
                write_bank(b)
                with (DATA / "bank_changes.jsonl").open("a") as fh:
                    fh.write(json.dumps({"ts": round(time.time(), 3), "id": q["id"],
                                         "fields": sorted(patch), "before": before,
                                         "after": {k: q.get(k) for k in patch},
                                         "reason": str(args.get("reason") or "")[:300]}) + "\n")
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

    if name == "regrade":
        qid = str(args.get("id") or "").strip()
        reason = str(args.get("reason") or "").strip()
        if not reason:
            return text_result("reason is required: say why this regrade is justified")
        bank = read_bank()
        q = next((x for x in bank["questions"] if x["id"] == qid), None)
        if not q:
            return text_result(f"no question {qid}")
        rows = _history_rows()
        cands = sorted((r for r in rows if r.get("id") == qid),
                       key=lambda r: float(r.get("ts") or 0))
        row = None
        if cands:
            if args.get("ts") is not None:
                want = float(args["ts"])
                row = min(cands, key=lambda r: abs(float(r.get("ts") or 0) - want))
            else:
                back = max(1, int(args.get("attempt") or 1))
                if back <= len(cands):
                    row = cands[-back]
                else:
                    return text_result(
                        f"{qid} has {len(cands)} recorded attempt(s); attempt {back} does not exist")
        elif args.get("given") is None:
            return text_result(f"no attempt recorded for {qid} and no `given` answer to grade")
        key_changed = None
        if args.get("answer_key") is not None:
            key_changed = {"from": q.get("answer"), "to": args["answer_key"]}
            q["answer"] = args["answer_key"]
            q.setdefault("accept", [])
            write_bank(bank)
        given = args.get("given") if args.get("given") is not None else (row or {}).get("given", "")
        correct, expected = _grade(q, str(given))
        prev = (row or {}).get("correct")
        entry = {
            "ts": round(time.time(), 3), "id": qid, "subject": q.get("subject"),
            "type": q.get("type"), "skill": q.get("skill") or "",
            "correct": correct, "given": str(given)[:400], "expected": str(expected)[:400],
            "regraded": True, "regraded_ts": (row or {}).get("ts"), "previous_correct": prev,
            "reason": reason[:300],
        }
        with HISTORY.open("a") as fh:
            fh.write(json.dumps(entry) + "\n")
        return text_result(json.dumps(
            {"regraded": qid, "attempt_ts": (row or {}).get("ts"),
             "student_gave": str(given)[:200], "was": prev, "now": correct,
             "expected": expected, "answer_key_change": key_changed,
             "attempts_on_record": len(cands)}, indent=1, ensure_ascii=False))

    if name == "award_points":
        reason = str(args.get("reason") or "award")
        if args.get("as_if_correct"):
            streak = int(_read_progress(args.get("subject")).get("streak") or 0)
            gain = 1 + streak
            e = _apply_points(args.get("subject"), gain, reason, streak=streak + 1)
            e["scoring"] = f"+1 plus +{streak} streak = +{gain}"
            return text_result(json.dumps(e, indent=1))
        pts = int(args.get("points") or 0)
        if pts <= 0:
            return text_result("points must be a positive number (or pass as_if_correct: true)")
        e = _apply_points(args.get("subject"), pts, reason)
        return text_result(json.dumps(e, indent=1))

    if name == "deduct_points":
        reason = str(args.get("reason") or "deduction")
        if args.get("as_if_miss"):
            streak = int(_read_progress(args.get("subject")).get("streak") or 0)
            loss = 1 + streak
            e = _apply_points(args.get("subject"), -loss, reason, streak=0)
            e["scoring"] = f"-1 minus {streak} streak = -{loss}, streak reset"
            return text_result(json.dumps(e, indent=1))
        pts = int(args.get("points") or 0)
        if pts <= 0:
            return text_result("points must be a positive number (or pass as_if_miss: true)")
        e = _apply_points(args.get("subject"), -pts, reason)
        return text_result(json.dumps(e, indent=1))

    if name == "point_ledger":
        limit = int(args.get("limit") or 20)
        entries: list[dict] = []
        if LEDGER.exists():
            for line in LEDGER.read_text().splitlines()[-limit:]:
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
        return text_result(json.dumps(entries, indent=1, ensure_ascii=False) if entries
                           else "no manual adjustments yet")

    if name == "reorder_questions":
        order = [str(x) for x in (args.get("order") or [])]
        if not order:
            return text_result("give at least one question id in `order`")
        b = read_bank()
        qs = b["questions"]
        by_id = {q["id"]: q for q in qs}
        missing = [i for i in order if i not in by_id]
        if missing:
            return text_result(f"unknown id(s): {', '.join(missing[:10])}")
        subj, setname = args.get("subject"), args.get("set")
        head = [by_id[i] for i in order
                if (not subj or by_id[i].get("subject") == subj)
                and (not setname or by_id[i].get("set") == setname)]
        if not head:
            return text_result("none of those ids match the subject/set filter")
        picked = {id(q) for q in head}
        b["questions"] = head + [q for q in qs if id(q) not in picked]
        write_bank(b)
        with (DATA / "bank_changes.jsonl").open("a") as fh:
            fh.write(json.dumps({"ts": round(time.time(), 3), "id": "order", "fields": ["order"],
                                 "before": None, "after": order,
                                 "reason": str(args.get("reason") or "")[:300]}) + "\n")
        return text_result(json.dumps({"reordered": len(head), "first": order[:10]}, indent=1))

    if name == "move_question":
        qid = str(args.get("id") or "")
        pos = int(args.get("position") or 0)
        b = read_bank()
        qs = b["questions"]
        idx = next((i for i, q in enumerate(qs) if q["id"] == qid), None)
        if idx is None:
            return text_result(f"no question {qid}")
        q = qs.pop(idx)
        pos = max(0, min(pos, len(qs)))
        qs.insert(pos, q)
        write_bank(b)
        with (DATA / "bank_changes.jsonl").open("a") as fh:
            fh.write(json.dumps({"ts": round(time.time(), 3), "id": qid, "fields": ["position"],
                                 "before": idx, "after": pos,
                                 "reason": str(args.get("reason") or "")[:300]}) + "\n")
        return text_result(f"{qid} moved from index {idx} to {pos}")

    if name == "shuffle_questions":
        import random as _r
        seed = args.get("seed")
        rnd = _r.Random(int(seed)) if seed is not None else _r.Random()
        keep_sets = args.get("keep_sets")
        keep_sets = True if keep_sets is None else bool(keep_sets)
        subj, setname = args.get("subject"), args.get("set")
        b = read_bank()
        qs = b["questions"]
        sel = [q for q in qs if (not subj or q.get("subject") == subj)
               and (not setname or q.get("set") == setname)]
        if len(sel) < 2:
            return text_result("nothing to shuffle in that scope")
        groups: dict[str, list] = {}
        for q in sel:
            key = (q.get("set") or q["id"]) if keep_sets else q["id"]
            groups.setdefault(key, []).append(q)
        buckets = list(groups.values())
        rnd.shuffle(buckets)
        new_sel = [q for g in buckets for q in (g if keep_sets else g)]
        if not keep_sets:
            rnd.shuffle(new_sel)
        it = iter(new_sel)
        b["questions"] = [next(it) if q in sel else q for q in qs]
        write_bank(b)
        with (DATA / "bank_changes.jsonl").open("a") as fh:
            fh.write(json.dumps({"ts": round(time.time(), 3), "id": "shuffle", "fields": ["order"],
                                 "before": None, "after": [q["id"] for q in new_sel[:20]],
                                 "reason": str(args.get("reason") or "")[:300],
                                 "seed": seed, "keep_sets": keep_sets}) + "\n")
        return text_result(json.dumps({"shuffled": len(new_sel),
                                       "first": [q["id"] for q in new_sel[:10]],
                                       "you_can_repeat_with_seed": seed}, indent=1))

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
