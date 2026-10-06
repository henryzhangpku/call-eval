# call-eval

**Post-call customer experience evaluation for contact-centre transcripts (lending and servicing calls).**

Every night a servicing desk records thousands of calls. This project scores each one for
customer satisfaction (1 to 5) and sentiment (happy, mild, not happy) in a way you can audit:
a model reads the transcript and extracts typed facts with evidence spans (was each request
resolved, how hard did the caller have to work, what did they say they felt), deterministic
code turns those facts into scores, a calibration layer anchors the score to post-call surveys,
and every number carries the transcript lines that produced it and a one-line explanation such
as *"scored 2: disputed charge or credit report not resolved; transferred once"*. It runs end to
end with no API key (rule-based extractor and a committed response cache), or live against Jev,
a System One model that answers typed questions with probabilities rather than prose.

> **All data in this repository is synthetic.** 400 generated calls, two simulated annotators,
> simulated surveys. The measurements below describe the system on that data, not on real callers.

**Demo:** `docs/` is a static site (no build step). Run `python -m http.server -d docs` and open
http://localhost:8000, or publish the folder with GitHub Pages.

## What it proves, measured

Measured on 400 synthetic calls. Agreement uses the 200-call dev split for iteration and a
100-call holdout that was evaluated **once per system** (hashes in `runs/holdout_ledger.json`).
Intervals are 95% bootstrap over calls.

| | dev (200) | sealed holdout (100) |
|---|---|---|
| **Human ceiling**: annotator A vs B, satisfaction (quadratic-weighted kappa) | 0.846 [0.799, 0.887] | 0.869 |
| **Human ceiling**: annotator A vs B, sentiment (kappa) | 0.631 [0.529, 0.720] | 0.586 |
| Jev, satisfaction vs adjudicated label | 0.858 [0.806, 0.900] | 0.854 [0.782, 0.911] |
| Jev, sentiment vs adjudicated label | 0.784 [0.701, 0.858] | 0.820 [0.699, 0.911] |
| Rules (offline), satisfaction vs adjudicated label | 0.874 [0.833, 0.905] | 0.848 [0.781, 0.896] |
| Rules (offline), sentiment vs adjudicated label | 0.808 [0.734, 0.882] | 0.871 [0.782, 0.962] |
| Like for like with the ceiling: system vs a single annotator, satisfaction (Jev / rules) | 0.760 / 0.757 | 0.761 / 0.751 |
| Coverage: share of labelled calls that passed the quality gate and were scored | 86.5% | 85% (Jev), 84% (rules) |

| Operations (Jev backend, model `jev-1.13.0`, measured against the live API) | |
|---|---|
| Latency per request | p50 140 ms, p95 200 ms |
| Latency per call (call-level request, then the intents in parallel) | p50 293 ms, p95 419 ms |
| Requests per call | 2.78 |
| Throughput at concurrency 6 | 37.7 requests/s, about 13.6 calls/s |
| Input tokens per call | 4,923 |
| Model cost per call / per 20,000 calls | $0.00021 / **$4.14** (at $0.042 per million input tokens, output free; published price checked 2026-10-06, verify on the day) |
| Run-to-run noise (same model, same questions, run twice on dev) | 98.8% identical satisfaction, 99.4% identical sentiment, kappa spread 0.012 |
| Rule-based throughput | about 6,300 calls/s on one core |

| Calibration (isotonic, fit on 83 non-holdout survey calls, error measured out of fold) | raw | calibrated |
|---|---|---|
| Jev: expected calibration error, survey points | 0.23 | **0.14** |
| Rules: expected calibration error, survey points | 0.11 | 0.14 (worse: see limitations) |

**What the numbers say, plainly.**

- Both backends reach the human ceiling on satisfaction. Against a single annotator they score
  about 0.76, against the annotators' 0.85 with each other, and both are within sampling noise
  of each other. Pushing for more on this data would be chasing annotator noise.
- **The rule-based extractor is not worse than Jev here, and that is a property of the data, not
  a result about rules.** Its lexicons were written by reading transcripts produced by the same
  template family the generator uses, so it is close to an upper bound for rules. Jev never saw
  the templates. The paired dev comparison, Jev minus rules, is -0.016 [-0.046, +0.011] on
  satisfaction and -0.025 [-0.080, +0.033] on sentiment: no detectable difference. On real
  transcripts, with paraphrase the rules never anticipated, expect the rules to fall away.
- One dev iteration of the Jev questions (q-v2 to q-v3) moved sentiment kappa by +0.059
  [+0.008, +0.110] and satisfaction by +0.020 [-0.001, +0.049]. The sentiment gain clears both
  noise floors; the satisfaction gain does not clear sampling noise, so it is reported as not shown.
- The churn-risk quadrant (polite and unresolved) is found with high precision but modest recall:
  on the holdout, rules flag 8 of 15 such calls and Jev 6 of 15, with no false alarms. That is the
  next thing to improve, and the reason the extraction of "resolved" matters more than anything else.
- Calibration helps the Jev scores (0.23 to 0.14 survey points) and does not help the rule scores,
  whose raw scale was already close to the survey scale; with 83 surveys an isotonic map adds noise
  to a scale that is already right. Rule for publishing: if calibrated error is not clearly below
  raw, publish buckets, not numbers.

## Quickstart

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"          # Windows: .venv\Scripts\pip install -e ".[dev]"
python -m calleval generate                # deterministic synthetic data (already committed)
python -m calleval run --backend offline   # rule-based extractor, no key, no network
python -m calleval run --backend jev       # Jev; replays cache/jev_cache.jsonl, calls the API only on a miss
python -m calleval evaluate                # ceiling, dev agreement, noise floor, paired comparisons
python -m calleval holdout --run offline   # sealed holdout: refuses a second run unless --force
python -m calleval export-demo             # docs/data/demo.json from the runs on disk
pytest
```

A run rewrites `runs/<run-id>/` (default: the backend name) and restamps every row with the
current code version; use `--run-id my-experiment` to keep the recorded runs untouched.

The Jev backend needs `pip install -e ".[jev]"` (the `typesafe-sdk` package) and, for a cache
miss, `TYPESAFE_API_KEY` in the environment. The SDK reads the key itself; this code never reads,
logs or stores it. Add `--replay` to forbid network calls entirely. The holdout for `offline` and
`jev` has already been used; a second run is refused, as designed.

## Architecture

```
  transcripts (nightly batch)
        |
   QUALITY GATE         speaker labels present, ASR confidence, inaudible share, length,
        |               dropped mid-sentence, cross-talk          -> failures go to human review
        |
   SEGMENT BY INTENT    one call -> N intents, each with a turn range (keywords; Jev adds
        |               intents the keywords miss, e.g. ASR turned "escrow" into "S grow")
        |
   EXTRACT, per intent, into a fixed typed schema           (calleval/schema.py)
        |   resolved: yes / partial / no         + evidence span (turn, start, end, quoted text)
        |   effort: repeats, transfers, holds, callback       + spans
        |   expressed feeling cues: positive / neutral / negative + spans
        |   backend: rules (offline)  |  Jev Choice/Noul questions, turns cited by label
        |
   VALIDATE             every span must quote real transcript text; counts need evidence
        |
   SCORE IN CODE        satisfaction = f(resolved, effort), worst-intent-weighted roll-up
        |               sentiment    = g(expressed cues)      <- separate evidence
        |               + one-line explanation + the spans that produced each score
        |
   CALIBRATE            isotonic map raw -> survey scale, inverse-response-rate weights,
        |               out-of-fold calibration error, reliability diagram
        |
   STORE                per call and intent: every field, span, score, and versions
        |               (model id, question version, backend, scoring, gate, code)
        |
   AGGREGATE            by agent / intent / day; satisfaction x sentiment quadrant;
                        churn-risk list; review queue with reasons
```

## Three design choices

**1. The model extracts, code scores.** The model never emits "3 out of 5". It answers typed
questions: was the payoff request resolved (yes/partial/no, with probabilities), how many times
did the caller repeat themselves, which numbered turn shows the outcome. `calleval/scoring.py`
turns those fields into the score. Scores are reproducible, retunable without re-running the
model (change a weight, rescore from stored extractions), and explainable in one line.

**2. Satisfaction and sentiment come from different evidence.** Satisfaction is resolution and
effort. Sentiment is what the caller expressed. A test pins this: changing resolution never
changes sentiment. The gap between them is the most useful output: a caller whose problem was not
solved but who stayed polite does not complain on the call, scores "mild" on sentiment, and is the
churn risk. A single blended score hides exactly that cell.

**3. Every score carries the spans that produced it.** When an agent disputes a review or a
lender asks why a number moved, the answer is transcript lines, not "the model said so". Spans are
validated against the transcript before anything is scored, Jev cites turns by label (so it can
only point at real turns), and a count with no supporting turn is dropped rather than scored.

## Why this is not RAG

There is nothing to retrieve. Each call is scored on its own content; no other document makes the
answer more correct. A vector index would add an embedding pipeline, a retrieval failure mode and
a cost line while contributing nothing to the judgement. The work is extraction into a fixed
schema, deterministic scoring, and calibration against an external signal (surveys), and the hard
part is evaluation discipline, not search.

## Four-week production plan

| week | do | the thing people skip |
|---|---|---|
| **1. Golden set and agreement** | Freeze a cutoff, sample 300 calls stratified by intent and agent, check ASR quality, two annotators label intent, resolution, effort and sentiment against a written guide | Measure inter-annotator agreement before building anything: it is the ceiling. Split 200 dev / 100 sealed now, and record the split |
| **2. Extraction and scoring** | Quality gate, segmentation, the typed schema, extraction questions, scoring in code; run on the 200 and get first numbers with bootstrap intervals | Store model id, question version and code version on every row from day one. Run the baseline twice to measure the run-to-run noise floor |
| **3. Calibration, sealed holdout** | Iterate questions and scoring weights on the dev 200 only; fit the isotonic calibration on survey calls with response-bias weights; evaluate on the sealed 100 once | A change counts only if a paired comparison clears both noise floors. The holdout is ledgered and refuses a second look |
| **4. Shadow run** | Run a full night, about 20,000 calls, in shadow: nobody outside the team sees a score. Compare with surveys where they exist, check the review-queue rate, check the score distribution | Publish as buckets until the reliability diagram is near the diagonal. Add an alert on score-distribution shift as the drift detector, and schedule recalibration |

**Cost of the shadow night.** Measured here: 4,923 Jev input tokens per call. 20,000 calls is
about 98 million input tokens; at the published Jev price of $0.042 per million input tokens
(output free, checked 2026-10-06) that is about **$4 a night**. Real transcripts run longer than
these synthetic ones (the design assumes about 2,000 transcript tokens per call), so budget two to
three times that, still under $15 a night. Verify the price on the pricing page on the day; prices
change. Throughput is not the constraint either: at the measured 13.6 calls/s with concurrency 6,
20,000 calls take about 25 minutes, against a six-hour nightly window.

## Honest limitations

- **Synthetic data.** Calls, annotators and surveys are generated (`calleval/generate.py`). The
  generator's phrasing comes from a closed set of templates with ASR noise on top, so agreement
  numbers are optimistic for any extractor, and much more so for the rules.
- **The offline extractor is rule-based** and was written against those templates. It exists so
  everything runs without a key and as a baseline; it is not a claim that rules work on real calls.
- **The adjudicated label is simulated** as recovering the latent truth. Real adjudication is
  noisier; the like-for-like comparison (system vs a single annotator) does not depend on it.
- **Real transcripts need real surveys.** Calibration here uses 83 simulated survey answers with a
  simulated response bias; the bias weights are estimated from who answered, which works only if
  response depends on what the score sees.
- **Jev's evidence for effort counts** combines the turn the model cites with lexical locators;
  an effort signal phrased in a way neither finds is dropped rather than scored.
- **One leak, disclosed.** An eight-call smoke test of the first question version included two
  holdout calls (see `METHODOLOGY.md`); the changes that followed were generic.

## Repository layout

```
calleval/            the package: generate, quality, segment, extract/{offline,jev,locate},
                     schema, scoring, calibration, metrics, evaluate, aggregate, export, cli
data/                synthetic calls, surveys, golden dev set, sealed holdout, splits, answer key
cache/               Jev responses (answers and timings only, no credentials)
runs/                predictions and summaries per run, dev report, holdout ledger
docs/                static web demo (index.html, app.js, style.css, data/demo.json)
tests/               pytest: determinism, span integrity, gate, holdout guard, calibration, schema
METHODOLOGY.md       how the evaluation was run, including what went wrong
```

## License

MIT. See `LICENSE`.
