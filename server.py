#!/usr/bin/env python3
"""GED practice GUI — local server (stdlib only).

Serves web/ and a small JSON API. Grading for mcq/fib happens here; open-ended
answers and hints go to the persistent HY4 tutor through a file queue
(data/requests -> data/replies), which the tutor reads with the ged MCP.
"""
from __future__ import annotations

import json
import os
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

BANK: dict = {"subjects": {}, "questions": []}
BY_ID: dict[str, dict] = {}
LOCK = threading.Lock()


def load_bank() -> None:
    global BANK, BY_ID
    raw = json.loads((DATA / "questions.json").read_text())
    with LOCK:
        BANK = raw
        BY_ID = {q["id"]: q for q in raw["questions"]}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower().rstrip(".")


def grade(q: dict, given: str) -> tuple[bool | None, str]:
    if q["type"] == "mcq":
        correct = norm(given)[:1] == str(q["answer"]).strip().lower()[:1]
        return correct, q["answer"]
    if q["type"] == "fib":
        want = norm(q["answer"])
        variants = {want} | {norm(a) for a in q.get("accept", [])}
        g = norm(given)
        if g in variants:
            return True, q["answer"]
        # numeric tolerance
        try:
            if abs(float(g.replace(",", "")) - float(re.sub(r"[^0-9.\-]", "", want))) < 1e-6:
                return True, q["answer"]
        except ValueError:
            pass
        return False, q["answer"]
    return None, q["answer"] or ""


def wake_tutor(request_id: str, ctx: dict | None = None, q: dict | None = None, kind: str = "chat") -> None:
    ctx = ctx or {}
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

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
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
        path = self.path.split("?")[0]
        query = self.path.split("?")[1] if "?" in self.path else ""

        if path == "/api/questions":
            subj = ""
            for part in query.split("&"):
                if part.startswith("subject="):
                    subj = part.split("=", 1)[1]
            with LOCK:
                qs = [q for q in BANK["questions"] if not subj or q["subject"] == subj]
                self._json({"subjects": BANK["subjects"], "questions": qs})
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
            self._json({"status": "pending" if age < 90 else "timeout", "reply": ""})
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
        path = self.path.split("?")[0]
        body = self._body()

        if path == "/api/answer":
            q = BY_ID.get(body.get("id", ""))
            if not q:
                self._json({"error": "unknown question"}, 404)
                return
            correct, expected = grade(q, body.get("answer", ""))
            self._json({"correct": correct, "expected": expected,
                        "explanation": q.get("explanation") or "", "type": q["type"]})
            return

        if path == "/api/help":
            rid = uuid.uuid4().hex[:12]
            qid = body.get("id") or ""
            q = BY_ID.get(qid) or {}
            ctx = body.get("context") or {}
            payload = {
                "id": rid, "kind": body.get("kind", "chat"), "question_id": qid,
                "subject": q.get("subject"), "answer": body.get("answer", ""),
                "text": body.get("text", ""), "created": time.time(),
                "progress": ctx,
                "question": {k: q.get(k) for k in ("prompt", "passage", "options", "answer", "type", "set")} if q else None,
            }
            (REQ / f"{rid}.json").write_text(json.dumps(payload, indent=1))
            (DATA / "session.json").write_text(json.dumps(
                {"updated": time.time(), "progress": ctx, "last_request": rid,
                 "question_id": qid}, indent=1))
            wake_tutor(rid, ctx, q, body.get("kind", "chat"))
            self._json({"request_id": rid})
            return

        if path == "/api/reload":
            load_bank()
            self._json({"ok": True, "total": len(BANK["questions"])})
            return

        self._json({"error": "not found"}, 404)


def main() -> None:
    load_bank()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"GED practice GUI → http://127.0.0.1:{PORT}  ({len(BY_ID)} questions)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
