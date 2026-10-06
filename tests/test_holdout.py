import json
import shutil

import pytest

from calleval import paths
from calleval.evaluate import HoldoutAlreadyUsed, evaluate_holdout


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    (runs / "offline").mkdir(parents=True)
    shutil.copy(paths.RUNS / "offline" / "predictions.jsonl", runs / "offline" / "predictions.jsonl")
    monkeypatch.setattr(paths, "RUNS", runs)
    monkeypatch.setattr(paths, "LEDGER", runs / "holdout_ledger.json")
    return runs


def test_holdout_runs_once_then_refuses(sandbox):
    first = evaluate_holdout("offline")
    assert first["forced"] is False and first["result"]["n_golden"] == 100
    with pytest.raises(HoldoutAlreadyUsed):
        evaluate_holdout("offline")
    ledger = json.loads((sandbox / "holdout_ledger.json").read_text())
    assert len(ledger) == 1 and len(ledger[0]["predictions_sha256"]) == 64


def test_forced_rerun_is_recorded(sandbox):
    evaluate_holdout("offline")
    again = evaluate_holdout("offline", force=True)
    assert again["forced"] is True and again["n_prior_uses"] == 1
    assert len(json.loads((sandbox / "holdout_ledger.json").read_text())) == 2


def test_cli_refuses_second_use(sandbox, capsys):
    from calleval.cli import main
    main(["holdout", "--run", "offline"])
    with pytest.raises(SystemExit) as e:
        main(["holdout", "--run", "offline"])
    assert e.value.code == 2
    assert "refused" in capsys.readouterr().err


def test_committed_ledger_shows_each_run_used_once():
    assert paths.LEDGER.exists(), "no holdout ledger committed"
    ledger = json.loads(paths.LEDGER.read_text())
    unforced = [e["run_id"] for e in ledger if not e["forced"]]
    assert unforced and len(unforced) == len(set(unforced))
