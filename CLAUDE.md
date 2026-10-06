# Working agreement for coding agents in this repository

This file is read by Claude Code (and is useful to any coding agent or human contributor).
The hooks in `.claude/settings.json` enforce the parts that can be enforced mechanically.

## How to work

1. **Plan first.** Before editing, state the step you are taking from `PLAN.md`, the files you
   will touch, and the test that will prove it. Wait for a go on anything that changes behaviour.
2. **Small steps.** One plan step per change. Run the tests after each step (the PostToolUse hook
   does this automatically and reports failures).
3. **Tests before code.** Write or extend the test that proves the step, watch it fail, then make
   it pass. New edge-case tests go in `tests/test_edge_cases.py`.
4. **Never weaken a test.** The acceptance tests (`tests/test_*.py`, except
   `tests/test_edge_cases.py`) are blocked from editing by `.claude/hooks/guard.py`. If one is
   wrong, stop and say so; do not edit around it, skip it, or mark it expected-to-fail.
5. **The model extracts, code decides.** A model may only fill the typed schema in
   `calleval/schema.py` (categorical fields, counts, evidence spans). It never produces a score.
   Scores, roll-ups, thresholds and explanations live in deterministic code
   (`calleval/scoring.py`, `calleval/aggregate.py`).
6. **Only the extractor may call a model.** Network calls to a model live in
   `calleval/extract/jev.py` and nowhere else. Every response is cached in `cache/`.
7. **The holdout is read through one function.** `calleval.evaluate.evaluate_holdout` is the only
   code that opens `data/golden/holdout_sealed.csv`. It writes the ledger and refuses a second run
   for the same run id. Never read the holdout file directly, never `--force` without the owner.
8. **Touch only the files the step names.** No drive-by refactors. Generated data, the answer key
   and the holdout ledger are never hand-edited (the guard blocks them); change the generator and
   regenerate instead.
9. **Secrets.** `TYPESAFE_API_KEY` comes from the environment and is read by the SDK. Never print
   it, log it, write it to a file, or put it in a command line.
10. **Honest results.** Report what the evaluation says, including regressions and noise. A change
    counts only if a paired comparison clears both the bootstrap and the run-to-run noise floor.

## Project facts

**Commands** (use the repo venv: `.venv/Scripts/python` on Windows, `.venv/bin/python` elsewhere)

```
python -m calleval generate                      # deterministic synthetic data, seed 20260914
python -m calleval run --backend offline         # rule-based extractor, no key
python -m calleval run --backend jev [--replay]  # Jev; cache first, API only on a miss
python -m calleval run --backend jev --run-id X  # experiments: never overwrite recorded runs
python -m calleval evaluate                      # dev split only: ceiling, agreement, noise, paired deltas
python -m calleval holdout --run <id>            # sealed holdout, once per run id
python -m calleval export-demo                   # docs/data/demo.json
python -m pytest -q                              # full suite, a few seconds, no network
```

**Data contract**

- `data/calls.jsonl`: one call per line, `{call_id, date, agent_id, duration_s, turns: [{speaker:
  "agent"|"caller"|null, t, text, conf}]}`. This is all the pipeline may see.
- `data/surveys.csv`: `call_id, survey_csat` for about a third of calls (biased toward unhappy).
- `data/golden/dev.csv` (200) and `holdout_sealed.csv` (100): two annotators (`a_*`, `b_*`) and the
  adjudicated label (`adj_*`). `splits.json` lists the ids only.
- `data/_answer_key/`: latent truth, for synthetic-only diagnostics. Never used to fit or tune.
- Extraction schema: `calleval/schema.py` (`IntentExtraction`, `Span`, `validate_call`). Every span
  must satisfy `turns[span.turn].text[span.start:span.end] == span.text`.
- Prediction rows (`runs/<id>/predictions.jsonl`) carry `versions`: code, backend, model id,
  question version, scoring, gate, segmenter, calibration.

**Where things live**

| what | where |
|---|---|
| quality gate | `calleval/quality.py` |
| intent segmentation | `calleval/segment.py` |
| extractors | `calleval/extract/offline.py`, `calleval/extract/jev.py`, shared locators in `locate.py` |
| scoring (code, not model) | `calleval/scoring.py` |
| calibration | `calleval/calibration.py` |
| metrics, evaluation, holdout guard | `calleval/metrics.py`, `calleval/evaluate.py` |
| roll-ups, export | `calleval/aggregate.py`, `calleval/export.py` |
| plan, decisions, method | `PLAN.md`, `DECISIONS.md`, `METHODOLOGY.md` |
| agent tooling | `.claude/settings.json`, `.claude/hooks/`, `.claude/agents/`, `.claude/commands/` |
