import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from gridledger.audit import DataContractError
from gridledger.provenance import verify
from gridledger.real import (FEATURES, RealConfig, available_load, causal_fill, feature_frame,
                             folds, interval_width, seasonal_scale, split_masks, stress_mask)
from gridledger.real_data import dst_mask, load_hourly, quarter_to_hour, sha256
from gridledger.verify import check_manifest

ROOT = Path(__file__).resolve().parents[1]


class RealProtocolChecks(unittest.TestCase):
    def setUp(self):
        self.index = pd.date_range("2013-01-01", periods=1000, freq="h")
        self.values = pd.Series(10 + np.arange(1000) / 100, index=self.index)

    def test_all_horizons_ignore_present_and_future_measurements(self):
        changed = self.values.copy()
        changed.iloc[400:] += 1000
        for horizon in (1, 6, 24, 168):
            a = feature_frame(self.values, horizon, 15)
            b = feature_frame(changed, horizon, 15)
            np.testing.assert_allclose(a.iloc[:401][FEATURES], b.iloc[:401][FEATURES], equal_nan=True)

    def test_future_missing_values_cannot_repair_past_features(self):
        missing = self.values.copy()
        missing.iloc[350:400] = np.nan
        changed = missing.copy()
        changed.iloc[400:] *= 100
        a, b = (feature_frame(v, 24, 15) for v in (missing, changed))
        np.testing.assert_allclose(a.iloc[:401][FEATURES], b.iloc[:401][FEATURES], equal_nan=True)

    def test_no_backfill_and_limited_forward_fill(self):
        values = pd.Series([np.nan, 5, np.nan, np.nan, np.nan, 99])
        np.testing.assert_array_equal(causal_fill(values, 7, 2), [7, 5, 5, 5, 7, 99])

    def test_horizon_target_alignment(self):
        for h in (1, 6, 24, 168):
            frame = feature_frame(self.values, h, 15)
            self.assertEqual(frame.target_time.iloc[400], self.index[400] + pd.Timedelta(hours=h - 1))
            self.assertEqual(frame.lag1.iloc[400], self.values.iloc[399])

    def test_seasonal_forecast_never_reads_future_at_long_horizons(self):
        for h in (1, 6, 24, 48, 168):
            frame = feature_frame(self.values, h, 15)
            for period in (24, 168):
                offset = period - ((h - 1) % period)
                self.assertGreaterEqual(offset, 1)
                self.assertEqual(frame[f"seasonal{period}"].iloc[400], self.values.iloc[400 - offset])

    def test_training_and_calibration_labels_are_purged(self):
        split = {"train_end": self.index[600], "calibration_end": self.index[720], "test_end": self.index[960]}
        for horizon in (1, 6, 24):
            frame = feature_frame(self.values, horizon, 15)
            masks = split_masks(frame, self.values.shift(-(horizon - 1)), split, "2013-01-01")
            train, cal, test = (frame.loc[masks[s]] for s in ("train", "calibration", "test"))
            self.assertLess(train.target_time.max(), split["train_end"])
            self.assertGreaterEqual(cal.index.min(), split["train_end"])
            self.assertLess(cal.target_time.max(), split["calibration_end"])
            self.assertGreaterEqual(test.index.min(), split["calibration_end"])
            self.assertLess(test.target_time.max(), split["test_end"])
            self.assertFalse(np.any(masks["train"] & masks["calibration"]))
            self.assertEqual(int(masks["train"].sum()), 600 - 168 - (horizon - 1))

    def test_unavailable_truth_is_excluded_rather_than_imputed(self):
        truth = self.values.copy()
        truth.iloc[800] = np.nan
        frame = feature_frame(truth, 6, 15)
        split = {"train_end": self.index[600], "calibration_end": self.index[720], "test_end": self.index[960]}
        masks = split_masks(frame, truth.shift(-5), split, "2013-01-01")
        self.assertFalse(masks["test"][795])
        self.assertTrue(np.isfinite(frame.loc[self.index[801], FEATURES].astype(float)).all())

    def test_only_initial_zero_run_is_excluded(self):
        values = self.values.copy()
        values.iloc[:100] = 0
        values.iloc[500] = 0
        available = available_load(values, self.index[100].isoformat())
        self.assertTrue(available.iloc[:100].isna().all())
        self.assertEqual(available.iloc[500], 0)

    def test_provider_dst_dates_and_crossing_windows(self):
        index = pd.date_range("2014-03-28", "2014-04-02", freq="h", inclusive="left")
        self.assertEqual(int(dst_mask(index).sum()), 24)
        values = pd.Series(10.0, index=index)
        frame = feature_frame(values, 24, 10)
        self.assertFalse(bool(frame.loc["2014-03-29 12:00", "clock_safe"]))
        self.assertFalse(bool(frame.loc["2014-03-30 12:00", "clock_safe"]))
        self.assertTrue(bool(frame.loc["2014-03-31 12:00", "clock_safe"]))

    def test_training_scale_cannot_see_future_targets(self):
        changed = self.values.copy()
        changed.iloc[600:] += 1000
        self.assertEqual(seasonal_scale(self.values, self.index[600]), seasonal_scale(changed, self.index[600]))

    def test_quarter_hour_power_is_averaged_not_summed(self):
        q = pd.DataFrame({"meter": [4.0, 8, 12, 16]}, index=pd.date_range("2013-01-01", periods=4, freq="15min"))
        self.assertEqual(quarter_to_hour(q).iloc[0, 0], 10)

    def test_incomplete_source_hour_is_not_an_observed_target(self):
        q = pd.DataFrame({"meter": [4.0, 8, 12]}, index=pd.date_range("2013-01-01", periods=3, freq="15min"))
        self.assertTrue(np.isnan(quarter_to_hour(q).iloc[0, 0]))

    def test_irregular_source_cadence_is_rejected(self):
        q = pd.DataFrame({"meter": [4.0, 8, 12]}, index=pd.to_datetime(["2013-01-01 00:00", "2013-01-01 00:15", "2013-01-01 00:45"]))
        with self.assertRaises(DataContractError):
            quarter_to_hour(q)

    def test_duplicate_hourly_origins_are_rejected(self):
        duplicate = pd.concat([self.values.iloc[:2], self.values.iloc[1:]])
        with self.assertRaises(DataContractError):
            feature_frame(duplicate, 1, 15)

    def test_missing_hourly_rows_require_explicit_nan_slots(self):
        with self.assertRaises(DataContractError):
            feature_frame(self.values.drop(self.index[300]), 1, 15)

    def test_infinite_and_negative_readings_are_rejected(self):
        for invalid in (-1, np.inf):
            values = self.values.copy()
            values.iloc[300] = invalid
            with self.assertRaises(DataContractError):
                feature_frame(values, 1, 15)

    def test_invalid_horizons_are_rejected(self):
        for horizon in (0, 169, 1.5):
            with self.assertRaises(ValueError):
                feature_frame(self.values, horizon, 15)

    def test_stress_is_seeded_and_only_changes_test_inputs(self):
        index = pd.date_range("2013-01-01", "2015-01-01", freq="h", inclusive="left")
        split = folds()[0]
        a, b = stress_mask(index, split, 42), stress_mask(index, split, 42)
        np.testing.assert_array_equal(a, b)
        self.assertFalse(a[index < split["calibration_end"]].any())
        self.assertFalse(a[index >= split["test_end"]].any())
        self.assertTrue(a[(index >= "2014-01-21 08:00") & (index < "2014-01-22 08:00")].all())

    def test_calibration_width_uses_finite_sample_quantile(self):
        self.assertEqual(interval_width(np.arange(10), np.zeros(10), .9), 9)
        with self.assertRaises(ValueError):
            interval_width([], [], .9)

    def test_test_windows_are_disjoint_and_training_expands(self):
        windows = folds()
        self.assertEqual(len(windows), 4)
        for left, right in zip(windows, windows[1:]):
            self.assertLess(left["train_end"], right["train_end"])
            self.assertLessEqual(left["test_end"], right["calibration_end"])


class RealArtifactChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo = json.loads((ROOT / "assets/real-data.json").read_text())
        cls.report = json.loads((ROOT / "results/real_benchmark.json").read_text())

    def test_real_extract_contract_and_official_source_attribution(self):
        hourly, source = load_hourly(ROOT)
        self.assertEqual(hourly.shape, (17520, 20))
        self.assertEqual(source["doi"], "10.24432/C58C86")
        self.assertEqual(source["license"], "CC BY 4.0")
        self.assertEqual(source["hourly_csv_sha256"], sha256(ROOT / "data/uci_hourly.csv"))

    def test_all_real_artifact_checksums(self):
        self.assertEqual(check_manifest(ROOT), 10)

    def test_altered_file_is_rejected_by_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "results").mkdir()
            (root / "sample.txt").write_text("original")
            (root / "results/real_manifest.json").write_text(json.dumps({"files": {"sample.txt": sha256(root / "sample.txt")}}))
            (root / "sample.txt").write_text("changed")
            with self.assertRaises(DataContractError):
                check_manifest(root)

    def test_browser_models_reproduce_python_on_every_real_replay(self):
        checked = 0
        for meter in self.demo["meters"]:
            for horizon in meter["horizons"].values():
                model = horizon["model"]
                self.assertEqual(len(horizon["rows"]), 72)
                for row in horizon["rows"]:
                    prediction = max(0, float(np.dot((np.asarray(row["features"]) - model["mean"]) / model["scale"], model["coef"]) + model["intercept"]))
                    self.assertAlmostEqual(prediction, row["prediction"], places=8)
                    checked += 1
        self.assertEqual(checked, 4320)

    def test_every_fold_has_purged_labels_and_original_truth(self):
        self.assertEqual(len(self.report["folds"]), 240)
        for record in self.report["folds"]:
            self.assertLess(record["last_training_target"], record["train_end_exclusive"])
            self.assertLess(record["last_calibration_target"], record["calibration_end_exclusive"])
            self.assertLess(record["last_test_target"], record["test_end_exclusive"])
            self.assertEqual(len(record["models"]), 5)

    def test_real_provenance_detects_target_tampering(self):
        self.assertTrue(verify(self.demo["chain"], self.demo["checkpoint"])[0])
        changed = copy.deepcopy(self.demo["chain"])
        changed[0]["payload"]["target"] = "2014-01-01T00:00:00"
        self.assertFalse(verify(changed, self.demo["checkpoint"])[0])


if __name__ == "__main__":
    unittest.main()
