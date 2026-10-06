# Design decisions

The decisions that shape this repository, the alternative each one was weighed against, and why.

| decision | alternative considered | chosen | why |
|---|---|---|---|
| Retrieval | Embed transcripts into a vector store and retrieve similar calls or policy text | **No vector store, no retrieval** | Each call is judged on its own content; nothing retrieved makes the judgement more correct. Retrieval adds a pipeline, a failure mode and a cost line for no gain |
| Who produces the score | Ask the model for "satisfaction 1-5" directly | **The model extracts typed fields; code scores** (`scoring.py`) | Reproducible, retunable without re-running the model, explainable in one line, and testable. A model's 1-5 is an uncalibrated opinion |
| Satisfaction vs sentiment | One model judgement, or one blended score | **Separate evidence**: satisfaction = f(resolution, effort); sentiment = g(expressed cues) | The gap between them is the most useful output (polite and unresolved is the churn risk). A test pins that resolution never changes sentiment |
| Evidence | Trust extracted fields as given | **Every field carries spans; spans are validated; a count with no supporting turn is dropped** | When a score is disputed, the answer is transcript lines. Jev cites turns by label, so it can only point at real turns |
| Bad transcripts | Score everything, perhaps with a lower confidence | **Quality gate routes to human review, never scored** | Scoring garbled or unlabelled transcripts produces confident garbage. The gate's reasons go into the review queue |
| Multi-intent calls | Score the call once | **Segment by intent, score each, worst-weighted roll-up** (0.65 worst + 0.35 mean) | A resolved balance query must not hide an unresolved complaint in the same call |
| Agent gaming | Count an agent's "that's all taken care of" as resolution | **Resolution judged from the caller's side**; a disputed claim is flagged | Agents learn the markers; the caller's reaction is harder to game |
| Evaluation split | Iterate and report on the same labelled set | **200 dev / 100 sealed holdout**, holdout read once per run through one function, ledgered by hash | Iterating on the evaluation set finds a winner by chance |
| Noise floor | Compare point estimates | **Bootstrap CIs, the baseline run twice, paired bootstrap of differences** | A change counts only if it clears both sampling and run-to-run noise |
| Ceiling | Report model accuracy alone | **Two annotators; report their agreement first; compare the system with a single annotator like for like** | If humans agree at 0.85, a system at 0.76 vs one annotator may be at ceiling |
| Calibration method | Platt / ordinal logistic, or linear rescaling | **Weighted isotonic regression**, out-of-fold error | Monotone, assumption-light, works on a few dozen points. Its weakness (variance at small n) is reported rather than hidden |
| Survey response bias | Average survey answers as they come | **Inverse response-rate weights per raw-score band** | Unhappy callers answer more; the response rate per band is observable because every call has a raw score |
| Model backend | A general LLM with prompt-and-parse | **Jev (System One): typed Choice/Noul answers with probabilities**, behind an interface with a rule-based backend | Typed answers need no parsing, give a confidence per field, and cost about $4 per 20,000 calls at the published price. The rule backend lets everything run without a key |
| Reproducibility | Re-call the API on every run | **Pinned model id, versioned questions, disk cache of every response, versions on every row** | A score that cannot be regenerated cannot be defended |
| Agent workflow | Free-form agent edits | **Working agreement in `CLAUDE.md`, guard hook on protected data and acceptance tests, tests after every edit, read-only reviewer** | Makes the rules above mechanical rather than aspirational |
