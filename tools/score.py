"""Score a tool's hits on a set's questions by the rule of funes's `score_recall`.

usage: score.py QUESTIONS HITS [--k 8] [--lenient] [--ranks]

QUESTIONS holds one question a line, its `gold` the turns that answer it, the answer and each restatement, each a
`session_id` and a `turn`. HITS holds one JSON object a line, a question's hits in the order the tool returned
them:

    {"id": "q001", "hits": [{"session_id": "…", "seq": 41, "frame": [38, 44]}, {"session_id": "…", "from": 3, "to": 5}, …]}

A hit is a turn (`seq`), a run of turns a passage covers (`from`, `to`), or a session alone. It shows its turn or
the turns of its run, and the turns its `frame` lists: the turns of its session the tool shows beside it, such as
funes's exchange frame. A question's rank is the position of its first hit showing an answering turn among the
first K hits. `as a hit` counts the questions where one of those hits is an answering turn itself, not through its
frame. A hit that names only a session shows no turn. A passage whose text is in several turns is placed at the
first (`seq`), the others listed in `alt`; `--lenient` counts it when any of them is an answering turn. The session
row scores the same hits by their session alone, the first K distinct sessions, as deja-vu's day-zero page does.
"""
import argparse
import collections
import json


def load_questions(path):
    qs = [json.loads(l) for l in open(path) if l.strip()]
    for q in qs:
        if not q["gold"] or any("turn" not in a for a in q["gold"]):
            raise SystemExit(f"{q['id']}: its gold must list answering turns, each a `session_id` and a `turn`")
    return qs


def shows(hit, answer, lenient=False, frame=True):
    """Whether the hit shows the answering turn: as its own turn or run, or in its frame."""
    if hit.get("session_id") != answer["session_id"]:
        return False
    t = answer["turn"]
    if "seq" in hit:
        if t == hit["seq"] or (lenient and t in hit.get("alt", ())):
            return True
    elif "from" in hit and hit["from"] <= t <= hit["to"]:
        return True
    return frame and t in hit.get("frame", ())


def turn_rank(hits, gold, k, lenient=False):
    return next((i for i, h in enumerate(hits[:k]) if any(shows(h, a, lenient) for a in gold)), None)


def as_hit(hits, gold, k, lenient=False):
    """Whether one of the first K hits is an answering turn itself."""
    return any(shows(h, a, lenient, frame=False) for h in hits[:k] for a in gold)


def session_rank(hits, gold, k):
    want = {a["session_id"] for a in gold}
    order = []
    for h in hits:
        sid = h.get("session_id")
        if sid and sid not in order:
            order.append(sid)
    return next((i for i, s in enumerate(order[:k]) if s in want), None)


def row(label, ranks, own=None):
    n = len(ranks)
    within = lambda c: sum(1 for r in ranks if r is not None and r < c)  # noqa: E731
    mrr = sum(1.0 / (r + 1) for r in ranks if r is not None) / n
    found = sum(1 for r in ranks if r is not None)
    own = "" if own is None else sum(own)
    return f"{label:28} {within(1):5} {within(5):5} {found:7}  {mrr:.3f} {own:>10}   (of {n})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("questions")
    ap.add_argument("hits")
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--ranks", action="store_true", help="print each question's rank")
    ap.add_argument("--lenient", action="store_true",
                    help="count a passage found in several turns when any of them is an answering turn")
    a = ap.parse_args()
    qs = load_questions(a.questions)
    got = {}
    for l in open(a.hits):
        if l.strip():
            d = json.loads(l)
            got[d["id"]] = d
    missing = [q["id"] for q in qs if q["id"] not in got]
    if missing:
        raise SystemExit(f"{len(missing)} questions have no hits line, first {missing[0]}")
    turn, own, sess, empty = [], [], [], 0
    bykind = collections.defaultdict(lambda: ([], []))
    for q in qs:
        hits = got[q["id"]]["hits"]
        if not hits:
            empty += 1
        r = turn_rank(hits, q["gold"], a.k, a.lenient)
        o = as_hit(hits, q["gold"], a.k, a.lenient)
        turn.append(r)
        own.append(o)
        sess.append(session_rank(hits, q["gold"], a.k))
        bykind[q.get("kind") or "-"][0].append(r)
        bykind[q.get("kind") or "-"][1].append(o)
    print(f"{len(qs)} questions, the first {a.k} hits a question, {empty} answered with no hits")
    print()
    print(f"{'':28} hit@1 hit@5 found@{a.k}    MRR   as a hit")
    print(row("all", turn, own))
    for kind in sorted(bykind):
        print(row("  " + kind, *bykind[kind]))
    print(row("session", sess))
    if a.ranks:
        print("\nrank per question (- = no hit shows an answering turn):")
        for q, r in zip(qs, turn):
            print(f"  {q['id']}  {'-' if r is None else r + 1}")


if __name__ == "__main__":
    main()
