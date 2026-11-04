"""Score claude-history (github.com/raine/claude-history) on a set: ask each question through
`claude-history agent search`, the retrieval interface its Claude Code skill gives an agent.

usage: claude_history.py CLAUDE_HISTORY CORPUS QUESTIONS HOME OUT_DIR PHASE [ARM ...]

HOME holds a copy of CORPUS's `.claude`. claude-history reads `~/.claude/projects` directly and keeps its
keyword store and semantic cache under HOME/.cache/claude-history. Commands run from HOME, which is no project
of the corpus (agent search is global by default anyway). Each ARM names one of the phase's arms to ask (default:
all of them). PHASE is:

- lexical: the first command on an empty cache builds the keyword store, then two arms:
  - default: `agent search <q>`, the question verbatim at the defaults (lexical, which needs every word to
    match; 10 conversations, 2 hits each, a 6000-character output budget that cuts the tail).
  - keywords: the same with deja-vu's stop words removed from the question (a concession).
- semantic: `claude-history --generate-semantic-cache` embeds every conversation (the local
  snowflake-arctic-embed-xs model, no key), then arms `semantic` (`--mode semantic`) and `hybrid`
  (`--mode hybrid`), the two modes the skill gives for conceptual recall, each with the question verbatim.
- unbudgeted: no build; `keywords`, `semantic` and `hybrid` again with `--no-budget`, since the default
  6000-character budget shows fewer than 8 passages for most questions (asking for 8, by the rules).

A passage is one `hit` record, in output order. A conversation record whose hits the budget cut is a hit with
no turn. A hit's `focus=mA..mB` names canonical message ordinals; each is placed at the file line that the
tool's own `agent read` gives for that ordinal (`message mN ... line=L`, 1-based), read once per session with
every message shown, and kept in OUT_DIR/raw/ordinal_lines.json for the other phases. The ordinals skip records
the tool does not list (local-command records), so they are not file lines themselves. A focus of several
messages is a `from`/`to` run. Semantic hits can focus on long runs (a chunk of conversation text spans the
tool calls between its messages), so OUT_DIR/<arm>.narrowed.jsonl also places each run at the first turn inside
it that holds the hit's preview, a bound on what runs add.

Writes OUT_DIR/<arm>.jsonl for score.py, each answer under OUT_DIR/raw, and the commands and how passages were
placed to OUT_DIR/run.json (merged across phases). With SKIP_BUILD=1 a phase asks its questions over the store
or cache an earlier run of it built.
"""
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Resolver, clean_env, keywords, questions, run, write  # noqa: E402

ATOM = re.compile(r"(\w[\w-]*)=(\S*)")
MESSAGE = re.compile(r"^message m(\d+) role=\S+ line=(\d+) ", re.M)
FOCUS = re.compile(r"^m(\d+)\.\.m(\d+)$")


def atoms(line):
    head, _, text = line.partition(" | ")
    return dict(ATOM.findall(head)), text


def ordinal_lines(ch, env, home, tm, out_dir):
    """Each session's ordinal -> 1-based file line, as `agent read` prints them with every message shown."""
    path = os.path.join(out_dir, "raw", "ordinal_lines.json")
    if os.path.exists(path):
        return {fid: {int(m): l for m, l in t.items()} for fid, t in json.load(open(path)).items()}
    table = {}
    for fid in sorted(tm.by_file):
        r = run([ch, "agent", "read", fid, "--tools", "--tool-results", "--thinking", "--subagents", "--no-budget"],
                env, cwd=home)
        if r.returncode != 0:
            raise SystemExit(f"agent read {fid} failed: {r.stderr[-300:]}")
        table[fid] = {int(m): int(l) for m, l in MESSAGE.findall(r.stdout)}
    json.dump(table, open(path, "w"))
    return table


def passages(stdout, res, table, check):
    """The hits, and the same hits with each run narrowed to the turn of the run that holds its preview."""
    hits, narrowed, conv, shown = [], [], None, 0

    def close():
        if conv and not shown and res.tm.session(conv):
            hits.append({"session_id": res.tm.session(conv)})
            narrowed.append(hits[-1])
            res.stats["session_only"] += 1

    for line in stdout.splitlines():
        kind = line.split(" ", 1)[0]
        if kind == "conversation":
            close()
            conv, shown = atoms(line)[0].get("uuid"), 0
        elif kind == "hit":
            a, text = atoms(line)
            fid, m = a.get("uuid"), FOCUS.match(a.get("focus", ""))
            lines = [table.get(fid, {}).get(int(g)) for g in m.groups()] if m else [None]
            rows = [res.tm.line(fid, n - 1) for n in lines] if None not in lines else [None]
            if None in rows:
                h = nh = res.by_text(fid, text)
            else:
                sid = rows[0]["session_id"]
                h = ({"session_id": sid, "seq": rows[0]["seq"]} if rows[0] is rows[1] else
                     {"session_id": sid, "from": rows[0]["seq"], "to": rows[1]["seq"]})
                res.stats["exact"] += 1
                check["run_len"][lines[1] - lines[0] + 1] += 1
                # Whether the hit's preview is the text of a turn it was placed at: a check, not a placement.
                found = {r["line"] for r in res.tm.locate(fid, text)}
                at = set(range(lines[0] - 1, lines[1]))
                check["preview_in_turn" if found & at else "preview_elsewhere" if found else "preview_nowhere"] += 1
                inside = sorted(found & at)
                nh = {"session_id": sid, "seq": res.tm.line(fid, inside[0])["seq"]} if "from" in h and inside else h
            if h:
                hits.append(h)
                narrowed.append(nh)
                shown += 1
    close()
    return hits, narrowed


def main():
    ch, corpus, qpath, home, out_dir, phase = sys.argv[1:7]
    os.makedirs(os.path.join(out_dir, "raw"), exist_ok=True)
    env = clean_env(home)
    path = os.path.join(out_dir, "run.json")
    info = json.load(open(path)) if os.path.exists(path) else {}
    info["version"] = run([ch, "--version"], env).stdout.strip()
    info["env"] = {k: v for k, v in env.items() if k != "PATH"}
    qs = questions(qpath)
    verbatim = lambda q: q  # noqa: E731
    if phase == "lexical":
        store = os.path.join(home, ".cache", "claude-history", "v3")
        if os.path.exists(store):
            raise SystemExit(f"{store} exists: remove it so the first command builds the keyword store")
        build = [ch, "agent", "search", "warmup"]
        arms = {"default": (verbatim, []), "keywords": (keywords, [])}
    elif phase == "semantic":
        build = [ch, "--generate-semantic-cache"]
        arms = {"semantic": (verbatim, ["--mode", "semantic"]), "hybrid": (verbatim, ["--mode", "hybrid"])}
    elif phase == "unbudgeted":
        build = None
        arms = {"keywords-nobudget": (keywords, ["--no-budget"]),
                "semantic-nobudget": (verbatim, ["--mode", "semantic", "--no-budget"]),
                "hybrid-nobudget": (verbatim, ["--mode", "hybrid", "--no-budget"])}
    else:
        raise SystemExit(f"unknown phase {phase}")
    unknown = set(sys.argv[7:]) - set(arms)
    if unknown:
        raise SystemExit(f"{phase} has no arm {' '.join(sorted(unknown))}: its arms are {' '.join(arms)}")
    arms = {a: arms[a] for a in sys.argv[7:]} or arms
    if build and not os.environ.get("SKIP_BUILD"):
        r = run(build, env, timeout=48 * 3600)
        info.setdefault("builds", {})[" ".join(build[1:])] = {"rc": r.returncode}
        open(os.path.join(out_dir, "raw", f"build.{phase}.out"), "w").write(r.stdout + "\n" + r.stderr)
        if r.returncode != 0:
            raise SystemExit(f"{' '.join(build[1:])} failed ({r.returncode}): {r.stderr[-600:]}")
    res0 = Resolver(corpus)
    table = ordinal_lines(ch, env, home, res0.tm, out_dir)
    info["listed"] = {"sessions": len(table), "messages": sum(len(v) for v in table.values()),
                      "records": len(res0.tm.rows)}
    for arm, (query_of, flags) in arms.items():
        res = Resolver(corpus)
        res.tm = res0.tm
        check = {"preview_in_turn": 0, "preview_elsewhere": 0, "preview_nowhere": 0,
                 "run_len": collections.Counter()}
        empty, warnings, modes = 0, collections.Counter(), collections.Counter()
        with open(os.path.join(out_dir, arm + ".jsonl"), "w") as f, \
                open(os.path.join(out_dir, arm + ".narrowed.jsonl"), "w") as fn:
            for q in qs:
                r = run([ch, "agent", "search", query_of(q["question"])] + flags, env, cwd=home)
                open(os.path.join(out_dir, "raw", f"{q['id']}.{arm}.txt"), "w").write(r.stdout + r.stderr)
                if r.returncode != 0:
                    raise SystemExit(f"{q['id']} {arm}: agent search failed ({r.returncode}): {r.stderr[-400:]}")
                head = atoms(r.stdout.split("\n", 1)[0])[0]
                modes[head.get("mode")] += 1
                for line in (r.stdout + r.stderr).splitlines():
                    if line.startswith("protocol agent-warning"):
                        warnings[atoms(line)[0].get("kind")] += 1
                hits, narrowed = passages(r.stdout, res, table, check)
                empty += not hits
                write(f, q["id"], hits)
                write(fn, q["id"], narrowed)
        info.setdefault("arms", {})[arm] = {
            "command": ["claude-history", "agent", "search", "<q>" if query_of is verbatim else "<keywords(q)>"] + flags,
            "questions": len(qs), "empty": empty, "resolver": res.stats, "modes": dict(modes),
            "warnings": dict(warnings), "check": dict(check, run_len=dict(sorted(check["run_len"].items())))}
        print(arm, json.dumps(info["arms"][arm]))
    json.dump(info, open(path, "w"), indent=1)


if __name__ == "__main__":
    main()
