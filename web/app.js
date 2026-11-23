/* GED Practice — front end. No build step, no deps. */
const $ = (s) => document.querySelector(s);
const state = {
  bank: null, subject: null, questions: [], i: 0,
  answers: {}, score: 0, asked: 0, pending: new Set(),
};

async function api(path, body) {
  const opt = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {};
  const r = await fetch(path, opt);
  return r.json();
}

/* ---------------------------------------------------------------- home */
async function boot() {
  state.bank = await api("/api/questions");
  const box = $("#subjects");
  box.innerHTML = "";
  for (const [key, meta] of Object.entries(state.bank.subjects)) {
    const n = state.bank.questions.filter((q) => q.subject === key).length;
    const el = document.createElement("button");
    el.className = "card-sub";
    el.innerHTML = `<h3>${meta.name}</h3><span>${n} questions · ${meta.time} min on the real test</span>`;
    el.onclick = () => start(key);
    box.appendChild(el);
  }
}

function start(subject) {
  state.subject = subject;
  state.questions = state.bank.questions.filter((q) => q.subject === subject);
  state.i = 0; state.answers = {}; state.score = 0; state.asked = 0;
  $("#home").classList.add("hidden");
  $("#summary").classList.add("hidden");
  $("#test").classList.remove("hidden");
  render();
}


function ctx() {
  const meta = state.bank.subjects[state.subject] || {};
  return {
    subject: state.subject,
    subject_name: meta.name || state.subject,
    index: state.i + 1,
    total: state.questions.length,
    score: state.score,
    asked: state.asked,
    answered: Object.keys(state.answers).filter((k) => !k.startsWith("done-")).length,
  };
}

/* ---------------------------------------------------------------- test */
function q() { return state.questions[state.i]; }

function render() {
  const item = q();
  const total = state.questions.length;
  $("#counter").textContent = `${state.i + 1} / ${total}`;
  $("#fill").style.width = `${((state.i + 1) / total) * 100}%`;
  $("#score").textContent = `${state.score} / ${state.asked}`;
  $("#feedback").classList.add("hidden");

  $("#setline").classList.toggle("hidden", !item.set);
  $("#setline").textContent = item.set || "";

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
      row.innerHTML = `<span class="key">${"ABCD"[idx]}</span><span>${text}</span>`;
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

async function check() {
  const item = q();
  const given = state.answers[item.id] || "";
  if (!given.trim()) return;

  if (item.type === "open") {
    showFeedback("", "Sent to Jarvis for grading…", null, true);
    const { request_id } = await api("/api/help", { id: item.id, kind: "grade", answer: given, context: ctx() });
    const reply = await waitReply(request_id);
    showFeedback("", reply || "Jarvis is not answering. Compare with the model answer in the explanation.", null, true);
    if (!state.answers[`done-${item.id}`]) {
      state.asked++; state.answers[`done-${item.id}`] = true;
      $("#score").textContent = `${state.score} / ${state.asked}`;
    }
    return;
  }

  const res = await api("/api/answer", { id: item.id, answer: given });
  if (!state.answers[`done-${item.id}`]) {
    state.asked++;
    if (res.correct) state.score++;
    state.answers[`done-${item.id}`] = true;
  }
  $("#score").textContent = `${state.score} / ${state.asked}`;

  if (item.type === "mcq") {
    document.querySelectorAll(".opt").forEach((o) => {
      const l = o.dataset.letter;
      if (l === res.expected) o.classList.add("good");
      else if (l === given) o.classList.add("bad");
    });
  }
  showFeedback(res.correct ? "Correct" : `Not quite — answer: ${res.expected}`,
    res.explanation || "", res.correct);
}

function showFeedback(title, body, correct, neutral) {
  const el = $("#feedback");
  el.className = "feedback" + (neutral ? "" : correct ? " ok" : " no");
  el.innerHTML = `${title ? `<strong>${title}</strong>` : ""}<p>${body || ""}</p>`;
  el.classList.remove("hidden");
}

/* ---------------------------------------------------------------- tutor */
async function waitReply(id, tries = 60) {
  for (let k = 0; k < tries; k++) {
    const r = await api(`/api/help/${id}`);
    if (r.status === "done") return r.reply;
    if (r.status === "timeout") return "";
    await new Promise((res) => setTimeout(res, 1500));
  }
  return "";
}

async function askTutor(kind, text) {
  const item = q();
  addMsg("me", text || kind);
  setTutorState("thinking");
  const { request_id } = await api("/api/help", {
    id: item.id, kind, text: text || "", answer: state.answers[item.id] || "", context: ctx(),
  });
  const reply = await waitReply(request_id);
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

/* ---------------------------------------------------------------- events */
$("#btn-home").onclick = () => { $("#test").classList.add("hidden"); $("#home").classList.remove("hidden"); };
$("#btn-tutor").onclick = () => $("#tutor").scrollIntoView({ behavior: "smooth" });
$("#btn-check").onclick = check;
$("#btn-hint").onclick = () => askTutor("hint", "Give me a hint for this one.");
$("#btn-why").onclick = () => askTutor("why", "Why is that the answer?");
$("#btn-prev").onclick = () => { if (state.i > 0) { state.i--; render(); } };
$("#btn-next").onclick = () => {
  if (state.i < state.questions.length - 1) { state.i++; render(); }
  else finish();
};
$("#chatform").onsubmit = (e) => {
  e.preventDefault();
  const v = $("#chatinput").value.trim();
  if (!v) return;
  $("#chatinput").value = "";
  askTutor("chat", v);
};

function finish() {
  $("#test").classList.add("hidden");
  $("#summary").classList.remove("hidden");
  const pct = state.asked ? Math.round((state.score / state.asked) * 100) : 0;
  $("#summaryline").textContent = `You answered ${state.asked} questions and got ${state.score} right (${pct}%).`;
}

document.addEventListener("keydown", (e) => {
  if ($("#test").classList.contains("hidden")) return;
  const item = q();
  if (["1", "2", "3", "4"].includes(e.key) && item.type === "mcq") {
    const idx = Number(e.key) - 1;
    const rows = document.querySelectorAll(".opt");
    if (rows[idx]) rows[idx].click();
  } else if (e.key === "Enter" && !e.shiftKey && e.target.tagName !== "TEXTAREA") {
    e.preventDefault(); check();
  } else if (e.key.toLowerCase() === "n") {
    $("#btn-next").click();
  }
});

boot();
