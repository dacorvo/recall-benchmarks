# recall-benchmarks

How often does a tool that searches past agent sessions put the turn that answers a question among
the first 8 passages it returns? Each tool here reads the same sessions and is asked the same
questions, verbatim, at its defaults. Its passages are then placed at the turns they come from and
scored against labeled spans.

## Sets

| set | questions | sessions | a question is found by a passage in |
|---|---|---|---|
| funes-memory | 244 about funes's development | 139 coding-agent sessions | the gold turn or the 3 turns on each side of it |
| [longmemeval](longmemeval/) | 470, LongMemEval-S's answerable ones | 19,195 chat sessions | an evidence turn or the turn after it, in its session or a copy of it |

- funes-memory is the set of the [funes recall benchmark](https://huggingface.co/datasets/dacorvo/funes-recall-benchmark)
  (`funes-memory/questions.jsonl`), over the public memory
  [`huggingface/funes-memory`](https://huggingface.co/datasets/huggingface/funes-memory). Its questions
  are worded the way someone asks weeks later and avoid the answer's words, so a tool cannot find the
  turn by matching them. Its README says how they were written.
- longmemeval asks the questions of [LongMemEval](https://github.com/xiaowu0162/LongMemEval)
  (arXiv:2410.10813, `longmemeval_s_cleaned.json` of `xiaowu0162/longmemeval-cleaned`) over one pile of
  the 19,195 distinct sessions of its 500 haystacks, rather than over each question's own haystack of
  about 48 sessions. [longmemeval/](longmemeval/) says how the gold spans were drawn.

## Results

funes-memory, 244 questions, each tool at its defaults with the question verbatim
([receipt](results/funes-memory/2026-11-03.md)):

| tool | asked with | hit@1 | hit@5 | found@8 | MRR | session |
|---|---|---|---|---|---|---|
| funes 1.10.0+dev | `funes recall` (a pool of 30, reranked) | 62 | 111 | 128 | 0.339 | 211 |
| MemPalace 3.11.0 | MCP `mempalace_search` | 37 | 72 | 85 | 0.207 | 189 |
| agentmemory 0.9.31 | MCP `memory_smart_search`, keyless | 21 | 57 | 66 | 0.141 | 198 |
| deja-vu 0.23.5 | `deja search --limit 8` | 18 | 53 | 58 | 0.128 | 171 |
| deja-vu 0.23.5 | `deja recall`, its MCP page | 5 | 35 | 43 | 0.073 | 121 |
| ctx 2.3.0 | `ctx search` | 5 | 26 | 29 | 0.054 | 105 |
| cass 0.10.0 | `cass search --robot --limit 8` | 1 | 1 | 1 | 0.004 | 10 |
| claude-history 0.1.81 | `claude-history agent search` | 1 | 1 | 1 | 0.004 | 4 |
| agentsview 0.46.1 | `agentsview session search` | 0 | 0 | 0 | 0.000 | 0 |

With an opt-in local mode, claude-history's semantic search finds 104 (140 counting its runs of turns
whole, where funes does not rank the gold above it question by question), MemPalace with `sweep`
100, cass with its MiniLM model 90 and ctx with its E5 model 25. The receipt has every arm.
`session` counts a question found when one of the first 8 distinct sessions is a gold session.

## Rules

1. **The same files.** Every tool reads a set's sessions as Claude Code transcripts, rebuilt from the
   set's funes memory by the funes recall benchmark's
   [`rebuild_sessions.py`](https://huggingface.co/datasets/dacorvo/funes-recall-benchmark/blob/main/funes-memory/tools/rebuild_sessions.py):
   one record per turn, with `turns.jsonl` mapping each record back to its turn. funes reads the
   published memory itself. On funes-memory, funes finds the same 128 answers when it indexes the
   rebuilt files instead (the control in the [receipt](results/funes-memory/2026-11-03.md)).
2. **Isolation.** Each tool gets its own HOME, holding a copy of the transcripts, and runs with HOME,
   a system PATH, LANG and TERM and its own data-directory variables, nothing else from the calling
   environment. No agent is wired to a tool and no API key or hosted service is used. ctx's and
   agentsview's telemetry and update checks, and cass's update prompt, are turned off by their
   environment variables. A tool may download its own local model. Every daemon a run starts is
   stopped at its end.
3. **Defaults, verbatim.** A tool indexes the history its documented way. Each question is asked
   once, verbatim, at the tool's defaults, through the interface it gives an agent: its MCP tool, or
   the CLI command that returns the same results. A tool that returns fewer than 8 results by default
   is asked for 8.
4. **Concessions and opt-in modes.** When a tool's lexical search needs every word of the question
   and answers nothing to most questions as typed, a second arm asks without the stop words of
   deja-vu's own comparison, named as a concession. An optional local mode (no key) is scored as an
   arm of its own.
5. **Passages.** A passage is one result, in the tool's order. It is placed at the turn its exact
   metadata names (a uuid, timestamp, line or message number, checked against the files), else by its
   text within its session. A passage that covers several turns is a run of turns. A result that names
   a session but no place in it counts for the session row only.
6. **Scoring** (`tools/score.py`, the rule of funes's `score_recall`). A question is found when one of
   the first 8 passages is a turn in a gold span, or a run that overlaps one. Its rank is the position
   of the first such passage. hit@1, hit@5 and found@8 count the questions found within the first 1, 5
   and 8 passages, and MRR is the mean of 1/rank (0 when not found). The session row scores the same
   passages by their session alone, the first 8 distinct sessions, as deja-vu's
   [day-zero page](https://vshulcz.github.io/deja-vu/guide/day-zero.html) does.

The receipts report precision only: no latency, build time or output size. Several tools ran at once
on one machine.

## Running a tool

Rebuild a set's transcripts (this needs pylance), give the tool a home with a copy of them, run its
driver, then score each arm:

```bash
hf download dacorvo/funes-recall-benchmark --repo-type dataset --revision 59b1ed846301eb3bccf384c1ffbfe11e8ec7c441 --local-dir bench
hf download huggingface/funes-memory --repo-type dataset --revision 347686a1c7ed495fb653d650d78f9b92f8744c7a --include 'chunks.lance/*' --local-dir mem
python3 bench/funes-memory/tools/rebuild_sessions.py mem/chunks.lance corpus
mkdir -p homes/deja && cp -a corpus/home/.claude homes/deja/
python3 -I drivers/deja.py path/to/deja corpus bench/funes-memory/questions.jsonl homes/deja runs/deja
python3 tools/score.py bench/funes-memory/questions.jsonl runs/deja/search.jsonl
```

| set | memory | transcripts digest | questions |
|---|---|---|---|
| funes-memory | `huggingface/funes-memory` at `347686a1c7ed495fb653d650d78f9b92f8744c7a` | `62ef948a1587f59a8506a6bfb4c4255fc8074a1d927c6fb299572aeaf42540ff` | `bench/funes-memory/questions.jsonl` |
| longmemeval | `dacorvo/funes-xiaowu0162-longmemeval-cleaned-s` at `58450d98655f3d104359fb119933d7a4d6597d13` | `3298cc7cdccadb42255aa628d49a963ae7367619642b1f216abd82d3287db7e0` | [`longmemeval/questions.jsonl`](longmemeval/questions.jsonl) |

The digest is what `(cd corpus && find home turns.jsonl -type f | LC_ALL=C sort | xargs sha256sum | sha256sum)`
prints. Each driver's docstring gives its usage, its arms and how it places passages. The releases
scored, each checked against its published checksum:

| tool | release | sha256 | driver |
|---|---|---|---|
| [funes](https://github.com/huggingface/funes) | `main` at `29075cb`, built with `cargo build --release` and `cargo build --release --example score_recall` | | `funes.py FUNES MEMORY QUESTIONS OUT`, MEMORY a local copy of the memory |
| [deja-vu](https://github.com/vshulcz/deja-vu) | v0.23.5, `deja-vu_0.23.5_linux_amd64.tar.gz` | `b8f8b62c96e56fcb0d7c6110d4cc14cffce4b3075e8881ad4112e1da1e8d3e00` | `deja.py DEJA CORPUS QUESTIONS HOME OUT_DIR` |
| [cass](https://github.com/Dicklesworthstone/coding_agent_session_search) | v0.10.0, `cass-linux-amd64.tar.gz` | `638ea8a8a9023c2e046bf8868392e6191218b89cf006e81af3ca205b546c4681` | `cass.py CASS CORPUS QUESTIONS HOME OUT_DIR lexical`, then `semantic` |
| [claude-history](https://github.com/raine/claude-history) | v0.1.81, `claude-history-linux-amd64.tar.gz` | `0f85c5693b5b81c2f383b206e361d90db43171cbf19d08805f83a3752e16012e` | `claude_history.py CLAUDE_HISTORY CORPUS QUESTIONS HOME OUT_DIR lexical`, then `semantic` and `unbudgeted` |
| [ctx](https://github.com/ctxrs/ctx) | v2.3.0, `ctx-linux-x64` and `ctx-onnxruntime-linux-x64.tar.gz` | `8bc22cb45c7fa9acc2049a3c741925939a3da2801ef7d3b6e9c9c4faeb2fcc8d`, `d59280037cf71b3ad7f6c4c2a28b52ecd09bdc83943f18d5bc8fc39bcdc8a76c` | `ctx.py CTX CORPUS QUESTIONS HOME OUT_DIR`, then `--semantic ORT_TARBALL` |
| [agentsview](https://github.com/kenn-io/agentsview) | v0.46.1, `agentsview_0.46.1_linux_amd64.tar.gz` | `e7822006d7bafa3aef9a5e4f7d7caffca56051bb039b848222a73633ed4c6c9b` | `agentsview.py AGENTSVIEW CORPUS QUESTIONS HOME OUT_DIR` |
| [agentmemory](https://github.com/rohitg00/agentmemory) | 0.9.31 from npm (`npm install --ignore-scripts @agentmemory/agentmemory@0.9.31`), and the iii engine v0.25.0 its CLI pins, `iii-x86_64-unknown-linux-gnu.tar.gz` from `iii-hq/iii` | `sha512-+KciN5Ybl6+AhxDLQ1185a/Am0PnzQOvyijmChAuwtsFIhc8WEcsFtZwBemOQfjag5aGYUSofaflnHYPARSnPA==` (npm integrity), `4c4d14063eb55d79663db553e960497731420df6d78eca3aafe670e2fbaba8e2` (iii) | `agentmemory.py AM_DIR ENGINE_DIR CORPUS QUESTIONS HOME OUT_DIR` |
| [MemPalace](https://github.com/MemPalace/mempalace) | 3.11.0 from PyPI (`uv pip install mempalace==3.11.0`), `mempalace-3.11.0-py3-none-any.whl` | `43e4c690e339b66e86a3177fe4eea15da3d9541ecbd58e671431c1e13dc1bf0c` | `mempalace.py VENV_BIN CORPUS QUESTIONS HOME OUT_DIR mcp mcp-sweep` |

funes is also scored with its own `score_recall` on the published memory:
`score_recall QUESTIONS --memory <memory>`, from a funes checkout. `tools/compare.py QUESTIONS
funes=HITS tool=HITS ...` puts the arms side by side and runs a paired sign test of each against the
first. `tools/clean.sh HOME CMD ...` runs a command in the same clean environment as the drivers.

## Layout

- `drivers/`: one driver per tool, and `common.py`, which they share
- `tools/`: `score.py`, `compare.py`, `turnmap.py` (places a tool's passages at the memory's turns)
  and `clean.sh`
- `longmemeval/`: `questions.py` and the questions it writes
- `results/<set>/`: the receipt of each run (`<date>.md`) and each arm's hits
  (`<tool>/<arm>.jsonl`, one line a question, the passages in order as turns of the memory)

The tools' raw answers are in the bucket
[`dacorvo/recall-benchmark`](https://huggingface.co/buckets/dacorvo/recall-benchmark), under
`<set>/<tool>/raw/`, each run's `run.json` beside them.

## License

Apache-2.0. `longmemeval/questions.jsonl` holds LongMemEval's questions and answers, under its MIT
license.
