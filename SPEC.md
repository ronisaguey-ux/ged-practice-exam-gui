# GED Practice GUI — build spec (contract)

Everything lives in this repo. Python 3.11+, stdlib only, no npm, no pip installs.
No git commands by workers. Do not touch files you do not own.

## Files and owners

| file | owner |
|---|---|
| `tools/build_bank.py` → `data/questions.json` | worker A |
| `web/index.html`, `web/app.js`, `web/style.css` | worker B |
| `server.py` | worker C |
| `mcp/ged_mcp.py` | worker D |
| `web/img/*.svg`, `data/images.json` | worker E |

## Question bank schema (`data/questions.json`)

```json
{
  "subjects": {
    "math": {"name": "Mathematical Reasoning", "time": 115, "questions": 46},
    "science": {"name": "Science", "time": 90, "questions": 40},
    "social_studies": {"name": "Social Studies", "time": 70, "questions": 35},
    "rla": {"name": "Reasoning Through Language Arts", "time": 150, "questions": 46}
  },
  "questions": [
    {
      "id": "sci-001",
      "subject": "science",
      "type": "mcq",
      "set": "SET 1 — PLANT GROWTH AND LIGHT",
      "passage": "A student placed ten identical bean seedlings...",
      "image": null,
      "prompt": "Which conclusion is best supported by the data?",
      "options": ["Sunlight causes...", "Sunlight significantly increases...", "..."],
      "answer": "B",
      "accept": [],
      "explanation": "Both measures were higher in sunlight."
    }
  ]
}
```

Rules:
- `type` is one of `mcq`, `fib`, `open`.
- `mcq`: `options` has 4 strings, `answer` is `"A"|"B"|"C"|"D"`.
- `fib`: `options` is `[]`, `answer` is the canonical short answer string,
  `accept` lists lowercase variants that also count (`"0.8"`, `"0.8 g/ml"`).
- `open`: `options` is `[]`, `answer` is a model answer or `null`.
- `passage` may be `null`. Questions sharing a `set` are shown together.
- `image` is either `null` or a path like `img/foodweb.svg` (relative to `web/`).
- Every question has `explanation` (1-2 sentences).
- Target: at least 25 questions per subject, at least 110 total, a mix of all
  three types per subject.

## Server (`server.py`)

Python stdlib `http.server`, binds `127.0.0.1:8765`, single file.

Routes:
- `GET /` and any static path → serve from `web/` (correct content types).
- `GET /api/questions` → the whole bank JSON. `?subject=science` filters.
- `GET /api/stats` → `{"total": n, "by_subject": {...}, "by_type": {...}}`
- `POST /api/answer` `{"id": "...", "answer": "B"}` →
  `{"correct": true|false|null, "expected": "...", "explanation": "..."}`
  Graded locally for mcq and fib (case/space-insensitive, `accept` list honoured).
  `open` returns `{"correct": null, ...}` and the GUI asks the tutor.
- `POST /api/help` `{"id": "...", "kind": "hint"|"why"|"grade"|"chat", "text": "..."}`
  → `{"request_id": "<uuid>"}`
- `GET /api/help/<request_id>` → `{"status": "pending"|"done", "reply": "..."}`
- `POST /api/reload` → re-read `data/questions.json` from disk.

Tutor bridge (files, no LLM in the server):
- On `/api/help`, write `data/requests/<request_id>.json` with
  `{"id", "kind", "question_id", "answer", "text", "subject", "created"}`.
- Then wake the tutor: `subprocess.Popen(["oc2","send","--session", SID, "--detach",
  "--raw", "ged: new request <id>"])`, SID read from
  `~/.local/state/opencode/ged_tutor_session` (ignore errors if missing).
- `GET /api/help/<id>` returns `done` when `data/replies/<id>.json` exists,
  with `reply` from that file.
- If a request has no reply after 90 s, return `{"status": "timeout"}` and let
  the GUI fall back to the local `explanation`.

## MCP server (`mcp/ged_mcp.py`)

Newline-delimited JSON-RPC 2.0 over stdio, MCP `initialize` / `tools/list` /
`tools/call`. Server name `ged`, tool names prefixed `ged__`.

Tools:
- `ged__list_questions({"subject"?, "limit"?})` → ids + prompts.
- `ged__get_question({"id"})` → full question object.
- `ged__update_question({"id", "patch": {...}})` → merges patch into the
  question, rewrites `data/questions.json`, returns the new object.
- `ged__pending_requests({"limit"?})` → unanswered requests (oldest first) with
  the question text inlined.
- `ged__reply({"request_id", "text"})` → writes `data/replies/<id>.json`
  `{"request_id", "text", "ts"}`.
- `ged__web_search({"query"})` → DuckDuckGo HTML endpoint scrape, returns up to
  5 `{"title", "url", "snippet"}`.
- `ged__stats()` → counts by subject and type.

Paths resolve relative to the repo root (parent of `mcp/`).

## Frontend (`web/`)

Single page, no build step, no CDN. Dark, calm, readable. Three columns max.
- Subject picker (4 cards) with question counts.
- Test view: passage panel (with image if present), prompt, answer control
  chosen by `type` (radio list / text input / textarea), Check button,
  Next/Previous, running score, progress bar, "Finish test" summary.
- When a set has several questions they are shown as a group with the passage
  pinned above.
- Tutor panel (right side or drawer): chat box, "Hint", "Why was I wrong?",
  "Grade my answer" buttons; polls `/api/help/<id>` every 1.5 s.
- Keyboard: 1-4 pick an option, Enter checks, N next.
- Mobile-width friendly.

## Images (`web/img/*.svg`, `data/images.json`)

Hand-written SVG, 600x360, no external fonts. One per topic that needs it:
`foodweb.svg`, `circuit-series.svg`, `moon-phases.svg`, `plate-boundary.svg`,
`heating-curve.svg`, `water-cycle.svg`, `plant-growth.svg`, `enzyme-graph.svg`.
`data/images.json` maps `{"sci-001": "img/plant-growth.svg", ...}` and worker A
merges it into the bank.
