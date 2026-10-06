# Build plan

Each step names the test that proves it. A step is ticked only when that test passes on the
committed code. Unticked steps are the open work for whoever continues.

## Data

- [x] **1. Seeded synthetic generator.** 400 multi-intent servicing calls drawn from a latent truth
  (resolution, effort, expressed feeling), with ASR noise, lost speaker labels, dropped calls,
  cross-talk and garbled audio. Proof: `tests/test_generate.py::test_generator_is_deterministic`,
  `::test_shape_of_the_data`.
- [x] **2. Biased surveys and a two-annotator golden set, split 200 / 100.** Proof:
  `tests/test_generate.py::test_golden_split_is_200_100_and_disjoint` (realistic disagreement,
  disjoint splits) and the response-bias assertion in `::test_shape_of_the_data`.

## Pipeline

- [x] **3. Quality gate routes bad transcripts to review.** Proof: `tests/test_quality.py`, including
  `::test_gate_catches_every_bad_transcript_in_the_data`.
- [x] **4. Typed extraction schema with validated evidence spans.** Proof: `tests/test_schema.py`.
- [x] **5. Intent segmentation and the rule-based extractor.** Proof:
  `tests/test_spans.py::test_offline_spans_point_at_real_text`.
- [x] **6. Deterministic scoring with explanations; sentiment independent of resolution.** Proof:
  `tests/test_scoring.py` (determinism, ordering, bounds, `::test_sentiment_ignores_resolution`,
  explanations and versions on every row).
- [x] **7. Jev extractor behind the same interface, cached, with latency and token accounting.**
  Proof: `tests/test_spans.py::test_jev_cached_spans_point_at_real_text` (replays the committed cache
  with no network) and `tests/test_architecture.py::test_only_the_jev_extractor_calls_a_model`.
- [x] **8. Isotonic calibration with response-bias weights and out-of-fold error.** Proof:
  `tests/test_calibration.py`.

## Evaluation

- [x] **9. Agreement metrics and the annotator ceiling.** Proof: `tests/test_metrics.py`.
- [x] **10. Sealed holdout: one read per run, ledgered, refuses a second.** Proof:
  `tests/test_holdout.py` and `tests/test_architecture.py::test_only_evaluate_holdout_reads_the_sealed_holdout`.
- [x] **11. Baseline run twice for the run-to-run noise floor; paired bootstrap for comparisons.**
  Proof: `runs/dev_report.json` (`noise_floor_run_to_run`, `iterations`), produced by
  `python -m calleval evaluate`.
- [x] **12. Record the runs: rules and Jev on all calls, holdout once each.** Proof:
  `tests/test_holdout.py::test_ledger_hashes_match_committed_predictions`,
  `::test_committed_ledger_shows_each_run_used_once`.

## Delivery

- [x] **13. Roll-ups, churn-risk quadrant, review queue; static demo from real runs.** Proof:
  `python -m calleval export-demo` writes `docs/data/demo.json`; `tests/test_spans.py::test_prediction_rows_spans_match_transcripts`.
- [x] **14. Agent tooling: working agreement, edit guard, post-edit tests, reviewer, commands.**
  Proof: `tests/test_guard.py`, `tests/test_architecture.py`.

## Open

- [ ] **15. Raise churn-quadrant recall.** On the holdout both backends flag the polite-unresolved
  calls with precision 1.0 but recall 8/15 (rules) and 6/15 (Jev). Work on dev only: inspect missed
  calls, decide whether the miss is resolution or sentiment, change one thing, re-measure with the
  paired bootstrap. Proof: a new dev-only metric test plus a paired delta that clears both noise floors.
- [ ] **16. Tighten Jev intent precision.** Model-added intents (0.936 dev, 0.853 holdout precision)
  get scored. Candidate: require a caller turn the model cites for a model-only intent. Proof: dev
  intent precision up without recall loss, in `diagnostics_vs_latent_truth`.
- [ ] **17. Score-distribution drift alert.** Compare each night's score histogram with a reference
  window and alert past a threshold. Proof: a unit test with a synthetic shifted night.
- [ ] **18. Replace synthetic data with a frozen sample of real calls and real annotators.** Proof:
  a new ceiling measured on real labels, recorded before any extraction work.
