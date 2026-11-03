"""Score agentsview (github.com/kenn-io/agentsview) on a set: sync the rebuilt transcripts, then ask each question.

usage: agentsview.py AGENTSVIEW CORPUS QUESTIONS HOME OUT_DIR

HOME holds a copy of CORPUS's `.claude`. The archive is `agentsview sync` with AGENTSVIEW_NO_DAEMON=1 (its
one-shot offline sync), from an empty data directory at HOME/.agentsview. Every command runs with update
checks and telemetry off (AGENTSVIEW_DISABLE_UPDATE_CHECK=1, AGENTSVIEW_TELEMETRY_ENABLED=0). Searches go
through the daemon, started after the sync (on 127.0.0.1:8080, or a free port when that one is taken) and
stopped at the end.

Arms, each asking every question once with `agentsview session search ... --json` (50 matches by default):

- default: the question verbatim, at the defaults: a substring match, the same matches in the same order
  as the MCP tool `search_content` gives an agent.
- fts: the question verbatim with `--fts`, its tokenized full-text search (every term in one message).
- fts-keywords: `--fts` on the question with deja-vu's stop words removed. A concession: the question is
  not asked as typed.
- fts-keywords-oneshot: fts-keywords with `--include-one-shot`, to measure what the default exclusion of
  one-shot sessions costs. A diagnostic, not the tool's default.

A match is one message (or one tool input or result attached to it): placed at the transcript record its
timestamp names, in the session its id names, else by its snippet's text in that session.

Writes OUT_DIR/<arm>.jsonl for score.py, each answer under OUT_DIR/raw, and the commands, what the archive
lists and how passages were placed to OUT_DIR/run.json.
"""
import json
import os
import shutil
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Resolver, clean_env, keywords, questions, run, write  # noqa: E402

ARMS = {
    "default": lambda q: [q],
    "fts": lambda q: [q, "--fts"],
    "fts-keywords": lambda q: [keywords(q), "--fts"],
    "fts-keywords-oneshot": lambda q: [keywords(q), "--fts", "--include-one-shot"],
}
PREFER = {"user": ["user"], "assistant": ["assistant"]}


def av_env(home, **extra):
    return clean_env(home, AGENTSVIEW_DATA_DIR=os.path.join(home, ".agentsview"),
                     AGENTSVIEW_DISABLE_UPDATE_CHECK="1", AGENTSVIEW_TELEMETRY_ENABLED="0", **extra)


def port_free(port):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def listed(av, env, flags):
    """How many sessions `session list` counts (its `total`), or its error: on a large archive, listing every
    kind of session outlasts the daemon's 30-second response timeout."""
    r = run([av, "session", "list", "--json", "--limit", "1"] + flags, env)
    try:
        return json.loads(r.stdout)["total"]
    except (ValueError, KeyError):
        return r.stderr.strip()[-300:]


def fid_of(res, sid):
    """The session's file id: agentsview's id is the transcript's session id, maybe behind an agent prefix."""
    if res.tm.session(sid):
        return sid
    tail = sid.rsplit(":", 1)[-1]
    return tail if res.tm.session(tail) else None


def passages(d, res, extra):
    hits = []
    for m in d.get("matches") or []:
        fid = fid_of(res, m.get("session_id", ""))
        if not fid:
            # Kept in its place, so the passages after it keep their rank.
            extra["unknown_session"] += 1
            hits.append({"session_id": m.get("session_id")})
            continue
        got = res.by_time(fid, m["timestamp"]) if m.get("timestamp") else None
        if not got:
            loc = m.get("location")
            prefer = PREFER.get(m.get("role")) if loc == "message" else (["user", "tool"] if loc == "tool_result" else None)
            got = res.by_text(fid, m.get("snippet") or "", prefer)
        hits.append(got)
    return hits


def main():
    av, corpus, qpath, home, out = sys.argv[1:6]
    os.makedirs(os.path.join(out, "raw"), exist_ok=True)
    env = av_env(home)
    version = run([av, "version"], env).stdout.strip()
    data = os.path.join(home, ".agentsview")
    if os.path.isdir(data):
        run([av, "daemon", "stop"], env, timeout=120)
        shutil.rmtree(data)
    sync = run([av, "sync"], av_env(home, AGENTSVIEW_NO_DAEMON="1"), timeout=6 * 3600)
    if sync.returncode != 0:
        raise SystemExit(f"agentsview sync failed: {sync.stderr[-500:]}")
    port = 8080
    if not port_free(port):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        with open(os.path.join(data, "config.toml"), "a") as f:
            f.write(f"port = {port}\n")
    start = run([av, "daemon", "start"], env, timeout=300)
    if start.returncode != 0:
        raise SystemExit(f"agentsview daemon start failed: {start.stderr[-500:]}{start.stdout[-500:]}")
    qs = questions(qpath)
    stats, empty, errors = {}, {}, {}
    try:
        sessions = {"default": listed(av, env, []),
                    "all": listed(av, env, ["--include-one-shot", "--include-automated", "--include-children"])}
        for arm, args in ARMS.items():
            res = Resolver(corpus)
            extra = {"unknown_session": 0}
            empty[arm], errors[arm] = 0, 0
            with open(os.path.join(out, arm + ".jsonl"), "w") as f:
                for q in qs:
                    r = run([av, "session", "search"] + args(q["question"]) + ["--json"], env)
                    open(os.path.join(out, "raw", f"{q['id']}.{arm}.json"), "w").write(r.stdout)
                    if r.returncode != 0:
                        errors[arm] += 1
                        open(os.path.join(out, "raw", f"{q['id']}.{arm}.err"), "w").write(r.stderr)
                    d = json.loads(r.stdout) if r.stdout.strip() else {}
                    empty[arm] += not d.get("matches")
                    write(f, q["id"], passages(d, res, extra))
            stats[arm] = dict(res.stats, **extra)
    finally:
        stop = run([av, "daemon", "stop"], env, timeout=120)
    info = {"version": version, "commands": {
        "build": "AGENTSVIEW_NO_DAEMON=1 sync", "daemon": ["daemon start", "daemon stop"],
        "search": {arm: " ".join(["session search"] + args("QUESTION") + ["--json"]).replace(
            "question", "<q without stop words>").replace("QUESTION", "<q>") for arm, args in ARMS.items()},
        "env": {k: v for k, v in env.items() if k not in ("HOME", "PATH", "LANG", "TERM")}},
        "port": port, "sync_stdout": sync.stdout[-400:], "sessions_listed": sessions, "empty_answers": empty,
        "search_errors": errors, "resolver": stats, "stop_rc": stop.returncode}
    json.dump(info, open(os.path.join(out, "run.json"), "w"), indent=1)
    print(json.dumps({k: info[k] for k in ("port", "sessions_listed", "empty_answers", "search_errors", "resolver")}))


if __name__ == "__main__":
    main()
