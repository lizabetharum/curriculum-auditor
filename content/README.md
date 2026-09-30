# Test content

Everything in this folder is synthetic. It was written for this repository to exercise the auditor, and none of it is real student work or a lesson taught in a classroom.

| File | What it is |
|---|---|
| `lesson-heights.md` | A one-period lesson on right-triangle trigonometry, with three planted errors in its answer key |
| `answer-key.json` | The same answer key as structured items for `curriculum-auditor math` |
| `responses.json` | 16 student responses: r01 to r08 answer Task A, r09 to r16 answer Task B |
| `responses.md` | The same responses, formatted for reading |
| `targets.sha256` | A hash of the hidden target levels (see below) |

## The planted errors

The answer key has three mistakes. They were chosen to show what deterministic checking can and cannot catch.

1. **Calculator in radian mode (B4).** The key says 15 × tan(38°) + 1.5 = 6.15 m. In degrees the height is 13.22 m. The 6.15 comes from computing tan(38) in radians, and it looks plausible for a tree, which is what makes the error dangerous. The math checker catches it.
2. **Dropped a term (extension).** The key writes 25 × tan(25°) + 1.5 but reports 11.66 m, the value without the 1.5. (The correct 13.16 m agrees with Task B's 13.22 m to within 6 cm, which is the point of the extension.) The math checker catches it.
3. **Wrong ratio (exit ticket).** The key uses 40 × cos(55°) = 22.94 m. The arithmetic is right, but the kite's height is opposite the angle, so it needs sine: 32.77 m. The math checker does not catch this, and it is not designed to. It confirms that an answer matches an expression. Whether the expression models the problem is a judgment call, which Claude may flag and a teacher has to confirm.

Run the check yourself:

```sh
uv run curriculum-auditor math content/answer-key.json
```

## The responses and their hidden targets

Each response was written to show a specific level (or no evidence) on two XQ component skills:

- Task A: FL.MST.2.a Modeling and FL.MST.1.e Checking results
- Task B: FL.ID.3.b Explaining my reasoning and FL.MST.2.c Explaining models

Those intended levels are the targets. They sit in `data/targets.json`, which Git ignores, so they stay out of sight until the blind labels are done. `targets.sha256` is committed now. When the targets are published later, anyone can confirm they match this hash and were not adjusted after the labels or the model scores came in.

The targets are one person's intent while writing. They are not ground truth. The agreement report compares Claude's scores with the human labels, not with the targets.

## Blind labeling

About 30 minutes. Do this before looking at any model scores or at `data/targets.json`.

1. Fetch XQ if you have not: `uv run curriculum-auditor fetch`
2. Read the four skills' levels: `uv run curriculum-auditor describe FL.MST.2.a FL.MST.1.e FL.ID.3.b FL.MST.2.c`
3. Read the task text in `lesson-heights.md` and the responses in `responses.md`.
4. Fill in the `level` column of `labels/xq-labels.csv`: 1, 2, 3, or 4, or `IE` when the work does not show enough to place it at any level. Missing evidence is IE, not Level 1.
5. Commit the file. Only IDs and levels are in it, so no XQ text is published.
