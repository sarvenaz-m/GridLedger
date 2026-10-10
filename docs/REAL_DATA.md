# Real electricity protocol · GridLedger 2.0

This benchmark measures future hourly consumption for the same clients and robustness to unavailable historical inputs. It supplements the preserved [synthetic studio](METHODOLOGY.md).

## Source and cohort

[ElectricityLoadDiagrams20112014](https://archive.ics.uci.edu/dataset/321/electricityloaddiagrams20112014), created by **Artur Trindade**, contains quarter-hour readings for 370 clients. DOI: [10.24432/C58C86](https://doi.org/10.24432/C58C86). License: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

The fixed cohort is **MT_001–MT_020**, in source order, during **2013–2014**: 17,520 hourly timestamps and 350,400 client/hour observations. Identifiers and dates were chosen before evaluation; no client was removed for an unfavorable test result. This is a subset, rather than an evaluation of all 370 clients.

`gridledger-fetch` downloads the official archive, checks the project's pinned SHA-256, reads only `LD2011_2014.txt`, and reproduces `data/uci_hourly.csv`. It also hashes the source member. The archive pin was measured from the official download; it is not an independently published UCI checksum. Hashes, source URL, DOI, license, conversion and activation times are recorded in [uci_source.json](../data/uci_source.json).

## Units and provider clock

The source supplies **kW** per quarter hour; quarter-hour energy is `kW / 4` kWh. Hourly power is the **mean of four readings**, rather than their sum.

We retain the timezone-naive Portuguese provider clock. Labels in `[t, t+1h)` form the row labelled `t`, treated as available at `t+1h`. This is an explicit benchmark convention; it does not infer an unprovided UTC clock or precise meter interval-end semantics. Duplicate labels, irregular cadence and incomplete hourly bins fail validation.

The provider keeps 96 slots even on clock-change days: spring includes artificial zeros and autumn combines consumption. The benchmark excludes each whole March/October transition day from targets and treats those historical inputs as unavailable. Origin-to-target windows crossing a transition day are also excluded. The affected dates are 2013-03-31, 2013-10-27, 2014-03-30 and 2014-10-26. Horizons denote provider-clock steps in this filtered experiment.

The source reports no missing readings. Initial zeros can represent clients that have not yet started. We find each client's first positive reading **in the initial 2013 training period**, exclude earlier zeros, and require seven days of history after activation. All subsequent zeros stay valid. MT_012 and MT_015 activate after the extract begins; both remain in the cohort.

## Origins and direct targets

At origin `t`, only hourly rows labelled **strictly before t** are available. Horizon `h` predicts the row labelled `t+h-1`, the h-th next hourly slot. Each client/fold/horizon has a separate direct model. Earlier test observations become available to later origins. The 72-target replay contains rolling direct forecasts.

Example with origin **2014-11-03 10:00**:

| Horizon | Latest available row | Target row | Target available after |
|---|---|---|---|
| 1 hour | Nov 3, 09:00 | Nov 3, 10:00 | Nov 3, 11:00 |
| 6 hours | Nov 3, 09:00 | Nov 3, 15:00 | Nov 3, 16:00 |
| 24 hours | Nov 3, 09:00 | Nov 4, 09:00 | Nov 4, 10:00 |

Features contain known target-calendar harmonics/weekend, past load lags 1/2/24/48/168, preceding 24/168-hour means, the latest known daily/weekly seasonal value, recent availability and gap age. The real experiment uses consumption and calendar information. Weather, PV, EV, feeder capacities and fault labels belong to the synthetic studio.

## Expanding training and calibration

Training begins with each client's valid 2013 history. Models and scalers are refitted per fold. Parameters are fixed; there is no test tuning or random early-stopping split.

| Fold | Training ends before | Calibration origins | Test origins start | Test ends before |
|---|---|---|---|---|
| 1 | 2014-01-01 | Jan 1–14 | 2014-01-15 | 2014-04-01 |
| 2 | 2014-04-01 | Apr 1–14 | 2014-04-15 | 2014-07-01 |
| 3 | 2014-07-01 | Jul 1–14 | 2014-07-15 | 2014-10-01 |
| 4 | 2014-10-01 | Oct 1–14 | 2014-10-15 | 2015-01-01 |

Training targets must precede the training boundary. Calibration origins start on/after that boundary and targets precede the test boundary. Test origins start on/after the test boundary and targets precede the fold end. Origins whose future labels cross boundaries are **purged**. Longer horizons have fewer valid targets. Later folds can train on earlier test observations once they are historical.

## Models

- **Last value:** most recent available input.
- **Seasonal 24h / 168h:** latest fully known daily/weekly cycle. The cycle wraps at longer horizons; future realized loads never enter a baseline.
- **Ridge:** training-only `StandardScaler` then `Ridge(alpha=10)`.
- **Gradient boosting:** `HistGradientBoostingRegressor`, 120 iterations, 15 leaves, learning rate 0.07, seed 42, `early_stopping=False`.

Learned predictions are clipped at zero. Browser Ridge follows the same rule. Boosting runs in Python; its complete benchmark results are displayed in the UI.

## Missing inputs and stress

Unavailable history uses forward fill for up to six hours, then that fold's **training median**. There is no interpolation or backward fill. Scalers, fallback medians and normalization denominators use training only. Unavailable targets are excluded rather than imputed.

Input loss is **controlled corruption of real readings**: 5% seeded random test slots plus a 24-hour outage starting at 08:00 on day 21 of each test month. Masks differ deterministically by client/fold and are independent of consumption values. The exported mask count describes requested slots; QC may already have made some unavailable.

Models and bands remain frozen. Original observed targets are preserved. All five models are evaluated at exactly the same scored origins after historical input loss. These outages are not provider ground truth.

## Scores, calibration and uncertainty

Client/fold/horizon results report MAE and RMSE in kW. MASE divides MAE by the mean absolute difference between valid **training** readings and their weekly lag, omitting unavailable pairs. MASE below 1 compares against that training scale; the held-out weekly baseline has its own score.

Fold MAE/MASE are weighted by target count within a client, then averaged with equal weight across 20 clients. Large loads therefore do not dominate primary macro MASE. Raw scores remain available. Relative error reduction uses the held-out weekly baseline's macro MASE.

Each learned model's nominal 90% band uses the finite-sample-adjusted 90th percentile of absolute calibration residuals. The lower endpoint is clipped at zero. Coverage is measured over observed targets and under input loss. Dependence and shift prevent a universal coverage guarantee; the 24-hour boosting band falls below its nominal level.

Daily paired contrasts normalize errors by each fold's training scale and average client means equally. Seven-observed-day circular moving blocks are resampled **within each fold**, jointly across clients, for 1,000 replicates with seed 42. Descriptive 95% intervals condition on this cohort and temporal resampling assumptions. Daily contrasts differ slightly from primary observation-weighted macro MASE. They do not quantify unseen-site performance.

Per-hour and per-client error analysis follows evaluation and never informs tuning. Training-reference PSI and normalized Wasserstein distances on three historical features are descriptive distribution scores.

## Reproduction

```sh
python -m pip install -e '.[plots]'
gridledger-real --root .
gridledger-verify --root .
python scripts/plot-real.py
```

The committed extract supports offline fitting. Repeat original-source extraction with:

```sh
gridledger-fetch --root .
# Or reuse the official ZIP:
gridledger-fetch --root . --archive /path/to/electricityloaddiagrams20112014.zip
```

The ~249 MiB archive stays in the ignored cache. `real_predictions.csv.gz` stores every target and all clean/stressed predictions at round-trip floating-point precision with deterministic gzip metadata. `gridledger-verify` checks hashes, timing, purged boundaries, training-only imputation/normalization, causal baselines, every saved metric/coverage, and the real chain.

The browser uses a fixed 3–5 November replay. Python and Node check 4,320 real Ridge predictions. Its 60-record chain contains client, origin, target, horizon and model/dataset digests. The real manifest is independent of the synthetic manifest.

## Primary references

- [UCI source and license](https://archive.ics.uci.edu/dataset/321/electricityloaddiagrams20112014)
- [pandas 2.2 resampling](https://pandas.pydata.org/pandas-docs/version/2.2/reference/api/pandas.DataFrame.resample.html)
- [scikit-learn histogram boosting](https://scikit-learn.org/1.8/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html)
- [scikit-learn Ridge](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html)
