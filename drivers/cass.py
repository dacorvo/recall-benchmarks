"""Score cass (github.com/Dicklesworthstone/coding_agent_session_search) on a set: index the rebuilt
transcripts, then ask each question through `cass search --robot`, its agent surface (cass has no MCP server).

usage: cass.py CASS CORPUS QUESTIONS HOME OUT_DIR PHASE

HOME holds a copy of CORPUS's `.claude`. cass keeps its data in HOME/cass-data (CASS_DATA_DIR). PHASE is:

- lexical: `cass index --full --json`, then two arms, before any semantic model is installed:
  - default: `cass search <q> --robot --limit 8`, the question verbatim at the default mode (hybrid-preferred,
    which runs lexically when no model is installed). Its lexical query is a strict AND over every word.
  - keywords: the same with deja-vu's stop words removed from the question (a concession).
- semantic: `cass models install --yes` (the optional local all-MiniLM-L6-v2 model, no key),
  `cass index --semantic --json`, then arms `hybrid` (the question verbatim at the default mode, which now
  fuses lexical and semantic results) and `hybrid-keywords` (stop words removed, a concession).

`--limit 8`: the default limit is 0 (every match, each with its whole message), so the 8 passages scored are
asked for. A passage is one hit, in order. Each hit names its file (`source_path`) and carries its message's
own timestamp (`created_at`, epoch ms), which places it at a turn exactly. Its `line_number` is not the file's
line: it is the 1-based index among the messages cass kept (it skips thinking-only records), so it is not used.

Writes OUT_DIR/<arm>.jsonl for score.py, each answer under OUT_DIR/raw, and the commands, what the index holds
and how passages were placed to OUT_DIR/run.json (merged across phases). With SKIP_BUILD=1 a phase asks its
questions over the index an earlier run of it built.
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Resolver, clean_env, keywords, norm, questions, run, ts_key, write  # noqa: E402


def iso(ms):
    dt = datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def passages(d, res, check):
    hits = []
    for h in d.get("hits") or []:
        fid = os.path.basename(h.get("source_path", ""))[: -len(".jsonl")]
        got = res.by_time(fid, iso(h["created_at"])) if h.get("created_at") else None
        if got:
            # How often the hit's text is the placed turn's text: a check of the placement, not a placement.
            row = res.by_instant[(fid, round(ts_key(iso(h["created_at"])), 3))]
            body = norm(h.get("content") or "")
            probe = body[len(body) // 2: len(body) // 2 + 60]
            if body.startswith("[tool: "):
                check["tool_render"] += 1
            elif probe and probe in res.tm.texts(fid)[row["line"]]:
                check["content_in_turn"] += 1
            else:
                check["content_not_in_turn"] += 1
        else:
            got = res.by_text(fid, h.get("content") or h.get("snippet") or "")
        if got:
            hits.append(got)
    return hits


def ask(cass, env, home, qs, query_of, arm, out_dir, corpus, check):
    res = Resolver(corpus)
    empty = 0
    with open(os.path.join(out_dir, arm + ".jsonl"), "w") as f:
        for q in qs:
            r = run([cass, "search", query_of(q["question"]), "--robot", "--limit", "8"], env, cwd=home)
            open(os.path.join(out_dir, "raw", f"{q['id']}.{arm}.json"), "w").write(r.stdout)
            if r.returncode != 0:
                raise SystemExit(f"{q['id']} {arm}: cass search failed ({r.returncode}): {r.stderr[-400:]}")
            hits = passages(json.loads(r.stdout), res, check)
            empty += not hits
            write(f, q["id"], hits)
    return dict(res.stats, empty=empty)


def realized(cass, env, home, qs, query_of):
    """The mode each of the first questions ran in, from a second call with --robot-meta (not scored)."""
    seen = {}
    for q in qs[:10]:
        r = run([cass, "search", query_of(q["question"]), "--robot", "--robot-meta", "--limit", "8"], env, cwd=home)
        m = json.loads(r.stdout).get("_meta", {})
        key = f"{m.get('search_mode')} ({m.get('fallback_reason') or m.get('semantic_refinement')})"
        seen[key] = seen.get(key, 0) + 1
    return seen


def main():
    cass, corpus, qpath, home, out_dir, phase = sys.argv[1:7]
    os.makedirs(os.path.join(out_dir, "raw"), exist_ok=True)
    env = clean_env(home, CASS_DATA_DIR=os.path.join(home, "cass-data"), CODING_AGENT_SEARCH_NO_UPDATE_PROMPT="1",
                    TUI_HEADLESS="1")
    path = os.path.join(out_dir, "run.json")
    info = json.load(open(path)) if os.path.exists(path) else {}
    info["version"] = run([cass, "--version"], env).stdout.strip()
    info["env"] = {k: v for k, v in env.items() if k != "PATH"}
    qs = questions(qpath)
    verbatim = lambda q: q  # noqa: E731
    if phase == "lexical":
        if os.path.exists(env["CASS_DATA_DIR"]):
            raise SystemExit(f"{env['CASS_DATA_DIR']} exists: remove it so the build is a first index")
        builds = [[cass, "index", "--full", "--json"]]
        arms = {"default": verbatim, "keywords": keywords}
    elif phase == "semantic":
        # `models install` takes no --json, though `cass models status` names that as its next command.
        builds = [[cass, "models", "install", "--yes"],
                  [cass, "index", "--semantic", "--json"]]
        arms = {"hybrid": verbatim, "hybrid-keywords": keywords}
    else:
        raise SystemExit(f"unknown phase {phase}")
    if os.environ.get("SKIP_BUILD"):
        builds = []
    for cmd in builds:
        r = run(cmd, env, timeout=48 * 3600)
        open(os.path.join(out_dir, "raw", f"build.{phase}.{cmd[1]}.{cmd[2]}.out"), "w").write(r.stdout + "\n" + r.stderr)
        if r.returncode != 0:
            raise SystemExit(f"{' '.join(cmd[1:])} failed ({r.returncode}): {r.stderr[-600:]}")
        try:
            d = json.loads(r.stdout)
            info.setdefault("builds", {})[" ".join(cmd[1:])] = {k: d[k] for k in ("conversations", "messages")
                                                                 if k in d}
        except ValueError:
            info.setdefault("builds", {})[" ".join(cmd[1:])] = {}
    stats = run([cass, "stats", "--json"], env).stdout
    info["stats"] = {k: v for k, v in json.loads(stats).items() if k in ("conversations", "messages", "by_agent",
                                                                       "top_workspaces")}
    for arm, query_of in arms.items():
        check = {"content_in_turn": 0, "content_not_in_turn": 0, "tool_render": 0}
        st = ask(cass, env, home, qs, query_of, arm, out_dir, corpus, check)
        info.setdefault("arms", {})[arm] = {
            "command": ["cass", "search", "<q>" if query_of is verbatim else "<keywords(q)>", "--robot", "--limit", "8"],
            "questions": len(qs), "resolver": st, "check": check,
            "realized_mode_first10": realized(cass, env, home, qs, query_of)}
        print(arm, json.dumps(info["arms"][arm]))
    json.dump(info, open(path, "w"), indent=1)


if __name__ == "__main__":
    main()
