#!/usr/bin/env python3
"""GED practice GUI — local server (stdlib only).

Serves web/ and a small JSON API. Grading for mcq/fib happens here; open-ended
answers and hints go to the persistent HY4 tutor through a file queue
(data/requests -> data/replies), which the tutor reads with the ged MCP.
"""
from __future__ import annotations

import difflib
import json
import os
import random
import collections
import re
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DATA = ROOT / "data"
REQ = DATA / "requests"
REP = DATA / "replies"
SID_FILE = Path.home() / ".local/state/opencode/ged_tutor_session"
PORT = int(os.environ.get("GED_PORT", "8765"))

REQ.mkdir(parents=True, exist_ok=True)
REP.mkdir(parents=True, exist_ok=True)
VJOBS = DATA / "variant_jobs.jsonl"
SESSIONS = DATA / "sessions"
SESSIONS.mkdir(parents=True, exist_ok=True)
HISTORY = DATA / "history.jsonl"
PASSWORD = os.environ.get("GED_PASS", "Mongosged999")
RATE_LIMIT = int(os.environ.get("GED_RATE", "10"))      # writes per minute
READ_LIMIT = int(os.environ.get("GED_READ_RATE", "120"))  # reads per minute
HITS: dict[str, collections.deque] = {}
ALLOWED_ORIGINS = {
    "https://ged-practice-rs.surge.sh",
    "http://127.0.0.1:8765",
    "http://localhost:8765",
}

BANK: dict = {"subjects": {}, "questions": []}
BY_ID: dict[str, dict] = {}


def append_history(record: dict) -> None:
    """One line per graded attempt. Append-only: a session's counters can be
    reset, the record of what was actually asked and answered cannot."""
    line = json.dumps(record, ensure_ascii=False)
    with LOCK:
        with HISTORY.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def read_history(limit: int = 200) -> list[dict]:
    if not HISTORY.exists():
        return []
    rows: collections.deque[dict] = collections.deque(maxlen=max(1, limit))
    with HISTORY.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return list(rows)


NAMES = {"math": "Mathematical Reasoning", "rla": "Reasoning Through Language Arts",
         "science": "Science", "social": "Social Studies", "social_studies": "Social Studies",
         "mega": "Mega (all four)", "unknown": "Other"}


def scoreboard() -> dict:
    """Per-subject totals, from the attempt log plus each session's counters."""
    totals: dict[str, dict] = {}
    for row in read_history(100000):
        subj = row.get("subject") or "unknown"
        slot = totals.setdefault(subj, {"asked": 0, "correct": 0, "wrong": 0,
                                        "skipped": 0, "points": 0, "best_streak": 0})
        slot["asked"] += 1
        if row.get("correct") is True:
            slot["correct"] += 1
        elif row.get("correct") is False:
            slot["wrong"] += 1
        else:
            slot["skipped"] += 1
    for f in SESSIONS.glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        prog = d.get("progress") or {}
        subj = prog.get("subject") or d.get("subject") or f.stem
        slot = totals.setdefault(subj, {"asked": 0, "correct": 0, "wrong": 0,
                                        "skipped": 0, "points": 0, "best_streak": 0})
        slot["points"] = max(slot["points"], int(prog.get("points") or 0))
        slot["best_streak"] = max(slot["best_streak"], int(prog.get("streak") or 0))
        if prog.get("subject_name"):
            slot["name"] = prog["subject_name"]
    for subj, slot in totals.items():
        slot.setdefault("name", NAMES.get(subj, subj.replace("_", " ").title()))
        graded = slot["correct"] + slot["wrong"]
        slot["accuracy"] = round(100.0 * slot["correct"] / graded, 1) if graded else 0.0
    return totals
LOCK = threading.Lock()
BANK_MTIME = 0.0


def load_bank() -> None:
    global BANK, BY_ID, BANK_MTIME
    raw = json.loads((DATA / "questions.json").read_text())
    with LOCK:
        BANK = raw
        BY_ID = {q["id"]: q for q in raw["questions"]}
        BANK_MTIME = (DATA / "questions.json").stat().st_mtime


def ensure_fresh() -> None:
    """The tutor edits the bank while the app runs, so reload when it changes."""
    try:
        if (DATA / "questions.json").stat().st_mtime != BANK_MTIME:
            load_bank()
    except Exception:
        pass


def queue_variant(q: dict, correct: bool) -> None:
    job = {"job_id": uuid.uuid4().hex[:10], "question_id": q["id"], "subject": q["subject"],
           "correct": bool(correct), "ts": time.time(), "done": False}
    with VJOBS.open("a") as f:
        f.write(json.dumps(job) + "\n")


def pending_variant_jobs() -> int:
    if not VJOBS.exists():
        return 0
    n = 0
    for line in VJOBS.read_text().splitlines():
        try:
            if not json.loads(line).get("done"):
                n += 1
        except Exception:
            continue
    return n


def _lev(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return len(a) or len(b)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower().rstrip(".")


def grade(q: dict, given: str) -> tuple[bool | None, str]:
    if q["type"] == "mcq":
        correct = norm(given)[:1] == str(q["answer"]).strip().lower()[:1]
        return correct, q["answer"]
    if q["type"] == "fib":
        variants = [norm(q["answer"])] + [norm(a) for a in q.get("accept", [])]
        tight = {v.replace(" ", "") for v in variants}
        g = norm(given)
        gt = g.replace(" ", "")
        if g in variants or gt in tight:
            return True, q["answer"]
        # typo tolerance for word answers only; numbers and fractions must match
        for v in variants:
            if len(v) < 3 or not re.search(r"[a-z]{3}", v):
                continue
            vt = v.replace(" ", "")
            if len(vt) >= 6 and difflib.SequenceMatcher(None, gt, vt).ratio() >= 0.87:
                return True, q["answer"]
            if len(vt) < 6 and _lev(gt, vt) <= 1:
                return True, q["answer"]
        return False, q["answer"]
    return None, q["answer"] or ""


def wake_tutor(request_id: str, ctx: dict | None = None, q: dict | None = None, kind: str = "chat") -> None:
    ctx = ctx or {}
    if kind == "variant":
        n = pending_variant_jobs()
        msg = (f"ged: {n} variant job(s) queued — call ged_variant_jobs, then ged_add_variant "
               f"for each (reword it, keep the same answer correct, pick options), then stop. No reply needed.")
        try:
            if subprocess.run(["tmux", "has-session", "-t", "jarvis"],
                              capture_output=True).returncode == 0:
                subprocess.run(["tmux", "send-keys", "-t", "jarvis", msg, "Enter"], capture_output=True)
                return
        except Exception:
            pass
        return
    parts = [f"ged: new request {request_id}"]
    if ctx:
        subj = ctx.get("subject_name") or ctx.get("subject") or "?"
        pos = f"{ctx.get('index', '?')}/{ctx.get('total', '?')}"
        parts.append(f"{subj} question {pos}")
        if "score" in ctx:
            parts.append(f"score {ctx.get('score')}/{ctx.get('asked', 0)}")
        if ctx.get("streak"):
            parts.append(f"streak {ctx['streak']}")
    parts.append(f"kind={kind}")
    msg = " — ".join(parts) + " — call ged_pending_requests for the full question and stats, then ged_reply"
    # The tutor lives in a tmux pane; typing into it is the wake.
    try:
        if subprocess.run(["tmux", "has-session", "-t", "jarvis"],
                          capture_output=True).returncode == 0:
            subprocess.run(["tmux", "send-keys", "-t", "jarvis", msg, "Enter"],
                           capture_output=True)
            return
    except Exception:
        pass
    # Fallback: the shared opencode service, if the tutor is pinned there.
    try:
        sid = SID_FILE.read_text().strip().splitlines()[0].strip()
    except Exception:
        return
    if not sid:
        return
    try:
        subprocess.Popen(
            ["oc2", "send", "--session", sid, "--detach", "--raw", msg],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass


class Handler(BaseHTTPRequestHandler):
    server_version = "GED/1.0"

    def log_message(self, *a):  # quiet
        pass

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Ged-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _gate(self) -> bool:
        """Password gate with a 10/min login budget and a 300/min request budget."""
        bare = self.path.split("?")[0]
        ip = self.headers.get("CF-Connecting-IP") or self.client_address[0]
        now = time.time()

        def prune(dq, window=60.0):
            while dq and now - dq[0] > window:
                dq.popleft()

        allq = HITS.setdefault("all:" + ip, collections.deque())
        prune(allq)
        if len(allq) >= 300:
            self._json({"error": "rate limited", "retry_after": int(60 - (now - allq[0]))}, 429)
            return False
        allq.append(now)

        if bare == "/api/ping" or not bare.startswith("/api/"):
            return True
        if self.headers.get("X-Ged-Key") == PASSWORD:
            return True

        # failed password attempt — this is what the 10/min budget protects
        authq = HITS.setdefault("auth:" + ip, collections.deque())
        prune(authq)
        if len(authq) >= 10:
            self._json({"error": "too many login attempts", "retry_after": int(60 - (now - authq[0]))}, 429)
            return False
        authq.append(now)
        self._json({"error": "password required"}, 401)
        return False

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except Exception:
            return {}

    def do_GET(self) -> None:  # noqa: N802
        ensure_fresh()
        if not self._gate():
            return
        path = self.path.split("?")[0]
        query = self.path.split("?")[1] if "?" in self.path else ""

        if path == "/api/questions":
            subj = ""
            for part in query.split("&"):
                if part.startswith("subject="):
                    subj = part.split("=", 1)[1]
            now = time.time()
            with LOCK:
                qs = [q for q in BANK["questions"]
                      if (not subj or q["subject"] == subj)
                      and (not q.get("variant") or (q.get("due") or 0) <= now)]
            self._json({"subjects": BANK["subjects"], "questions": qs})
            return
        if path == "/api/ping":
            self._json({"ok": True})
            return
        if path == "/api/sessions":
            out = {}
            for f in SESSIONS.glob("*.json"):
                try:
                    d = json.loads(f.read_text())
                except Exception:
                    continue
                out[f.stem] = {"updated": d.get("updated"), "progress": d.get("progress")}
            self._json(out)
            return
        if path.startswith("/api/session/"):
            subj = path.rsplit("/", 1)[-1]
            f = SESSIONS / f"{subj}.json"
            if not f.exists():
                self._json({"error": "no session"}, 404)
                return
            self._json(json.loads(f.read_text()))
            return
        if path == "/api/scoreboard":
            self._json({"subjects": scoreboard()})
            return
        if path == "/api/history":
            limit = 100
            for part in query.split("&"):
                if part.startswith("limit="):
                    try:
                        limit = max(1, min(1000, int(part.split("=", 1)[1])))
                    except ValueError:
                        pass
            rows = read_history(limit)
            out = []
            for row in reversed(rows):
                q = BY_ID.get(row.get("id") or "") or {}
                out.append({
                    "ts": row.get("ts"),
                    "id": row.get("id"),
                    "subject": row.get("subject"),
                    "type": row.get("type"),
                    "correct": row.get("correct"),
                    "given": row.get("given"),
                    "expected": row.get("expected"),
                    "prompt": (q.get("prompt") or "")[:160],
                })
            self._json({"rows": out})
            return
        if path == "/api/stats":
            with LOCK:
                qs = BANK["questions"]
                by_s, by_t = {}, {}
                for q in qs:
                    by_s[q["subject"]] = by_s.get(q["subject"], 0) + 1
                    by_t[q["type"]] = by_t.get(q["type"], 0) + 1
            self._json({"total": len(qs), "by_subject": by_s, "by_type": by_t})
            return
        if path.startswith("/api/help/"):
            rid = path.rsplit("/", 1)[-1]
            f = REP / f"{rid}.json"
            if f.exists():
                self._json({"status": "done", "reply": json.loads(f.read_text()).get("text", "")})
                return
            req = REQ / f"{rid}.json"
            age = time.time() - (json.loads(req.read_text()).get("created", time.time()) if req.exists() else time.time())
            self._json({"status": "pending" if age < 90 else "timeout", "reply": "",
                        "age": round(age, 1)})
            return

        # static
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (WEB / rel).resolve()
        if not str(target).startswith(str(WEB.resolve())) or not target.is_file():
            self._send(404, b"not found", "text/plain")
            return
        ctype = {
            ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml",
            ".json": "application/json", ".png": "image/png", ".ico": "image/x-icon",
        }.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)

    def do_POST(self) -> None:  # noqa: N802
        ensure_fresh()
        if not self._gate():
            return
        path = self.path.split("?")[0]
        body = self._body()

        if path == "/api/answer":
            q = BY_ID.get(body.get("id", ""))
            if not q:
                self._json({"error": "unknown question"}, 404)
                return
            given = body.get("answer", "")
            correct, expected = grade(q, given)
            append_history({
                "ts": round(time.time(), 3),
                "id": q.get("id"),
                "subject": q.get("subject"),
                "type": q.get("type"),
                "skill": q.get("skill") or "",
                "correct": correct,
                "given": str(given)[:400],
                "expected": str(expected)[:400],
            })
            if correct is not None:
                queue_variant(q, correct)
            self._json({"correct": correct, "expected": expected,
                        "explanation": q.get("explanation") or "", "type": q["type"]})
            return

        if path == "/api/help":
            rid = uuid.uuid4().hex[:12]
            qid = body.get("id") or ""
            q = BY_ID.get(qid) or {}
            ctx = body.get("context") or {}
            focus = BY_ID.get(body.get("focus_id") or "") or {}
            payload = {
                "id": rid, "kind": body.get("kind", "chat"), "question_id": qid,
                "subject": q.get("subject"), "answer": body.get("answer", ""),
                "text": body.get("text", ""), "created": time.time(),
                "guide": body.get("guide", ""), "explanation": body.get("explanation", ""),
                "progress": ctx,
                "focus_question": {k: focus.get(k) for k in
                                   ("id", "subject", "prompt", "passage", "options", "answer", "type", "set")} if focus else None,
                "question": {k: q.get(k) for k in ("prompt", "passage", "options", "answer", "type", "set")} if q else None,
            }
            (REQ / f"{rid}.json").write_text(json.dumps(payload, indent=1))
            (DATA / "session.json").write_text(json.dumps(
                {"updated": time.time(), "progress": ctx, "last_request": rid,
                 "question_id": qid}, indent=1))
            wake_tutor(rid, ctx, q, body.get("kind", "chat"))
            self._json({"request_id": rid})
            return

        if path == "/api/session":
            subj = str(body.get("subject") or "").strip()
            if not subj.isalnum() and "_" not in subj:
                self._json({"error": "bad subject"}, 400)
                return
            (SESSIONS / f"{subj}.json").write_text(json.dumps(
                {"subject": subj, "updated": time.time(), "progress": body.get("progress"),
                 "state": body.get("state")}, indent=1))
            self._json({"ok": True})
            return

        if path == "/api/reload":
            load_bank()
            self._json({"ok": True, "total": len(BANK["questions"])})
            return

        self._json({"error": "not found"}, 404)


def variant_waker() -> None:
    """Wake the tutor when variant jobs pile up and nothing else is waiting."""
    while True:
        time.sleep(40)
        try:
            if pending_variant_jobs() == 0:
                continue
            waiting = [f for f in REQ.glob("*.json") if not (REP / f.name).exists()]
            if waiting:
                continue
            wake_tutor("variant-batch", {"subject_name": "variant review"}, None, "variant")
        except Exception:
            continue


def main() -> None:
    load_bank()
    threading.Thread(target=variant_waker, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"GED practice GUI → http://127.0.0.1:{PORT}  ({len(BY_ID)} questions)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
