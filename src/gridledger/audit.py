"""Input contracts, expanding-window evaluation and distribution diagnostics.

Run: PYTHONPATH=src python -m gridledger.audit --root .
The audit reads the versioned CSV and never overwrites the deployed models.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import tempfile
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import wasserstein_distance
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .pipeline import FEATURES, features, metrics


class DataContractError(ValueError):
    """The input cannot support a correctly aligned hourly experiment."""


@dataclass(frozen=True)
class AuditConfig:
    initial_train_days: int = 60
    calibration_days: int = 20
    test_days: int = 20
    step_days: int = 20
    interval_level: float = 0.90
    seed: int = 42

    def __post_init__(self) -> None:
        if min(self.initial_train_days, self.calibration_days, self.test_days, self.step_days) < 1:
            raise ValueError('All temporal windows must be positive.')
        if self.initial_train_days <= 7:
            raise ValueError('Training must extend beyond the 7-day feature warm-up.')
        if self.step_days < self.test_days:
            raise ValueError('Test windows must be disjoint.')
        if not 0 < self.interval_level < 1:
            raise ValueError('Interval level must lie strictly between zero and one.')


def validate_input(frame: pd.DataFrame) -> dict[str, Any]:
    required = {'timestamp', 'feeder', 'step', 'load_kw', 'pv_kw', 'ev_kw',
                'temperature_forecast', 'capacity_kw', 'anomaly_label'}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise DataContractError('Missing columns: ' + ', '.join(missing))
    if frame.empty or frame[list(required)].isna().any().any():
        raise DataContractError('Required fields must be present and non-null.')
    try:
        timestamps = pd.to_datetime(frame.timestamp, utc=True, errors='raise')
        numeric = frame[list(required - {'timestamp', 'feeder'})].to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise DataContractError('Invalid timestamp or numeric value.') from exc
    if not np.isfinite(numeric).all():
        raise DataContractError('Numeric fields must be finite.')
    if not frame.anomaly_label.isin([0, 1]).all():
        raise DataContractError('Anomaly labels must be binary.')
    if (frame[['pv_kw', 'ev_kw']] < 0).any().any() or (frame.capacity_kw <= 0).any():
        raise DataContractError('PV/EV must be nonnegative; capacity must be positive.')
    if not frame.feeder.map(lambda x: isinstance(x, str) and bool(x.strip())).all():
        raise DataContractError('Feeder identifiers must be nonempty strings.')
    checked = frame.assign(timestamp=timestamps)
    if checked.duplicated(['feeder', 'timestamp']).any():
        raise DataContractError('Duplicate feeder/timestamp observations.')
    reports = []
    for feeder, group in checked.groupby('feeder', sort=True):
        if not group.timestamp.is_monotonic_increasing:
            raise DataContractError(f'{feeder}: rows must be ordered by time.')
        if not group.timestamp.diff().iloc[1:].eq(pd.Timedelta(hours=1)).all():
            raise DataContractError(f'{feeder}: missing or irregular hourly observations.')
        if not np.array_equal(group.step.to_numpy(), np.arange(len(group))):
            raise DataContractError(f'{feeder}: step must start at zero and match hourly order.')
        if group.capacity_kw.nunique() != 1:
            raise DataContractError(f'{feeder}: capacity changes need an explicit regime model.')
        reports.append({'feeder': str(feeder), 'rows': len(group),
                        'start': group.timestamp.iloc[0].isoformat(),
                        'end': group.timestamp.iloc[-1].isoformat()})
    return {'status': 'passed', 'rows': len(frame), 'feeders': reports,
            'checks': ['required fields', 'finite values', 'binary labels',
                       'physical input bounds', 'unique timestamps',
                       'ordered hourly cadence', 'step alignment', 'constant capacity']}


def windows(length: int, config: AuditConfig) -> list[dict[str, int]]:
    result = []
    train_end = config.initial_train_days * 24
    while train_end + (config.calibration_days + config.test_days) * 24 <= length:
        calibration_end = train_end + config.calibration_days * 24
        result.append({'fold': len(result) + 1, 'train_end': train_end,
                       'calibration_end': calibration_end,
                       'test_end': calibration_end + config.test_days * 24})
        train_end += config.step_days * 24
    if not result:
        raise DataContractError('Insufficient observations for the configured audit windows.')
    return result


def distribution_shift(reference: np.ndarray, current: np.ndarray) -> dict[str, float]:
    """Descriptive drift scores with bins defined by reference data only."""
    ref, cur = np.asarray(reference, float), np.asarray(current, float)
    if not len(ref) or not len(cur) or not np.isfinite(ref).all() or not np.isfinite(cur).all():
        raise ValueError('Distribution samples must be nonempty and finite.')
    quantiles = np.unique(np.quantile(ref, np.linspace(0, 1, 11)))
    edges = np.unique(np.r_[-np.inf, quantiles, np.inf])
    # Pseudocounts make empty bins finite; both histograms sum to one.
    p = np.histogram(ref, bins=edges)[0] + 0.5
    q = np.histogram(cur, bins=edges)[0] + 0.5
    p, q = p / p.sum(), q / q.sum()
    psi = float(np.sum((q - p) * np.log(q / p)))
    scale = max(float(np.subtract(*np.percentile(ref, [75, 25]))), float(np.std(ref)), 1e-8)
    return {'psi': psi, 'wasserstein_iqr': float(wasserstein_distance(ref, cur) / scale)}


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n'
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False, suffix='.tmp') as stream:
        stream.write(payload)
        temporary = Path(stream.name)
    temporary.replace(path)


def run(root: Path, config: AuditConfig = AuditConfig()) -> dict[str, Any]:
    source = root / 'data/synthetic_hourly.csv'
    raw = pd.read_csv(source)
    contract = validate_input(raw)
    raw['timestamp'] = pd.to_datetime(raw.timestamp, utc=True)
    records, shifts = [], []
    for feeder, group in raw.groupby('feeder', sort=True):
        f = features(group)
        for split in windows(len(group), config):
            train = f[f.step < split['train_end']]
            calibration = f[(f.step >= split['train_end']) & (f.step < split['calibration_end'])]
            test = f[(f.step >= split['calibration_end']) & (f.step < split['test_end'])]
            clean = test.anomaly_label.to_numpy() == 0
            if len(train) < 48 or not len(calibration) or not clean.any():
                raise DataContractError('A fold has insufficient training, calibration or clean evaluation rows.')
            ridge = make_pipeline(StandardScaler(), Ridge(alpha=6))
            boosting = HistGradientBoostingRegressor(max_iter=120, max_leaf_nodes=15,
                learning_rate=.07, early_stopping=False, random_state=config.seed)
            predictions = {'Seasonal naive (24h)': test.lag24.to_numpy()}
            for name, model in [('Ridge', ridge), ('Gradient boosting', boosting)]:
                model.fit(train[FEATURES], train.load_kw)
                predictions[name] = model.predict(test[FEATURES])
            residuals = np.abs(calibration.load_kw.to_numpy() - ridge.predict(calibration[FEATURES]))
            level = min(1.0, math.ceil((len(residuals) + 1) * config.interval_level) / len(residuals))
            width = float(np.quantile(residuals, level, method='higher'))
            errors = np.abs(test.load_kw.to_numpy() - predictions['Ridge'])
            model_scores = {name: metrics(test.load_kw.to_numpy()[clean], pred[clean])
                            for name, pred in predictions.items()}
            records.append({'feeder': str(feeder), **split,
                'n_train': len(train), 'n_calibration': len(calibration), 'n_test': len(test),
                'n_clean_test': int(clean.sum()), 'test_start': test.timestamp.iloc[0].isoformat(),
                'test_last': test.timestamp.iloc[-1].isoformat(), 'models': model_scores,
                'coverage_clean': float(np.mean(errors[clean] <= width)),
                'coverage_all': float(np.mean(errors <= width)), 'interval_half_width_kw': width,
                'calibration_injected_hours': int(calibration.anomaly_label.sum())})
            for feature in ['temperature_forecast', 'lag1', 'lag24', 'rolling24']:
                shifts.append({'feeder': str(feeder), 'fold': split['fold'], 'feature': feature,
                    **distribution_shift(train[feature].to_numpy(), test[feature].to_numpy())})
    aggregate = []
    for feeder in sorted(raw.feeder.unique()):
        subset = [r for r in records if r['feeder'] == feeder]
        scores = {}
        for model in ['Ridge', 'Gradient boosting', 'Seasonal naive (24h)']:
            weights = np.array([r['n_clean_test'] for r in subset])
            maes = np.array([r['models'][model]['mae_kw'] for r in subset])
            scores[model] = {'pooled_mae_kw': float(np.average(maes, weights=weights)),
                            'fold_mae_std_kw': float(np.std(maes)), 'worst_fold_mae_kw': float(maes.max())}
        aggregate.append({'feeder': str(feeder), 'folds': len(subset), 'models': scores,
                          'mean_coverage': float(np.mean([r['coverage_clean'] for r in subset]))})
    output = {'schema': 'gridledger.audit.v1', 'config': asdict(config),
        'dataset_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'data_contract': contract,
        'summary': aggregate, 'folds': records, 'distribution_shift': shifts,
        'notes': ['Synthetic data; descriptive temporal robustness experiment.',
                  'Expanding training windows; disjoint test windows; refit per fold.',
                  'Scalers and histogram bins use training values only.',
                  'MAE excludes injected measurement hours; coverage is also reported over all hours.',
                  'Calibration uses observed readings, including any injected events in later folds.',
                  'PSI and normalized Wasserstein distance are descriptive scores, not significance tests.',
                  'Fixed hyperparameters; no model selection or tuning on test scores.',
                  'The audit does not replace the exported inference model.']}
    atomic_json(root / 'results/advanced_audit.json', output)
    js = 'window.GRIDLEDGER_AUDIT = ' + json.dumps(output, separators=(',', ':'), allow_nan=False) + ';\n'
    (root / 'assets/advanced-data.js').write_text(js)
    atomic_json(root / 'results/advanced_manifest.json', {'schema': 'gridledger.audit-manifest.v1',
        'files': {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                  for name in ['results/advanced_audit.json', 'assets/advanced-data.js',
                               'src/gridledger/audit.py', 'data/synthetic_hourly.csv']}})
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.'))
    args = parser.parse_args()
    report = run(args.root)
    print(json.dumps({'data_contract': report['data_contract']['status'],
                      'folds_executed': len(report['folds']), 'feeders': len(report['summary'])}))


if __name__ == '__main__':
    main()
