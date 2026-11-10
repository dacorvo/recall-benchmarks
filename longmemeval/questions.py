"""Write LongMemEval's answerable questions with their answering turns in the numbering of its funes memory.

usage: questions.py LONGMEMEVAL_JSON CHUNKS > questions.jsonl

LONGMEMEVAL_JSON is `longmemeval_s_cleaned.json` from `xiaowu0162/longmemeval-cleaned`. CHUNKS is a local copy of
the `chunks.lance` of `dacorvo/funes-xiaowu0162-longmemeval-cleaned-s`, the funes memory of the file's 19,195
distinct sessions. Each answerable question (the 470 whose id does not end in `_abs`) is written verbatim, one a
line, with LongMemEval's question type as its `kind` and its reference answer:

    {"id": "e47becba", "kind": "single-session-user", "question": "…", "answer": "…",
     "gold": [{"session_id": "answer_280352e9", "turn": 4}]}

Its gold lists the evidence turns (`has_answer`) as answering turns, in the turns funes numbers: funes skips blank
turns, so a turn's `seq` is its index among its session's non-blank turns. Some sessions of the pile are copies of
each other under different ids (the same non-blank turns, role and text). A copy of a gold session holds the same
turns, so each answering turn is also named in every copy of its session, after the turns of the sessions
LongMemEval marks, with `copy_of` naming the session it copies:

    {"session_id": "280352e9", "turn": 4, "copy_of": "answer_280352e9"}

Each answering turn is checked against the memory, which must hold that turn's text.
"""
import collections
import json
import sys

import lance

OVERLAP = 150


def stitch(a, b):
    for k in range(min(len(a), len(b), OVERLAP), 0, -1):
        if a[-k:] == b[:k]:
            return a + b[k:]
    return a + b


def memory_turns(chunks):
    """Each (session, seq)'s text, its splits stitched back as funes's `chunk::stitch` does."""
    rows = lance.dataset(chunks).to_table(columns=["session_id", "seq", "split_idx", "text"]).to_pylist()
    by = collections.defaultdict(list)
    for r in rows:
        by[(r["session_id"], r["seq"])].append(r)
    turns = {}
    for key, parts in by.items():
        parts.sort(key=lambda r: r["split_idx"])
        text = parts[0]["text"]
        for r in parts[1:]:
            text = stitch(text, r["text"])
        turns[key] = text
    return turns


def copies(data):
    """Each session's copies: the other sessions of the pile with the same non-blank turns, role and text."""
    content = {}
    for q in data:
        for sid, turns in zip(q["haystack_session_ids"], q["haystack_sessions"]):
            key = tuple((t["role"], t["content"]) for t in turns if t["content"].strip())
            if content.setdefault(sid, key) != key:
                raise SystemExit(f"{sid} differs between haystacks")
    by = collections.defaultdict(list)
    for sid, key in content.items():
        by[key].append(sid)
    return {sid: sorted(s for s in by[key] if s != sid) for sid, key in content.items()}


def answers(q, mem, copy):
    marked = []
    for sid, turns in zip(q["haystack_session_ids"], q["haystack_sessions"]):
        kept = [i for i, t in enumerate(turns) if t["content"].strip()]
        for seq, i in enumerate(kept):
            if not turns[i].get("has_answer"):
                continue
            if sid not in q["answer_session_ids"]:
                raise SystemExit(f"{q['question_id']}: evidence in {sid}, which is not an answer session")
            marked.append((sid, seq, turns[i]["content"]))
    if not marked:
        raise SystemExit(f"{q['question_id']}: no evidence turn")
    out = [({"session_id": sid, "turn": seq}, text) for sid, seq, text in marked]
    for sid, seq, text in marked:
        for c in copy[sid]:
            if not any(g["session_id"] == c and g["turn"] == seq for g, _ in out):
                out.append(({"session_id": c, "turn": seq, "copy_of": sid}, text))
    for g, text in out:
        s = g["turn"]
        if mem.get((g["session_id"], s), "").strip() != text.strip():
            raise SystemExit(f"{q['question_id']}: {g['session_id']} turn {s} is not the memory's turn {s}")
    return [g for g, _ in out]


def main():
    data = json.load(open(sys.argv[1]))
    mem = memory_turns(sys.argv[2])
    copy = copies(data)
    for q in data:
        if q["question_id"].endswith("_abs"):
            continue
        print(json.dumps({"id": q["question_id"], "kind": q["question_type"], "question": q["question"],
                          "answer": q["answer"], "gold": answers(q, mem, copy)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
