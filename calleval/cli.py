"""Command line.

    python -m calleval generate                       synthetic calls, surveys, golden set, answer key
    python -m calleval run --backend offline          rule-based extractor, no key needed
    python -m calleval run --backend jev              Jev via typesafe-sdk (replays the cache; live calls on a miss)
    python -m calleval evaluate                       dev split: annotator ceiling, agreement, noise floor
    python -m calleval holdout --run offline          sealed holdout, once per run (ledgered)
    python -m calleval export-demo                    docs/data/demo.json from the runs on disk
"""

from __future__ import annotations

import argparse
import json
import sys

from calleval import paths


def _print_dev(report: dict) -> None:
    c = report["annotator_ceiling"]
    print(f"\nDEV split, {c['n']} calls")
    print(f"  annotator ceiling (A vs B): CSAT weighted kappa {c['csat_weighted_kappa']} {c['csat_weighted_kappa_ci']}, "
          f"sentiment kappa {c['sentiment_kappa']} {c['sentiment_kappa_ci']}")
    hdr = f"  {'run':<12}{'coverage':>9}{'CSAT wk adj':>13}{'95% CI':>16}{'wk vs ann':>11}{'within1':>9}" \
          f"{'sent k adj':>12}{'k vs ann':>10}"
    print(hdr)
    for r, m in report["runs"].items():
        print(f"  {r:<12}{m['coverage']:>9}{m['csat_weighted_kappa_vs_adjudicated']:>13}"
              f"{str(m['csat_weighted_kappa_vs_adjudicated_ci']):>16}{m['csat_weighted_kappa_vs_annotators']:>11}"
              f"{m['csat_within_one_vs_adjudicated']:>9}{m['sentiment_kappa_vs_adjudicated']:>12}"
              f"{m['sentiment_kappa_vs_annotators']:>10}")
    for r, nf in report.get("noise_floor_run_to_run", {}).items():
        print(f"  run-to-run ({' vs '.join(nf['runs'])}, {nf['n_calls']} calls): CSAT identical {nf['csat_identical']}, "
              f"sentiment identical {nf['sentiment_identical']}, resolved identical {nf['resolved_identical']}, "
              f"CSAT kappa spread {nf['csat_kappa_spread']}")
    for it in report.get("iterations", []):
        print(f"  {it['after']} vs {it['before']} (paired bootstrap, {it['n']} calls): "
              f"CSAT wk {it['csat']['delta']:+} {it['csat']['ci']}, sentiment k {it['sentiment']['delta']:+} "
              f"{it['sentiment']['ci']}")
    print(f"  wrote {paths.RUNS / 'dev_report.json'}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="calleval", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="write the synthetic data set")
    g.add_argument("--seed", type=int, default=None)
    r = sub.add_parser("run", help="score calls with a backend")
    r.add_argument("--backend", choices=["offline", "jev"], required=True)
    r.add_argument("--run-id", default=None, help="output directory name under runs/ (default: the backend)")
    r.add_argument("--split", choices=["all", "dev"], default="all")
    r.add_argument("--concurrency", type=int, default=6)
    r.add_argument("--cache", default=None, help="Jev cache file (default cache/jev_cache.jsonl)")
    r.add_argument("--no-cache-read", action="store_true", help="Jev: ignore cached answers and call the API")
    r.add_argument("--replay", action="store_true", help="Jev: cache only; fail instead of calling the API")
    sub.add_parser("evaluate", help="dev-split evaluation of every run on disk")
    h = sub.add_parser("holdout", help="evaluate a run on the sealed holdout, once")
    h.add_argument("--run", required=True)
    h.add_argument("--force", action="store_true")
    sub.add_parser("export-demo", help="write docs/data/demo.json")
    a = ap.parse_args(argv)

    if a.cmd == "generate":
        from calleval.generate import SEED, generate
        print(json.dumps(generate(seed=a.seed if a.seed is not None else SEED), indent=1))
    elif a.cmd == "run":
        from calleval.pipeline import load_splits, run
        ids = set(load_splits()["dev"]) if a.split == "dev" else None
        kw = {}
        if a.backend == "jev":
            kw = {"concurrency": a.concurrency, "read_cache": not a.no_cache_read, "offline_only": a.replay}
            if a.cache:
                kw["cache_path"] = a.cache
        s = run(a.backend, run_id=a.run_id, call_ids=ids, **kw)
        show = {k: v for k, v in s.items() if k not in ("calibration",)}
        if "calibration" in s:
            show["calibration"] = {k: s["calibration"][k] for k in ("n_survey_calls", "ece_raw", "ece_calibrated_oof",
                                                                    "ece_calibrated_oof_unweighted")}
        print(json.dumps(show, indent=1))
    elif a.cmd == "evaluate":
        from calleval.evaluate import evaluate_dev
        _print_dev(evaluate_dev())
    elif a.cmd == "holdout":
        from calleval.evaluate import HoldoutAlreadyUsed, evaluate_holdout
        try:
            e = evaluate_holdout(a.run, force=a.force)
        except HoldoutAlreadyUsed as err:
            print(f"refused: {err}", file=sys.stderr)
            sys.exit(2)
        m, c = e["result"], e["annotator_ceiling"]
        print(f"HOLDOUT ({m['n_golden']} calls) for run '{a.run}'{' [FORCED]' if e['forced'] else ''}")
        print(f"  annotator ceiling: CSAT wk {c['csat_weighted_kappa']}, sentiment k {c['sentiment_kappa']}")
        print(f"  coverage {m['coverage']}, CSAT wk vs adjudicated {m['csat_weighted_kappa_vs_adjudicated']} "
              f"{m['csat_weighted_kappa_vs_adjudicated_ci']}, vs annotators {m['csat_weighted_kappa_vs_annotators']}")
        print(f"  sentiment k vs adjudicated {m['sentiment_kappa_vs_adjudicated']} {m['sentiment_kappa_vs_adjudicated_ci']}, "
              f"vs annotators {m['sentiment_kappa_vs_annotators']}")
        print(f"  ledger: {paths.LEDGER} (predictions sha256 {e['predictions_sha256'][:12]}...)")
    elif a.cmd == "export-demo":
        from calleval.export import export_demo
        print(json.dumps(export_demo(), indent=1))


if __name__ == "__main__":
    main()
