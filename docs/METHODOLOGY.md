# Methodology

Synthetic studio reference experiment · seed 42 · timestamps UTC

GridLedger 2.0 preserves this simulation. The main real-electricity experiment uses a different input contract and clock: see [Real electricity protocol](REAL_DATA.md) and [Executed results](RESULTS.md).

## Question and scope

Can a compact, inspectable pipeline forecast hourly electricity demand, flag unusual meter readings, and bind its output to an auditable model/data record? This is a software and research-method demonstrator. The three feeders are fictional and do not represent Lisbon substations or an operational utility dataset.

## Data

`data/synthetic_hourly.csv` contains 12,960 observations: three feeders × 180 days × 24 hours. The generator combines daily harmonics, weekday effects, temperature response, evening EV demand, solar output and random measurement noise. No external or personal data are used. Weather forecasts are simulated noisy exogenous inputs assumed available before the target hour; they are not realized weather silently used as a forecast.

The last 30 days contain 21 injected abnormal measurement hours per feeder. These are spikes and negative offsets, not engineering diagnoses of physical faults. Training and calibration are free of injected events by construction. Anomaly labels and `clean_load_kw` are never model features.

## Time and leakage

Each feeder is trained separately. Days 1–120 form the training period, days 121–150 the calibration period, and days 151–180 the test period. The first 168 hours are omitted for lag warm-up, leaving 2,712 training rows per feeder. There are 720 calibration and 720 test rows per feeder.

Predictors are hour harmonics, weekend, a noisy temperature forecast, derived heating/cooling terms, load lags 1/24/168 hours and the mean of the preceding 24 hours. All load-derived features are shifted. The evaluation is **rolling one hour ahead**: observed test readings become available to later predictions. It is not a 72-hour-ahead forecast. The demo displays 72 successive one-hour forecasts. A corrupted earlier measurement can affect later lag features.

## Models and calibration

The deployed model is `StandardScaler` fitted on training features followed by `Ridge(alpha=6)`. Fixed parameters were specified before the held-out comparison. A 120-iteration histogram gradient boosting model and a 24-hour seasonal naive forecast are comparison methods. Gradient boosting uses no random validation split or early stopping.

The symmetric nominal 90% interval uses a finite-sample adjusted 90th percentile of absolute calibration residuals. The detector uses the 99th percentile of the same residuals. Calibration data select these thresholds; test data do not. Temporal dependence prevents a distribution-free coverage guarantee. Coverage is reported empirically.

`results/metrics.json` separates forecasting error on non-injected test hours from error over all observed hours, and reports anomaly precision/recall/F1 against the injected labels. Neither the selected replay window nor the interactive sliders recompute the benchmark. Three feeders from one generator are not independent external validation.

## Browser inference and scenarios

The browser evaluates the exported Ridge coefficient/scaler arrays on the same causal feature vectors as Python. Cross-runtime tests compare 216 predictions. The browser does not train scikit-learn or execute the comparison model.

Additional EV demand is an evening Gaussian load profile, in kW. PV output is multiplied by the selected factor. Net-load estimate = baseline load forecast + additional EV demand − scaled PV. Headroom = aggregate feeder limit − peak net load. This arithmetic is not AC power flow, optimal charging, or a voltage stability assessment. The meter-spike button changes the displayed measurement and residual calculation, not fitted weights or historical benchmark scores.

## Provenance

Raw CSV and artifact bytes have SHA-256 checksums. A prediction payload stores integer watts, feeder, UTC timestamp, canonical model digest and raw data digest. Schema fields use ASCII strings, integers and booleans. Canonical JSON uses sorted keys and compact separators; it is an application encoding rather than a general RFC 8785 implementation.

Records are SHA-256-linked. A pinned head detects rewrites and truncation only while that checkpoint is independently trusted. The Solidity registry anchors the head and manifest digest, accepts authorized writers and rejects duplicate identifiers. `scripts/test-contract.cjs` deploys and tests the contract on a temporary local EVM. The browser's local chain does not provide blockchain consensus or independent notarization.

## Reproduction

Python 3.11–3.12 and Node 20+ are recommended; exact library versions are pinned in `pyproject.toml` and `package-lock.json`. The checked environment is recorded in `results/metrics.json`. Floating point results can vary slightly between platforms.

```sh
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows: .venv\Scripts\activate
python -m pip install -e .
gridledger --out .
python -m unittest discover -s tests -v
npm ci
npm run test:browser-model
npm run test:contract
python -m http.server 8000
```

Open `http://localhost:8000`. Re-running the pipeline regenerates the dataset, metrics, weights, demo data and chain. Re-run the contract test afterward to anchor the new manifest in a fresh ephemeral chain. No credentials, wallets or public-chain fees are needed.

## Next research steps

1. Evaluate licensed operational data with weather and calendar information actually available at forecast time.
2. Use multiple chronological folds, seasonal stress tests, group/site holdouts and error analysis.
3. Introduce missing-data handling and explicit data validation for external telemetry.
4. Add network topology and a validated power-flow model before operational grid claims.
5. Compare a signed database log against a permissioned ledger; justify consensus and governance before choosing a blockchain.
6. Test identity, key rotation, external anchoring, privacy and threat assumptions with project partners.

## Primary references

- scikit-learn Ridge: https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html
- scikit-learn histogram gradient boosting: https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html
- Solidity contracts: https://docs.soliditylang.org/en/latest/contracts.html
- GitHub Pages: https://docs.github.com/en/pages/quickstart

These primary references document the methods and implementation tools.
