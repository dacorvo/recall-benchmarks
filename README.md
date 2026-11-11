# recall-benchmarks

How often does a tool that searches past agent sessions show the turn that answers a question in its
first 8 results? Each tool reads the same sessions and gets the same questions, asked as written, at
its defaults.

I wrote funes, one of the tools compared here. Everything needed to check the results is public:
the rules, the drivers and each tool's raw answers.

## Results

Questions answered within a tool's first 8 results:

| tool | funes-memory | sharegpt-en | sharegpt-zh | swe-chat-zh | swe-chat-pt | thomasmustier-pi-sessions | longmemeval |
|---|---|---|---|---|---|---|---|
| questions | 240 | 100 | 100 | 100 | 36 | 100 | 470 |
| funes 1.12.0+dev | 199 | 99 | 91 | 89 | 33 | 86 | 270 |
| MemPalace 3.11.0 | 103 | 97 | 53 | 24 | 24 | 42 | 139 |
| agentmemory 0.9.33 | 80 | 84 | 68 | 53 | 23 | 36 | 230 |
| deja-vu 0.24.1, `search` | 63 | 71 | 50 | 41 | 15 | 35 | 195 |
| deja-vu 0.24.1, `recall` | 57 | 85 | 32 | 31 | 9 | 40 | 166 |

funes finds the most answers on every set. Its reply shows each hit with the turns of its exchange
(the prompt that opened it, the assistant's last text and the next prompt), and an answer shown there
counts. Counting the hits alone, it finds 159, 98, 76, 61, 26, 68 and 257, still the most on every
set.

The receipts give every score, including each tool's optional modes:
[funes-memory](results/funes-memory/2026-11-10.md), [sharegpt-en](results/sharegpt-en/2026-11-10.md),
[sharegpt-zh](results/sharegpt-zh/2026-11-10.md), [swe-chat-zh](results/swe-chat-zh/2026-11-10.md),
[swe-chat-pt](results/swe-chat-pt/2026-11-10.md),
[thomasmustier-pi-sessions](results/thomasmustier-pi-sessions/2026-11-10.md),
[longmemeval](results/longmemeval/2026-11-10.md).

## The sets

- **funes-memory**: questions about funes's own development, over its public memory of 139 coding
  sessions.
- **sharegpt**: the same 100 questions in English and in Chinese, over the same 2,000 programming chats
  with a model: the English originals from ShareGPT (sharegpt-en) and their Chinese machine
  translation (sharegpt-zh).
- **swe-chat**: coding-agent sessions of public repositories whose developers write in Chinese or in
  Portuguese. 100 questions in Chinese over 635 sessions, 398 of them mostly in Chinese (swe-chat-zh),
  and 36 in Portuguese over 153 sessions, 34 of them mostly in Portuguese (swe-chat-pt).
- **thomasmustier-pi-sessions**: 100 questions over the 715 sessions of one developer with the pi agent.
- **longmemeval**: the answerable questions of [LongMemEval](https://github.com/xiaowu0162/LongMemEval),
  asked over all 19,195 of its chat sessions at once. [longmemeval/](longmemeval/) says how its
  answers were marked.

The first four come from the [funes recall benchmark](https://huggingface.co/datasets/dacorvo/funes-recall-benchmark).
Their questions are worded the way someone asks weeks later, without the answer's words, and each
lists its answering turns: the answer and its reviewed restatements.

## How the tools are compared

- Every tool reads the same sessions: funes from its published memory of them, the others as Claude
  Code transcripts rebuilt from that memory.
- Each tool runs at its defaults, in its own home, with no API key or hosted service. That leaves
  out claude-mem, which needs an LLM to write its memory.
- Each question is asked once, as written. Each result is traced back to the turns it shows, and a
  question counts as answered when one of the first 8 results shows one of its answering turns.
- Each tool's raw answers are in the bucket
  [`dacorvo/recall-benchmark`](https://huggingface.co/buckets/dacorvo/recall-benchmark).

[METHOD.md](METHOD.md) has the full rules, how results are traced and scored, and how to run a tool.

## License

Apache-2.0. `longmemeval/questions.jsonl` holds LongMemEval's questions and answers, under its MIT
license.
