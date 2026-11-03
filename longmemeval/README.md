# LongMemEval

[LongMemEval](https://github.com/xiaowu0162/LongMemEval) (arXiv:2410.10813) asks 500 questions about
long chat histories between a user and an assistant, and marks the turns that hold each answer
(`has_answer`). These are its questions, asked over every distinct session of its LongMemEval-S
haystacks at once, with a gold span at each marked turn.

- source: `longmemeval_s_cleaned.json` of
  [`xiaowu0162/longmemeval-cleaned`](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned)
  at `98d7416c24c778c2fee6e6f3006e7a073259d48f`, sha256
  `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`
- memory: [`dacorvo/funes-xiaowu0162-longmemeval-cleaned-s`](https://huggingface.co/datasets/dacorvo/funes-xiaowu0162-longmemeval-cleaned-s)
  at `58450d98655f3d104359fb119933d7a4d6597d13`, funes's memory of the 19,195 distinct sessions of the
  500 haystacks (311,583 chunks). A session that several haystacks share is held once.
- questions: the 470 answerable ones, verbatim. The 30 abstention questions (ids ending in `_abs`)
  are left out: the history does not hold what they ask, and the expected answer is to decline.

`questions.jsonl` holds one question a line, with LongMemEval's question type as its `kind` and its
reference answer:

```json
{"id": "e47becba", "kind": "single-session-user", "question": "What degree did I graduate with?", "answer": "Business Administration", "gold": [{"session_id": "answer_280352e9", "from": 4, "to": 5}, {"session_id": "answer_280352e9", "from": 5, "to": 6}]}
```

A gold span is a marked turn and the turn after it, the rule of the funes recall benchmark's sharegpt
set, since a turn here is one whole message. Turns are numbered as funes numbers them: funes skips
blank turns, so a turn's number is its index among its session's non-blank turns (10 turns of 5
sessions are blank). A question is found by a passage in any of its spans, also when its answer is
spread over several sessions (LongMemEval's own `recall_all` asks for every one of them).

| kind | questions |
|---|---|
| temporal-reasoning | 127 |
| multi-session | 121 |
| knowledge-update | 72 |
| single-session-user | 64 |
| single-session-assistant | 56 |
| single-session-preference | 30 |

The 470 questions have 886 spans in 837 sessions. 187 questions have their spans in one session, 228 in
two and 55 in three to six. 13 spans hold one turn, where the marked turn ends its session.

`questions.py` writes the file from the source and a local copy of the memory (it needs pylance), and
checks that the memory holds every span's turns with the source's text. They all do. (6 turns of the
memory differ from the source, all by funes's redaction of a secret, and none is in a span.)

```bash
hf download xiaowu0162/longmemeval-cleaned longmemeval_s_cleaned.json --repo-type dataset --revision 98d7416c24c778c2fee6e6f3006e7a073259d48f --local-dir src
hf download dacorvo/funes-xiaowu0162-longmemeval-cleaned-s --repo-type dataset --revision 58450d98655f3d104359fb119933d7a4d6597d13 --include 'chunks.lance/*' --local-dir mem
python3 questions.py src/longmemeval_s_cleaned.json mem/chunks.lance > questions.jsonl
```
