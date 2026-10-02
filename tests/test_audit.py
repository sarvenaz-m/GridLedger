import hashlib
import json
from pathlib import Path
import unittest
import numpy as np
from gridledger.audit import AuditConfig, DataContractError, distribution_shift, validate_input, windows
from gridledger.pipeline import simulate

ROOT = Path(__file__).resolve().parents[1]

class ContractChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.frame = simulate().query('feeder == "F01"').reset_index(drop=True)

    def test_valid_hourly_data(self):
        self.assertEqual(validate_input(self.frame)['status'], 'passed')

    def test_duplicate_measurements_rejected(self):
        import pandas as pd
        with self.assertRaises(DataContractError):
            validate_input(pd.concat([self.frame, self.frame.iloc[[0]]]))

    def test_missing_hour_rejected(self):
        with self.assertRaises(DataContractError): validate_input(self.frame.drop(index=100))

    def test_nonfinite_predictor_rejected(self):
        frame = self.frame.copy(); frame.loc[5, 'temperature_forecast'] = np.inf
        with self.assertRaises(DataContractError): validate_input(frame)

    def test_reordered_rows_rejected(self):
        with self.assertRaises(DataContractError): validate_input(self.frame.iloc[::-1])

    def test_invalid_physical_input_rejected(self):
        frame = self.frame.copy(); frame.loc[2, 'pv_kw'] = -1
        with self.assertRaises(DataContractError): validate_input(frame)

class TemporalAuditChecks(unittest.TestCase):
    def test_windows_ordered_and_test_periods_disjoint(self):
        folds = windows(180 * 24, AuditConfig())
        self.assertEqual(len(folds), 5)
        for fold in folds:
            self.assertLess(fold['train_end'], fold['calibration_end'])
            self.assertLess(fold['calibration_end'], fold['test_end'])
        for left, right in zip(folds, folds[1:]):
            self.assertLessEqual(left['test_end'], right['calibration_end'])

    def test_overlap_configuration_rejected(self):
        with self.assertRaises(ValueError): AuditConfig(step_days=10)

    def test_short_input_rejected(self):
        with self.assertRaises(DataContractError): windows(24 * 30, AuditConfig())

    def test_identical_and_shifted_distributions(self):
        values = np.linspace(-2, 2, 1000)
        self.assertEqual(distribution_shift(values, values)['psi'], 0)
        shifted = distribution_shift(values, values + 8)
        self.assertGreater(shifted['psi'], 1)
        self.assertGreater(shifted['wasserstein_iqr'], 1)

    def test_constant_distribution_stays_finite(self):
        scores = distribution_shift(np.ones(100), np.ones(100))
        self.assertTrue(all(np.isfinite(v) for v in scores.values()))

    def test_audit_artifacts_match_checksums(self):
        manifest = json.loads((ROOT / 'results/advanced_manifest.json').read_text())
        for name, digest in manifest['files'].items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest, name)

    def test_executed_folds_have_finite_metrics_and_no_test_overlap(self):
        report = json.loads((ROOT / 'results/advanced_audit.json').read_text())
        self.assertEqual(len(report['folds']), 15)
        for fold in report['folds']:
            self.assertEqual(fold['n_test'], 480)
            self.assertTrue(0 <= fold['coverage_clean'] <= 1)
            for score in fold['models'].values():
                self.assertTrue(np.isfinite(score['mae_kw']) and score['mae_kw'] >= 0)

if __name__ == '__main__': unittest.main()
