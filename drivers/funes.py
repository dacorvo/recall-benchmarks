"""Ask funes each question through `funes recall`, as an agent does, and write its hits for score.py.

usage: funes.py FUNES MEMORY QUESTIONS OUT

MEMORY is a local copy of a funes memory, the directory holding its `chunks.lance`, at a path no session in the
memory mentions. One arm: `funes recall <q> --memory MEMORY`, the question verbatim at recall's defaults (8 hits,
reranked from a pool of 30, each framed by its exchange). A hit is a `→ get` line that names MEMORY: a hit's text
can quote an earlier recall, `→ get` lines included, and those name the memory that recall read. The hit is the
turn its line reads around: `--to` is the hit's seq plus 3, never clamped (`hint_range` in funes's
src/ui/render.rs). Its frame is the `↳ [role text seqN]` lines between its text and the next hit: the turns of its
session that open and close its exchange (`attach_exchange` in src/commands/recall.rs), at most three, in turn
order. A hit whose frame lines break that shape, as a turn quoting a recall's frame would, stops the run.

`score_recall` (funes's benchmark/score_recall.rs) scores the same recall from its hits rather than its text.
This driver gives the hits themselves, for the session row and the paired comparison.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import questions, run, write  # noqa: E402

K = 8
FRAME = re.compile(r"^  ↳ \[\w+ text seq(\d+)\]$")


def hits_of(text, memory):
    """A recall's hits, each with the turns of its frame."""
    get = re.compile(r"^  → get (\S+) --from \d+ --to (\d+) --memory " + re.escape(memory) + "$")
    lines = text.split("\n")
    starts = [(i, m) for i, m in ((i, get.match(l)) for i, l in enumerate(lines)) if m]
    hits = []
    for n, (i, m) in enumerate(starts):
        # A hit's lines run to the next hit's provenance header, the line above its `→ get`.
        end = starts[n + 1][0] - 1 if n + 1 < len(starts) else len(lines)
        frame = [int(f.group(1)) for f in map(FRAME.match, lines[i + 1:end]) if f]
        hits.append({"session_id": m.group(1), "seq": int(m.group(2)) - 3, "frame": frame})
    return hits


def main():
    funes, memory, qpath, out = sys.argv[1:5]
    memory = os.path.abspath(memory)
    with open(out, "w") as f:
        for q in questions(qpath):
            r = run([funes, "recall", q["question"], "--memory", memory], dict(os.environ), cwd="/tmp")
            if r.returncode != 0:
                raise SystemExit(f"{q['id']}: funes recall failed: {r.stderr[-400:]}")
            hits = hits_of(r.stdout, memory)
            if len(hits) > K:
                raise SystemExit(f"{q['id']}: {len(hits)} hits name {memory}, more than recall returns")
            for h in hits:
                if len(h["frame"]) > 3 or h["frame"] != sorted(set(h["frame"])):
                    raise SystemExit(f"{q['id']}: the hit at {h['session_id']} {h['seq']} has frame lines {h['frame']}")
            write(f, q["id"], hits)


if __name__ == "__main__":
    main()
