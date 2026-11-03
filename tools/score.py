"""Score a tool's hits on a set's questions by the rule of funes's `score_recall`.

usage: score.py QUESTIONS HITS [--k 8] [--lenient] [--ranks]

HITS holds one JSON object a line, a question's hits in the order the tool returned them:

    {"id": "q001", "hits": [{"session_id": "…", "seq": 41}, {"session_id": "…", "from": 3, "to": 5}, …]}

A hit is a turn (`seq`), a run of turns a passage covers (`from`, `to`), or a session alone. A question's rank
is the position of its first hit in a gold span among the first K hits: a turn in the span, or a run that
overlaps it, in the gold session. A hit that names only a session is never in a span. A passage whose text is in
several turns is placed at the first (`seq`), the others listed in `alt`; `--lenient` counts it when any of them
is in the span. The session row scores the same hits by their session alone, the first K distinct sessions, as
deja-vu's day-zero page does.
"""
import argparse
import collections
import json


def in_span(hit, span, lenient=False):
    if hit.get("session_id") != span["session_id"]:
        return False
    lo, hi = span.get("from"), span.get("to")
    if lenient and hit.get("alt"):
        return any(in_span({"session_id": hit["session_id"], "seq": s}, span) for s in [hit["seq"]] + hit["alt"])
    if "seq" in hit:
        a = b = hit["seq"]
    elif "from" in hit:
        a, b = hit["from"], hit["to"]
    else:
        return False
    return (lo is None or b >= lo) and (hi is None or a <= hi)


def turn_rank(hits, gold, k, lenient=False):
    return next((i for i, h in enumerate(hits[:k]) if any(in_span(h, s, lenient) for s in gold)), None)


def session_rank(hits, gold, k):
    want = {s["session_id"] for s in gold}
    order = []
    for h in hits:
        sid = h.get("session_id")
        if sid and sid not in order:
            order.append(sid)
    return next((i for i, s in enumerate(order[:k]) if s in want), None)


def row(label, ranks):
    n = len(ranks)
    within = lambda c: sum(1 for r in ranks if r is not None and r < c)  # noqa: E731
    mrr = sum(1.0 / (r + 1) for r in ranks if r is not None) / n
    found = sum(1 for r in ranks if r is not None)
    return f"{label:28} {within(1):5} {within(5):5} {found:7}  {mrr:.3f}   (of {n})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("questions")
    ap.add_argument("hits")
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--ranks", action="store_true", help="print each question's rank")
    ap.add_argument("--lenient", action="store_true",
                    help="count a passage found in several turns when any of them is in the span")
    a = ap.parse_args()
    qs = [json.loads(l) for l in open(a.questions) if l.strip()]
    got = {}
    for l in open(a.hits):
        if l.strip():
            d = json.loads(l)
            got[d["id"]] = d
    missing = [q["id"] for q in qs if q["id"] not in got]
    if missing:
        raise SystemExit(f"{len(missing)} questions have no hits line, first {missing[0]}")
    turn, sess, empty, bykind = [], [], 0, collections.defaultdict(list)
    for q in qs:
        hits = got[q["id"]]["hits"]
        if not hits:
            empty += 1
        r = turn_rank(hits, q["gold"], a.k, a.lenient)
        turn.append(r)
        sess.append(session_rank(hits, q["gold"], a.k))
        bykind[q.get("kind") or "-"].append(r)
    print(f"{len(qs)} questions, the first {a.k} hits a question, {empty} answered with no hits")
    print()
    print(f"{'':28} hit@1 hit@5 found@{a.k}    MRR")
    print(row("all", turn))
    for kind in sorted(bykind):
        print(row("  " + kind, bykind[kind]))
    print(row("session", sess))
    if a.ranks:
        print("\nrank per question (- = not in the hits):")
        for q, r in zip(qs, turn):
            print(f"  {q['id']}  {'-' if r is None else r + 1}")


if __name__ == "__main__":
    main()
