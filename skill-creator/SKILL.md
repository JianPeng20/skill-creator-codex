---
name: skill-creator
description: Create, revise, and evaluate Codex skills. Use when the user wants to build a new skill, update an existing skill, define trigger conditions, add eval prompts or assertions, benchmark a skill against a baseline, optimize the SKILL.md description for better Codex triggering, or package/share a Codex-ready skill or plugin.
---

# Skill Creator

A workflow for creating and improving Codex skills.

At a high level, the process is:

- Decide what the skill should do and where it should live
- Draft or revise the skill
- Create realistic test prompts
- Run the skill and a baseline on those prompts
- Review qualitative outputs and quantitative assertions
- Improve the skill and repeat
- Optionally optimize the frontmatter description for better triggering
- Optionally package the result for sharing or wrap it in a plugin

Your job is to figure out where the user is in that loop and help them move
forward without making them do unnecessary process work.

## Communicating with the user

Skill authors vary a lot in familiarity with coding jargon. Default to plain
language, and only lean on terms like "assertion", "schema", or "benchmark"
when the user is clearly comfortable with them or when you briefly explain
them.

If the user just wants to "vibe" on a draft, do that. If they want rigor, drive
the full loop.

---

## Creating a skill

### Capture intent

Start by understanding the skill's job:

1. What should this skill enable Codex to do?
2. When should it trigger?
3. What should the output look like?
4. Where should it live?

For Codex, the usual destinations are:

- Local personal skill: `~/.agents/skills/<skill-name>/`
- Repo or plugin skill: `<plugin-root>/skills/<skill-name>/`

If the user already described a workflow in the conversation, mine the thread
for the tools used, step ordering, corrections, and output expectations before
asking follow-up questions.

### Interview and research

Ask about:

- edge cases
- input and output formats
- example files
- success criteria
- dependencies
- whether the skill needs scripts, references, or assets

If research helps, use local docs, MCP resources, Context7, or official docs as
appropriate. Come back with concrete options instead of pushing the burden to
the user.

### Write the SKILL.md

Every skill needs:

- `name`: lowercase, digits, hyphens only; keep it under 64 characters
- `description`: the trigger surface; include what the skill does and when to
  use it
- body instructions: the actual workflow Codex should follow after the skill is
  chosen

Descriptions matter a lot. Codex decides whether to load a skill mostly from
the `name` and `description` frontmatter, so be explicit about user intent. Do
not hide trigger guidance only in the body.

### Skill writing guide

#### Anatomy of a skill

```text
skill-name/
├── SKILL.md
├── scripts/      # optional deterministic helpers
├── references/   # optional docs loaded only when needed
└── assets/       # optional output assets/templates
```

#### Progressive disclosure

Keep `SKILL.md` lean. Move detailed docs to `references/` and point to them
clearly from the body.

Patterns that work well:

- variant-specific references such as `references/aws.md` and
  `references/gcp.md`
- large domain docs such as `references/finance.md` or `references/api.md`
- helper scripts for tasks the model otherwise rewrites repeatedly

Guidelines:

- Keep `SKILL.md` under roughly 500 lines when possible
- Link directly to reference files from `SKILL.md`
- Add a table of contents to longer reference files
- Avoid duplicating the same explanation in multiple places

#### Principle of lack of surprise

Do not help create misleading or malicious skills. The skill's contents should
match what the user intends to automate.

#### Writing patterns

Prefer imperative instructions and explain why steps matter. The goal is to
help Codex reason well, not to bury it in rigid rules unless the workflow is
fragile enough to need them.

Examples are useful. Include them when they sharpen behavior, not as filler.

### Test cases

After drafting the skill, create 2-3 realistic prompts that a real Codex user
would type. Save them to `evals/evals.json`.

Start with prompts only. Add assertions in the next step while runs are in
progress.

```json
{
  "skill_name": "example-skill",
  "evals": [
    {
      "id": 1,
      "prompt": "User task prompt",
      "expected_output": "Description of success",
      "files": []
    }
  ]
}
```

See `references/schemas.md` for the full schema.

---

## Running and evaluating test cases

Treat this as one continuous sequence. Do not stop after only running prompts or
only writing assertions.

Put results in `<skill-name>-workspace/` beside the skill directory. Organize by
iteration (`iteration-1/`, `iteration-2/`, ...) and by eval
(`eval-0/`, `eval-1/`, ...).

### Step 1: Materialize the candidate skill for evaluation

Codex only discovers skills from skill locations it knows about, so make the
candidate visible before running evals:

- For local personal evals, place or symlink the skill under
  `~/.agents/skills/<temp-skill-name>/`
- For plugin or repo evals, keep the skill in the plugin's `skills/` directory
- For description-only trigger evals, the bundled `scripts/run_eval.py` creates
  a temporary skill automatically

When iterating on an existing installed skill, snapshot the current version
before editing so you have a clean baseline.

### Step 2: Run with-skill and baseline executions

If `spawn_agent` is available, launch the with-skill run and the baseline run in
the same turn so they finish around the same time.

If agent spawning is not available, run the prompts sequentially with
`codex exec --ephemeral` or inline.

For each eval:

- write `eval_metadata.json`
- save outputs under `with_skill/outputs/`
- save the baseline under `without_skill/outputs/` or `old_skill/outputs/`

Use a descriptive eval directory name, not just `eval-0`.

```json
{
  "eval_id": 0,
  "eval_name": "descriptive-name-here",
  "prompt": "The user's task prompt",
  "assertions": []
}
```

Baseline rules:

- New skill: baseline is no skill
- Existing skill: baseline is the old version or previous iteration, depending
  on what comparison will be most informative

### Step 3: Draft assertions while runs are in progress

Do not wait idly. Draft or refine assertions while the runs are happening.

Good assertions are:

- objectively checkable
- easy to understand at a glance
- hard to satisfy by accident

Do not force assertions onto subjective tasks like prose quality or taste-driven
design unless you can turn them into something genuinely measurable.

Update both `eval_metadata.json` and `evals/evals.json` once the assertions are
ready.

### Step 4: Capture timing data

When a worker or `codex exec` run finishes, capture timing immediately.

- If your environment exposes `total_tokens` and `duration_ms`, save them
- Otherwise, record wall-clock start/end and compute `total_duration_seconds`
- Leaving `total_tokens` blank or `0` is acceptable when the environment does
  not expose it directly

Write `timing.json` beside each run:

```json
{
  "total_tokens": 0,
  "duration_ms": 23332,
  "total_duration_seconds": 23.3
}
```

### Step 5: Grade, aggregate, and launch the viewer

Once the runs finish:

1. Grade each run
   Use `agents/grader.md` or a programmatic checker where possible.
   Save results to `grading.json`.

2. Aggregate the benchmark

```bash
python -m scripts.aggregate_benchmark <workspace>/iteration-N --skill-name <name>
```

3. Do an analyst pass
   Use `agents/analyzer.md` to spot non-discriminating assertions, flaky evals,
   and time/token tradeoffs.

4. Launch the review UI

```bash
nohup python <skill-creator-path>/eval-viewer/generate_review.py \
  <workspace>/iteration-N \
  --skill-name "my-skill" \
  --benchmark <workspace>/iteration-N/benchmark.json \
  > /dev/null 2>&1 &
VIEWER_PID=$!
```

For iteration 2+, also pass `--previous-workspace <workspace>/iteration-<N-1>`.

If there is no browser or display, use `--static <output_path>` and have the
user open the HTML file directly. In static mode, feedback is downloaded as a
`feedback.json` file.

5. Tell the user what to review
   Point them to both the qualitative outputs and the benchmark tab.

### Step 6: Read the feedback

When the user finishes, read `feedback.json` and focus improvements on the evals
that received concrete complaints.

If you launched a live server, stop it afterward:

```bash
kill $VIEWER_PID 2>/dev/null
```

---

## Improving the skill

### How to think about improvements

1. Generalize from feedback instead of overfitting to the current prompts
2. Keep the prompt lean; remove instructions that create wasted work
3. Explain the why behind important behaviors
4. Look for repeated work across evals and turn it into bundled scripts or
   references

Read transcripts, not just final outputs. Often the real issue is in how the
skill steers the work, not just in the final file.

### The iteration loop

After revising the skill:

1. Apply the changes
2. Rerun the eval set into a new iteration directory
3. Relaunch the review UI with the previous iteration attached
4. Wait for user review
5. Improve again if needed

Stop when:

- the user is happy
- feedback is empty
- improvements stop being meaningful

---

## Advanced: Blind comparison

For stricter A/B comparisons, read `agents/comparator.md` and
`agents/analyzer.md`. This is useful when the user asks whether a new version is
actually better, not just different.

Blind comparison is optional.

---

## Description optimization

After the skill itself is in good shape, offer to optimize the frontmatter
description for better Codex triggering.

### Step 1: Generate trigger eval queries

Create about 20 realistic queries split between:

- should trigger
- should not trigger

The best negative examples are near misses, not obviously unrelated prompts.

The queries should sound like things a real Codex user would type: concrete
files, context, URLs, casual language, ambiguity, typos, and backstory.

### Step 2: Review with the user

Use `assets/eval_review.html`:

1. Read the template
2. Replace:
   - `__EVAL_DATA_PLACEHOLDER__`
   - `__SKILL_NAME_PLACEHOLDER__`
   - `__SKILL_DESCRIPTION_PLACEHOLDER__`
3. Write it to a temp HTML file and open it
4. Let the user edit the eval set and export the final JSON

This step matters. A bad eval set produces a bad description.

### Step 3: Run the optimization loop

Save the final eval set, then run:

```bash
python -m scripts.run_loop \
  --eval-set <path-to-trigger-eval.json> \
  --skill-path <path-to-skill> \
  --model <model-id-powering-this-session> \
  --max-iterations 5 \
  --verbose
```

The bundled scripts use `codex exec` under the hood. The loop evaluates the
current description, proposes revisions, re-runs train and held-out test sets,
and writes an HTML report showing each iteration.

### How triggering works in Codex

Codex decides whether to load a skill mainly from the `name` and `description`
frontmatter fields in `SKILL.md`.

Typical discovery locations are:

- `~/.agents/skills/`
- plugin `skills/` directories

Simple one-step prompts may not trigger a skill even if they share keywords,
because Codex may handle them directly. Multi-step or specialized prompts are
better trigger evals.

### Step 4: Apply the result

Update `SKILL.md` with `best_description`, then show the user:

- before/after description
- best score
- held-out test score if present

---

## Packaging and sharing

Codex does not need a Claude-style `.skill` bundle.

Use one of these paths instead:

- Local install: place the folder at `~/.agents/skills/<skill-name>/` and
  restart Codex
- Portable archive: run `python -m scripts.package_skill <path/to/skill-folder>`
  to create a `.zip` of the skill folder for sharing or backup
- First-class Codex distribution: use `plugin-creator` to scaffold a plugin,
  put the skill under `skills/`, and share the plugin

When updating an existing skill, preserve the original folder name and
frontmatter `name` unless the user explicitly wants a rename.

---

## Headless or no-collab environments

If you do not have agent spawning:

- run evals sequentially via `codex exec` or inline
- skip blind comparison unless you can emulate it cleanly
- use the static HTML reviewer if there is no browser

If you are editing a skill in a read-only install location, copy it to a
writable temp directory first, iterate there, then copy the final version back
or repackage it.

---

## Reference files

- `agents/grader.md` — grading assertions against outputs
- `agents/comparator.md` — blind A/B comparison
- `agents/analyzer.md` — benchmark and comparison analysis
- `references/schemas.md` — JSON structures for evals, grading, timing, and
  benchmarks

---

Core loop, one more time:

- Understand the skill
- Draft or revise it
- Run realistic prompts
- Review outputs and assertions with the user
- Improve the skill
- Optimize the description if useful
- Share it as a skill folder, archive, or plugin
