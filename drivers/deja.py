"""Score deja-vu (github.com/vshulcz/deja-vu) on a set: index the rebuilt transcripts, then ask each question.

usage: deja.py DEJA CORPUS QUESTIONS HOME OUT_DIR

HOME holds a copy of CORPUS's `.claude`. The index is `deja index --rebuild`. Two arms, each asking every question
verbatim at deja's defaults:

- recall: `deja recall <q>`, the page deja's MCP recall tool gives an agent, with DEJA_RECALL_GLOBAL=1 and run
  from a directory that is no project of the corpus, so no project is ranked first. Its passages are the page's
  excerpts in page order, each found by its text in the session the page names. A session the page lists with
  no excerpt is a hit with no turn.
- search: `deja search --json --limit 8 <q>`. Its passages are each hit's snippets (the excerpts the text output
  prints), hit by hit, each found among the hit's messages by text and placed at that message's time, else by
  its text in the session.

Writes OUT_DIR/recall.jsonl and OUT_DIR/search.jsonl for score.py, each answer under OUT_DIR/raw, and what the
index read and how passages were placed to OUT_DIR/run.json.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Resolver, clean_env, norm, questions, run, write  # noqa: E402

HEADER = re.compile(r"^\d+\. \[[^\]]+\] ")
SESSION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
PASSAGE = re.compile(r"^(?:- |\s+→ )(.*)$")
LABEL = re.compile(r"^([A-Z][A-Za-z ]{0,24}?)(?: \([^)]*\))?: ")
PREFER = {"User": ["user"], "Model said": ["assistant"], "Output": ["user", "tool"]}


def recall_passages(page, res):
    hits, fid, shown = [], None, 0

    def close():
        if fid and not shown and res.tm.session(fid):
            hits.append({"session_id": res.tm.session(fid)})

    for line in page.splitlines():
        if HEADER.match(line):
            close()
            m = SESSION_ID.search(line)
            fid, shown = (m.group(0) if m else None), 0
            continue
        m = PASSAGE.match(line)
        if not m or fid is None:
            continue
        text = m.group(1)
        lab = LABEL.match(text)
        prefer = PREFER.get(lab.group(1)) if lab else None
        if lab:
            text = text[lab.end():]
        text = text.lstrip("→- ")
        h = res.by_text(fid, text.replace(" | ", "\n").replace(" → ", "\n"), prefer)
        if h:
            hits.append(h)
            shown += 1
    close()
    return hits


def search_passages(d, res):
    hits = []
    for h in d.get("hits") or []:
        s = h["session"]
        fid = s["id"]
        msgs = [(norm(m.get("text", "")), m.get("time")) for m in s.get("messages") or []]
        for snip in h.get("snippets") or []:
            pieces = sorted((norm(p) for p in re.split(r"…|\n", snip)), key=len, reverse=True)
            piece = pieces[0] if pieces else ""
            at = next((t for txt, t in msgs if piece and piece in txt and t), None)
            got = res.by_time(fid, at) if at else None
            got = got or res.by_text(fid, snip)
            if got:
                hits.append(got)
        if not h.get("snippets"):
            sid = res.tm.session(fid)
            if sid:
                hits.append({"session_id": sid})
    return hits


def main():
    deja, corpus, qpath, home, out = sys.argv[1:6]
    os.makedirs(os.path.join(out, "raw"), exist_ok=True)
    neutral = os.path.join(home, "neutral")
    os.makedirs(neutral, exist_ok=True)
    env = clean_env(home)
    idx = run([deja, "index", "--rebuild"], env, timeout=6 * 3600)
    # 3: the index was written, but part of the input was left unread, as its stderr names (deja's CHANGELOG).
    if idx.returncode not in (0, 3):
        raise SystemExit(f"deja index failed: {idx.stderr[-500:]}")
    res_r, res_s = Resolver(corpus), Resolver(corpus)
    with open(os.path.join(out, "recall.jsonl"), "w") as fr, open(os.path.join(out, "search.jsonl"), "w") as fs:
        for q in questions(qpath):
            r = run([deja, "recall", q["question"]], dict(env, DEJA_RECALL_GLOBAL="1"), cwd=neutral)
            open(os.path.join(out, "raw", q["id"] + ".recall.txt"), "w").write(r.stdout)
            write(fr, q["id"], recall_passages(r.stdout, res_r))
            r = run([deja, "search", "--json", "--limit", "8", q["question"]], env, cwd=neutral)
            open(os.path.join(out, "raw", q["id"] + ".search.json"), "w").write(r.stdout)
            d = json.loads(r.stdout) if r.stdout.strip() else {}
            write(fs, q["id"], search_passages(d, res_s), tier=d.get("tier"))
    info = {"version": run([deja, "--version"], env).stdout.strip(), "index_rc": idx.returncode,
            "index_stderr": idx.stderr[-600:], "recall": res_r.stats, "search": res_s.stats}
    json.dump(info, open(os.path.join(out, "run.json"), "w"), indent=1)
    print(json.dumps(info))


if __name__ == "__main__":
    main()
