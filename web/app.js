/* GED Practice — front end. No build step, no deps. */
const $ = (s) => document.querySelector(s);
const state = {
  bank: null, subject: null, questions: [], i: 0,
  answers: {}, score: 0, asked: 0,
  points: 0, streak: 0, focusId: null, mentionIdx: 0, mentionHits: [],
};

const API = (location.hostname === "127.0.0.1" || location.hostname === "localhost")
  ? "" : (window.GED_API || "");

function key() { return localStorage.getItem("gedKey") || ""; }

async function api(path, body) {
  const headers = { "X-Ged-Key": key() };
  if (body) headers["Content-Type"] = "application/json";
  const r = await fetch(API + path, body ? { method: "POST", headers, body: JSON.stringify(body) } : { headers });
  if (r.status === 401) throw new Error("401");
  return r.json();
}


/* --- offline mode ------------------------------------------------------- */
const norm = (s) => String(s || "").toLowerCase().replace(/\s+/g, " ").trim().replace(/[.]+$/, "");

function lev(a, b) {
  if (a === b) return 0;
  if (!a || !b) return a.length || b.length;
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) {
      cur.push(Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)));
    }
    prev = cur;
  }
  return prev[b.length];
}

function ratio(a, b) {
  const m = a.length, n = b.length;
  if (!m || !n) return 0;
  let prev = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= m; i++) {
    const cur = [i];
    for (let j = 1; j <= n; j++) {
      cur.push(Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)));
    }
    prev = cur;
  }
  return 1 - prev[n] / Math.max(m, n);
}

function localGrade(q, given) {
  if (q.type === "mcq") {
    return { correct: norm(given)[0] === String(q.answer).trim().toLowerCase()[0],
             expected: q.answer, explanation: q.explanation || "", type: "mcq" };
  }
  if (q.type === "fib") {
    const variants = [norm(q.answer), ...(q.accept || []).map(norm)];
    const tight = new Set(variants.map((v) => v.replace(/ /g, "")));
    const g = norm(given), gt = g.replace(/ /g, "");
    if (variants.includes(g) || tight.has(gt)) return { correct: true, expected: q.answer, explanation: q.explanation || "" };
    for (const v of variants) {
      if (v.length < 3 || !/[a-z]{3}/.test(v)) continue;
      const vt = v.replace(/ /g, "");
      if (vt.length >= 6 && ratio(gt, vt) >= 0.87) return { correct: true, expected: q.answer, explanation: q.explanation || "" };
      if (vt.length < 6 && lev(gt, vt) <= 1) return { correct: true, expected: q.answer, explanation: q.explanation || "" };
    }
    return { correct: false, expected: q.answer, explanation: q.explanation || "" };
  }
  return { correct: null, expected: q.answer, explanation: q.explanation || "" };
}

function shuffle(a) {
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

/* Group questions so a passage set stays together, then shuffle the groups. */
function randomOrder(questions) {
  const groups = new Map();
  for (const q of questions) {
    const key = q.set || q.id;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(q);
  }
  const out = [];
  for (const g of shuffle([...groups.values()])) out.push(...g);
  return out;
}

function ctx() {
  const meta = state.bank.subjects[state.subject] || {};
  return {
    subject: state.subject, subject_name: meta.name || state.subject,
    index: state.i + 1, total: state.questions.length,
    score: state.score, asked: state.asked, points: state.points, streak: state.streak,
  };
}

let lastSaveAt = 0;

function saveSession() {
  if (state.offline) return;
  lastSaveAt = Date.now() / 1000;
  api("/api/session", {
    subject: state.subject,
    progress: { index: state.i + 1, total: state.questions.length, points: state.points,
                streak: state.streak, score: state.score, asked: state.asked },
    state: { i: state.i, order: state.questions.map((q) => q.id), answers: state.answers,
             score: state.score, asked: state.asked, points: state.points, streak: state.streak },
  }).catch(() => {});
}

/* Jarvis can adjust points while you are mid-session (a regrade, a manual
   award). The page owns the counters, so without this the next autosave would
   quietly overwrite his change and the UIS would never show it. Poll the session
   and adopt any write that is newer than ours. */
let syncing = false;

async function syncExternal() {
  if (state.offline || syncing || $("#test").classList.contains("hidden")) return;
  syncing = true;
  try {
    const doc = await api(`/api/session/${state.subject}`);
    const prog = doc.progress || {};
    const stamp = Number(doc.updated || 0);
    if (stamp > lastSaveAt + 0.4 && prog.points !== undefined) {
      const before = state.points;
      const beforeStreak = state.streak;
      state.points = Number(prog.points) || 0;
      state.streak = Number(prog.streak || 0);
      paintScore();
      lastSaveAt = stamp;
      if (state.points !== before) {
        const d = state.points - before;
        addMsg("bot", `Score updated: ${before} → ${state.points} pts (${d > 0 ? "+" : ""}${d}).`
          + (state.streak !== beforeStreak ? ` Streak is now ${state.streak}.` : ""));
      }
    }
  } catch (e) {
    /* offline or no session yet - nothing to adopt */
  } finally {
    syncing = false;
  }
}

setInterval(syncExternal, 8000);

document.addEventListener("click", (e) => {
  if (e.target && e.target.id === "btn-board") loadBoard();
});

function paintScore() {
  $("#points").textContent = `${state.points} pts`;
  $("#streak").textContent = `streak ${state.streak}`;
  $("#score").textContent = `${state.score} / ${state.asked}`;
}


/* ---------------------------------------------------------- scoreboard */
const SUBJECT_ORDER = ["math", "rla", "science", "social"];

function when(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  const today = new Date();
  const same = d.toDateString() === today.toDateString();
  return same ? `${pad(d.getHours())}:${pad(d.getMinutes())}`
              : `${pad(d.getMonth() + 1)}/${pad(d.getDate())}`;
}

function esc(v) {
  return String(v == null ? "" : v).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

async function loadBoard() {
  const score = $("#scoretable tbody");
  const hist = $("#historytable tbody");
  if (!score || !hist) return;
  try {
    const [board, history] = await Promise.all([api("/api/scoreboard"), api("/api/history?limit=40")]);
    const rows = Object.entries(board.subjects || {}).sort((a, b) => {
      const ia = SUBJECT_ORDER.indexOf(a[0]), ib = SUBJECT_ORDER.indexOf(b[0]);
      return (ia < 0 ? 9 : ia) - (ib < 0 ? 9 : ib);
    });
    score.innerHTML = rows.length
      ? rows.map(([subj, s]) => `<tr><td>${esc(s.name || subj)}</td><td>${s.asked}</td><td>${s.correct}</td>` +
          `<td class="${s.accuracy >= 70 ? "ok" : s.asked && s.accuracy < 50 ? "no" : ""}">${s.accuracy}%</td>` +
          `<td>${s.points}</td><td>${s.best_streak}</td></tr>`).join("")
      : '<tr><td colspan="6" class="muted">No attempts yet.</td></tr>';

    const hrows = (history.rows || []).slice(0, 40);
    hist.innerHTML = hrows.length
      ? hrows.map((r) => {
          const badge = r.correct === true ? '<td class="ok">correct</td>'
            : r.correct === false ? '<td class="no">wrong</td>' : '<td class="muted">ungraded</td>';
          return `<tr><td>${when(r.ts)}</td><td>${esc(r.subject || "")}</td>` +
                 `<td class="q" title="${esc(r.prompt || "")}">${esc(r.prompt || r.id || "")}</td>` +
                 `<td class="q" title="${esc(r.given || "")}">${esc(r.given || "")}</td>${badge}</tr>`;
        }).join("")
      : '<tr><td colspan="5" class="muted">Nothing answered yet.</td></tr>';
  } catch (e) {
    score.innerHTML = '<tr><td colspan="6" class="muted">Scoreboard unavailable.</td></tr>';
    hist.innerHTML = '<tr><td colspan="5" class="muted">History unavailable.</td></tr>';
  }
}

/* ---------------------------------------------------------------- home */
async function unlock() {
  const box = $("#gate");
  box.classList.remove("hidden");
  $("#gateform").onsubmit = async (e) => {
    e.preventDefault();
    const v = $("#gatepass").value.trim();
    localStorage.setItem("gedKey", v);
    try {
      await api("/api/stats");
      box.classList.add("hidden");
      if (key()) { api('/api/stats').then(() => boot()).catch(() => unlock()); } else { unlock(); }
    } catch (err) {
      $("#gateerr").textContent = "Wrong password.";
      localStorage.removeItem("gedKey");
    }
  };
}

async function boot() {
  try {
    state.bank = await api("/api/questions");
  } catch (e) {
    state.offline = true;
    const r = await fetch("data/bank.json");
    state.bank = await r.json();
    $("#offline").classList.remove("hidden");
    $("#chatinput").disabled = true;
    $("#chatinput").placeholder = "Jarvis runs on your computer — open the app there to chat";
  }
  const box = $("#subjects");
  box.innerHTML = "";
  let sessions = {};
  loadBoard();
  try { sessions = await api("/api/sessions"); } catch (e) { sessions = {}; }

  const cards = Object.entries(state.bank.subjects).map(([k, m]) => ({
    key: k, name: m.name, n: state.bank.questions.filter((q) => q.subject === k).length,
    meta: `${m.time} min on the real test`,
  }));
  cards.push({ key: "mega", name: "Mega", n: state.bank.questions.length,
               meta: "all four subjects, randomized" });

  for (const c of cards) {
    const saved = sessions[c.key];
    const el = document.createElement("button");
    el.className = "card-sub" + (c.key === "mega" ? " mega" : "");
    el.innerHTML = `<h3>${c.name}</h3><span>${c.n} questions · ${c.meta}</span>`
      + (saved ? `<span class="resume">resume at ${saved.progress ? saved.progress.index : "?"} · ${saved.progress ? saved.progress.points : 0} pts</span>` : "");
    el.onclick = () => {
      if (saved && saved.state) {
        openResume(c.key, saved);
      } else {
        start(c.key);
      }
    };
    box.appendChild(el);
  }
}

function openResume(subject, saved) {
  const box = $("#modal");
  box.innerHTML = `<div class="modal-card">
      <h3>Resume ${subject}?</h3>
      <p>You have a saved run: question ${saved.progress.index} of ${saved.progress.total},
         ${saved.progress.points} points, streak ${saved.progress.streak}.</p>
      <div class="modal-actions">
        <button class="ghost" id="modal-new">Start over</button>
        <button class="primary" id="modal-resume">Resume</button>
      </div>
    </div>`;
  box.classList.remove("hidden");
  $("#modal-new").onclick = () => { box.classList.add("hidden"); start(subject); };
  $("#modal-resume").onclick = () => { box.classList.add("hidden"); start(subject, saved); };
}

function start(subject, saved) {
  state.subject = subject;
  const pool = subject === "mega" ? state.bank.questions
                                  : state.bank.questions.filter((q) => q.subject === subject);
  if (saved && saved.state && Array.isArray(saved.state.order)) {
    const byId = new Map(pool.map((q) => [q.id, q]));
    state.questions = saved.state.order.map((id) => byId.get(id)).filter(Boolean);
    state.i = saved.state.i || 0;
    state.answers = saved.state.answers || {};
    state.score = saved.state.score || 0;
    state.asked = saved.state.asked || 0;
    state.points = saved.state.points || 0;
    state.streak = saved.state.streak || 0;
  } else {
    state.questions = randomOrder(pool);
    state.i = 0; state.answers = {}; state.score = 0; state.asked = 0;
    state.points = 0; state.streak = 0;
  }
  state.focusId = null;
  $("#home").classList.add("hidden");
  $("#summary").classList.add("hidden");
  $("#test").classList.remove("hidden");
  paintScore();
  render();
  saveSession();
}

/* ---------------------------------------------------------------- test */
function q() { return state.questions[state.i]; }

function render() {
  const item = q();
  const total = state.questions.length;
  $("#counter").textContent = `${state.i + 1} / ${total}`;
  $("#fill").style.width = `${((state.i + 1) / total) * 100}%`;
  paintScore();
  $("#feedback").classList.add("hidden");

  const inSet = item.set ? state.questions.filter((x) => x.set === item.set) : [];
  const setPos = inSet.findIndex((x) => x.id === item.id);
  $("#setline").classList.toggle("hidden", !item.set);
  $("#setline").textContent = item.set
    ? `${item.set} — question ${setPos + 1} of ${inSet.length}`
    : "";
  window.scrollTo({ top: 0, behavior: "instant" });

  const hasStim = !!(item.passage || item.image);
  $("#stimulus").classList.toggle("hidden", !hasStim);
  $("#image").classList.toggle("hidden", !item.image);
  if (item.image) $("#image").src = item.image;
  $("#passage").textContent = item.passage || "";

  $("#prompt").textContent = item.prompt;

  const box = $("#answerbox");
  box.innerHTML = "";
  const saved = state.answers[item.id];

  if (item.type === "mcq") {
    item.options.forEach((text, idx) => {
      const row = document.createElement("div");
      row.className = "opt" + (saved === "ABCD"[idx] ? " sel" : "");
      row.dataset.letter = "ABCD"[idx];
      const note = (item.option_notes || [])[idx];
      row.innerHTML = `<span class="key">${"ABCD"[idx]}</span><span>${text}</span>`
        + (note ? `<div class="note hidden">${note}</div>` : "");
      row.onclick = () => {
        box.querySelectorAll(".opt").forEach((o) => o.classList.remove("sel"));
        row.classList.add("sel");
        state.answers[item.id] = row.dataset.letter;
      };
      box.appendChild(row);
    });
  } else if (item.type === "fib") {
    const inp = document.createElement("input");
    inp.type = "text"; inp.placeholder = "Type your answer";
    inp.value = saved || "";
    inp.oninput = () => (state.answers[item.id] = inp.value);
    box.appendChild(inp);
    setTimeout(() => inp.focus(), 30);
  } else {
    const ta = document.createElement("textarea");
    ta.placeholder = "Write your answer, then Check to have Jarvis grade it";
    ta.value = saved || "";
    ta.oninput = () => (state.answers[item.id] = ta.value);
    box.appendChild(ta);
  }
}

/* Points: +1 plus +1 per question already on the streak; a miss costs the same. */
function award(correct) {
  if (correct === true) {
    const gain = 1 + state.streak;
    state.points += gain;
    state.streak += 1;
    return `+${gain} pts`;
  }
  if (correct === false) {
    const loss = 1 + state.streak;
    state.points -= loss;
    state.streak = 0;
    return `−${loss} pts`;
  }
  return "";
}

async function check() {
  const item = q();
  const given = state.answers[item.id] || "";
  if (!given.trim()) return;

  const words = given.trim().split(/\s+/).filter(Boolean).length;
  if (item.type === "open" && words < 5) {
    // a handful of words is a fill-in, not an essay — grade it here, no AI
    const guide = String(item.answer || item.explanation || "").toLowerCase();
    const hit = guide.includes(given.trim().toLowerCase());
    let delta = "";
    if (!state.answers[`done-${item.id}`]) {
      state.asked++; state.answers[`done-${item.id}`] = true;
      if (hit) { delta = award(true); state.score++; } else { delta = award(false); }
    }
    paintScore(); saveSession();
    showFeedback(`${hit ? "Close enough" : "Not quite"}${delta ? `  (${delta})` : ""}`,
      `${item.answer || item.explanation || ""}<br><br><small>Short answers are checked here — write 10-20 words to get Jarvis' grading.</small>`,
      hit);
    return;
  }

  if (item.type === "open" && state.offline) {
    const guide = item.answer || item.explanation || "No guide for this one.";
    showFeedback("Answer guide", `${guide}<br><br>Score yourself:`,
      null, true);
    const box = document.createElement("div");
    box.className = "selfgrade";
    box.innerHTML = `<button data-s="2">Right (2)</button><button data-s="1">Partial (1)</button><button data-s="0">Wrong (0)</button>`;
    $("#feedback").appendChild(box);
    box.querySelectorAll("button").forEach((b) => {
      b.onclick = () => {
        const sc = Number(b.dataset.s);
        if (!state.answers[`done-${item.id}`]) {
          state.asked++; state.answers[`done-${item.id}`] = true;
          if (sc === 2) { award(true); state.score++; }
          else if (sc === 1) { state.points += 1; }
          else { award(false); }
        }
        paintScore();
        box.remove();
      };
    });
    return;
  }

  if (item.type === "open") {
    showFeedback("", "Sent to Jarvis for grading…", null, true);
    showTyping("grade");
    const { request_id } = await api("/api/help", {
      id: item.id, kind: "grade", answer: given, context: ctx(),
      guide: item.answer || "", explanation: item.explanation || "",
    });
    const reply = await waitReply(request_id);
    hideTyping();
    const m = /SCORE\s*[:=]\s*([0-2])/i.exec(reply || "");
    const score = m ? Number(m[1]) : null;
    let delta = "";
    if (!state.answers[`done-${item.id}`]) {
      state.asked++; state.answers[`done-${item.id}`] = true;
      if (score !== null) {
        if (score === 2) { delta = award(true); state.score++; }
        else if (score === 1) { state.points += 1; delta = "+1 pt (partial)"; }
        else { delta = award(false); }
      }
    }
    paintScore();
    saveSession();
    const clean = (reply || "").replace(/SCORE\s*[:=]\s*[0-2]\s*/i, "").trim();
    const head = score === null ? "Jarvis' take" : `Score ${score}/2${delta ? `  (${delta})` : ""}`;
    showFeedback(head, clean || "No answer from Jarvis yet.", score === 2, score === null);
    return;
  }

  const res = state.offline ? localGrade(item, given)
    : await api("/api/answer", { id: item.id, answer: given });
  let delta = "";
  if (!state.answers[`done-${item.id}`]) {
    state.asked++;
    if (res.correct) state.score++;
    state.answers[`done-${item.id}`] = true;
    delta = award(res.correct);
  }
  paintScore();
  saveSession();

  if (item.type === "mcq") {
    document.querySelectorAll(".opt").forEach((o) => {
      const l = o.dataset.letter;
      if (l === res.expected) o.classList.add("good");
      else if (l === given) o.classList.add("bad");
      const note = o.querySelector(".note");
      if (note) note.classList.remove("hidden");
    });
  }
  const title = (res.correct ? "Correct" : `Not quite — answer: ${res.expected}`) + (delta ? `  (${delta})` : "");
  showFeedback(title, res.explanation || "", res.correct);
  loadBoard();
}

function showFeedback(title, body, correct, neutral) {
  const el = $("#feedback");
  el.className = "feedback" + (neutral ? "" : correct ? " ok" : " no");
  el.innerHTML = `${title ? `<strong>${title}</strong>` : ""}<p>${body || ""}</p>`;
  el.classList.remove("hidden");
}

/* ---------------------------------------------------------------- tutor */

/* --- working indicator -------------------------------------------------
   Every word here describes something that is actually happening. The line
   has three honest phases and nothing else:
     sending  - the POST to /api/help is in flight
     queued   - the request file exists and Jarvis has not answered yet
                (verb says how long Jarvis has had it; timeouts are reported,
                 not hidden behind an endlessly rotating verb)
     failed   - the server said timeout, or the tutor has been silent for
                longer than the request age, so the wait is no longer real work
   There is no verb cycling: a word only changes when the state does.
   ---------------------------------------------------------------------- */
const WAIT_TEXT = {
  sending: "sending to Jarvis",
  queued: (kind) => (kind === "grade" ? "Jarvis has your answer" : "Jarvis has your question"),
  stale: "Jarvis is not answering",
};
let typingTimer = null;

function paintTyping(verb, secs, warn) {
  const d = $("#typing");
  if (!d) return;
  d.classList.toggle("warn", !!warn);
  d.innerHTML = `<span class="verb">${verb}</span><span class="dots"><i></i><i></i><i></i></span><span class="secs">${secs}s</span>`;
}

function showTyping(kind) {
  const log = $("#chatlog");
  const d = document.createElement("div");
  d.className = "msg bot typing";
  d.id = "typing";
  log.appendChild(d);
  const started = Date.now();
  paintTyping(WAIT_TEXT.sending, 0, false);
  clearInterval(typingTimer);
  // the timer only advances the elapsed counter - it never changes the verb
  typingTimer = setInterval(() => {
    paintTyping(d.dataset.verb || WAIT_TEXT.sending, Math.round((Date.now() - started) / 1000), d.dataset.warn === "1");
  }, 1000);
  log.scrollTop = log.scrollHeight;
  return { started, kind };
}

function setTypingVerb(el, verb, warn) {
  const d = $("#typing");
  if (!d) return;
  d.dataset.verb = verb;
  d.dataset.warn = warn ? "1" : "0";
  const secs = el ? Math.round((Date.now() - el.started) / 1000) : 0;
  paintTyping(verb, secs, warn);
}

function hideTyping() {
  clearInterval(typingTimer);
  typingTimer = null;
  const el = $("#typing");
  if (el) el.remove();
}

async function waitReply(id, ctx, tries = 60) {
  for (let k = 0; k < tries; k++) {
    const r = await api(`/api/help/${id}`);
    if (r.status === "done") return r.reply;
    if (r.status === "timeout") {
      setTypingVerb(ctx, WAIT_TEXT.stale, true);
      return "";
    }
    // Jarvis has had the request long enough that its own 90s promise expired
    const age = Number(r.age || 0);
    if (age > 90) {
      setTypingVerb(ctx, WAIT_TEXT.stale, true);
      return "";
    }
    setTypingVerb(ctx, WAIT_TEXT.queued(ctx && ctx.kind), false);
    await new Promise((res) => setTimeout(res, 1500));
  }
  return "";
}

async function askTutor(kind, text) {
  const item = q();
  addMsg("me", text || kind);
  setTutorState("working");
  const wait = showTyping(kind);
  const { request_id } = await api("/api/help", {
    id: item.id, kind, text: text || "", answer: state.answers[item.id] || "",
    context: ctx(), focus_id: state.focusId || null,
  });
  const reply = await waitReply(request_id, wait);
  hideTyping();
  setTutorState("ready");
  addMsg("bot", reply || "No answer from Jarvis yet — try again in a moment.");
}

function addMsg(who, text) {
  const log = $("#chatlog");
  const d = document.createElement("div");
  d.className = `msg ${who === "me" ? "me" : "bot"}`;
  d.textContent = text;
  log.appendChild(d);
  log.scrollTop = log.scrollHeight;
}

function setTutorState(s) { $("#tutor-state").textContent = s; }

/* ---------------------------------------------------------------- @mentions */
function openMention(query) {
  // only questions you have already answered are offered
  const answered = new Set(Object.keys(state.answers)
    .filter((k) => k.startsWith("done-")).map((k) => k.slice(5)));
  const all = state.bank.questions.filter((x) => answered.has(x.id));
  const ql = query.toLowerCase();
  state.mentionHits = all
    .filter((x) => !ql || x.prompt.toLowerCase().includes(ql) || x.id.includes(ql))
    .slice(0, 8);
  const count = all.length;
  const box = $("#mention");
  if (!state.mentionHits.length) {
    box.innerHTML = `<div class="mention-item"><span>${all.length ? "no match" : "answer a question first — @ lists what you have done"}</span></div>`;
    box.classList.remove("hidden");
    return;
  }
  state.mentionIdx = 0;
  box.innerHTML = `<div class="mention-head">${count} answered so far — pick one</div>`
    + state.mentionHits
      .map((x, i) => `<div class="mention-item${i === 0 ? " on" : ""}" data-id="${x.id}">
        <span class="mid">${x.id}</span><span>${x.prompt.slice(0, 70)}</span></div>`)
      .join("");
  box.classList.remove("hidden");
  box.querySelectorAll(".mention-item").forEach((el) => {
    el.onmousedown = (e) => { e.preventDefault(); pickMention(el.dataset.id); };
  });
}

function closeMention() { $("#mention").classList.add("hidden"); state.mentionHits = []; }

function pickMention(id) {
  state.focusId = id;
  const inp = $("#chatinput");
  inp.value = inp.value.replace(/@[^@]*$/, "");
  const item = state.bank.questions.find((x) => x.id === id);
  const chip = $("#focus");
  chip.innerHTML = `<span>Asking about <b>${id}</b> — ${(item.prompt || "").slice(0, 60)}</span><button type="button" id="clearfocus">×</button>`;
  chip.classList.remove("hidden");
  $("#clearfocus").onclick = () => { state.focusId = null; chip.classList.add("hidden"); };
  closeMention();
  inp.focus();
}

/* ---------------------------------------------------------------- events */
$("#btn-home").onclick = () => { $("#test").classList.add("hidden"); $("#home").classList.remove("hidden"); };
$("#btn-tutor").onclick = () => $("#tutor").scrollIntoView({ behavior: "smooth" });

/* ------------------------------------------------------------ cheat sheet */
/* A floating sheet of paper: draggable by its bar, minimisable, expandable,
   closable, and its position/size survive a reload. Autosaves; Jarvis writes
   into the same text. */
let paperTimer = null;
let paperDirty = false;

function paperPanel() { return $("#notes"); }

function paperGeometrySave() {
  const el = paperPanel();
  const r = (el.classList.contains("min") && paperBeforeMin) ? paperBeforeMin : el.getBoundingClientRect();
  localStorage.setItem("gedPaper", JSON.stringify({
    left: r.left, top: r.top, width: r.width, height: r.height,
    min: el.classList.contains("min") ? 0 : 1,
    max: el.classList.contains("max") ? 1 : 0,
  }));
}

function paperGeometryLoad() {
  const el = paperPanel();
  let g = null;
  try { g = JSON.parse(localStorage.getItem("gedPaper") || "null"); } catch (e) { g = null; }
  if (!g) return;
  if (g.max) { el.classList.add("max"); return; }
  const w = Math.min(g.width || 470, window.innerWidth - 20);
  const h = Math.min(g.height || 430, window.innerHeight - 20);
  const left = Math.max(10, Math.min(window.innerWidth - 120, g.left || 0));
  const top = Math.max(10, Math.min(window.innerHeight - 60, g.top || 0));
  el.style.left = left + "px";
  el.style.top = top + "px";
  el.style.right = "auto";
  el.style.bottom = "auto";
  el.style.width = w + "px";
  el.style.height = h + "px";
  if (!g.min) el.classList.add("min");
}

function showNotes() {
  const el = paperPanel();
  el.classList.remove("hidden");
  paperGeometryLoad();
  loadPaper();
}

async function loadPaper() {
  let doc = { text: "", by: "" };
  try {
    doc = await api("/api/paper");
  } catch (e) {
    $("#paperstatus").textContent = "offline";
  }
  if (!paperDirty) {
    $("#paper").value = doc.text || "";
    $("#paperstatus").textContent = doc.updated
      ? `${doc.by || "you"} · ${new Date(doc.updated * 1000).toLocaleTimeString()}`
      : "empty";
  }
}

async function savePaper(by) {
  paperDirty = false;
  $("#paperstatus").textContent = "saving…";
  try {
    await api("/api/paper", { text: $("#paper").value, by: by || "student" });
    $("#paperstatus").textContent = "saved";
  } catch (e) {
    $("#paperstatus").textContent = "not saved";
    paperDirty = true;
  }
}

/* drag by the bar - window-level listeners, so it works whether or not the
   browser grants pointer capture (and cannot get stuck mid-drag) */
(function paperDrag() {
  const bar = $("#paperbar");
  const el = paperPanel();
  let dx = 0, dy = 0, dragging = false;

  function move(e) {
    if (!dragging) return;
    const w = el.getBoundingClientRect().width;
    const x = Math.max(-w + 90, Math.min(window.innerWidth - 60, e.clientX - dx));
    const y = Math.max(0, Math.min(window.innerHeight - 38, e.clientY - dy));
    el.style.left = x + "px";
    el.style.top = y + "px";
    e.preventDefault();
  }
  function up() {
    if (!dragging) return;
    dragging = false;
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    paperGeometrySave();
  }
  bar.addEventListener("pointerdown", (e) => {
    if (e.target.closest("button")) return;
    const r = el.getBoundingClientRect();
    dx = e.clientX - r.left;
    dy = e.clientY - r.top;
    dragging = true;
    el.classList.remove("max");
    el.style.left = r.left + "px";
    el.style.top = r.top + "px";
    el.style.right = "auto";
    el.style.bottom = "auto";
    el.style.width = r.width + "px";
    el.style.height = r.height + "px";
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    e.preventDefault();
  });
})();

/* the bar buttons act on the panel's real size, not just a class, because the
   panel carries inline geometry from the last drag/resize */
let paperBeforeMin = null;
let paperBeforeMax = null;

function takeGeometry() {
  const r = paperPanel().getBoundingClientRect();
  return { left: r.left, top: r.top, width: r.width, height: r.height };
}
function applyGeometry(g) {
  const el = paperPanel();
  el.style.left = g.left + "px";
  el.style.top = g.top + "px";
  el.style.right = "auto";
  el.style.bottom = "auto";
  el.style.width = g.width + "px";
  el.style.height = g.height + "px";
}

$("#paper-min").onclick = () => {
  const el = paperPanel();
  if (el.classList.contains("min")) {
    el.classList.remove("min");
    if (paperBeforeMin) applyGeometry(paperBeforeMin);
    paperBeforeMin = null;
  } else {
    paperBeforeMin = takeGeometry();
    el.classList.remove("max");
    el.classList.add("min");
    el.style.height = "38px";
  }
  paperGeometrySave();
};

$("#paper-max").onclick = () => {
  const el = paperPanel();
  if (el.classList.contains("max")) {
    el.classList.remove("max");
    if (paperBeforeMax) applyGeometry(paperBeforeMax);
    paperBeforeMax = null;
  } else {
    paperBeforeMax = takeGeometry();
    el.classList.remove("min");
    el.classList.add("max");
    el.style.left = (window.innerWidth * 0.02) + "px";
    el.style.top = (window.innerHeight * 0.02) + "px";
    el.style.right = "auto";
    el.style.bottom = "auto";
    el.style.width = (window.innerWidth * 0.96) + "px";
    el.style.height = (window.innerHeight * 0.96) + "px";
  }
  paperGeometrySave();
};

$("#paper-close").onclick = () => {
  paperPanel().classList.add("hidden");
  paperGeometrySave();
};

/* manual resize (the browser's own corner grip): remember whatever size the
   student drags the panel to */
let paperResizeTimer = null;
if (typeof ResizeObserver !== "undefined") {
  new ResizeObserver(() => {
    const el = paperPanel();
    if (el.classList.contains("hidden") || el.classList.contains("min")) return;
    clearTimeout(paperResizeTimer);
    paperResizeTimer = setTimeout(paperGeometrySave, 250);
  }).observe(paperPanel());
}

$("#btn-notes").onclick = showNotes;
$("#paper").addEventListener("input", () => {
  paperDirty = true;
  $("#paperstatus").textContent = "unsaved…";
  clearTimeout(paperTimer);
  paperTimer = setTimeout(() => savePaper("student"), 900);
});
$("#paper").addEventListener("blur", () => { if (paperDirty) savePaper("student"); });
$("#btn-check").onclick = check;
$("#btn-hint").onclick = () => askTutor("hint", "Give me a hint for this one.");
$("#btn-why").onclick = () => askTutor("why", "Why is that the answer?");
$("#btn-prev").onclick = () => { if (state.i > 0) { state.i--; render(); } };
function advance() {
  if (state.i < state.questions.length - 1) {
    const before = state.questions[state.i] && state.questions[state.i].id;
    state.i++;
    // skip exact duplicates so a stale list can never show the same item twice
    let guard = 0;
    while (guard++ < 5 && state.questions[state.i] && state.questions[state.i].id === before) {
      if (state.i >= state.questions.length - 1) break;
      state.i++;
    }
    render();
    saveSession();
  } else finish();
}

function tryNext() {
  const box = $("#modal");
  if (box && !box.classList.contains("hidden")) return;   // never stack or double-fire
  const item = q();
  const answered = state.answers[`done-${item.id}`] || state.answers[`skip-${item.id}`];
  if (answered) { advance(); return; }
  openSkip(item);
}

function openSkip(item) {
  const box = $("#modal");
  box.innerHTML = `<div class="modal-card">
      <h3>Skip this question?</h3>
      <p>You have not answered it. Skipping costs <b>3 points</b> and does not break your streak (${state.streak}).</p>
      <div class="modal-actions">
        <button type="button" class="ghost" id="modal-cancel">Keep working</button>
        <button type="button" class="primary" id="modal-skip">Skip (−3)</button>
      </div>
    </div>`;
  box.classList.remove("hidden");
  const openedAt = Date.now();
  const cancel = $("#modal-cancel");
  const skip = $("#modal-skip");
  // A skip is only ever a deliberate pointer click on that button: no Enter
  // key, no key-repeat, no stray event that arrives right after the modal opens.
  skip.dataset.armed = "0";
  setTimeout(() => { skip.dataset.armed = "1"; }, 600);
  cancel.onclick = () => box.classList.add("hidden");
  cancel.focus();
  skip.onclick = (e) => {
    if (!e.isTrusted || skip.dataset.armed !== "1" || Date.now() - openedAt < 600) return;
    state.points -= 3;
    state.answers[`skip-${item.id}`] = true;
    box.classList.add("hidden");
    paintScore();
    saveSession();
    advance();
  };
}

$("#btn-next").onclick = tryNext;

$("#chatinput").addEventListener("input", (e) => {
  const v = e.target.value;
  const m = /@([^@]*)$/.exec(v);
  if (m) openMention(m[1].trim()); else closeMention();
});

$("#chatinput").addEventListener("keydown", (e) => {
  if ($("#mention").classList.contains("hidden")) return;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    state.mentionIdx = (state.mentionIdx + (e.key === "ArrowDown" ? 1 : -1) + state.mentionHits.length) % state.mentionHits.length;
    $("#mention").querySelectorAll(".mention-item").forEach((el, i) =>
      el.classList.toggle("on", i === state.mentionIdx));
  } else if (e.key === "Enter") {
    e.preventDefault();
    const hit = state.mentionHits[state.mentionIdx];
    if (hit) pickMention(hit.id);
  } else if (e.key === "Escape") {
    closeMention();
  }
});

/* chat queue: you can type and send while Jarvis is still answering. Messages
   go out one at a time, in the order you sent them. */
const chatQueue = [];
let chatBusy = false;

function paintQueue() {
  const badge = $("#queued");
  if (!badge) return;
  badge.textContent = chatQueue.length ? `${chatQueue.length} queued` : "";
  badge.classList.toggle("hidden", !chatQueue.length);
}

async function pumpChat() {
  if (chatBusy) return;
  chatBusy = true;
  while (chatQueue.length) {
    const text = chatQueue.shift();
    paintQueue();
    try {
      await askTutor("chat", text);
    } catch (err) {
      addMsg("bot", "That message did not go through. Send it again and I will retry.");
    }
  }
  chatBusy = false;
  paintQueue();
}

$("#chatform").onsubmit = (e) => {
  e.preventDefault();
  const input = $("#chatinput");
  const v = input.value.trim();
  if (!v && !state.focusId) return;
  const text = v || "Tell me about the question I pointed at.";
  input.value = "";
  closeMention();
  input.focus();            // stay in the box: keep typing the next one
  chatQueue.push(text);
  paintQueue();
  pumpChat();
};

function finish() {
  $("#test").classList.add("hidden");
  $("#summary").classList.remove("hidden");
  const pct = state.asked ? Math.round((state.score / state.asked) * 100) : 0;
  $("#summaryline").textContent =
    `${state.asked} answered, ${state.score} right (${pct}%). Points: ${state.points}. Best streak: ${state.streak}.`;
}

document.addEventListener("keydown", (e) => {
  if ($("#test").classList.contains("hidden")) return;
  const el = document.activeElement;
  if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable)) return;
  if (!($("#modal") || {}).classList || !$("#modal").classList.contains("hidden")) {
    // a modal is open: only Escape closes it, keys never reach the quiz
    if (e.key === "Escape") $("#modal").classList.add("hidden");
    return;
  }
  const item = q();
  if (["1", "2", "3", "4"].includes(e.key) && item.type === "mcq") {
    const rows = document.querySelectorAll(".opt");
    if (rows[Number(e.key) - 1]) rows[Number(e.key) - 1].click();
  } else if (e.key === "Enter" && !e.shiftKey && e.target.tagName !== "TEXTAREA") {
    e.preventDefault(); check();
  } else if (e.key.toLowerCase() === "n") {
    tryNext();
  }
});

window.__ged = state;  // handy for debugging in the console
if (key()) { api('/api/stats').then(() => boot()).catch(() => unlock()); } else { unlock(); }
