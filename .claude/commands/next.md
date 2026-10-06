---
description: Take the next unticked PLAN.md step, plan it, and wait for go
argument-hint: "[optional step number]"
---

Take the next step of the build plan.

1. Read `PLAN.md` and `CLAUDE.md`. Pick the first unticked step, or step $ARGUMENTS if given.
2. Write a short plan, and stop:
   - the step, in one sentence
   - the files you will touch (only those)
   - the test that will prove it, and whether it exists yet
   - risks: anything touching the holdout, the schema, scoring, or the model call
3. **Wait for the owner to say go.** Do not edit before that.
4. After go: write or extend the test first and show it failing, implement the smallest change
   that passes, run the suite, then ask the `reviewer` subagent to review the diff.
5. Tick the step in `PLAN.md` only when its proving test passes, and say what you measured.
