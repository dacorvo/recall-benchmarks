"""Score ctx (github.com/ctxrs/ctx) on a set: index the rebuilt transcripts with its own setup, then ask each question.

usage: ctx.py CTX CORPUS QUESTIONS HOME OUT_DIR [--semantic ORT_TARBALL | --resolve ARM]

HOME holds a copy of CORPUS's `.claude`. The index is `ctx setup --wait`, ctx's documented way of reading
existing history, from an empty data root at HOME/.ctx. When setup's bounded probe of `~/.claude/projects` hits
its scan budget (the source's status is `unknown`), setup indexes nothing, and the index is the targeted import
ctx's docs give instead: `ctx import --provider claude --path ~/.claude/projects`. Every command runs with
analytics and upgrade checks off (CTX_ANALYTICS_ENABLED=false, CTX_UPGRADE_AUTO=off), which changes no search.

Arm `search`: `ctx search --format json -- <q>` at ctx's defaults (lexical, 20 results, one best event per
session). ctx's MCP search tool returns the same results in the same order in its structuredContent, and
renders the first 5 of them in its text content. Each result is one event of a transcript record, placed at
that record's turn by its session file (`provider_session_id`) and the record's timestamp, which ctx returns
to the millisecond. `event_seq` holds the record's line in its high bits (line << 16): it places a result
whose timestamp is not found, and is checked against every timestamp placement. A second pass asks each
question as `ctx search -- <q>`, the text an agent is told to read, only to check that it lists the same events
in the same order.

Arm `hybrid`, with --semantic: the same search once ctx's local semantic search is ready, which makes hybrid
its default backend. It reuses the index the first arm built. The built-in E5 executor loads an ONNX Runtime
that ships apart from the binary (ORT_TARBALL, ctx's `ctx-onnxruntime-linux-x64.tar.gz` of the same release),
unpacked where ctx's installer puts it, under the data root's `runtime/onnxruntime/<version>/linux-x64`. ctx
throttles its built-in embedding by default. This arm turns that off (`builtin_throttling = false`), which
changes the pace of indexing, not the model or its vectors. A result whose snippet is a semantic passage is
placed at the messages the passage cites (`semantic_passage.citations`, line << 16 again), a run when it
cites several: its own event and timestamp are its turn's anchor, the turn's first message, which need not
hold the passage.

--resolve ARM places an arm's saved answers (OUT_DIR/raw) again with this code.

Setup starts ctx's daemon, as does enabling semantic search. `ctx index mode manual` stops it at the end.

Writes OUT_DIR/<arm>.jsonl for score.py, each answer under OUT_DIR/raw, and the commands, what the index holds
and how passages were placed to OUT_DIR/run.json.
"""
import json
import os
import re
import shutil
import sys
import tarfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Resolver, clean_env, questions, run, write  # noqa: E402

TEXT_EVENT = re.compile(r"^   Event\s+([0-9a-f]{8,32})$", re.M)
STOP = ["index", "mode", "manual", "--format", "json"]


def ctx_env(home):
    return clean_env(home, CTX_DATA_ROOT=os.path.join(home, ".ctx"), CTX_ANALYTICS_ENABLED="false",
                     CTX_UPGRADE_AUTO="off")


def passage_rows(r, res, fid):
    """The turns of the messages a semantic passage cites in the result's session. The result's own event,
    id and timestamp are its turn's anchor (the turn's first message), which need not hold the passage."""
    rows = {}
    for c in (r.get("semantic_passage") or {}).get("citations") or []:
        if c.get("target_type") == "event" and c.get("ctx_session_id") == r.get("ctx_session_id") \
                and isinstance(c.get("event_seq"), int):
            row = res.tm.line(fid, c["event_seq"] >> 16)
            if row:
                rows[row["seq"]] = row
    return [rows[s] for s in sorted(rows)]


def new_extra():
    return {"seq_agrees": 0, "seq_disagrees": 0, "by_line": 0, "unplaced": 0, "semantic_passages": 0,
            "passage_not_at_anchor": 0, "runs": 0, "run_turns": []}


def close_extra(extra):
    lengths = sorted(extra.pop("run_turns"))
    extra["run_turns_p50_max"] = [lengths[len(lengths) // 2], lengths[-1]] if lengths else None
    return extra


def passages(d, res, extra):
    hits = []
    for r in d.get("results") or []:
        fid = r.get("provider_session_id")
        seq = r.get("event_seq")
        line = seq >> 16 if isinstance(seq, int) else None
        cited = passage_rows(r, res, fid) if fid else []
        if cited:
            extra["semantic_passages"] += 1
            extra["passage_not_at_anchor"] += line not in {row["line"] for row in cited}
            if len(cited) == 1:
                hits.append(res.hit(cited[0]))
            else:
                # A passage stitched from several messages: the run of turns it cites.
                extra["runs"] += 1
                extra["run_turns"].append(cited[-1]["seq"] - cited[0]["seq"] + 1)
                hits.append({"session_id": cited[0]["session_id"], "from": cited[0]["seq"], "to": cited[-1]["seq"]})
            continue
        got = res.by_time(fid, r["timestamp"]) if fid and r.get("timestamp") else None
        if got:
            row = res.tm.by_ts.get((fid, r["timestamp"]))
            extra["seq_agrees" if row and row["line"] == line else "seq_disagrees"] += 1
        elif line is not None and res.tm.line(fid, line):
            row = res.tm.line(fid, line)
            extra["by_line"] += 1
            got = res.hit(row)
        elif fid:
            got = res.by_text(fid, r.get("snippet") or "")
        if not got:
            # Kept in its place, so the passages after it keep their rank.
            extra["unplaced"] += 1
            got = {"session_id": res.tm.session(fid) or fid}
        hits.append(got)
    return hits


def ask(ctx, env, corpus, qs, out, arm):
    """Ask every question once in JSON; returns how passages were placed, results per question, modes and the
    event ids of each answer."""
    res, extra = Resolver(corpus), new_extra()
    counts, modes, ids = {}, {}, {}
    with open(os.path.join(out, arm + ".jsonl"), "w") as f:
        for q in qs:
            r = run([ctx, "search", "--format", "json", "--", q["question"]], env)
            open(os.path.join(out, "raw", f"{q['id']}.{arm}.json"), "w").write(r.stdout)
            if r.returncode != 0:
                open(os.path.join(out, "raw", f"{q['id']}.{arm}.err"), "w").write(r.stderr)
            d = json.loads(r.stdout) if r.stdout.strip() else {}
            results = d.get("results") or []
            counts[len(results)] = counts.get(len(results), 0) + 1
            mode = (d.get("retrieval") or {}).get("effective_mode")
            modes[mode] = modes.get(mode, 0) + 1
            ids[q["id"]] = [x.get("ctx_event_id") or "" for x in results]
            write(f, q["id"], passages(d, res, extra), mode=mode)
    return dict(res.stats, **close_extra(extra)), counts, modes, ids


def lexical(ctx, env, corpus, qs, home, out):
    root = os.path.join(home, ".ctx")
    if os.path.isdir(root):
        run([ctx] + STOP, env, timeout=300)
        shutil.rmtree(root)
    setup = [ctx, "setup", "--wait", "--format", "json", "--progress", "none"]
    s = run(setup, env, timeout=6 * 3600)
    open(os.path.join(out, "setup.json"), "w").write(s.stdout)
    src = run([ctx, "sources", "--format", "json"], env)
    open(os.path.join(out, "sources.json"), "w").write(src.stdout)
    sources = json.loads(src.stdout).get("sources", [])
    commands = {"build": " ".join(setup[1:])}
    if s.returncode == 0:
        sd = json.loads(s.stdout)
        index = {k: sd.get(k) for k in ("indexed_sessions", "indexed_events", "indexed_sources", "indexed_items")}
    elif any(x.get("provider") == "claude" and x.get("status") == "unknown" for x in sources):
        # Setup's bounded probe of ~/.claude/projects hit its scan budget, so setup could not tell the source is
        # there and indexed nothing. ctx's docs give a targeted import for a source setup did not take.
        projects = os.path.join(home, ".claude", "projects")
        imp = [ctx, "import", "--provider", "claude", "--path", projects, "--format", "json", "--progress", "none"]
        i = run(imp, env, timeout=6 * 3600)
        open(os.path.join(out, "import.json"), "w").write(i.stdout)
        if i.returncode != 0:
            raise SystemExit(f"ctx import failed: {i.stderr[-500:]}")
        t = json.loads(i.stdout).get("totals") or {}
        index = {"indexed_sessions": t.get("current_indexed_sessions"),
                 "indexed_events": t.get("current_indexed_documents"),
                 "indexed_sources": t.get("current_source_count"), "rejected_records": t.get("rejected_records")}
        commands["import"] = " ".join(imp[1:]).replace(home, "~")
    else:
        run([ctx] + STOP, env, timeout=300)
        raise SystemExit(f"ctx setup failed: {s.stderr[-500:]}")
    index["sources"] = {x["path"].replace(home, "~"): x.get("status") for x in sources if x.get("status") != "missing"}
    stats, counts, modes, ids = ask(ctx, env, corpus, qs, out, "search")
    text = {"same_order": 0, "differs": 0}
    for q in qs:
        r = run([ctx, "search", "--", q["question"]], env)
        open(os.path.join(out, "raw", q["id"] + ".search.txt"), "w").write(r.stdout)
        shown = TEXT_EVENT.findall(r.stdout)
        same = len(shown) == len(ids[q["id"]]) and all(e.replace("-", "").startswith(p)
                                                       for p, e in zip(shown, ids[q["id"]]))
        text["same_order" if same else "differs"] += 1
    stop = run([ctx] + STOP, env, timeout=300)
    commands.update({"search": "search --format json -- <q>", "text": "search -- <q>", "stop": " ".join(STOP)})
    return {"commands": commands, "setup_rc": s.returncode, "index": index, "results_per_question": counts,
            "modes": modes, "search": stats, "text_pass": text, "stop_rc": stop.returncode}


def semantic(ctx, env, corpus, qs, home, out, tarball):
    root = os.path.join(home, ".ctx")
    if not os.path.isdir(root):
        raise SystemExit("no ctx index: run the lexical arm first")
    with tarfile.open(tarball) as tf:
        version = tf.extractfile("VERSION_NUMBER").read().decode().strip()
        dest = os.path.join(root, "runtime", "onnxruntime", version, "linux-x64")
        if not os.path.exists(os.path.join(dest, "lib", "libonnxruntime.so")):
            os.makedirs(dest, exist_ok=True)
            tf.extractall(dest, filter="data")
    config = os.path.join(root, "config.toml")
    if "builtin_throttling" not in (open(config).read() if os.path.exists(config) else ""):
        with open(config, "a") as f:
            f.write("\n[semantic]\nbuiltin_throttling = false\n")
    run([ctx, "index", "mode", "auto", "--format", "json"], env, timeout=300)
    enable = [ctx, "semantic", "enable", "--executor", "builtin", "--wait", "--format", "json"]
    e = run(enable, env, timeout=24 * 3600)
    open(os.path.join(out, "semantic-enable.json"), "w").write(e.stdout)
    st = run([ctx, "semantic", "status", "--format", "json"], env)
    open(os.path.join(out, "semantic-status.json"), "w").write(st.stdout)
    status = json.loads(st.stdout) if st.stdout.strip() else {}
    if status.get("status") != "ready":
        run([ctx] + STOP, env, timeout=300)
        raise SystemExit(f"ctx semantic search is not ready: {status.get('status')} {status.get('reason')}")
    stats, counts, modes, _ = ask(ctx, env, corpus, qs, out, "hybrid")
    stop = run([ctx] + STOP, env, timeout=300)
    return {"commands": {"runtime": f"{os.path.basename(tarball)} unpacked to {dest}",
                         "config": "[semantic] builtin_throttling = false", "start": "index mode auto",
                         "enable": " ".join(enable[1:]), "search": "search --format json -- <q>",
                         "stop": " ".join(STOP)},
            "enable_rc": e.returncode, "projection": status.get("projection"), "results_per_question": counts,
            "modes": modes, "search": stats, "stop_rc": stop.returncode}


def resolve(corpus, qs, out, arm):
    """Place an arm's saved answers again."""
    res, extra = Resolver(corpus), new_extra()
    path = os.path.join(out, arm + ".jsonl")
    with open(path, "w") as f:
        for q in qs:
            raw = open(os.path.join(out, "raw", f"{q['id']}.{arm}.json")).read()
            d = json.loads(raw) if raw.strip() else {}
            write(f, q["id"], passages(d, res, extra), mode=(d.get("retrieval") or {}).get("effective_mode"))
    return dict(res.stats, **close_extra(extra))


def main():
    ctx, corpus, qpath, home, out = sys.argv[1:6]
    tarball = sys.argv[sys.argv.index("--semantic") + 1] if "--semantic" in sys.argv else None
    os.makedirs(os.path.join(out, "raw"), exist_ok=True)
    env = ctx_env(home)
    qs = questions(qpath)
    path = os.path.join(out, "run.json")
    if "--resolve" in sys.argv:
        arm = sys.argv[sys.argv.index("--resolve") + 1]
        info = json.load(open(path))
        info[arm]["search"] = resolve(corpus, qs, out, arm)
        info[arm]["placed_again_from_raw"] = True
        json.dump(info, open(path, "w"), indent=1)
        print(json.dumps(info[arm]["search"]))
        return
    info = json.load(open(path)) if tarball and os.path.exists(path) else {}
    info["version"] = run([ctx, "--version"], env).stdout.strip()
    info["env"] = {k: v for k, v in env.items() if k not in ("HOME", "PATH", "LANG", "TERM")}
    arm = "hybrid" if tarball else "search"
    info[arm] = semantic(ctx, env, corpus, qs, home, out, tarball) if tarball else lexical(ctx, env, corpus, qs, home, out)
    json.dump(info, open(path, "w"), indent=1)
    print(json.dumps({k: v for k, v in info[arm].items() if k != "commands"}))


if __name__ == "__main__":
    main()
