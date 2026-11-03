"""Score agentmemory (github.com/rohitg00/agentmemory) on a set: start its server, import the rebuilt
transcripts, then ask each question through its MCP server.

usage: agentmemory.py AM_DIR ENGINE_DIR CORPUS QUESTIONS HOME OUT_DIR

AM_DIR holds the npm install (`node_modules/.bin/agentmemory`). ENGINE_DIR holds the pinned iii engine that
agentmemory's first run would otherwise download into ~/.agentmemory/bin: the CLI takes an `iii` of the pinned
version from PATH. HOME holds a copy of CORPUS's `.claude` and nothing of an earlier run. agentmemory runs
keyless (no LLM provider, no embeddings), its data under HOME/data. The driver starts the server with
`agentmemory`, imports with `agentmemory import-jsonl` (its default root, ~/.claude/projects), asks, and stops
the server with `agentmemory stop`. `import-jsonl` reads at most 200 files, or up to 1,000 with `--max-files`,
and its warning advises batching a larger tree by subdirectory: so a history of more than 200 files has each
project's files moved into subdirectories of 1,000 in HOME, each imported with `--max-files 1000`.

Each question is asked once, verbatim, through `agentmemory mcp` (the stdio MCP server an agent is wired to,
proxying to the running server), at the tools' defaults (10 results), in two arms:

- smart: `memory_smart_search {query}`, the call agentmemory's own recall skill makes. Its passages are its
  `results`, in order. The `lessons` it lists beside them name no session: they are counted, not placed.
- recall: `memory_recall {query}`, the tool behind REST /agentmemory/search. Its passages are its `results`.

A result is an observation, and an observation is one content block of one transcript record (a prompt, a
reply's text, a tool call or a tool result) that keeps the record's timestamp. So each passage is placed at
the one turn whose record has its session and timestamp, and checked against the turn its id names (the id is
a hash of the record's uuid and the block's index).

Writes OUT_DIR/smart.jsonl and OUT_DIR/recall.jsonl for score.py, each answer under OUT_DIR/raw, and the
commands, what the index holds and how passages were placed to OUT_DIR/run.json.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import SYSTEM_PATH, Resolver, clean_env, questions, run, write  # noqa: E402

IMPORTED = re.compile(r"imported (\d+) file\(s\), (\d+) observation\(s\) across (\d+) session\(s\)")
STATUS = re.compile(r"(Sessions|Observations|Memories|Provider|Embeddings):\s+(.+?)\s*│")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# What the MCP server prints when it stops proxying and answers from its own empty local store.
FALLBACK = re.compile(r"falling back|LOCAL FALLBACK|proxy call failed", re.I)
ARMS = {"smart": "memory_smart_search", "recall": "memory_recall"}
DEFAULT_CAP, UPPER_CAP = 200, 1000


class Mcp:
    """One stdio MCP session with `agentmemory mcp`, newline-delimited JSON-RPC, as an agent holds it."""

    def __init__(self, cmd, env, cwd):
        self.p = subprocess.Popen(cmd, env=env, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, bufsize=1)
        self.stderr, self.seen, self.next_id = [], 0, 0
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self):
        for line in self.p.stderr:
            self.stderr.append(line)

    def request(self, method, params):
        self.next_id += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.next_id, "method": method,
                                       "params": params}) + "\n")
        self.p.stdin.flush()
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise SystemExit(f"agentmemory mcp exited: {''.join(self.stderr)[-500:]}")
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("id") == self.next_id:
                if "error" in msg:
                    raise SystemExit(f"{method}: {msg['error']}")
                return msg["result"]

    def notify(self, method):
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.p.stdin.flush()

    def new_stderr(self):
        lines = self.stderr[self.seen:]
        self.seen += len(lines)
        return lines

    def close(self):
        self.p.stdin.close()
        try:
            self.p.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.p.kill()


def import_commands(am, home):
    """The import: the default command, or one command a subdirectory of at most 1,000 files."""
    projects = os.path.join(home, ".claude", "projects")
    n = sum(f.endswith(".jsonl") for _, _, fs in os.walk(projects) for f in fs)
    if n <= DEFAULT_CAP:
        return [[am, "import-jsonl"]]
    cmds = []
    for proj in sorted(os.listdir(projects)):
        d = os.path.join(projects, proj)
        names = sorted(f for f in os.listdir(d) if f.endswith(".jsonl"))
        for i in range(0, len(names), UPPER_CAP):
            part = os.path.join(d, f"part-{i // UPPER_CAP:03d}")
            os.makedirs(part)
            for f in names[i:i + UPPER_CAP]:
                os.rename(os.path.join(d, f), os.path.join(part, f))
            cmds.append([am, "import-jsonl", part, "--max-files", str(UPPER_CAP)])
    return cmds


def obs_ids(res):
    """Each observation id agentmemory's JSONL import gives a record's blocks, to the record's turn."""
    ids = {}
    for fid, rows in res.tm.by_file.items():
        with open(res.tm.path[fid]) as f:
            for i, line in enumerate(f):
                rec = json.loads(line)
                content = rec["message"]["content"]
                for k in range(len(content) if isinstance(content, list) else 1):
                    ids["obs_" + hashlib.sha256(f"{rec['uuid']}:{k}".encode()).hexdigest()[:16]] = rows[i]
    return ids


def place(res, ids, check, sid, obs_id, ts):
    """A result at the turn its session and timestamp name, checked against the turn its id names."""
    by_id = ids.get(obs_id)
    hit = res.by_time(sid, ts) if ts else None
    if hit:
        agree = bool(by_id) and by_id["file_session_id"] == sid and by_id["seq"] == hit["seq"]
        check["id_agrees" if agree else "id_disagrees"] += 1
        return hit
    if by_id and by_id["file_session_id"] == sid:
        check["placed_by_id"] += 1
        return {"session_id": by_id["session_id"], "seq": by_id["seq"]}
    res.stats["session_only"] += 1
    s = res.tm.session(sid)
    return {"session_id": s} if s else {}


def passages(arm, answer, res, ids, check):
    hits = []
    for r in answer.get("results") or []:
        if arm == "smart":
            sid, obs_id, ts = r.get("sessionId"), r.get("obsId"), r.get("timestamp")
        else:
            o = r.get("observation") or {}
            sid, obs_id, ts = r.get("sessionId") or o.get("sessionId"), o.get("id"), o.get("timestamp")
        check["layers"][r.get("layer") or "-"] = check["layers"].get(r.get("layer") or "-", 0) + 1
        hits.append(place(res, ids, check, sid, obs_id, ts))
    return hits


def rest_get(base, path, secret):
    req = urllib.request.Request(base + path, headers={"Authorization": f"Bearer {secret}",
                                                       "Accept": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=600))


def main():
    am_dir, engine, corpus, qpath, home, out = sys.argv[1:7]
    am = os.path.join(am_dir, "node_modules", ".bin", "agentmemory")
    data = os.path.join(home, "data")
    if any(os.path.exists(os.path.join(home, d)) for d in ("data", ".agentmemory", ".iii")):
        raise SystemExit(f"{home} holds an earlier run's state: start from a home with only .claude")
    os.makedirs(os.path.join(out, "raw"), exist_ok=True)
    # /snap/bin for node (the CLI is a `#!/usr/bin/env node` script).
    env = clean_env(home, path=f"{engine}:/snap/bin:{SYSTEM_PATH}", AGENTMEMORY_DATA_DIR=data)
    imports = import_commands(am, home)
    info = {"version": run([am, "--version"], env).stdout.strip(),
            "iii": run([os.path.join(engine, "iii"), "--version"], env).stdout.strip(),
            "env": {k: v for k, v in env.items()},
            "commands": {"start": [am], "import": imports, "status": [am, "status"], "mcp": [am, "mcp"],
                         "stop": [am, "stop"],
                         "ask": {arm: {"tool": tool, "arguments": {"query": "<question>"}}
                                 for arm, tool in ARMS.items()}}}
    mcp = None
    try:
        r = run([am], env, timeout=900)
        if r.returncode != 0:
            raise SystemExit(f"agentmemory start failed: {ANSI.sub('', r.stdout + r.stderr)[-800:]}")
        info["import"] = []
        for cmd in imports:
            r = run(cmd, env, timeout=900)
            got = IMPORTED.search(ANSI.sub("", r.stdout + r.stderr))
            if r.returncode != 0 or not got:
                raise SystemExit(f"{' '.join(cmd[1:])} failed: {ANSI.sub('', r.stdout + r.stderr)[-800:]}")
            info["import"].append(dict(zip(("files", "observations", "sessions"), map(int, got.groups()))))
        r = run([am, "status"], env)
        info["status"] = dict(STATUS.findall(ANSI.sub("", r.stdout + r.stderr)))
        base, secret = "http://localhost:3111", open(os.path.join(home, ".agentmemory", "secret")).read().strip()
        sessions = rest_get(base, "/agentmemory/sessions", secret)["sessions"]
        index = rest_get(base, "/agentmemory/status", secret).get("index", {})
        res = {arm: Resolver(corpus) for arm in ARMS}
        files = set(res["smart"].tm.by_file)
        info["index"] = {"sessions": len(sessions), "same_ids_as_corpus": {s["id"] for s in sessions} == files,
                         "observations": sum(s.get("observationCount", 0) for s in sessions),
                         "projects": sorted({s.get("project") or "-" for s in sessions}),
                         "bm25": {k: index.get(k) for k in ("bm25Documents", "breakdown", "sessions")}}
        ids = obs_ids(res["smart"])
        check = {arm: {"id_agrees": 0, "id_disagrees": 0, "placed_by_id": 0, "layers": {}} for arm in ARMS}
        lessons = []
        mcp = Mcp([am, "mcp"], env, home)
        mcp.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "recall-benchmarks", "version": "1"}})
        mcp.notify("notifications/initialized")
        info["mcp_tools"] = len(mcp.request("tools/list", {})["tools"])
        outs = {arm: open(os.path.join(out, arm + ".jsonl"), "w") for arm in ARMS}
        for q in questions(qpath):
            for arm, tool in ARMS.items():
                result = mcp.request("tools/call", {"name": tool, "arguments": {"query": q["question"]}})
                text = "".join(c.get("text", "") for c in result.get("content") or [])
                open(os.path.join(out, "raw", f"{q['id']}.{arm}.json"), "w").write(text)
                bad = [l for l in mcp.new_stderr() if FALLBACK.search(l)]
                if bad or result.get("isError"):
                    raise SystemExit(f"{q['id']} {tool}: not answered by the server: {bad or text[:300]}")
                answer = json.loads(text)
                extra = {"lessons": len(answer["lessons"])} if "lessons" in answer else {}
                if arm == "smart":
                    lessons.append(len(answer.get("lessons") or []))
                write(outs[arm], q["id"], passages(arm, answer, res[arm], ids, check[arm]), **extra)
        mcp.close()
        stderr = "".join(mcp.stderr)
        info["mcp_stderr"] = stderr[-600:]
        if FALLBACK.search(stderr):
            raise SystemExit(f"agentmemory mcp left the server during the run: {stderr[-600:]}")
        info["resolver"] = {arm: dict(res[arm].stats, **check[arm]) for arm in ARMS}
        info["smart_lessons_per_question"] = {"min": min(lessons), "max": max(lessons)} if lessons else None
    finally:
        if mcp:
            mcp.close()
        r = run([am, "stop"], env, timeout=300)
        info["stop"] = ANSI.sub("", r.stdout + r.stderr).strip()[-300:]
        json.dump(info, open(os.path.join(out, "run.json"), "w"), indent=1)
    print(json.dumps({k: info.get(k) for k in ("version", "import", "index", "resolver")}))


if __name__ == "__main__":
    main()
