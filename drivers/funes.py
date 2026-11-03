"""Ask funes each question through `funes recall`, as an agent does, and write its hits for score.py.

usage: funes.py FUNES MEMORY QUESTIONS OUT

MEMORY is a local copy of a funes memory, the directory holding its `chunks.lance`, at a path no session in the
memory mentions. One arm: `funes recall <q> --memory MEMORY`, the question verbatim at recall's defaults (8 hits,
reranked from a pool of 30). A hit is a `→ get` line that names MEMORY: a hit's text can quote an earlier recall,
`→ get` lines included, and those name the memory that recall read. The hit is the turn its line reads around:
`--to` is the hit's seq plus 3, never clamped (`hint_range` in funes's src/ui/render.rs).

`score_recall` (funes's benchmark/score_recall.rs) scores the same recall from its hits rather than its text.
This driver gives the hits themselves, for the session row and the paired comparison.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import questions, run, write  # noqa: E402

K = 8


def main():
    funes, memory, qpath, out = sys.argv[1:5]
    memory = os.path.abspath(memory)
    get = re.compile(r"^  → get (\S+) --from \d+ --to (\d+) --memory " + re.escape(memory) + "$", re.M)
    with open(out, "w") as f:
        for q in questions(qpath):
            r = run([funes, "recall", q["question"], "--memory", memory], dict(os.environ), cwd="/tmp")
            if r.returncode != 0:
                raise SystemExit(f"{q['id']}: funes recall failed: {r.stderr[-400:]}")
            hits = [{"session_id": sid, "seq": int(to) - 3} for sid, to in get.findall(r.stdout)]
            if len(hits) > K:
                raise SystemExit(f"{q['id']}: {len(hits)} hits name {memory}, more than recall returns")
            write(f, q["id"], hits)


if __name__ == "__main__":
    main()
