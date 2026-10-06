# Methodology

How the numbers in the README were produced, in the order they were produced, including the
parts that went wrong. Everything here is reproducible from the repository.

## 1. Data (synthetic)

`python -m calleval generate` (seed 20260914) writes 400 calls. For each call the generator first
draws a latent truth and only then writes the transcript from it:

- **Intents.** 1 to 3 per call (55% / 35% / 10%) from balance, payment, escrow, payoff, hardship,
  dispute, late fee. Each intent has a difficulty; each of 12 agents has a skill.
- **Per-intent truth.** Resolved yes / partial / no from skill minus difficulty plus noise; effort
  signals (repeats, holds, transfers, callback); the caller's expressed feeling, driven by
  resolution, effort and a caller temperament (polite, neutral, irritable). Polite callers stay
  mild even when nothing was solved, which creates the polite-but-unresolved quadrant.
- **Call truth.** Satisfaction = 0.65 x worst intent + 0.35 x mean intent, each intent from
  resolution minus effort penalties plus noise, rounded to 1-5. Sentiment from the expressed
  feelings, with the closing remark weighted. Truth distribution: 51 / 66 / 63 / 97 / 123 calls at
  1-5; 150 happy, 169 mild, 81 not happy; 72 calls in the low-satisfaction, not-unhappy cell.
- **Mess.** ASR substitutions in 30% of calls ("escrow" to "S grow", "forbearance" to "for
  bearings"), missing speaker labels (5%), dropped calls cut mid-sentence (4%), cross-talk merges
  (6%), garbled low-confidence audio (4%), and two agents who sometimes claim a fix that did not
  happen ("that's all taken care of"), which the caller then disputes.
- **Surveys.** About a third of calls (141), with response bias: response probability is 60% at a
  true 1 and 22-28% at 4-5. Answers are noisy and pulled to the extremes.
- **Golden set.** 300 calls labelled by two simulated annotators: each is off by one on
  satisfaction about 27% of the time (annotator A leans lenient), off by two 3%, and moves
  sentiment to a neighbouring class 17% of the time. Adjudication is simulated as recovering the
  latent label. Split 200 dev / 100 holdout at generation time (`data/golden/splits.json`).
- **Answer key.** The latent truth is in `data/_answer_key/`. It is used only for diagnostics
  reported as "vs latent truth", never for fitting or tuning.

## 2. The ceiling first

On dev, annotator A vs B: satisfaction quadratic-weighted kappa 0.846 [0.799, 0.887], exact
agreement 58%, within one 94.5%; sentiment kappa 0.631 [0.529, 0.720]. On the holdout (computed
when the holdout was opened): 0.869 and 0.586. A system compared with one annotator cannot be
expected to beat the annotators' agreement with each other; that comparison is reported as
"vs annotators" next to the comparison with the adjudicated label.

## 3. What was run, in order

1. **Rules (offline), `rules-v1`.** Lexicons written while reading generator output, before any
   evaluation. Run once on all 400 calls. Not changed afterwards.
2. **Jev smoke test, question version q-v1.** Eight calls, C0001 to C0008, to check the SDK, the
   key and the answer shapes. **Two of the eight (C0003, C0007) are holdout calls.** This was a
   mistake: the smoke test should have drawn from dev. Their extracted fields were looked at. The
   problems seen were generic: payoff calls also triggered a "balance enquiry" intent at 0.82-0.84,
   and a single "which turn shows extra effort" question let a transfer turn stand in as evidence
   for a hold. The q-v1 cache was discarded.
3. **q-v2.** Sharper intent definitions (balance enquiry explicitly not a payoff quote), intent
   threshold 0.8, and one evidence-turn question per effort type. Smoke-tested on ten dev calls,
   then run on all 400 calls (`runs/jev-qv2`), and run a second time on dev with the cache
   bypassed (`runs/jev-qv2-r2`) to measure run-to-run noise.
4. **One dev iteration, q-v3.** Dev errors showed two patterns: a plan approved on the call with
   paperwork to follow ("I'll send the agreement today") was called partial, and impatience at
   repeating oneself ("I've said this twice now") was read as feeling, double-counting effort into
   sentiment. q-v3 clarifies both in the question text. Run on dev, compared with q-v2, then run on
   all 400 calls (`runs/jev`) and again on dev with the cache bypassed (`runs/jev-r2`).
5. **Holdout, once each.** `calleval holdout --run offline`, then `--run jev`. A third invocation
   was refused (exit code 2), as designed. The ledger records the sha256 of each predictions file,
   and a test checks that the committed predictions still match those hashes.

The holdout ledger records the code version as `0.1.0+0c77a46.dirty`: the q-v3 question text was
in the working tree and was committed immediately afterwards (commit a743236). The offline
predictions were produced before the first commit and carry `nogit.dirty`; that code is commit
94beb0f.

## 4. Noise floors and the comparisons that count

- **Sampling noise:** 95% bootstrap intervals over calls (1,000 resamples), about +/-0.05 on
  satisfaction kappa and +/-0.08 on sentiment kappa at n = 173.
- **Run-to-run noise:** Jev q-v3 run twice on dev gives 98.8% identical satisfaction, 99.4%
  identical sentiment, 99.0% identical resolution, kappa spread 0.012. (q-v2: 99.4%, 100%, 99.7%,
  0.001.) The rules are deterministic, so their run-to-run noise is zero.
- **Paired comparisons** (bootstrap of the difference over the same calls, 2,000 resamples):

| comparison on dev | satisfaction wk delta | sentiment k delta |
|---|---|---|
| Jev q-v3 minus Jev q-v2 | +0.020 [-0.001, +0.049] | **+0.059 [+0.008, +0.110]** |
| Jev q-v3 minus rules | -0.016 [-0.046, +0.011] | -0.025 [-0.080, +0.033] |

Only the sentiment improvement from q-v3 clears both noise floors.

## 5. Calibration

The raw satisfaction score (continuous, 1-5) is mapped to the survey scale with weighted isotonic
regression (pool adjacent violators), fit on survey calls that passed the gate and are not in the
holdout (83 calls). Each survey answer is weighted by the inverse response rate of its raw-score
band, estimated from which calls answered (the survey response depends on the caller's
experience, which the raw score sees). Calibration error is the count-weighted mean absolute gap
between mean predicted and mean observed survey score across the five bands, measured with
5-fold out-of-fold predictions so no call is scored by a map fit on itself.

| backend | raw | calibrated, weighted | calibrated, unweighted |
|---|---|---|---|
| Jev q-v3 | 0.228 | 0.141 | 0.157 |
| Jev q-v2 | 0.239 | 0.092 | 0.101 |
| rules | 0.105 | 0.142 | 0.083 |

Calibration helps where the raw scale is off (Jev) and hurts where it is already close (rules):
with 83 answers the isotonic map has few points per band and adds variance. The observed survey
mean is 3.40; reweighted for response bias it is 3.54, which is the size of the bias a naive
average would carry onto a dashboard.

## 6. Diagnostics against the latent truth (synthetic only)

On dev scored calls:

| | rules | Jev q-v3 |
|---|---|---|
| intent precision / recall | 1.000 / 0.993 | 0.936 / 1.000 |
| resolution accuracy per intent | 0.948 | 0.918 |
| weakest intent for resolution | payoff 0.902 | hardship 0.686 |
| repeats / holds exact | 0.997 / 0.997 | 0.966 / 0.935 |
| churn-quadrant precision / recall (vs adjudicated) | 1.000 / 0.857 | 0.875 / 0.667 |

On the holdout the churn quadrant is found with precision 1.0 by both, recall 8/15 (rules) and 6/15
(Jev). Jev's intent precision drops to 0.853 on the holdout: it adds intents the caller only
touched on, which then get scored. Hardship resolution is Jev's weakest field: it tends to call an
opened application "partial" where the generator's truth says resolved, which is
partly a labelling-guide question rather than a model error.

## 7. What would change with real data

- Replace the generator with a frozen sample of real calls and real annotators working from a
  written guide; the ceiling will be lower than 0.85 and must be measured, not assumed.
- Expect the rules to degrade sharply on real paraphrase; keep them only as a smoke test.
- Fit calibration on real surveys, weight for the real response pattern, recalibrate on a schedule,
  and alert on score-distribution shift.
