"""Executed, multi-horizon UCI benchmark with purged temporal boundaries.

An origin t sees only completed source-clock hours labelled before t.
Horizon h predicts the reading labelled t + h - 1 hours, directly.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import platform

import numpy as np
import pandas as pd
import scipy
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from .audit import DataContractError, atomic_json, distribution_shift
from .provenance import append, digest, verify
from .real_data import METERS, dst_mask, load_hourly, sha256

FEATURES = ["target_hour_sin", "target_hour_cos", "target_hour_sin2", "target_hour_cos2",
            "target_week_sin", "target_week_cos", "target_month_sin", "target_month_cos", "target_weekend",
            "lag1", "lag2", "lag24", "lag48", "lag168", "rolling24", "rolling168",
            "seasonal24", "seasonal168", "available_fraction24", "last_missing", "gap_age"]
MODELS = ["Last value", "Seasonal 24h", "Seasonal 168h", "Ridge", "Gradient boosting"]
LEARNED = ["Ridge", "Gradient boosting"]
PRED_COLUMNS = {name: "pred_" + str(i) for i, name in enumerate(MODELS)}
STRESS_COLUMNS = {name: "stress_" + str(i) for i, name in enumerate(MODELS)}


@dataclass(frozen=True)
class RealConfig:
    horizons: tuple[int, ...] = (1, 6, 24)
    calibration_days: int = 14
    warmup_hours: int = 168
    forward_fill_limit: int = 6
    interval_level: float = 0.90
    ridge_alpha: float = 10.0
    boosting_iterations: int = 120
    seed: int = 42
    bootstrap_repetitions: int = 1000


def folds(config: RealConfig = RealConfig()) -> list[dict]:
    result = []
    boundaries = ["2014-01-01", "2014-04-01", "2014-07-01", "2014-10-01", "2015-01-01"]
    for i in range(4):
        train_end = pd.Timestamp(boundaries[i])
        result.append({"fold": i + 1, "train_end": train_end,
                       "calibration_end": train_end + pd.Timedelta(days=config.calibration_days),
                       "test_end": pd.Timestamp(boundaries[i + 1])})
    return result


def available_load(load: pd.Series, activation: str) -> pd.Series:
    values = load.astype(float).copy()
    values.loc[(values.index < pd.Timestamp(activation)) | dst_mask(values.index)] = np.nan
    return values


def causal_fill(values: pd.Series, fallback: float, limit: int = 6) -> pd.Series:
    if not np.isfinite(fallback) or limit < 1:
        raise ValueError("Finite training fallback and positive fill limit required.")
    # No interpolation or backfill: future observations cannot repair the past.
    return values.ffill(limit=limit).fillna(fallback)


def feature_frame(values: pd.Series, horizon: int, fallback: float, limit: int = 6) -> pd.DataFrame:
    if not isinstance(horizon, int) or not 1 <= horizon <= 168:
        raise ValueError("Direct horizons must be integer source-clock steps in 1..168.")
    index = values.index
    if not isinstance(index, pd.DatetimeIndex) or index.tz is not None:
        raise DataContractError("Use the timezone-naive provider clock.")
    if index.has_duplicates or not index.is_monotonic_increasing or not np.all(index.diff()[1:] == pd.Timedelta(hours=1)):
        raise DataContractError("An ordered, complete hourly grid is required; represent gaps by NaN.")
    if np.isinf(values.to_numpy()).any() or (values.dropna() < 0).any():
        raise DataContractError("Loads must be nonnegative finite readings or NaN.")
    filled = causal_fill(values, fallback, limit)
    target = index + pd.Timedelta(hours=horizon - 1)
    f = pd.DataFrame(index=index)
    f["target_time"] = target
    for k in (1, 2):
        suffix = "" if k == 1 else str(k)
        f["target_hour_sin" + suffix] = np.sin(2 * np.pi * k * target.hour / 24)
        f["target_hour_cos" + suffix] = np.cos(2 * np.pi * k * target.hour / 24)
    f["target_week_sin"] = np.sin(2 * np.pi * target.dayofweek / 7)
    f["target_week_cos"] = np.cos(2 * np.pi * target.dayofweek / 7)
    f["target_month_sin"] = np.sin(2 * np.pi * (target.month - 1) / 12)
    f["target_month_cos"] = np.cos(2 * np.pi * (target.month - 1) / 12)
    f["target_weekend"] = (target.dayofweek >= 5).astype(float)
    for lag in (1, 2, 24, 48, 168):
        f[f"lag{lag}"] = filled.shift(lag)
    for period in (24, 168):
        f[f"rolling{period}"] = filled.shift(1).rolling(period).mean()
        # Repeat the most recent fully known seasonal cycle at longer horizons.
        offset = period - ((horizon - 1) % period)
        f[f"seasonal{period}"] = filled.shift(offset)
    f["available_fraction24"] = values.notna().astype(float).shift(1).rolling(24).mean()
    f["last_missing"] = values.isna().astype(float).shift(1)
    positions = np.arange(len(values))
    last_seen = pd.Series(np.where(values.notna(), positions, np.nan), index=index).ffill()
    gap_age = pd.Series(positions, index=index) - last_seen
    f["gap_age"] = gap_age.fillna(168).clip(upper=168).shift(1)
    # DST is a clock encoding issue, so also reject forecast windows crossing it.
    safe = ~dst_mask(index)
    for step in range(1, horizon):
        safe &= ~dst_mask(index + pd.Timedelta(hours=step))
    f["clock_safe"] = safe
    return f


def split_masks(frame: pd.DataFrame, truth: pd.Series, split: dict,
                activation: str, warmup: int = 168) -> dict[str, np.ndarray]:
    origin = frame.index
    target = pd.DatetimeIndex(frame.target_time)
    valid = (np.isfinite(frame[FEATURES]).all(axis=1).to_numpy()
             & np.isfinite(truth.to_numpy()) & frame.clock_safe.to_numpy()
             & (origin >= pd.Timestamp(activation) + pd.Timedelta(hours=warmup)))
    # Purge origins whose labels cross the next boundary. No future training labels.
    return {
        "train": valid & (target < split["train_end"]),
        "calibration": valid & (origin >= split["train_end"]) & (target < split["calibration_end"]),
        "test": valid & (origin >= split["calibration_end"]) & (target < split["test_end"]),
    }


def seasonal_scale(values: pd.Series, train_end: pd.Timestamp) -> float:
    train = values.loc[values.index < train_end]
    differences = (train - train.shift(168)).abs().dropna()
    scale = float(differences.mean())
    if not np.isfinite(scale) or scale <= 1e-10:
        raise DataContractError("Weekly training MASE scale is undefined for this meter.")
    return scale


def score(truth: np.ndarray, prediction: np.ndarray, scale: float) -> dict[str, float]:
    error = np.asarray(truth) - np.asarray(prediction)
    if not len(error) or not np.isfinite(error).all() or scale <= 0:
        raise DataContractError("Scores need finite paired targets/predictions and a positive training scale.")
    return {"mae_kw": float(np.mean(np.abs(error))), "rmse_kw": float(np.sqrt(np.mean(error ** 2))),
            "mase": float(np.mean(np.abs(error)) / scale)}


def interval_width(truth, prediction, level: float) -> float:
    residuals = np.abs(np.asarray(truth) - np.asarray(prediction))
    if not len(residuals) or not np.isfinite(residuals).all() or not 0 < level < 1:
        raise ValueError("Finite calibration residuals and a level in (0,1) required.")
    quantile = min(1.0, math.ceil((len(residuals) + 1) * level) / len(residuals))
    return float(np.quantile(residuals, quantile, method="higher"))


def stress_mask(index: pd.DatetimeIndex, split: dict, seed: int) -> np.ndarray:
    """Controlled input loss only: 5% random + one 24h outage per test month."""
    in_test = (index >= split["calibration_end"]) & (index < split["test_end"])
    mask = np.random.default_rng(seed).random(len(index)) < .05
    mask &= in_test
    for month in pd.period_range(split["calibration_end"], split["test_end"] - pd.Timedelta(hours=1), freq="M"):
        start = month.start_time + pd.Timedelta(days=20, hours=8)
        mask |= in_test & (index >= start) & (index < start + pd.Timedelta(hours=24))
    return np.asarray(mask)


def predict_all(frame: pd.DataFrame, fitted: dict) -> dict[str, np.ndarray]:
    result = {"Last value": frame.lag1.to_numpy(), "Seasonal 24h": frame.seasonal24.to_numpy(),
              "Seasonal 168h": frame.seasonal168.to_numpy()}
    for name, model in fitted.items():
        result[name] = np.maximum(0.0, model.predict(frame[FEATURES]))
    return result


def aggregate(records: list[dict], horizons) -> list[dict]:
    output = []
    for horizon in horizons:
        selected = [r for r in records if r["horizon_hours"] == horizon]
        for model in MODELS:
            per_meter, stressed = [], []
            for meter in sorted({r["meter"] for r in selected}):
                rows = [r for r in selected if r["meter"] == meter]
                weights = [r["n_test"] for r in rows]
                per_meter.append({"meter": meter, **{k: float(np.average([r["models"][model][k] for r in rows], weights=weights))
                                                       for k in ("mae_kw", "mase")}})
                stressed.append(float(np.average([r["stress_models"][model]["mase"] for r in rows], weights=weights)))
            entry = {"horizon_hours": horizon, "model": model, "meters": len(per_meter),
                     "macro_mase": float(np.mean([r["mase"] for r in per_meter])),
                     "mean_meter_mae_kw": float(np.mean([r["mae_kw"] for r in per_meter])),
                     "stress_macro_mase": float(np.mean(stressed)), "per_meter": per_meter}
            if model in LEARNED:
                weights = [r["n_test"] for r in selected]
                entry["coverage"] = float(np.average([r["intervals"][model]["coverage"] for r in selected], weights=weights))
                entry["stress_coverage"] = float(np.average([r["intervals"][model]["stress_coverage"] for r in selected], weights=weights))
            output.append(entry)
    return output


def block_contrasts(daily: list[dict], config: RealConfig) -> list[dict]:
    """Resample 7-observed-day blocks jointly across meters, within each fold."""
    frame = pd.DataFrame(daily)
    rng = np.random.default_rng(config.seed)
    output = []
    for horizon in config.horizons:
        for left, right in [("Ridge", "Seasonal 168h"), ("Gradient boosting", "Seasonal 168h"), ("Gradient boosting", "Ridge")]:
            paired = frame[(frame.horizon_hours == horizon) & (frame.left == left) & (frame.right == right)]
            panel = paired.groupby(["fold", "date"], sort=True).difference.mean()
            samples, observed = [], []
            for fold in sorted(paired.fold.unique()):
                values = panel.loc[fold].to_numpy()
                observed.extend(values)
                starts = rng.integers(0, len(values), size=(config.bootstrap_repetitions, math.ceil(len(values) / 7)))
                indices = ((starts[:, :, None] + np.arange(7)) % len(values)).reshape(config.bootstrap_repetitions, -1)[:, :len(values)]
                samples.append(values[indices])
            boot = np.concatenate(samples, axis=1).mean(axis=1)
            low, high = np.quantile(boot, [.025, .975])
            output.append({"horizon_hours": horizon, "left": left, "right": right,
                           "mean_daily_scaled_error_difference": float(np.mean(observed)),
                           "bootstrap_95_low": float(low), "bootstrap_95_high": float(high),
                           "days": len(observed), "block_days": 7,
                           "interpretation": "Negative favors left; descriptive temporal uncertainty, conditional on this fixed meter cohort."})
    return output


def write_manifest(root: Path) -> dict:
    names = ["data/uci_hourly.csv", "data/uci_source.json", "results/real_benchmark.json",
             "results/real_predictions.csv.gz", "results/real_daily_contrasts.csv", "results/real_ledger.json",
             "assets/real-data.json", "assets/real-data.js", "src/gridledger/real.py", "src/gridledger/real_data.py"]
    manifest = {"schema": "gridledger.real-manifest.v2", "files": {name: sha256(root / name) for name in names}}
    atomic_json(root / "results/real_manifest.json", manifest)
    return manifest


@threadpool_limits.wrap(limits=1)
def run(root: Path, config: RealConfig = RealConfig()) -> dict:
    hourly, source = load_hourly(root)
    if not config.horizons or len(set(config.horizons)) != len(config.horizons) or not all(isinstance(h, int) and 1 <= h <= 168 for h in config.horizons):
        raise ValueError("Specify distinct integer horizons in 1..168.")
    records, daily, diagnostic, browser_meters, chain = [], [], [], [], []
    (root / "results").mkdir(parents=True, exist_ok=True)
    (root / "assets").mkdir(parents=True, exist_ok=True)
    demo = {"schema": "gridledger.real-browser.v2", "dataset_sha256": source["hourly_csv_sha256"],
            "source": source, "feature_names": FEATURES, "model_names": MODELS,
            "horizons": list(config.horizons), "meters": browser_meters,
            "replay": "Fixed target window 2014-11-03 to 2014-11-06; final-fold frozen Ridge, 72 rolling origins per horizon."}
    pred_path = root / "results/real_predictions.csv.gz"
    with pred_path.open("wb") as raw_stream, gzip.GzipFile(filename="", mode="wb", fileobj=raw_stream, mtime=0) as compressed:
        with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as stream:
            first_write = True
            for meter_number, meter in enumerate(METERS):
                activation = source["activation_from_first_training"][meter]
                values = available_load(hourly[meter], activation)
                browser_entry = {"id": meter, "activation": activation, "horizons": {}}
                for split in folds(config):
                    train_values = values.loc[values.index < split["train_end"]].dropna()
                    fallback = float(train_values.median())
                    scale = seasonal_scale(values, split["train_end"])
                    dropped = stress_mask(values.index, split, config.seed + meter_number * 100 + split["fold"])
                    damaged = values.mask(dropped)
                    for horizon in config.horizons:
                        f = feature_frame(values, horizon, fallback, config.forward_fill_limit)
                        truth = values.shift(-(horizon - 1))
                        masks = split_masks(f, truth, split, activation, config.warmup_hours)
                        train, calibration, test = (f.loc[masks[part]] for part in ("train", "calibration", "test"))
                        y_train, y_cal, y_test = (truth.loc[masks[part]].to_numpy() for part in ("train", "calibration", "test"))
                        if len(train) < 336 or len(calibration) < 100 or not len(test):
                            raise DataContractError(f"{meter}: insufficient valid data in fold {split['fold']}.")
                        fitted = {"Ridge": make_pipeline(StandardScaler(), Ridge(alpha=config.ridge_alpha)),
                                  "Gradient boosting": HistGradientBoostingRegressor(max_iter=config.boosting_iterations,
                                      max_leaf_nodes=15, learning_rate=.07, early_stopping=False, random_state=config.seed)}
                        for model in fitted.values():
                            model.fit(train[FEATURES], y_train)
                        clean_pred, cal_pred = predict_all(test, fitted), predict_all(calibration, fitted)
                        stress_features = feature_frame(damaged, horizon, fallback, config.forward_fill_limit).loc[masks["test"]]
                        damaged_pred = predict_all(stress_features, fitted)
                        intervals = {}
                        for name in LEARNED:
                            width = interval_width(y_cal, cal_pred[name], config.interval_level)
                            intervals[name] = {"half_width_kw": width,
                                               "coverage": float(np.mean(np.abs(y_test - clean_pred[name]) <= width)),
                                               "stress_coverage": float(np.mean(np.abs(y_test - damaged_pred[name]) <= width))}
                        entry = {"meter": meter, "fold": split["fold"], "horizon_hours": horizon,
                                 "train_end_exclusive": split["train_end"].isoformat(),
                                 "calibration_end_exclusive": split["calibration_end"].isoformat(), "test_end_exclusive": split["test_end"].isoformat(),
                                 "last_training_target": train.target_time.max().isoformat(), "first_calibration_origin": calibration.index.min().isoformat(),
                                 "last_calibration_target": calibration.target_time.max().isoformat(), "first_test_origin": test.index.min().isoformat(),
                                 "last_test_target": test.target_time.max().isoformat(),
                                 "n_train": len(train), "n_calibration": len(calibration), "n_test": len(test),
                                 "training_median_kw": fallback, "training_weekly_mae_scale_kw": scale,
                                 "stress_dropped_test_readings": int(dropped.sum()),
                                 "stress_total_test_readings": int(((values.index >= split["calibration_end"]) & (values.index < split["test_end"])).sum()),
                                 "models": {n: score(y_test, clean_pred[n], scale) for n in MODELS},
                                 "stress_models": {n: score(y_test, damaged_pred[n], scale) for n in MODELS}, "intervals": intervals}
                        records.append(entry)
                        output = pd.DataFrame({"meter": meter, "fold": split["fold"], "horizon_hours": horizon,
                                               "origin": test.index, "target": test.target_time.to_numpy(), "actual_kw": y_test})
                        for name in MODELS:
                            output[PRED_COLUMNS[name]], output[STRESS_COLUMNS[name]] = clean_pred[name], damaged_pred[name]
                        output.to_csv(stream, index=False, header=first_write, float_format="%.17g", lineterminator="\n")
                        first_write = False
                        target_dates = pd.DatetimeIndex(test.target_time).date
                        for left, right in [("Ridge", "Seasonal 168h"), ("Gradient boosting", "Seasonal 168h"), ("Gradient boosting", "Ridge")]:
                            delta = (np.abs(y_test - clean_pred[left]) - np.abs(y_test - clean_pred[right])) / scale
                            for day, value in pd.Series(delta, index=target_dates).groupby(level=0).mean().items():
                                daily.append({"meter": meter, "fold": split["fold"], "horizon_hours": horizon,
                                              "date": day.isoformat(), "left": left, "right": right, "difference": float(value)})
                        for feature in ("lag1", "rolling24", "seasonal168"):
                            diagnostic.append({"meter": meter, "fold": split["fold"], "horizon_hours": horizon, "feature": feature,
                                               **distribution_shift(train[feature].to_numpy(), test[feature].to_numpy())})
                        if split["fold"] == 4:
                            scaler, reg = fitted["Ridge"].steps[0][1], fitted["Ridge"].steps[1][1]
                            exported = {"algorithm": "StandardScaler + Ridge", "alpha": config.ridge_alpha, "clip_min": 0,
                                        "features": FEATURES, "mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist(),
                                        "coef": reg.coef_.tolist(), "intercept": float(reg.intercept_)}
                            model_hash = digest(exported)
                            replay = (test.target_time >= "2014-11-03") & (test.target_time < "2014-11-06")
                            rows = []
                            for i in np.flatnonzero(replay):
                                rows.append({"origin": test.index[i].isoformat(), "target": test.target_time.iloc[i].isoformat(),
                                             "actual": float(y_test[i]), "prediction": float(clean_pred["Ridge"][i]),
                                             "stress_prediction": float(damaged_pred["Ridge"][i]), "seasonal": float(clean_pred["Seasonal 168h"][i]),
                                             "features": test[FEATURES].iloc[i].to_list()})
                            browser_entry["horizons"][str(horizon)] = {"model": exported, "model_sha256": model_hash,
                                                                     "rows": rows, "metrics": entry}
                            append(chain, {"schema": "gridledger.prediction.v2", "meter": meter, "horizon_hours": horizon,
                                           "origin": rows[-1]["origin"], "target": rows[-1]["target"], "clock": "UCI Portuguese provider clock",
                                           "prediction_watts": round(rows[-1]["prediction"] * 1000), "model_sha256": model_hash,
                                           "dataset_sha256": source["hourly_csv_sha256"]})
                browser_meters.append(browser_entry)
                print(f"Evaluated {meter}: four folds × {len(config.horizons)} horizons", flush=True)
    environment = {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
                   "scikit_learn": sklearn.__version__, "scipy": scipy.__version__, "threads": 1}
    report = {"schema": "gridledger.real-benchmark.v2", "version": "2.0.0", "config": asdict(config),
              "source": source, "environment": environment, "feature_names": FEATURES, "prediction_columns": PRED_COLUMNS,
              "stress_prediction_columns": STRESS_COLUMNS, "meter_horizon_folds": len(records),
              "test_prediction_rows": sum(r["n_test"] for r in records), "model_evaluations": len(records) * len(MODELS),
              "summary": aggregate(records, config.horizons), "folds": records,
              "paired_daily_block_bootstrap": block_contrasts(daily, config), "distribution_shift": diagnostic,
              "protocol": {"origin": "At t only readings labelled < t are available; h predicts t+h-1.",
                           "parameters": "Fixed before held-out evaluation; no test tuning or random early-stopping validation.",
                           "aggregation": "Within each meter, fold scores weighted by target count; then equal weight per meter. MASE denominator is valid training weekly seasonal error.",
                           "missing": "Six-hour causal forward fill, then training-only median. Truth is never imputed; unavailable/DST targets excluded.",
                           "stress": "Controlled input corruption: 5% seeded random loss plus one 24h outage starting on day 21 at 08:00 of every test month. Frozen models and original observed targets.",
                           "interval": "Symmetric nominal 90% held-out calibration-residual band, clipped at zero. Empirical coverage; temporal dependence precludes a universal guarantee.",
                           "bootstrap": "1000 circular moving-block replicates, seven observed days, within fold; all meters share the resampled dates. Daily contrasts differ slightly from observation-weighted primary MASE.",
                           "limits": "20 fixed anonymized clients, one provider-clock dataset; future-time evaluation on known clients, not unseen-site generalization. No weather, PV, EV, feeder capacities or fault labels are supplied by UCI."}}
    pd.DataFrame(daily).to_csv(root / "results/real_daily_contrasts.csv", index=False, float_format="%.10f", lineterminator="\n")
    atomic_json(root / "results/real_benchmark.json", report)
    head = chain[-1]["hash"]
    assert verify(chain, head)[0]
    atomic_json(root / "results/real_ledger.json", {"records": chain, "checkpoint": head})
    demo.update({"summary": report["summary"], "contrasts": report["paired_daily_block_bootstrap"],
                 "chain": chain, "checkpoint": head, "config": asdict(config)})
    atomic_json(root / "assets/real-data.json", demo)
    (root / "assets/real-data.js").write_text("window.GRIDLEDGER_REAL = " + json.dumps(demo, separators=(",", ":"), allow_nan=False) + ";\n", encoding="utf-8", newline="\n")
    write_manifest(root)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    result = run(args.root)
    print(json.dumps({"meter_horizon_folds": result["meter_horizon_folds"], "predictions": result["test_prediction_rows"],
                      "summary": [{k: v for k, v in row.items() if k != "per_meter"} for row in result["summary"]]}, indent=2))


if __name__ == "__main__":
    main()
