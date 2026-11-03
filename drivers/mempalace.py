"""Score MemPalace (github.com/MemPalace/mempalace) on a set: mine the rebuilt transcripts, then ask each question.

usage: mempalace.py VENV_BIN CORPUS QUESTIONS HOME OUT_DIR [ARM ...]
       mempalace.py build VENV_BIN HOME ARM
       mempalace.py map CORPUS HOME ARM       (run by MemPalace's own interpreter: it replays MemPalace's code)
       mempalace.py spot CORPUS OUT_DIR ARM [K]

VENV_BIN holds MemPalace's `mempalace`, `mempalace-mcp` and `python`. HOME holds a copy of CORPUS's `.claude`.
Each ARM (default: mcp) asks every question verbatim through `mempalace_search`, the search tool of MemPalace's
MCP server (`mempalace-mcp --palace P`, stdio), with `limit` 8 (its default is 5) and its other arguments at their
defaults:

- mcp: the palace `mempalace mine ~/.claude/projects/ --mode convos` builds, the backfill MemPalace documents.
- mcp-sweep (opt-in): that palace plus `mempalace sweep ~/.claude/projects/`, the per-message drawers its README
  recommends "for per-message recall on top of the file-level chunks".

A passage is one result, placed by the drawer its `drawer_id` names. The convo miner files a session as drawers of
at most 800 characters of its normalized transcript (a user prompt, then the assistant records and tool results
after it, each tool call cut to a line), numbered by `chunk_index`. `map` replays MemPalace's normalizer and
chunker on each session keeping every record's offsets, checks each chunk against the stored drawer of that index,
and gives the drawer the run of turns its text covers (`from`/`to`). A swept drawer holds one record and stores
its uuid. A result whose drawer is not mapped, or whose chunk did not match, is placed by its text. `spot` prints
K random passages (5 by default) beside the turns they were placed at.

Writes OUT_DIR/<arm>.jsonl for score.py, each answer under OUT_DIR/raw, and the commands, what the palace holds
and how passages were placed to OUT_DIR/run.json.
"""
import bisect
import collections
import json
import os
import random
import re
import shutil
import subprocess
import sys

# Appended, not prepended: this file is named like the package `map` imports under MemPalace's interpreter.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from common import Resolver, clean_env, questions, run, write  # noqa: E402
from turnmap import TurnMap, norm  # noqa: E402

PALACE = {"mcp": "palace", "mcp-sweep": "palace-sweep"}
LIMIT = 8
# What a drawer adds before a record's text: the user-turn mark, or a swept drawer's role.
ROLE_MARK = re.compile(r"^(?:> |USER: |ASSISTANT: )")


def palace_of(home, arm):
    return os.path.join(home, PALACE[arm])


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))] if xs else None


def build(venv_bin, home, arm="mcp"):
    """Mine HOME's Claude Code history the way MemPalace documents a backfill, once per arm.

    `mcp-sweep` copies the `mcp` palace and sweeps the same directory into the copy.
    """
    mp = os.path.join(venv_bin, "mempalace")
    env = clean_env(home)
    projects = os.path.join(home, ".claude", "projects") + "/"
    out = os.path.join(home, "build-" + arm + ".json")
    if os.path.exists(out):
        return json.load(open(out))
    steps = []
    if arm == "mcp":
        cmd = [mp, "--palace", palace_of(home, arm), "mine", projects, "--mode", "convos"]
    else:
        build(venv_bin, home, "mcp")
        shutil.copytree(palace_of(home, "mcp"), palace_of(home, arm))
        steps.append({"copied": palace_of(home, "mcp")})
        cmd = [mp, "--palace", palace_of(home, arm), "sweep", projects]
    r = run(cmd, env, timeout=24 * 3600)
    steps.append({"cmd": cmd, "rc": r.returncode, "stdout_tail": r.stdout[-3000:], "stderr_tail": r.stderr[-3000:]})
    if r.returncode != 0:
        raise SystemExit(f"{cmd[3]} failed ({r.returncode}): {r.stderr[-800:]}")
    st = run([mp, "--palace", palace_of(home, arm), "status"], env, timeout=3600)
    d = {"arm": arm, "steps": steps, "status": st.stdout[-4000:], "env": sorted(env)}
    json.dump(d, open(out, "w"), indent=1)
    return d


# ---- map: run by MemPalace's interpreter --------------------------------------------------------------------


def transcript(path):
    """MemPalace's normalized transcript of one Claude Code session, and the span each record's text fills.

    The steps of `normalize._try_claude_code_jsonl` and `_messages_to_transcript`, through their own helpers;
    the caller checks the text against `normalize_conversations`.
    """
    from mempalace.normalize import _extract_content, _read_transcript_file, strip_noise
    from mempalace.spellcheck import spellcheck_user_text

    content = _read_transcript_file(path)
    lines = [l.strip() for l in content.strip().split("\n") if l.strip()]
    msgs, tool_names = [], {}

    def add(role, text, ln, merge):
        if merge:
            m = msgs[-1]
            m["text"] += "\n"
            m["spans"].append((len(m["text"]), len(m["text"]) + len(text), ln))
            m["text"] += text
        else:
            msgs.append({"role": role, "text": text, "spans": [(0, len(text), ln)]})

    for ln, line in enumerate(lines):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(e, dict) or not isinstance(e.get("message", {}), dict):
            continue
        typ, c = e.get("type", ""), e.get("message", {}).get("content", "")
        if typ == "assistant" and isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id", ""):
                    tool_names[b["id"]] = b.get("name", "Unknown")
        if typ not in ("human", "user", "assistant"):
            continue
        text = _extract_content(c, tool_use_map=tool_names)
        text = strip_noise(text) if text else text
        if not text:
            continue
        if typ == "assistant":
            add("assistant", text, ln, bool(msgs) and msgs[-1]["role"] == "assistant")
        elif isinstance(c, list) and all(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            # Tool results join the assistant turn before them, or are dropped.
            if msgs and msgs[-1]["role"] == "assistant":
                add("assistant", text, ln, True)
        else:
            add("user", text, ln, False)
    if len(msgs) < 2:
        return None, [], len(lines)
    out, spans, pos, i = [], [], 0, 0

    def put(s, prefix=0, m=None):
        nonlocal pos
        if m:
            spans.extend((pos + prefix + a, pos + prefix + b, ln) for a, b, ln in m["spans"])
        out.append(s)
        pos += len(s) + 1

    while i < len(msgs):
        m = msgs[i]
        if m["role"] == "user":
            if spellcheck_user_text(m["text"]) != m["text"]:
                raise ValueError(f"{path}: spellcheck changed a user turn, offsets would shift")
            put("> " + m["text"], 2, m)
            if i + 1 < len(msgs) and msgs[i + 1]["role"] == "assistant":
                put(msgs[i + 1]["text"], 0, msgs[i + 1])
                i += 1
        else:
            put(m["text"], 0, m)
        i += 1
        put("")
    return "\n".join(out), spans, len(lines)


def squash(s):
    """s with each run of whitespace made one space, and the index in s of each character kept."""
    out, idx, ws = [], [], False
    for i, ch in enumerate(s):
        if ch.isspace():
            if not ws:
                out.append(" ")
                idx.append(i)
            ws = True
        else:
            out.append(ch)
            idx.append(i)
            ws = False
    return "".join(out), idx


def chunk_spans(text, chunks):
    """Each chunk's [start, end) in the transcript, in order. `loose` counts the chunks found only with their
    whitespace squashed: the chunker strips a user line, and joins a short unit to the drawer before it with
    one newline where the transcript has a blank line."""
    cur, out, loose, sq = 0, [], 0, None
    for ch in chunks:
        s = ch["content"]
        at = text.find(s, cur)
        if at >= 0:
            out.append((at, at + len(s)))
            cur = at + len(s)
            continue
        if sq is None:
            sq = squash(text)
        flat, idx = sq
        q = squash(s.strip())[0]
        k = flat.find(q, bisect.bisect_left(idx, cur)) if q else -1
        if k < 0:
            out.append(None)
            continue
        loose += 1
        out.append((idx[k], idx[k + len(q) - 1] + 1))
        cur = idx[k + len(q) - 1] + 1
    return out, loose


def drawer_map(corpus, home, arm):
    """drawer id -> the session and run of turns it covers, checked against the stored drawers."""
    from mempalace.config import MempalaceConfig
    from mempalace.convo_miner import MIN_CHUNK_SIZE, chunk_exchanges
    from mempalace.normalize import normalize_conversations
    from mempalace.palace import get_collection
    from mempalace.sweeper import parse_claude_jsonl

    palace = palace_of(home, arm)
    tm = TurnMap(corpus)
    cfg = MempalaceConfig(palace_path=palace)
    size = cfg.chunk_size
    floor = cfg.min_chunk_size_explicit
    floor = MIN_CHUNK_SIZE if floor is None else floor
    col = get_collection(palace, create=False, read_only=True)
    stored, off = [], 0
    while True:
        g = col.get(include=["documents", "metadatas"], limit=5000, offset=off)
        ids = g.get("ids") or []
        if not ids:
            break
        stored.extend(zip(ids, g.get("documents"), g.get("metadatas")))
        off += len(ids)
    by_file = collections.defaultdict(dict)
    swept, modes = [], collections.Counter()
    for did, doc, meta in stored:
        meta = meta or {}
        modes[meta.get("ingest_mode")] += 1
        if meta.get("ingest_mode") == "convos":
            by_file[meta["source_file"]][meta["chunk_index"]] = (did, doc)
        elif meta.get("ingest_mode") == "sweep":
            swept.append((did, doc, meta))
    st = collections.Counter()
    dmap = {}
    projects = os.path.realpath(os.path.join(home, ".claude", "projects"))
    outside = [f for f in by_file if not os.path.realpath(f).startswith(projects + os.sep)]
    for src, drawers in sorted(by_file.items()):
        fid = os.path.basename(src)[: -len(".jsonl")]
        rows = tm.by_file.get(fid)
        sid = tm.session(fid)
        text, spans, nlines = transcript(src)
        if rows is None or nlines != len(rows):
            raise SystemExit(f"{src}: {nlines} records, the turn map has {len(rows or [])}")
        mp_text = normalize_conversations(src)
        if mp_text != [text]:
            st["file_transcript_mismatch"] += 1
            continue
        chunks = chunk_exchanges(text, chunk_size=size, min_chunk_size=floor)
        if len(chunks) != len(drawers):
            st["file_count_mismatch"] += 1
        places, loose = chunk_spans(text, chunks)
        st["loose"] += loose
        starts = [a for a, _, _ in spans]
        for ch, place in zip(chunks, places):
            got = drawers.get(ch["chunk_index"])
            if got is None:
                st["chunk_not_stored"] += 1
                continue
            did, doc = got
            if place is None:
                st["chunk_not_located"] += 1
                continue
            a, b = place
            j = max(0, bisect.bisect_right(starts, a) - 1)
            lines = []
            while j < len(spans) and spans[j][0] < b:
                if spans[j][1] > a:
                    lines.append(spans[j][2])
                j += 1
            if not lines:
                st["chunk_no_record"] += 1
                continue
            # The store keeps a NUL as U+FFFD.
            nul = doc != ch["content"] and doc == ch["content"].replace("\x00", "�")
            ok = doc == ch["content"] or nul
            st["verified_nul_as_fffd" if nul else "verified" if ok else "text_differs"] += 1
            lo, hi = min(lines), max(lines)
            dmap[did] = {"fid": fid, "sid": sid, "from": rows[lo]["seq"], "to": rows[hi]["seq"], "n": hi - lo + 1,
                         "chars": len(doc), "ok": ok, "how": "chunk"}
        st["convo_drawers"] += len(drawers)
    want = {}
    for did, doc, meta in swept:
        src = meta["source_file"]
        if src not in want:
            want[src] = {r["uuid"]: f"{r['role'].upper()}: {r['content']}" for r in parse_claude_jsonl(src)}
        row = tm.by_uuid.get(meta.get("message_uuid"))
        if row is None:
            st["sweep_unknown_uuid"] += 1
            continue
        ok = want[src].get(meta["message_uuid"]) == doc
        st["sweep_verified" if ok else "sweep_text_differs"] += 1
        dmap[did] = {"fid": row["file_session_id"], "sid": row["session_id"], "from": row["seq"], "to": row["seq"],
                     "n": 1, "chars": len(doc), "ok": ok, "how": "sweep"}
    runs = [d["n"] for d in dmap.values() if d["how"] == "chunk"]
    chars = [d["chars"] for d in dmap.values() if d["how"] == "chunk"]
    stats = {"stored": len(stored), "ingest_modes": dict(modes), "sessions": len(by_file),
             "sessions_outside_projects": outside, "chunk_size": size, "min_chunk_size": floor, **st,
             "turns_per_drawer": {"p50": pct(runs, 0.5), "p90": pct(runs, 0.9), "max": max(runs or [0]),
                                  "mean": round(sum(runs) / max(1, len(runs)), 2)},
             "chars_per_drawer": {"p50": pct(chars, 0.5), "max": max(chars or [0])}}
    json.dump({"stats": stats, "drawers": dmap}, open(os.path.join(home, f"drawers-{arm}.json"), "w"))
    return stats


# ---- asking ---------------------------------------------------------------------------------------------------


class MCP:
    """A stdio MCP session, one JSON-RPC message a line."""

    def __init__(self, cmd, env, log):
        self.p = subprocess.Popen(cmd, env=env, cwd=env["HOME"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=open(log, "w"), text=True, encoding="utf-8")
        self.n = 0

    def send(self, msg):
        self.p.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.p.stdin.flush()

    def call(self, method, params=None):
        self.n += 1
        self.send({"jsonrpc": "2.0", "id": self.n, "method": method, **({"params": params} if params else {})})
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise SystemExit(f"mempalace-mcp exited ({self.p.poll()}) during {method}")
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("id") == self.n:
                return d

    def close(self):
        self.p.stdin.close()
        try:
            self.p.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self.p.kill()
            self.p.wait()


def place(r, dmap, res, xres, stats):
    """A result as a hit: by its drawer when the drawer is mapped and checked, else by its text."""
    fid = os.path.basename(r.get("source_path") or r.get("source_file") or "")
    fid = fid[: -len(".jsonl")] if fid.endswith(".jsonl") else fid
    d = dmap.get(r.get("drawer_id"))
    text = r.get("text") or ""
    if d and d["ok"]:
        stats["exact"] += 1
        h = {"session_id": d["sid"], "from": d["from"], "to": d["to"]}
        # Where the passage's text alone would put it, to measure the text resolver against the drawer's run.
        x = xres.by_text(d["fid"], ROLE_MARK.sub("", text))
        if "seq" not in x:
            stats["xcheck_text_unplaced"] += 1
        elif any(d["from"] <= s <= d["to"] for s in [x["seq"]] + x.get("alt", [])):
            stats["xcheck_text_in_run"] += 1
        else:
            stats["xcheck_text_outside_run"] += 1
        return h, d["n"]
    stats["by_text"] += 1
    h = res.by_text(fid, text)
    return h, None


def ask(venv_bin, corpus, qs, home, out, arm, dmap):
    env = clean_env(home)
    cmd = [os.path.join(venv_bin, "mempalace-mcp"), "--palace", palace_of(home, arm)]
    mcp = MCP(cmd, env, os.path.join(out, f"mcp-{arm}.stderr"))
    res, xres = Resolver(corpus), Resolver(corpus)
    stats, runs = collections.Counter(), []
    init = mcp.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "recall-benchmarks", "version": "1"}})
    mcp.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    tools = mcp.call("tools/list", {})
    json.dump({"initialize": init, "tools": tools}, open(os.path.join(out, "raw", f"tools-{arm}.json"), "w"),
              indent=1)
    with open(os.path.join(out, arm + ".jsonl"), "w") as f:
        for q in qs:
            resp = mcp.call("tools/call", {"name": "mempalace_search",
                                           "arguments": {"query": q["question"], "limit": LIMIT}})
            blocks = (resp.get("result") or {}).get("content") or []
            page = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            open(os.path.join(out, "raw", f"{q['id']}.{arm}.json"), "w").write(page)
            try:
                d = json.loads(page)
            except ValueError:
                d = {"error": "unparsed", "results": []}
            if d.get("error"):
                stats["errors"] += 1
            hits = []
            for r in d.get("results") or []:
                h, n = place(r, dmap, res, xres, stats)
                if h:
                    hits.append(h)
                if n:
                    runs.append(n)
            write(f, q["id"], hits)
    mcp.close()
    log = open(os.path.join(out, f"mcp-{arm}.stderr")).read().splitlines()
    return {"cmd": cmd, "arguments": {"limit": LIMIT},
            "embedder": next((l for l in log if "Embedding function initialized" in l), None),
            "placed": dict(stats), "text_resolver": res.stats, "xcheck_resolver": xres.stats,
            "turns_per_passage": {"p50": pct(runs, 0.5), "p90": pct(runs, 0.9), "max": max(runs or [0]),
                                  "mean": round(sum(runs) / max(1, len(runs)), 2)}}


def spot(corpus, out, arm, k=5, seed=7):
    """Print k random passages beside the turns they were placed at, each turn's text shown from where it
    holds the passage's longest line, when it does."""
    tm = TurnMap(corpus)
    seq_line = {(r["session_id"], r["seq"]): r for r in tm.rows}
    pool = []
    for l in open(os.path.join(out, arm + ".jsonl")):
        d = json.loads(l)
        page = json.loads(open(os.path.join(out, "raw", f"{d['id']}.{arm}.json")).read() or "{}")
        results = page.get("results") or []
        if len(results) != len(d["hits"]):
            raise SystemExit(f"{d['id']}: {len(results)} results, {len(d['hits'])} hits")
        pool.extend((d["id"], r, h) for r, h in zip(results, d["hits"]))
    for qid, r, h in random.Random(seed).sample(pool, k):
        print(f"=== {qid} {r.get('source_file')} {r.get('drawer_id')}\n    placed at {h}")
        print("    PASSAGE: " + norm(r["text"])[:400])
        lines = sorted((norm(ROLE_MARK.sub("", x.lstrip("→ "))) for x in r["text"].split("\n")), key=len)
        key = lines[-1][:60] if lines else ""
        lo, hi = h.get("from", h.get("seq")), h.get("to", h.get("seq"))
        for seq in range(lo, (hi if hi is not None else lo) + 1):
            row = seq_line.get((h["session_id"], seq))
            if row:
                t = tm.texts(row["file_session_id"])[row["line"]]
                at = t.find(key) if key else -1
                shown = t[max(0, at - 60): at + 240] if at >= 0 else t[:240]
                print(f"    turn {seq} [{row['role']}]{' holds its longest line' if at >= 0 else ''}: {shown}")
        print()


def main():
    if sys.argv[1] == "build":
        print(json.dumps(build(*sys.argv[2:5]), indent=1)[-3000:])
        return
    if sys.argv[1] == "map":
        print(json.dumps(drawer_map(*sys.argv[2:5]), indent=1))
        return
    if sys.argv[1] == "spot":
        spot(sys.argv[2], sys.argv[3], sys.argv[4], *(int(x) for x in sys.argv[5:6]))
        return
    venv_bin, corpus, qpath, home, out = sys.argv[1:6]
    arms = sys.argv[6:] or ["mcp"]
    os.makedirs(os.path.join(out, "raw"), exist_ok=True)
    qs = questions(qpath)
    run_json = os.path.join(out, "run.json")
    meta = json.load(open(run_json)) if os.path.exists(run_json) else {}
    ver = run([os.path.join(venv_bin, "mempalace"), "--version"], clean_env(home))
    meta.update({"version": ver.stdout.strip(), "questions": len(qs)})
    for arm in arms:
        b = build(venv_bin, home, arm)
        r = run([os.path.join(venv_bin, "python"), "-I", os.path.abspath(__file__), "map", corpus, home, arm],
                clean_env(home), timeout=6 * 3600)
        if r.returncode != 0:
            raise SystemExit(f"map failed: {r.stderr[-1500:]}")
        m = json.load(open(os.path.join(home, f"drawers-{arm}.json")))
        a = ask(venv_bin, corpus, qs, home, out, arm, m["drawers"])
        meta[arm] = {"build": {k: b[k] for k in ("steps", "status")}, "map": m["stats"], **a}
        print(json.dumps({arm: {"map": m["stats"], **{k: a[k] for k in a if k != "cmd"}}}, indent=1))
    json.dump(meta, open(run_json, "w"), indent=1)


if __name__ == "__main__":
    main()
