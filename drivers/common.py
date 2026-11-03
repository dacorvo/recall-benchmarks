"""What every driver shares: the questions, a clean environment, placing a tool's passages at the memory's turns,
and the hits file score.py reads."""
import datetime
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from turnmap import TurnMap, norm  # noqa: E402,F401

SYSTEM_PATH = "/usr/local/bin:/usr/bin:/bin"
# deja-vu's stop words (its scripts/day0compare/cass.py), for the arms that ask a question without them.
STOP = set("a an the of on in at to for with and or is are was were did do does i my me you your it its what where when "
           "how which who whom whose that this these those have has had been be am from by as into about over under "
           "after before than then there here".split())


def keywords(q):
    """The question without stop words, as deja-vu asks the tools whose lexical search needs every word."""
    toks = [t for t in re.findall(r"[A-Za-z0-9$']+", q.lower()) if t not in STOP]
    return " ".join(toks) or q


def clean_env(home, path=SYSTEM_PATH, **extra):
    """HOME, a system PATH, LANG and TERM, and nothing else of the calling environment: a variable such as
    CODEX_HOME would point a tool at the machine's own history."""
    env = {"HOME": home, "PATH": path, "LANG": "C.UTF-8", "TERM": "dumb"}
    env.update(extra)
    return env


def run(cmd, env, cwd=None, timeout=600):
    return subprocess.run(cmd, env=env, cwd=cwd or env["HOME"], capture_output=True, text=True, timeout=timeout)


def questions(path):
    """The set's questions, or the first N of them when N is set in the environment, to try a driver."""
    qs = [json.loads(l) for l in open(path) if l.strip()]
    return qs[: int(os.environ.get("N", "0")) or None]


def ts_key(s):
    """A timestamp as an instant, so 09:15:56.74Z and 09:15:56.740Z are the same."""
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


class Resolver:
    """Places a tool's passages at the memory's turns, counting how each was placed."""

    def __init__(self, corpus):
        self.tm = TurnMap(corpus)
        self.by_instant = {(r["file_session_id"], round(ts_key(r["timestamp"]), 3)): r for r in self.tm.rows}
        self.stats = {"exact": 0, "text": 0, "ambiguous": 0, "session_only": 0}

    def hit(self, row):
        return {"session_id": row["session_id"], "seq": row["seq"]}

    def by_time(self, fid, ts):
        row = self.by_instant.get((fid, round(ts_key(ts), 3)))
        if row:
            self.stats["exact"] += 1
            return self.hit(row)
        return None

    def by_text(self, fid, passage, prefer=None):
        rows = self.tm.locate(fid, passage)
        if not rows:
            self.stats["session_only"] += 1
            sid = self.tm.session(fid)
            return {"session_id": sid} if sid else None
        if len(rows) > 1 and prefer:
            preferred = [r for r in rows if r["role"] in prefer]
            rows = preferred or rows
        h = self.hit(rows[0])
        if len(rows) > 1:
            # The passage's text is in several turns: placed at the first, the others kept for a bound.
            self.stats["ambiguous"] += 1
            h["alt"] = [r["seq"] for r in rows[1:]]
        else:
            self.stats["text"] += 1
        return h


def write(out, qid, hits, **extra):
    d = {"id": qid, "hits": hits}
    d.update(extra)
    out.write(json.dumps(d, ensure_ascii=False) + "\n")
    out.flush()
