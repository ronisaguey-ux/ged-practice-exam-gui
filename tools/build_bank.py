#!/usr/bin/env python3
"""Build data/questions.json from the four GED study files.

Each practice section in the source files is parsed with its own answer key, so
restarting question numbers never cross-contaminate.

  ~/Ged/GED_Science.txt        -> passage sets (multi-question) with mcq items
  ~/Ged/GED_Math.txt           -> fill-in items
  ~/Ged/GED_RLA.txt            -> mcq where options exist, else fill-in
  ~/Ged/GED_Social_Studies.txt -> open-ended items
Stdlib only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HOME = Path.home()
GED = HOME / "Ged"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "questions.json"

NUM = re.compile(r"^(\d{1,3})\.\s+(.*)$")
OPT = re.compile(r"^\s{2,}([A-D])\)\s+(.*)$")
SET = re.compile(r"^SET (\d+) — (.+)$")
ANS = re.compile(r"^(\d{1,3})\.\s+([A-D])?\.?\s*(.*)$")


def lines_of(name: str) -> list[str]:
    return (GED / name).read_text(errors="replace").splitlines()


def find(lines: list[str], prefix: str, start: int = 0) -> int:
    for i in range(start, len(lines)):
        if lines[i].strip().startswith(prefix):
            return i
    return -1


def section(lines: list[str], start_prefix: str, end_prefixes: tuple[str, ...]) -> list[str]:
    s = find(lines, start_prefix)
    if s < 0:
        return []
    e = len(lines)
    for i in range(s + 1, len(lines)):
        if any(lines[i].strip().startswith(p) for p in end_prefixes):
            e = i
            break
    return lines[s:e]


# ---------------------------------------------------------------- answers
def parse_answers(block: list[str]) -> dict[int, tuple[str, str]]:
    """n -> (letter or '', explanation)."""
    out: dict[int, tuple[str, str]] = {}
    cur = None
    for l in block:
        m = ANS.match(l.strip())
        if m and int(m.group(1)) <= 200:
            cur = int(m.group(1))
            out[cur] = (m.group(2) or "", m.group(3).strip())
        elif cur is not None and l.startswith("    ") and l.strip():
            out[cur] = (out[cur][0], (out[cur][1] + " " + l.strip()).strip())
    return out


# ---------------------------------------------------------------- science
def parse_science_sets(block: list[str], answers: dict[int, tuple[str, str]]) -> list[dict]:
    out: list[dict] = []
    set_title = None
    passage: list[str] = []
    i = 0
    while i < len(block):
        raw = block[i]
        ms = SET.match(raw.strip())
        if ms:
            set_title = f"SET {ms.group(1)} — {ms.group(2)}"
            passage = []
            i += 1
            while i < len(block) and not NUM.match(block[i]) and not SET.match(block[i].strip()):
                if block[i].strip() and set(block[i].strip()) != {"-"}:
                    passage.append(block[i].strip())
                i += 1
            continue
        mq = NUM.match(raw)
        if mq:
            qn = int(mq.group(1))
            text = [mq.group(2).strip()]
            opts: list[str] = []
            i += 1
            while i < len(block) and not NUM.match(block[i]) and not SET.match(block[i].strip()):
                mo = OPT.match(block[i])
                if mo:
                    opts.append(f"{mo.group(1)}) {mo.group(2).strip()}")
                elif block[i].strip() and opts:
                    opts[-1] += " " + block[i].strip()
                elif block[i].strip():
                    text.append(block[i].strip())
                i += 1
            letter, expl = answers.get(qn, ("", ""))
            qtype = "mcq" if len(opts) == 4 else "open"
            out.append({
                "id": None, "subject": "science", "type": qtype, "set": set_title,
                "passage": " ".join(passage) or None, "image": None,
                "prompt": " ".join(text).strip(),
                "options": opts if qtype == "mcq" else [],
                "answer": letter if qtype == "mcq" else (expl or None),
                "accept": [], "explanation": expl,
            })
            continue
        i += 1
    return out


# ------------------------------------------------- generic numbered Q + key
def parse_numbered(block: list[str], answers: dict[int, tuple[str, str]],
                   subject: str, force_type: str | None = None) -> list[dict]:
    questions: dict[int, list[str]] = {}
    cur = None
    for l in block:
        m = NUM.match(l)
        if m and int(m.group(1)) <= 200:
            cur = int(m.group(1))
            questions[cur] = [m.group(2).strip()]
        elif cur is not None and l.strip() and not l.startswith("=") and not l.startswith("-") \
                and not re.match(r"^[A-Z][A-Z &,\-]{5,}$", l.strip()):
            questions[cur].append(l.strip())

    out = []
    for qn, parts in sorted(questions.items()):
        if qn not in answers:
            continue
        text = " ".join(parts).strip()
        if len(text) < 12:
            continue
        letter, expl = answers[qn]
        opts = re.findall(r"(?:^|\s)([A-D])\)\s*([^A-D]*?)(?=\s[A-D]\)|$)", text)
        qtype = force_type
        if qtype is None:
            qtype = "mcq" if len(opts) >= 3 and letter in "ABCD" else (
                "fib" if subject in ("math", "rla") else "open")
        if qtype == "mcq":
            stem = re.split(r"\s+[A-D]\)", text)[0].strip()
            out.append({"id": None, "subject": subject, "type": "mcq", "set": None,
                        "passage": None, "image": None, "prompt": stem,
                        "options": [f"{k}) {v.strip()}" for k, v in opts[:4]],
                        "answer": letter, "accept": [], "explanation": expl})
        else:
            out.append({"id": None, "subject": subject, "type": qtype, "set": None,
                        "passage": None, "image": None, "prompt": text,
                        "options": [], "answer": expl or None,
                        "accept": [], "explanation": expl})
    return out



def parse_rla_extra(block: list[str], answers: dict[int, tuple[str, str]]) -> list[dict]:
    """Numbered MCQ blocks that share a labelled PASSAGE above them."""
    out: list[dict] = []
    passage: list[str] = []
    qn = None
    buf: list[str] = []
    opts: list[list[str]] = [[]]

    def flush():
        nonlocal qn, buf, opts
        if qn is None:
            return
        letter, expl = answers.get(qn, ("", ""))
        text = " ".join(buf).strip()
        stem = re.split(r"\s+[A-D]\)", text)[0].strip()
        out.append({"id": None, "subject": "rla", "type": "mcq", "set": None,
                    "passage": " ".join(passage) or None, "image": None,
                    "prompt": stem,
                    "options": [f"{o}" for o in opts[0][:4]],
                    "answer": letter, "accept": [], "explanation": expl})
        qn, buf, opts = None, [], [[]]

    for raw in block:
        line = raw.strip()
        if line.startswith("PASSAGE"):
            flush()
            passage = []
            continue
        m = NUM.match(line)
        if m and int(m.group(1)) <= 200:
            flush()
            qn = int(m.group(1))
            buf = [m.group(2).strip()]
            opts = [[]]
            continue
        if qn is None:
            if line and not set(line) <= {"-"}:
                passage.append(line)
            continue
        mo = OPT.match(raw)
        if mo:
            opts[0].append(f"{mo.group(1)}) {mo.group(2).strip()}")
        elif line and not set(line) <= {"-"}:
            if opts[0]:
                opts[0][-1] += " " + line
            else:
                buf.append(line)
    flush()
    return out

def add_ids(qs: list[dict], prefix: str) -> None:
    for n, q in enumerate(qs, 1):
        q["id"] = f"{prefix}-{n:03d}"


def normalise_fib(q: dict) -> None:
    """Worked answers like '2x = 22 -> x = 11' become the short form 'x = 11'."""
    if q["type"] != "fib" or not q["answer"]:
        return
    work = q["answer"]
    tail = work.split("->")[-1].strip()
    if "=" in tail:
        tail = tail.split("=")[-1].strip()
    tail = tail.strip(" .$")
    if not tail or len(tail) > 40:
        tail = work
    q["answer"] = tail
    q["accept"] = sorted({tail.lower(), tail.replace(" ", "").lower(), work.lower()})
    if not q["explanation"]:
        q["explanation"] = work


def merge_images(bank: list[dict]) -> None:
    p = ROOT / "data" / "images.json"
    if not p.exists():
        return
    mapping = json.loads(p.read_text())
    for q in bank:
        if q["id"] in mapping:
            q["image"] = mapping[q["id"]]


def main() -> None:
    sci_lines = lines_of("GED_Science.txt")
    math_lines = lines_of("GED_Math.txt")
    rla_lines = lines_of("GED_RLA.txt")
    soc_lines = lines_of("GED_Social_Studies.txt")

    # science: two sets of passage-based practice, each with its own key
    sci_a = section(sci_lines, "PART 2 — GED-FORMAT PRACTICE SETS", ("ANSWERS WITH EXPLANATIONS",))
    sci_a_key = section(sci_lines, "ANSWERS WITH EXPLANATIONS", ("PART 3 —", "PART 4 —"))
    sci_b = section(sci_lines, "PART 4 — MORE GED-FORMAT PRACTICE SETS", ("ANSWERS WITH EXPLANATIONS",))
    sci_b_key = section(sci_lines, "ANSWERS WITH EXPLANATIONS", ("PART 5 —",))
    science = parse_science_sets(sci_a, parse_answers(sci_a_key))
    science += parse_science_sets(sci_b, parse_answers(sci_b_key))
    add_ids(science, "sci")

    # math: extended bank, worked-solutions set, rapid-fire
    math = []
    for start, end in (("PART 2 — EXTENDED PRACTICE BANK", ("ANSWER KEY WITH WORKED STEPS",)),
                       ("PART 5 — PRACTICE SET WITH FULLY WORKED SOLUTIONS", ("ANSWER KEY WITH WORKED STEPS",))):
        blk = section(math_lines, start, end)
        key = section(math_lines, "ANSWER KEY WITH WORKED STEPS", ("PART ", "PART 5B", "=" * 10))
        math += parse_numbered(blk, parse_answers(key), "math", "fib")
    rap = section(math_lines, "RAPID-FIRE QUESTIONS (61-100)", ("ANSWERS",))
    rap_key = section(math_lines, "ANSWERS", ("PART 5", "PART 6", "=" * 10))
    math += parse_numbered(rap, parse_answers(rap_key), "math", "fib")
    add_ids(math, "mat")

    # rla: practice set + rapid-fire
    rla = []
    blk = section(rla_lines, "PART 4 — PRACTICE QUESTIONS", ("ANSWER KEY",))
    key = section(rla_lines, "ANSWER KEY", ("PART 5 —",))
    rla += parse_numbered(blk, parse_answers(key), "rla")
    rap = section(rla_lines, "RAPID-FIRE QUESTIONS (41-80)", ("ANSWERS",))
    rap_key = section(rla_lines, "ANSWERS", ("PART 6", "=" * 10))
    rla += parse_numbered(rap, parse_answers(rap_key), "rla", "open")
    add_ids(rla, "rla")

    # social studies: practice set + rapid-fire
    soc = []
    blk = section(soc_lines, "PART 2 — PRACTICE QUESTIONS", ("ANSWER KEY",))
    key = section(soc_lines, "ANSWER KEY", ("PART 3 —",))
    soc += parse_numbered(blk, parse_answers(key), "social_studies", "open")
    rap = section(soc_lines, "RAPID-FIRE QUESTIONS (61-100)", ("ANSWERS",))
    rap_key = section(soc_lines, "ANSWERS", ("PART 4", "=" * 10))
    soc += parse_numbered(rap, parse_answers(rap_key), "social_studies", "open")
    add_ids(soc, "soc")

    # extra sections appended to the study files
    sci_tail = section(sci_lines, "PART 8 — EXTRA PRACTICE QUESTIONS", ())
    cut_s = next((i for i, l in enumerate(sci_tail) if l.strip().startswith("ANSWER KEY")), len(sci_tail))
    science += parse_science_sets(sci_tail[:cut_s], parse_answers(sci_tail[cut_s:]))

    rla_tail = section(rla_lines, "PART 7 — EXTRA PRACTICE QUESTIONS", ())
    cut = next((i for i, l in enumerate(rla_tail) if l.strip().startswith("ANSWER KEY")), len(rla_tail))
    rla += parse_rla_extra(rla_tail[:cut], parse_answers(rla_tail[cut:]))
    add_ids(science, "sci")
    add_ids(rla, "rla")
    clean, seen = [], set()
    for q in science + math + rla + soc:
        if q["id"] in seen or len(q["prompt"]) < 12:
            continue
        seen.add(q["id"])
        if q["type"] == "mcq":
            q["options"] = [re.sub(r"^[A-D]\)\s*", "", o) for o in q["options"]]
            if len(q["options"]) != 4:
                q["type"] = "open"
                q["options"] = []
        normalise_fib(q)
        clean.append(q)

    merge_images(clean)

    bank = {
        "subjects": {
            "math": {"name": "Mathematical Reasoning", "time": 115, "questions": 46},
            "science": {"name": "Science", "time": 90, "questions": 40},
            "social_studies": {"name": "Social Studies", "time": 70, "questions": 35},
            "rla": {"name": "Reasoning Through Language Arts", "time": 150, "questions": 46},
        },
        "questions": clean,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(bank, indent=1, ensure_ascii=False))
    counts, types = {}, {}
    for q in clean:
        counts[q["subject"]] = counts.get(q["subject"], 0) + 1
        types[q["type"]] = types.get(q["type"], 0) + 1
    print("total", len(clean), counts, types)


if __name__ == "__main__":
    main()
