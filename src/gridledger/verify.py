"""Offline checksums and independent re-scoring of every saved real prediction."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .audit import DataContractError
from .provenance import verify as verify_chain
from .real import (FEATURES, LEARNED, MODELS, RealConfig, aggregate, available_load,
                   feature_frame, predict_all, score, seasonal_scale, stress_mask)
from .real_data import load_hourly, sha256


def check_manifest(root: Path, name: str = "results/real_manifest.json") -> int:
    manifest = json.loads((root / name).read_text())
    for relative, expected in manifest["files"].items():
        path = root / relative
        if not path.resolve().is_relative_to(root.resolve()) or sha256(path) != expected:
            raise DataContractError(f"Artifact checksum mismatch: {relative}")
    return len(manifest["files"])


def assert_close(actual, expected, name: str) -> None:
    if not np.allclose(actual, expected, rtol=1e-7, atol=2e-7):
        raise DataContractError(f"Saved prediction evidence disagrees with {name}.")


def run(root: Path) -> dict:
    checked = check_manifest(root)
    hourly, source = load_hourly(root)
    report = json.loads((root / "results/real_benchmark.json").read_text())
    table = pd.read_csv(root / "results/real_predictions.csv.gz", parse_dates=["origin", "target"], float_precision="round_trip")
    if len(table) != report["test_prediction_rows"] or table.duplicated(["meter", "horizon_hours", "origin"]).any():
        raise DataContractError("Prediction counts or unique rolling origins do not match.")
    lookup = {(r["meter"], r["fold"], r["horizon_hours"]): r for r in report["folds"]}
    if len(lookup) != report["meter_horizon_folds"]:
        raise DataContractError("Duplicate or missing fold records.")
    config = RealConfig(**{**report["config"], "horizons": tuple(report["config"]["horizons"])})
    recomputed = []
    for key, group in table.groupby(["meter", "fold", "horizon_hours"], sort=True):
        meter, fold, horizon = key
        record = lookup[key]
        if len(group) != record["n_test"]:
            raise DataContractError(f"Test count mismatch: {key}")
        expected_target = group.origin + pd.Timedelta(hours=int(horizon) - 1)
        if not group.target.equals(expected_target) or not (group.origin >= pd.Timestamp(record["calibration_end_exclusive"])).all() or not (group.target < pd.Timestamp(record["test_end_exclusive"])).all():
            raise DataContractError(f"Forecast timing mismatch: {key}")
        if not pd.Timestamp(record["last_training_target"]) < pd.Timestamp(record["train_end_exclusive"]) <= pd.Timestamp(record["first_calibration_origin"]):
            raise DataContractError(f"Unpurged training labels: {key}")
        if not pd.Timestamp(record["last_calibration_target"]) < pd.Timestamp(record["calibration_end_exclusive"]) <= pd.Timestamp(record["first_test_origin"]):
            raise DataContractError(f"Unpurged calibration labels: {key}")
        values = available_load(hourly[meter], source["activation_from_first_training"][meter])
        target_truth = values.reindex(group.target).to_numpy()
        assert_close(group.actual_kw.to_numpy(), target_truth, "original observed targets")
        fallback = float(values.loc[values.index < record["train_end_exclusive"]].median())
        scale = seasonal_scale(values, pd.Timestamp(record["train_end_exclusive"]))
        assert_close(fallback, record["training_median_kw"], "training-only imputation")
        assert_close(scale, record["training_weekly_mae_scale_kw"], "training-only MASE denominator")
        original = feature_frame(values, int(horizon), fallback, config.forward_fill_limit).loc[pd.DatetimeIndex(group.origin)]
        if not original.clock_safe.all() or not np.isfinite(original[FEATURES]).all().all():
            raise DataContractError("Invalid/DST-contaminated scored forecast window.")
        split = {"calibration_end": pd.Timestamp(record["calibration_end_exclusive"]),
                 "test_end": pd.Timestamp(record["test_end_exclusive"])}
        mask = stress_mask(values.index, split, config.seed + source["meters"].index(meter) * 100 + int(fold))
        damaged = feature_frame(values.mask(mask), int(horizon), fallback, config.forward_fill_limit).loc[original.index]
        for name, prediction in predict_all(original, {}).items():
            assert_close(group[report["prediction_columns"][name]], prediction, "causal " + name)
        for name, prediction in predict_all(damaged, {}).items():
            assert_close(group[report["stress_prediction_columns"][name]], prediction, "causal stress " + name)
        scores, stress_scores = {}, {}
        for name in MODELS:
            column = report["prediction_columns"][name]
            stress_column = report["stress_prediction_columns"][name]
            scores[name] = score(group.actual_kw.to_numpy(), group[column].to_numpy(), scale)
            stress_scores[name] = score(group.actual_kw.to_numpy(), group[stress_column].to_numpy(), scale)
            for metric in scores[name]:
                assert_close(scores[name][metric], record["models"][name][metric], name + " " + metric)
                assert_close(stress_scores[name][metric], record["stress_models"][name][metric], "stress " + name + " " + metric)
            if name in LEARNED:
                width = record["intervals"][name]["half_width_kw"]
                for col, coverage_key in [(column, "coverage"), (stress_column, "stress_coverage")]:
                    coverage = np.mean(np.abs(group.actual_kw.to_numpy() - group[col].to_numpy()) <= width)
                    assert_close(coverage, record["intervals"][name][coverage_key], name + " " + coverage_key)
        recomputed.append({**record, "models": scores, "stress_models": stress_scores})
    if len(recomputed) != len(lookup):
        raise DataContractError("Some fold evidence is absent from the prediction file.")
    expected_summary = aggregate(recomputed, config.horizons)
    for actual, expected in zip(expected_summary, report["summary"], strict=True):
        for name in ("macro_mase", "mean_meter_mae_kw", "stress_macro_mase"):
            assert_close(actual[name], expected[name], "aggregate " + name)
    ledger = json.loads((root / "results/real_ledger.json").read_text())
    ok, message = verify_chain(ledger["records"], ledger["checkpoint"])
    if not ok:
        raise DataContractError(message)
    return {"status": "passed", "manifest_files": checked, "prediction_rows_rescored": len(table),
            "meter_horizon_folds": len(lookup), "model_evaluations_rescored": len(lookup) * len(MODELS),
            "causal_baselines_verified": True, "original_targets_verified": True, "real_ledger_records": len(ledger["records"])}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    print(json.dumps(run(args.root), indent=2))


if __name__ == "__main__":
    main()
