# GED Practice Exam GUI

A local, offline-first GED practice app. Four subjects, real question types,
and Jarvis — a persistent tutor agent that grades open answers, explains
mistakes, and can fix the question bank while you use it.

No frameworks, no build step, no CDN. Python stdlib for the server, plain
HTML/CSS/JS for the UI.

## Run it

```bash
ged
```

That starts the local server, opens the browser at `http://127.0.0.1:8765`,
and attaches the terminal to Jarvis (tmux session `jarvis`).

```bash
ged --no-attach   # leave the terminal free
ged --stop        # stop server + Jarvis
```

## What is in the box

| path | what |
|---|---|
| `server.py` | stdlib HTTP server, grading for mcq/fib, request queue for the tutor |
| `web/` | the GUI (index.html, app.js, style.css, SVG diagrams) |
| `tools/build_bank.py` | builds `data/questions.json` from the study files in `~/Ged/` |
| `data/questions.json` | 378 questions: 48 multiple choice, 160 fill-in, 170 open-ended, 25 passage sets |
| `mcp/ged_mcp.py` | GED MCP server the tutor uses (questions, replies, web search) |
| `bin/ged` | launcher |
| `bin/ged-jarvis` | spawn/attach the tutor |

## Scoring

- Correct: **+1, plus +1 for every question already on your streak** (so 1, 2, 3, 4…).
- Wrong: **−1, plus −1 for every question on the streak**, and the streak resets.
- Open answers graded 1/2 earn a flat +1 (partial credit) and keep the streak.
- Skipping costs a flat **−3** and keeps the streak. You cannot move past an
  unanswered question without confirming the skip in a popup.

## Question types

- **Multiple choice** — checked locally, instant feedback.
- **Fill in the blank** — checked locally with accepted variants and numeric tolerance.
- **Open ended** — sent to Jarvis for a 0-2 grade and a one-line reason.
- **Passage sets** — science questions come in sets of 2-3 that share one
  passage, table or experiment, exactly like the real test.
- **Option notes** — after a multiple-choice check, every option gets a 10-30
  word note explaining why it is right or wrong.
- **Random order** — questions are shuffled per run, with passage sets kept
  together.

## Variants

Every answered question is queued for Jarvis, who writes a reworded variant
(different scenario, same skill) and schedules it to reappear after a random
5-25 minute delay. Variants show up in later runs automatically.

## Jarvis

Jarvis is an OpenCode agent pinned to a free HY4 Flash model, running in its own
tmux pane with an isolated config (`~/.config/ged-tutor`). Its only MCP server
is `ged` — no shell, no file edits, no other tools.

Flow: the GUI writes a request to `data/requests/`, types a wake line into the
tmux pane, Jarvis calls `ged_pending_requests`, answers with `ged_reply`, and
the GUI picks the reply up on its next poll.

He can also `ged_update_question` to repair a broken item, and `ged_web_search`
to check a fact before teaching it.

## Rebuild the bank

```bash
python3 tools/build_bank.py
```

Reads `~/Ged/GED_Science.txt`, `GED_Math.txt`, `GED_RLA.txt`,
`GED_Social_Studies.txt` and rewrites `data/questions.json`.
`data/images.json` maps question ids to the SVG diagrams.
