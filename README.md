# GED Practice Exam GUI

A private GED practice app: four subjects plus a mixed **Mega** mode, real
question types, a point system that rewards streaks, and **Jarvis** — a
persistent tutor agent that grades open answers, explains mistakes, writes
reworded variants of what you miss, and can repair the question bank while you
use it.

No frameworks, no bundler, no CDN. Python standard library for the server,
plain HTML/CSS/JS for the interface.

---

## Quick start

```bash
ged
```

That starts the server, opens `http://127.0.0.1:8765`, and attaches the terminal
to Jarvis (tmux session `jarvis`).

```bash
ged --no-attach    # leave the terminal free
ged --stop         # stop server and Jarvis
```

First run on a fresh machine:

```bash
python3 tools/build_bank.py     # data/questions.json from ~/Ged/*.txt
python3 tools/build_site.py     # static export in site/
```

---

## The live copy

| | |
|---|---|
| URL | https://ged-practice-rs.surge.sh |
| Password | `Mongosged999` |
| Backend | `https://ged.helpotron.dpdns.org` (Cloudflare tunnel to this machine) |
| Indexing | `noindex, nofollow, noarchive` meta + Surge's own `robots.txt: Disallow: /` |

The web build is the same UI, but it talks to the local server through the
tunnel, so hints, grading and chat still reach Jarvis from a phone. The question
bank is never bundled into the static files — it is only served by the
password-protected API.

Redeploy after changing the UI:

```bash
GED_API=https://ged.helpotron.dpdns.org python3 tools/build_site.py
surge site ged-practice-rs.surge.sh
```

---

## Modes

| card | what it is |
|---|---|
| Mathematical Reasoning | 130 questions, 115 min on the real test |
| Science | 101 questions, 90 min |
| Social Studies | 100 questions, 70 min |
| Reasoning Through Language Arts | 105 questions, 150 min |
| **Mega** | all 436 questions, shuffled together |

Questions are shuffled every run, with passage sets kept together so a
stimulus is never split from its questions.

---

## Scoring

- **Correct:** +1, plus +1 for every question already on your streak — so 1, 2,
  3, 4… while you keep getting them right.
- **Wrong:** −1, plus −1 for every question on the streak, and the streak resets.
- **Open answer scored 1/2:** flat +1, streak continues (partial credit).
- **Skip:** flat **−3**, streak untouched. You cannot move past an unanswered
  question without confirming the skip in a popup — there is no silent advance.

The header always shows points, streak and score.

---

## Question types

| type | how it is graded |
|---|---|
| Multiple choice | instantly, in the browser |
| Fill in the blank | instantly, in the browser, with typo tolerance and accepted variants |
| Open ended | sent to Jarvis, who scores 0-2 against the answer guide |
| Passage sets | 2-3 questions sharing one passage, table or experiment (science) |

**Option notes.** After checking a multiple-choice question, every option
expands with a 10-30 word note explaining why it is right or wrong.

**Fill-in variants.** Each fill-in answer carries up to five accepted forms
(`3/4`, `0.75`, `x = 3/4`, …), and near-miss spellings still count for word
answers. Numbers must match.

---

## Jarvis

Jarvis is an OpenCode agent pinned to a free HY4 Flash model, running in its own
tmux pane with an isolated config (`~/.config/ged-tutor`). Its **only** MCP
server is `ged`; shell, file edits and webfetch are denied, so he cannot wander
off task.

**How a request flows**

```
GUI  --POST /api/help-->  server.py  --writes-->  data/requests/<id>.json
                                   --tmux send-keys-->  jarvis pane
Jarvis  --ged_pending_requests-->  reads the request + your progress
        --ged_reply-->             writes data/replies/<id>.json
GUI  --GET /api/help/<id>-->  shows the reply
```

Every wake carries your live state: subject, question position, score, points,
streak and the request kind. Ask `@` in the chat box to point him at a specific
question and he answers about that one instead of the current screen.

**What he can do**

| tool | purpose |
|---|---|
| `ged_pending_requests` | what you just asked, with the question inlined |
| `ged_reply` | send his answer back |
| `ged_get_question` / `ged_update_question` | read or repair a question |
| `ged_variant_jobs` / `ged_add_variant` | write reworded variants |
| `ged_session_state` | your live progress |
| `ged_web_search` | check a fact before teaching it |
| `ged_stats` / `ged_list_questions` | look around the bank |

**Variants.** Every question you answer is queued. Jarvis rewrites it — new
scenario, same skill — and schedules the variant to reappear after a random
5-25 minutes. Variants land in later runs automatically.

---

## Security

- Password required on every `/api/*` call (`X-Ged-Key`), plus the in-app gate.
- 10 failed logins per minute per IP, then 429.
- 300 requests per minute per IP otherwise.
- CORS restricted to the Surge origin and localhost.
- The bank is never shipped as a static file.

---

## Layout

| path | what |
|---|---|
| `server.py` | stdlib HTTP server: static files, grading, auth, rate limits, sessions, tutor queue |
| `web/` | `index.html`, `app.js`, `style.css`, `img/*.svg` |
| `mcp/ged_mcp.py` | the GED MCP server Jarvis uses |
| `tools/build_bank.py` | builds `data/questions.json` from the study files |
| `tools/gen_meta.py` | batch option notes and fill-in variants (free model) |
| `tools/gen_fib_local.py` | instant numeric variants, no model call |
| `tools/build_site.py` | static export for Surge |
| `tools/smoke.py` | end-to-end checks (`--tutor` waits for a real reply) |
| `bin/ged` | launcher |
| `bin/ged-jarvis` | spawn/attach the tutor |
| `data/questions.json` | 436 questions |
| `data/sessions/` | saved runs per subject |

---

## HTTP API

All endpoints require `X-Ged-Key: <password>`.

| method | path | body / result |
|---|---|---|
| GET | `/api/ping` | `{"ok":true}` (no key needed) |
| GET | `/api/questions?subject=science` | bank, filtered |
| GET | `/api/stats` | totals by subject and type |
| POST | `/api/answer` | `{id, answer}` → `{correct, expected, explanation}` |
| POST | `/api/help` | `{id, kind, answer, context, focus_id}` → `{request_id}` |
| GET | `/api/help/<id>` | `{status: pending\|done\|timeout, reply}` |
| GET | `/api/sessions` | saved runs summary |
| GET | `/api/session/<subject>` | one saved run |
| POST | `/api/session` | `{subject, progress, state}` |
| POST | `/api/reload` | re-read the bank |

`kind` is one of `hint`, `why`, `grade`, `chat`, `variant`.

---

## Services

```bash
systemctl --user status ged-server ged-tunnel
systemctl --user restart ged-server
```

- `ged-server.service` — the app on `127.0.0.1:8765`
- `ged-tunnel.service` — the Cloudflare tunnel for `ged.helpotron.dpdns.org`

Jarvis is a tmux session, not a unit: `bin/ged-jarvis --bg` starts him,
`--kill` stops him.

---

## Development

```bash
python3 tools/smoke.py            # server, grading, MCP
python3 tools/smoke.py --tutor    # also queue a request and wait for Jarvis
```

Rebuild the bank after editing `~/Ged/GED_*.txt`, then reload:

```bash
python3 tools/build_bank.py
curl -X POST -H "X-Ged-Key: $GED_PASS" http://127.0.0.1:8765/api/reload
```

The server also reloads automatically when `data/questions.json` changes on
disk, which is how Jarvis' repairs show up mid-session.

---

## Troubleshooting

| symptom | fix |
|---|---|
| `ged` opens a blank page | `systemctl --user restart ged-server`, then check `/api/stats` |
| chat never answers | `tmux ls` for `jarvis`; `bin/ged-jarvis --bg` to respawn |
| 401 on the web copy | wrong password, or the gate stored a stale key — clear site data |
| 429 on the web copy | 10 failed logins or 300 requests in a minute; wait one minute |
| tunnel down | `systemctl --user restart ged-tunnel` |
| a question looks broken | tell Jarvis; he calls `ged_update_question` |

---

## Notes

- The bank is generated from four study files in `~/Ged/`; the parsers are in
  `tools/build_bank.py` and each practice section carries its own answer key.
- `data/questions.json` is committed minified so one question set can be
  versioned as a single line.
- Everything here runs on the owner's machine; the only public surface is the
  Surge front end plus the password-gated tunnel.
