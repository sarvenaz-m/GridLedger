"""Build scientific figures and descriptive error analysis from saved evidence."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from gridledger.audit import atomic_json
from gridledger.real import MODELS
from gridledger.real_data import sha256

ROOT = Path(__file__).resolve().parents[1]
report = json.loads((ROOT / "results/real_benchmark.json").read_text())
summary = report["summary"]
figures = ROOT / "results/figures"
figures.mkdir(exist_ok=True)
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "axes.labelcolor": "#23384f", "text.color": "#23384f"})
colors = {"Last value": "#8594a6", "Seasonal 24h": "#cd8346", "Seasonal 168h": "#a56bba",
          "Ridge": "#466ed3", "Gradient boosting": "#0d938a"}
def row(model, horizon):
    return next(s for s in summary if s["model"] == model and s["horizon_hours"] == horizon)

fig, axes = plt.subplots(1, 3, figsize=(15.0, 4.6))
xs = np.arange(3)
for model in MODELS:
    axes[0].plot(xs, [row(model, h)["macro_mase"] for h in (1, 6, 24)], marker="o", color=colors[model], label=model)
axes[0].set_ylabel("MASE · equal weight per client")
axes[0].set_title("Observed input")
axes[0].legend(fontsize=8, loc="upper left")
for model in ("Seasonal 168h", "Ridge", "Gradient boosting"):
    axes[1].plot(xs, [row(model, h)["macro_mase"] for h in (1, 6, 24)], marker="o", color=colors[model], label=model)
    axes[1].plot(xs, [row(model, h)["stress_macro_mase"] for h in (1, 6, 24)], marker="x", linestyle="--", color=colors[model])
axes[1].set_title("Controlled input loss")
axes[1].set_ylabel("MASE · solid: original / dashed: loss")
axes[1].legend(fontsize=8)
for model in ("Ridge", "Gradient boosting"):
    axes[2].plot(xs, [row(model, h)["coverage"] * 100 for h in (1, 6, 24)], marker="o", color=colors[model], label=model)
    axes[2].plot(xs, [row(model, h)["stress_coverage"] * 100 for h in (1, 6, 24)], marker="x", linestyle="--", color=colors[model])
axes[2].axhline(90, color="#55677d", linestyle=":", label="Nominal 90%")
axes[2].set_title("Calibration-band coverage")
axes[2].set_ylabel("Observed coverage / %")
axes[2].set_ylim(80, 93)
axes[2].legend(fontsize=8)
for ax in axes:
    ax.set_xticks(xs, ["1 h", "6 h", "24 h"])
    ax.set_xlabel("Direct forecast horizon / provider clock")
    ax.grid(alpha=.18)
fig.suptitle("GridLedger 2.0 · Real UCI electricity demand", fontsize=17, x=.04, ha="left")
fig.text(.04, .01, "MT_001–MT_020 · 2013 training start · four disjoint 2014 test windows · parameters fixed · targets never imputed", fontsize=9)
fig.tight_layout(rect=[0, .04, 1, .93])
fig.savefig(figures / "real_benchmark.png", dpi=160)
plt.close(fig)

meters = report["source"]["meters"]
ratios = []
for meter in meters:
    ratios.append([next(s["mase"] for s in row("Gradient boosting", h)["per_meter"] if s["meter"] == meter) /
                   next(s["mase"] for s in row("Seasonal 168h", h)["per_meter"] if s["meter"] == meter) for h in (1, 6, 24)])
ratios = np.asarray(ratios)
fig, ax = plt.subplots(figsize=(6.6, 8.5))
# Color on a log scale; annotated cells retain exact ratios including failures.
image = ax.imshow(np.log2(ratios), cmap="RdYlGn_r", vmin=-2, vmax=2, aspect="auto")
ax.set_yticks(np.arange(len(meters)), meters)
ax.set_xticks([0, 1, 2], ["1 h", "6 h", "24 h"])
for i in range(20):
    for j in range(3):
        ax.text(j, i, f"{ratios[i,j]:.2f}×", ha="center", va="center", color="#162431", fontsize=10)
ax.set_title("Boosting error / weekly reference error\nClient-level MASE across all test folds", pad=18)
fig.colorbar(image, ax=ax, shrink=.7, ticks=[-2, -1, 0, 1, 2], label="log₂ error ratio · < 0 favors boosting")
fig.text(.12, .01, "Ratios above 1 favor the weekly reference. Color saturates at 0.25× / 4×.", fontsize=8)
fig.tight_layout(rect=[0, .03, 1, 1])
fig.savefig(figures / "client_error_ratios.png", dpi=160)
plt.close(fig)

table = pd.read_csv(ROOT / "results/real_predictions.csv.gz", parse_dates=["target"], float_precision="round_trip")
scales = pd.DataFrame([{k: record[k] for k in ("meter", "fold", "horizon_hours", "training_weekly_mae_scale_kw")} for record in report["folds"]])
table = table.merge(scales, on=["meter", "fold", "horizon_hours"], validate="many_to_one")
table["target_hour"] = table.target.dt.hour
hourly = []
for model in ("Ridge", "Gradient boosting", "Seasonal 168h"):
    error = np.abs(table.actual_kw - table[report["prediction_columns"][model]]) / table.training_weekly_mae_scale_kw
    temp = table[["meter", "horizon_hours", "target_hour"]].assign(scaled_error=error)
    # Average each meter's observed errors, then give the 20 meters equal weight.
    grouped = temp.groupby(["meter", "horizon_hours", "target_hour"]).scaled_error.mean()
    for (horizon, hour), value in grouped.groupby(level=[1, 2]).mean().items():
        hourly.append({"model": model, "horizon_hours": int(horizon), "target_hour": int(hour), "macro_scaled_error": float(value)})
analysis = {"schema": "gridledger.real-errors.v2", "prediction_sha256": sha256(ROOT / "results/real_predictions.csv.gz"),
            "hourly_errors": hourly,
            "boosting_worse_than_weekly_clients": {str(h): [meters[i] for i in range(20) if ratios[i, j] > 1] for j, h in enumerate((1, 6, 24))},
            "ratio_by_client": [{"meter": meters[i], "ratios_1_6_24h": ratios[i].tolist()} for i in range(20)],
            "interpretation": "Descriptive error analysis after evaluation; never used to tune hyperparameters or select the cohort."}
atomic_json(ROOT / "results/real_error_analysis.json", analysis)
fig, axes = plt.subplots(1, 2, figsize=(12, 4))
for ax, horizon in zip(axes, (1, 24)):
    for model in ("Ridge", "Gradient boosting", "Seasonal 168h"):
        values = sorted([x for x in hourly if x["model"] == model and x["horizon_hours"] == horizon], key=lambda x:x["target_hour"])
        ax.plot([x["target_hour"] for x in values], [x["macro_scaled_error"] for x in values], color=colors[model], label=model)
    ax.set_title(f"{horizon}-hour direct horizon")
    ax.set_xlabel("Target hour / provider clock")
    ax.set_ylabel("Scaled absolute error · equal client weight")
    ax.set_xticks([0, 6, 12, 18, 23])
    ax.grid(alpha=.2)
axes[0].legend(fontsize=9)
fig.suptitle("Error varies across the daily load cycle", fontsize=15)
fig.tight_layout()
fig.savefig(figures / "hourly_errors.png", dpi=160)
plt.close(fig)
names = ["results/real_benchmark.json", "results/real_predictions.csv.gz", "results/real_error_analysis.json", "scripts/plot-real.py",
         "results/figures/real_benchmark.png", "results/figures/client_error_ratios.png", "results/figures/hourly_errors.png"]
atomic_json(ROOT / "results/real_analysis_manifest.json", {"schema": "gridledger.real-analysis-manifest.v2",
                                                         "files": {name: sha256(ROOT / name) for name in names}})
print(json.dumps({"figures": 3, "hourly_model_scores": len(hourly), "boosting_worse_clients": analysis["boosting_worse_than_weekly_clients"]}))
