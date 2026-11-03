"""Map what a tool returns from the rebuilt transcripts back to the memory's turns.

As a module: `TurnMap(CORPUS)` reads `CORPUS/turns.jsonl` (written with the transcripts by the funes recall
benchmark's `rebuild_sessions.py`) and resolves a record's uuid, timestamp or line, or a passage of its text, to
the memory's session id and `seq`.

As a script: `turnmap.py gold CORPUS QUESTIONS` prints QUESTIONS with each gold span moved to the rebuilt
files' numbering (the file's session id, one turn a line), so funes can be scored on its index of them.
"""
import collections
import json
import os
import re
import sys

WS = re.compile(r"\s+")
# Where a tool's excerpt may join text that is not contiguous in the record: ellipses, highlight marks, and
# the separators an excerpt flattens lines, tables or a rendered result into.
SEPARATORS = r"…|\.\.\.|\*\*|</?mark>|</?b>|\[\.\.\.\]|\n| \| | --- | ~ "


def norm(s):
    return WS.sub(" ", s).strip().lower()


def record_text(rec):
    c = rec.get("message", {}).get("content")
    if isinstance(c, str):
        return c
    parts = []
    for b in c or []:
        t = b.get("type")
        if t == "text":
            parts.append(b["text"])
        elif t == "thinking":
            parts.append(b["thinking"])
        elif t == "tool_use":
            # Values as text, not escaped JSON: a tool shows a call's command or edit as it reads.
            vals = [v if isinstance(v, str) else json.dumps(v, ensure_ascii=False) for v in b["input"].values()]
            parts.append(b["name"] + " " + "\n".join(vals))
        elif t == "tool_result":
            parts.append(b["content"] if isinstance(b["content"], str) else json.dumps(b["content"]))
    return "\n".join(parts)


class TurnMap:
    def __init__(self, corpus):
        self.corpus = corpus
        self.rows = [json.loads(l) for l in open(os.path.join(corpus, "turns.jsonl"))]
        self.by_uuid = {r["uuid"]: r for r in self.rows}
        self.by_ts = {(r["file_session_id"], r["timestamp"]): r for r in self.rows}
        self.by_file = collections.defaultdict(list)
        for r in self.rows:
            self.by_file[r["file_session_id"]].append(r)
        self.sid = {r["file_session_id"]: r["session_id"] for r in self.rows}
        self.path = {r["file_session_id"]: os.path.join(corpus, r["path"]) for r in self.rows}
        self._texts = {}

    def session(self, fid):
        """The memory's session id for a file's session id (they differ only for non-UUID ids)."""
        return self.sid.get(fid)

    def line(self, fid, line):
        rows = self.by_file.get(fid)
        return rows[line] if rows and 0 <= line < len(rows) else None

    def texts(self, fid):
        """Each record's searchable text, normalized, in line order."""
        if fid not in self._texts:
            with open(self.path[fid]) as f:
                self._texts[fid] = [norm(record_text(json.loads(l))) for l in f]
        return self._texts[fid]

    def locate(self, fid, passage, min_len=12):
        """The rows whose text holds the passage. A passage cut with ellipses or highlight marks, or
        flattened with separators, is matched on its longest piece that some row holds."""
        pieces = [norm(p) for p in re.split(SEPARATORS, passage)]
        pieces = sorted((p for p in pieces if len(p) >= min_len), key=len, reverse=True)
        if not pieces or fid not in self.path:
            return []
        texts = self.texts(fid)
        rows = self.by_file[fid]
        for p in pieces[:6]:
            # A long piece may have a line dropped from inside it, unmarked: try its head and tail too.
            for q in (p, p[:80], p[-80:]) if len(p) > 120 else (p,):
                hit = [rows[i] for i, t in enumerate(texts) if q in t]
                if hit:
                    return hit
        return []


def gold(corpus, questions):
    tm = TurnMap(corpus)
    fid_of = {r["session_id"]: r["file_session_id"] for r in tm.rows}
    for l in open(questions):
        if not l.strip():
            continue
        q = json.loads(l)
        spans = []
        for s in q["gold"]:
            fid = fid_of[s["session_id"]]
            lines = [i for i, r in enumerate(tm.by_file[fid])
                     if s.get("from") is None or s["from"] <= r["seq"] <= s["to"]]
            if lines:
                spans.append({"session_id": fid, "from": min(lines), "to": max(lines)})
        q["gold"] = spans
        print(json.dumps(q, ensure_ascii=False))


if __name__ == "__main__":
    if sys.argv[1] == "gold":
        gold(sys.argv[2], sys.argv[3])
