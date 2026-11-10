"""Compare several tools' hits on one set: a row each, then each against a reference, question by question.

usage: compare.py QUESTIONS REF=HITS NAME=HITS ... [--k 8]

The first NAME=HITS is the reference. Rows are score.py's: hit@1, hit@5, found@K, MRR, found@K counting sessions
alone, and the questions found as a hit, by an answering turn itself rather than in a frame. Then, for each other
tool, the questions it ranks the gold higher and lower than the reference (a miss ranks below every hit), with a
two-sided sign test, and the answers each finds that the other misses.
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from score import as_hit, load_questions, session_rank, turn_rank  # noqa: E402


def sign_p(a, b):
    n, k = a + b, min(a, b)
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def load(path):
    return {d["id"]: d for d in (json.loads(l) for l in open(path) if l.strip())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("questions")
    ap.add_argument("arms", nargs="+")
    ap.add_argument("--k", type=int, default=8)
    a = ap.parse_args()
    qs = load_questions(a.questions)
    arms = [(s.split("=", 1)[0], load(s.split("=", 1)[1])) for s in a.arms]
    ranks = {}
    print(f"{'':28} hit@1 hit@5 found@{a.k}   MRR  session@{a.k}  as a hit")
    for name, got in arms:
        hits = [got[q["id"]]["hits"] for q in qs]
        t = [turn_rank(h, q["gold"], a.k) for h, q in zip(hits, qs)]
        s = [session_rank(h, q["gold"], a.k) for h, q in zip(hits, qs)]
        own = sum(as_hit(h, q["gold"], a.k) for h, q in zip(hits, qs))
        ranks[name] = t
        within = lambda c: sum(1 for r in t if r is not None and r < c)  # noqa: E731
        mrr = sum(1 / (r + 1) for r in t if r is not None) / len(qs)
        sessions = sum(r is not None for r in s)
        print(f"{name:28} {within(1):5} {within(5):5} {within(a.k + 1):7}  {mrr:.3f}  {sessions:9}  {own:8}")
    ref, rr = arms[0][0], ranks[arms[0][0]]
    big = a.k + 1
    print(f"\nagainst {ref}, question by question (a miss ranks below every hit):")
    for name, _ in arms[1:]:
        t = ranks[name]
        higher = sum(1 for x, y in zip(t, rr) if (x if x is not None else big) < (y if y is not None else big))
        lower = sum(1 for x, y in zip(t, rr) if (x if x is not None else big) > (y if y is not None else big))
        only = sum(1 for x, y in zip(t, rr) if x is not None and y is None)
        missed = sum(1 for x, y in zip(t, rr) if x is None and y is not None)
        print(f"  {name:26} higher {higher:3}  lower {lower:3}  sign test p = {sign_p(higher, lower):.2g}"
              f"   finds {only:3} that {ref} misses, misses {missed:3} that it finds")


if __name__ == "__main__":
    main()
