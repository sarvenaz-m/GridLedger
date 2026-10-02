import copy
import hashlib
import json
import unittest
from pathlib import Path
import numpy as np
from gridledger.pipeline import simulate, features, FEATURES, TRAIN_END, CAL_END, N
from gridledger.provenance import append, verify

ROOT=Path(__file__).resolve().parents[1]

class ResearchChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw=simulate()
        cls.frame=cls.raw[cls.raw.feeder=='F01'].reset_index(drop=True)
        cls.demo=json.loads((ROOT/'assets/demo-data.json').read_text())

    def test_generator_is_reproducible(self):
        self.assertTrue(self.raw.equals(simulate()))

    def test_features_do_not_read_present_or_future_load(self):
        changed=self.frame.copy()
        changed.loc[1000:,'load_kw']+=10000
        a=features(self.frame);b=features(changed)
        np.testing.assert_allclose(a.loc[a.step<=1000,FEATURES],b.loc[b.step<=1000,FEATURES])

    def test_splits_are_ordered_and_disjoint(self):
        f=features(self.frame)
        train=f[f.step<TRAIN_END];cal=f[(f.step>=TRAIN_END)&(f.step<CAL_END)];test=f[f.step>=CAL_END]
        self.assertLess(train.timestamp.max(),cal.timestamp.min())
        self.assertLess(cal.timestamp.max(),test.timestamp.min())
        self.assertEqual(len(train)+len(cal)+len(test),N-168)
        self.assertEqual(int(train.anomaly_label.sum()+cal.anomaly_label.sum()),0)

    def test_browser_model_export_matches_python_predictions(self):
        for feeder in self.demo['feeders']:
            m=feeder['model']
            for row in feeder['rows']:
                y=float(np.dot((np.array(row['features'])-m['mean'])/m['scale'],m['coef'])+m['intercept'])
                self.assertAlmostEqual(y,row['prediction'],places=9)

    def test_forecast_performance_exceeds_seasonal_naive(self):
        for feeder in self.demo['feeders']:
            x=feeder['metrics']['forecast_clean_hours']
            self.assertLess(x['Ridge']['mae_kw'],x['Seasonal naive (24h)']['mae_kw'])

    def test_output_manifest_matches_file_bytes(self):
        manifest=json.loads((ROOT/'results/manifest.json').read_text())
        for name,expected in manifest['files'].items():
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),expected,name)

class IntegrityChecks(unittest.TestCase):
    def setUp(self):
        self.chain=[]
        append(self.chain,{'prediction_watts':51000,'timestamp':'2025-01-01T00:00:00Z'})
        append(self.chain,{'prediction_watts':52000,'timestamp':'2025-01-01T01:00:00Z'})
        self.head=self.chain[-1]['hash']

    def test_valid_chain(self): self.assertTrue(verify(self.chain,self.head)[0])
    def test_value_tampering(self):
        self.chain[0]['payload']['prediction_watts']+=1
        self.assertFalse(verify(self.chain,self.head)[0])
    def test_truncation(self): self.assertFalse(verify(self.chain[:-1],self.head)[0])
    def test_reordering(self): self.assertFalse(verify(list(reversed(self.chain)),self.head)[0])
    def test_full_rewrite_requires_external_checkpoint(self):
        rewrite=[]
        append(rewrite,{'prediction_watts':999999})
        self.assertTrue(verify(rewrite)[0])
        self.assertFalse(verify(rewrite,self.head)[0])
    def test_empty_chain_cannot_match_nonempty_checkpoint(self): self.assertFalse(verify([],self.head)[0])

if __name__=='__main__':unittest.main()
