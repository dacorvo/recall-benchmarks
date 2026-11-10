# LongMemEval

[LongMemEval](https://github.com/xiaowu0162/LongMemEval) (arXiv:2410.10813) asks 500 questions about
long chat histories between a user and an assistant, and marks the turns that hold each answer
(`has_answer`). These are its questions, asked over every distinct session of its LongMemEval-S
haystacks at once, with each marked turn as an answering turn, along with every turn of the pile that
holds its role and text.

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
{"id": "e47becba", "kind": "single-session-user", "question": "What degree did I graduate with?", "answer": "Business Administration", "gold": [{"session_id": "answer_280352e9", "turn": 4}, {"session_id": "answer_280352e9", "turn": 5}, {"session_id": "280352e9", "turn": 4, "copy_of": "answer_280352e9"}, {"session_id": "280352e9", "turn": 5, "copy_of": "answer_280352e9"}]}
```

Its gold lists the marked turns as answering turns, the format of the funes recall benchmark's sets: a
question counts as answered when a tool's reply shows one of them. Turns are numbered as funes numbers
them: funes skips blank turns, so a turn's number is its index among its session's non-blank turns (10
turns of 5 sessions are blank). Any answering turn counts, also when the answer is spread over several
sessions (LongMemEval's own `recall_all` asks for every one of them).

Some sessions are copies of each other under different ids: 731 of the 19,195 repeat the non-blank
turns of another one, role and text (640 groups of 2 to 4 sessions, such as `280352e9` and
`answer_280352e9` above). A copy holds the same turns as the session LongMemEval marks, and no tool
can tell the two apart by what they hold. A tool that keeps one copy of each conversation can only
return the one it kept (MemPalace skips a conversation whose text it has already stored). So each
answering turn is also named in every copy of its session, with `copy_of` naming the session
LongMemEval marks. This departs from LongMemEval's labels, which name the marked session only. Scored
on the marked turns alone, every tool loses questions to how it orders two identical passages.

Other sessions repeat a marked turn without copying its whole session: 17 turns hold the role and
text of a marked turn of 12 questions, each in a session of its own. Most are opening prompts, such as
the first turn of `answer_5cc9b056`, which also opens `3bc55308` and `f26d40a1`. Each is an answering
turn too, with `repeats` naming the marked turn.

| kind | questions |
|---|---|
| temporal-reasoning | 127 |
| multi-session | 121 |
| knowledge-update | 72 |
| single-session-user | 64 |
| single-session-assistant | 56 |
| single-session-preference | 30 |

The 470 questions have 886 marked turns in 837 sessions. 187 questions have their marked turns in one
session, 228 in two and 55 in three to six. 318 of the marked sessions have copies (367 sessions),
which add 389 answering turns to 234 questions. With the 17 repeated turns, the gold holds 1,292
answering turns.

`questions.py` writes the file from the source and a local copy of the memory (it needs pylance), and
checks that the memory holds every answering turn, copies and repeats included, with the source's
text. They all do. (6 turns of the memory differ from the source, all by funes's redaction of a
secret, and none is an answering turn.)

```bash
hf download xiaowu0162/longmemeval-cleaned longmemeval_s_cleaned.json --repo-type dataset --revision 98d7416c24c778c2fee6e6f3006e7a073259d48f --local-dir src
hf download dacorvo/funes-xiaowu0162-longmemeval-cleaned-s --repo-type dataset --revision 58450d98655f3d104359fb119933d7a4d6597d13 --include 'chunks.lance/*' --local-dir mem
python3 questions.py src/longmemeval_s_cleaned.json mem/chunks.lance > questions.jsonl
```
