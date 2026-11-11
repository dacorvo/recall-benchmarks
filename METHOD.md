# Method

How the sets are built, how the tools are run and scored, and how to run one yourself. The
[README](README.md) has the results.

## Sets

| set | questions | sessions | answering turns |
|---|---|---|---|
| funes-memory | 240 about funes's development | 139 coding-agent sessions | the answer and its reviewed restatements |
| sharegpt | 100, each in English and in Chinese | 2,000 programming conversations, in English and in their Chinese machine translation | the reply and its restatements |
| swe-chat | 100 in Chinese, 36 in Portuguese | 635 and 153 coding-agent sessions | the answering turn and its restatements |
| thomasmustier-pi-sessions | 100 | 715 sessions of one developer with the pi agent | the answering turn and its restatements |
| [longmemeval](longmemeval/) | 470, LongMemEval-S's answerable ones | 19,195 chat sessions | each evidence turn, and every other turn of the pile with its role and text |

- funes-memory, sharegpt, swe-chat and thomasmustier-pi-sessions are the sets of the
  [funes recall benchmark](https://huggingface.co/datasets/dacorvo/funes-recall-benchmark), each over public
  funes memories (listed under [Running a tool](#running-a-tool)). Their questions are worded the way
  someone asks weeks later and avoid the answer's words, so a tool cannot find the turn by matching them.
  Each set's README says how its questions were written and which turns answer them.
- longmemeval asks the questions of [LongMemEval](https://github.com/xiaowu0162/LongMemEval)
  (arXiv:2410.10813, `longmemeval_s_cleaned.json` of `xiaowu0162/longmemeval-cleaned`) over one pile of
  the 19,195 distinct sessions of its 500 haystacks, rather than over each question's own haystack of
  about 48 sessions. [longmemeval/](longmemeval/) says how its answering turns were drawn.

## Rules

1. **The same files.** Every tool reads a set's sessions as Claude Code transcripts, rebuilt from the
   set's funes memory by the funes recall benchmark's
   [`rebuild_sessions.py`](https://huggingface.co/datasets/dacorvo/funes-recall-benchmark/blob/main/funes-memory/tools/rebuild_sessions.py):
   one record per turn, with `turns.jsonl` mapping each record back to its turn. funes reads the
   published memory itself.
2. **Isolation.** Each tool gets its own HOME, holding a copy of the transcripts, and runs with HOME,
   a system PATH, LANG and TERM and its own data-directory variables, nothing else from the calling
   environment. No agent is wired to a tool and no API key or hosted service is used. That leaves out
   claude-mem, which needs an LLM to write its memory. A tool may download its own local model.
   Every daemon a run starts is stopped at its end.
3. **Defaults, verbatim.** A tool indexes the history its documented way. Each question is asked
   once, verbatim, at the tool's defaults, through the interface it gives an agent: its MCP tool, or
   the CLI command that returns the same results. A tool that returns fewer than 8 results by default
   is asked for 8.
4. **Opt-in modes.** An optional local mode (no key) is scored as an arm of its own.
5. **Passages.** A passage is one result, in the tool's order. It is placed at the turn its exact
   metadata names (a uuid, timestamp, line or message number, checked against the files), else by its
   text within its session. A passage that covers several turns is a run of turns. funes frames each
   hit with turns of its exchange (the prompt that opened it, the assistant's last text and the next
   prompt), and those turns are part of its passage. A result that names a session but no place in it
   counts for the session row only.
6. **Scoring** (`tools/score.py`, the rule of funes's `score_recall`). A question is found when one of
   the first 8 passages shows one of its answering turns: as its turn, as a turn of its run, or in its
   frame. Its rank is the position of the first such passage. hit@1, hit@5 and found@8 count the
   questions found within the first 1, 5 and 8 passages, and MRR is the mean of 1/rank (0 when not
   found). `as a hit` counts the questions where one of the first 8 passages is an answering turn
   itself, not through a frame. The session row scores the same passages by their session alone, over
   the first 8 distinct sessions. deja-vu's
   [day-zero page](https://vshulcz.github.io/deja-vu/guide/day-zero.html) scores by session too, over
   the first 50 results.

The receipts report precision only: no latency, build time or output size. Several tools ran at once
on one machine. funes's rows on the funes recall benchmark's sets come from that benchmark's own
receipts, made on another machine at the same funes commit (each receipt says which).

## Running a tool

Rebuild a set's transcripts (this needs pylance), give the tool a home with a copy of them, run its
driver, then score each arm:

```bash
hf download dacorvo/funes-recall-benchmark --repo-type dataset --revision 098ad102a0e7bece7d7c7f18e0f32430ee49a953 --local-dir bench
hf download huggingface/funes-memory --repo-type dataset --revision 347686a1c7ed495fb653d650d78f9b92f8744c7a --include 'chunks.lance/*' --local-dir mem
python3 bench/funes-memory/tools/rebuild_sessions.py mem/chunks.lance corpus
mkdir -p homes/deja && cp -a corpus/home/.claude homes/deja/
python3 -I drivers/deja.py path/to/deja corpus bench/funes-memory/questions.jsonl homes/deja runs/deja
python3 tools/score.py bench/funes-memory/questions.jsonl runs/deja/search.jsonl
```

| set | memory | transcripts digest | questions |
|---|---|---|---|
| funes-memory | `huggingface/funes-memory` at `347686a1c7ed495fb653d650d78f9b92f8744c7a` | `62ef948a1587f59a8506a6bfb4c4255fc8074a1d927c6fb299572aeaf42540ff` | `bench/funes-memory/questions.jsonl` |
| sharegpt-en | `huggingface/funes-sharegpt-en` at `c9aa03279a825cdd5218421a303fd6ca541b40bb` | `0d73c2e45bdbd66308baa4e84484f025a5097dd924eb401982b51f0305ce3d53` | `bench/sharegpt/questions-en.jsonl` |
| sharegpt-zh | `huggingface/funes-sharegpt-zh` at `39b42e1e789c107b2b913e5abd897ed89064f81e` | `3e02149ff1c6c03caa82ac9b4306b39b8b012d76bdf44122e60f02c6a27f644f` | `bench/sharegpt/questions-zh.jsonl` |
| swe-chat-zh | `huggingface/funes-swe-chat-zh-e5` at `31749928929be585964d248a132ddd116bb3b885` | `c97af069ca3d3e76a67c23b16e6aad7ea4195fe730a29d1e489f0eb5c54b5c98` | `bench/swe-chat/questions.jsonl` |
| swe-chat-pt | `huggingface/funes-swe-chat-pt-e5` at `457d2154e6ac2843faa393c05400073bc4e5e8db` | `ebcad94a8fdecce615969e525b2c9b6fbe45fc696f19153854a00d63778801da` | `bench/swe-chat/questions-pt.jsonl` |
| thomasmustier-pi-sessions | `huggingface/funes-thomasmustier-pi-sessions` at `42244122ebbf42166ffb73897dd6eaaa2f977dc8` | `87d664be889dc15a188cfaa9e814034bbc29e27bbf1402752cf6c6f64566571d` | `bench/thomasmustier-pi-sessions/questions.jsonl` |
| longmemeval | `dacorvo/funes-xiaowu0162-longmemeval-cleaned-s` at `58450d98655f3d104359fb119933d7a4d6597d13` | `3298cc7cdccadb42255aa628d49a963ae7367619642b1f216abd82d3287db7e0` | [`longmemeval/questions.jsonl`](longmemeval/questions.jsonl) |

The digest is what `(cd corpus && find home turns.jsonl -type f | LC_ALL=C sort | xargs sha256sum | sha256sum)`
prints on a case-sensitive filesystem: four project folders of thomasmustier-pi-sessions differ only in case,
and a case-insensitive one merges them. The memories are at the revisions the benchmark's results pin. Each
driver's docstring gives its usage, its arms and how it places passages. The releases
scored, each checked against its published checksum:

| tool | release | sha256 | driver |
|---|---|---|---|
| [funes](https://github.com/huggingface/funes) | `main` at `7250df3`, built with `cargo build --release` | | `funes.py FUNES MEMORY QUESTIONS OUT`, MEMORY a local copy of the memory |
| [deja-vu](https://github.com/vshulcz/deja-vu) | v0.24.1, `deja-vu_0.24.1_linux_amd64.tar.gz` | `c2489d191edfb085a267c819b1ade32c795a6849e2b90097fb699c6f77989168` | `deja.py DEJA CORPUS QUESTIONS HOME OUT_DIR` |
| [agentmemory](https://github.com/rohitg00/agentmemory) | 0.9.33 from npm (`npm install --ignore-scripts @agentmemory/agentmemory@0.9.33`), and the iii engine v0.25.1 its CLI pins, `iii-x86_64-unknown-linux-gnu.tar.gz` from `iii-hq/iii` | `sha512-YUW8nLg9nx+v70B8fyltvmlJrU1POKz7X7/90EpqJ367nksbOzek0FuuwI5tbcncebdmL1A/dqO92ix5mPncRw==` (npm integrity), `0f486f0fb175013fdebd482735228a47de5fd5014d375a9720cb4f958341208a` (iii) | `agentmemory.py AM_DIR ENGINE_DIR CORPUS QUESTIONS HOME OUT_DIR` |
| [MemPalace](https://github.com/MemPalace/mempalace) | 3.11.0 from PyPI (`uv pip install mempalace==3.11.0`), `mempalace-3.11.0-py3-none-any.whl` | `43e4c690e339b66e86a3177fe4eea15da3d9541ecbd58e671431c1e13dc1bf0c` | `mempalace.py VENV_BIN CORPUS QUESTIONS HOME OUT_DIR mcp mcp-sweep` |

funes is also scored with its own `score_recall` on the published memory:
`score_recall QUESTIONS --memory <memory>`, from a funes checkout. Its receipt lists the turns each
reply showed, a hit's own turn and its frame's, and those are funes's hits on the funes recall
benchmark's sets: `tools/score.py` gives the receipt's totals from them. `tools/compare.py QUESTIONS
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
`<set>/<tool>/<date>/` with each run's `run.json`.
Each run's scripts, logs and releases are under `runs/<date>/`.
