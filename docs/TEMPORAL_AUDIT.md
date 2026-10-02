# Temporal audit

The audit is an independent, deterministic experiment over the versioned hourly CSV. It preserves the original inference model and final-month benchmark.

## Input contract

Required fields are timestamp, feeder, step, observed load, PV, EV, temperature forecast, capacity and anomaly label. Validation rejects missing or nonfinite values, duplicate feeder/time pairs, reversed rows, hourly gaps, misaligned steps, negative PV/EV, nonpositive capacity and nonbinary event labels. Each feeder's capacity must be constant within this experiment.

## Expanding-window design

Training begins with 60 days, including a 7-day feature warm-up. Each fold adds 20 days to the training period. Calibration and testing each span 20 days. With 180 days of data, this produces five folds per feeder and 15 total evaluations. Test windows are disjoint; later training windows can include earlier test periods once those observations are in the past.

Each fold fits its own StandardScaler and Ridge model, plus a fixed-configuration histogram gradient boosting comparison. A 24-hour seasonal baseline is computed separately. Hyperparameters are fixed before the audit; the audit does not select the deployed model based on test results.

Features use strictly earlier load values. Earlier observations within the test window become available to subsequent one-hour predictions. This is sequential one-hour evaluation rather than a single forecast for the entire test window.

## Calibration and reporting

The Ridge interval half-width is the finite-sample-adjusted 90th percentile of absolute calibration residuals. Both clean-hour and all-observed-hour coverage are exported. Clean-hour MAE excludes injected measurement events, while their effect on later lag features remains present. Later calibration windows can contain injected events; their counts are exported explicitly.

Pooled MAE weights fold means by their clean-hour sample counts. Worst-fold error and standard deviation across fold MAEs describe temporal variation. Mean coverage is the arithmetic mean of the five clean-hour fold coverage values. Temporal dependence means empirical coverage is not a universal guarantee.

## Distribution comparisons

For temperature forecasts, lag-1 load, lag-24 load and rolling-24 load, the audit compares training-reference and test distributions. Quantile-bin edges use reference values only, with infinite outer edges and a 0.5 pseudocount per bin.

- **PSI:** sum of `(current - reference) * log(current / reference)` across normalized bins.
- **Normalized Wasserstein distance:** one-dimensional distance divided by the maximum of training IQR, training standard deviation and a small numerical floor.

Both scores are descriptive, without a hypothesis-test interpretation or automatic operational alert threshold. Constant reference features remain finite.

## Outputs

- `results/advanced_audit.json`: input report, split configuration, all fold scores, summaries and distribution comparisons.
- `assets/advanced-data.js`: the same evidence in a static browser-readable form.
- `results/advanced_manifest.json`: byte checksums for the audit, browser export, audit source and dataset.

Run `gridledger-audit --root .` after the original experiment. JSON evidence is written through a temporary file followed by atomic replacement.
