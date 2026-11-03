"""Write LongMemEval's answerable questions with their gold spans in the numbering of its funes memory.

usage: questions.py LONGMEMEVAL_JSON CHUNKS > questions.jsonl

LONGMEMEVAL_JSON is `longmemeval_s_cleaned.json` from `xiaowu0162/longmemeval-cleaned`. CHUNKS is a local copy of
the `chunks.lance` of `dacorvo/funes-xiaowu0162-longmemeval-cleaned-s`, the funes memory of the file's 19,195
distinct sessions. Each answerable question (the 470 whose id does not end in `_abs`) is written verbatim, one a
line, with LongMemEval's question type as its `kind` and its reference answer:

    {"id": "e47becba", "kind": "single-session-user", "question": "…", "answer": "…",
     "gold": [{"session_id": "answer_280352e9", "from": 4, "to": 5}]}

A gold span is an evidence turn (`has_answer`) and the turn after it, in the turns funes numbers: funes skips
blank turns, so a turn's `seq` is its index among its session's non-blank turns. Each turn of a span is checked
against the memory, which must hold that turn's text.
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


def spans(q, mem):
    out = []
    for sid, turns in zip(q["haystack_session_ids"], q["haystack_sessions"]):
        kept = [i for i, t in enumerate(turns) if t["content"].strip()]
        for seq, i in enumerate(kept):
            if not turns[i].get("has_answer"):
                continue
            if sid not in q["answer_session_ids"]:
                raise SystemExit(f"{q['question_id']}: evidence in {sid}, which is not an answer session")
            span = range(seq, min(seq + 2, len(kept)))
            for s in span:
                if mem.get((sid, s), "").strip() != turns[kept[s]]["content"].strip():
                    raise SystemExit(f"{q['question_id']}: {sid} turn {s} is not the memory's turn {s}")
            out.append({"session_id": sid, "from": span[0], "to": span[-1]})
    if not out:
        raise SystemExit(f"{q['question_id']}: no evidence turn")
    return out


def main():
    data = json.load(open(sys.argv[1]))
    mem = memory_turns(sys.argv[2])
    for q in data:
        if q["question_id"].endswith("_abs"):
            continue
        print(json.dumps({"id": q["question_id"], "kind": q["question_type"], "question": q["question"],
                          "answer": q["answer"], "gold": spans(q, mem)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
