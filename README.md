# recall-benchmarks

How often does a tool that searches past agent sessions return the turn that answers a question
among its first 8 results? Each tool reads the same sessions and gets the same questions, asked as
written, at its defaults.

I wrote funes, one of the tools compared here. Everything needed to check the results is public:
the rules, the drivers and each tool's raw answers.

## Results

Questions answered within a tool's first 8 results:

| tool | funes-memory (244 questions) | longmemeval (470 questions) |
|---|---|---|
| funes 1.10.0+dev | 128 | 254 |
| MemPalace 3.11.0 | 85 | 153 |
| agentmemory 0.9.31 | 66 | 225 |
| deja-vu 0.23.5, `search` | 58 | 219 |
| deja-vu 0.23.5, `recall` | 43 | 184 |

funes leads on both sets. Counting the right session rather than the right turn, it ties with
deja-vu's `search` on longmemeval.

The receipts give every score, including each tool's optional modes:
[funes-memory](results/funes-memory/2026-11-03.md), [longmemeval](results/longmemeval/2026-11-04.md).

The same runs also scored ctx, cass, claude-history and agentsview, which are no longer compared
here. At their defaults none found more than 29 funes-memory answers or 67 longmemeval ones.
claude-history's optional semantic search was level with funes on funes-memory, but its cache cannot
hold longmemeval's sessions. Their scores are in the receipts at `3aebb37`:
[funes-memory](https://github.com/dacorvo/recall-benchmarks/blob/3aebb37dffb4748ea92f9d9273dd2129cc021440/results/funes-memory/2026-11-03.md),
[longmemeval](https://github.com/dacorvo/recall-benchmarks/blob/3aebb37dffb4748ea92f9d9273dd2129cc021440/results/longmemeval/2026-11-04.md).

## The two sets

- **funes-memory**: questions about funes's own development, over its public memory of 139 coding
  sessions. They are worded the way someone asks weeks later, without the answer's words. They come
  from the [funes recall benchmark](https://huggingface.co/datasets/dacorvo/funes-recall-benchmark).
- **longmemeval**: the answerable questions of [LongMemEval](https://github.com/xiaowu0162/LongMemEval),
  asked over all 19,195 of its chat sessions at once. [longmemeval/](longmemeval/) says how its
  answers were marked.

## How the tools are compared

- Every tool reads the same sessions: funes from its published memory of them, the others as Claude
  Code transcripts rebuilt from that memory.
- Each tool runs at its defaults, in its own home, with no API key or hosted service. That leaves
  out claude-mem, which needs an LLM to write its memory.
- Each question is asked once, as written. Each result is traced back to the turn it comes from,
  and a question counts as answered when one of the first 8 results falls on the answer's turn or
  next to it.
- Each tool's raw answers are in the bucket
  [`dacorvo/recall-benchmark`](https://huggingface.co/buckets/dacorvo/recall-benchmark).

[METHOD.md](METHOD.md) has the full rules, how results are traced and scored, and how to run a tool.

## License

Apache-2.0. `longmemeval/questions.jsonl` holds LongMemEval's questions and answers, under its MIT
license.
