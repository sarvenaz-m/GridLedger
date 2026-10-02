"""Deterministic hourly simulation, chronological evaluation and browser export.

Run with: PYTHONPATH=src python -m gridledger.pipeline --out .
All dates are UTC; all load values are kW; each observation spans one hour.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, precision_score, recall_score, f1_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from .provenance import append, canonical, digest, verify

SEED = 42
TRAIN_END = 120 * 24
CAL_END = 150 * 24
N = 180 * 24
FEEDERS = [("F01", "Riverside", 1.0, 132.0), ("F02", "University", 1.32, 176.0), ("F03", "Harbour", 1.7, 218.0)]
FEATURES = ["hour_sin", "hour_cos", "hour_sin2", "hour_cos2", "hour_sin3", "hour_cos3", "weekend", "temperature_forecast", "cooling", "heating", "lag1", "lag24", "lag168", "rolling24"]


def simulate(seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = np.arange(N)
    h = t % 24
    times = pd.date_range("2025-01-01", periods=N, freq="h", tz="UTC")
    weekend = (times.dayofweek >= 5).astype(float)
    weather = rng.normal(0, 2.0, N)
    temp = 16 + 6 * np.sin(2 * np.pi * t / (24 * 100)) + 4 * np.sin((h-8) * np.pi / 12) + weather
    # Forecasts are simulated exogenous inputs available before each target hour.
    temp_fc = temp + rng.normal(0, 1.2, N)
    irradiance = np.maximum(0, np.sin((h - 6) * np.pi / 12)) * rng.uniform(.55, 1, N)
    frames = []
    for fid, name, scale, capacity in FEEDERS:
        daily = 57 + 12 * np.cos((h-15) * np.pi/12) + 9 * np.cos((h-19)*np.pi/6)
        ev = 18 * np.exp(-.5*((h-19)/2.2)**2) + 4 * np.exp(-.5*((h-9)/1.5)**2)
        base = scale * (daily - 8*weekend + 1.8*np.maximum(temp-21,0) + 1.2*np.maximum(13-temp,0))
        clean = np.maximum(1, base + ev*scale + rng.normal(0, 2.5*scale, N))
        pv = irradiance * 26 * scale
        observed = clean.copy()
        anomaly = np.zeros(N, dtype=int)
        # Inject measurement spikes/dropouts only in the held-out test period.
        indices = CAL_END + np.array([19, 80, 153, 220, 293, 364, 421, 494, 568, 635, 703])
        for j, start in enumerate(indices):
            length = 1 + (j % 3)
            observed[start:start+length] += (42*scale if j % 2 == 0 else -32*scale)
            anomaly[start:start+length] = 1
        frames.append(pd.DataFrame({"timestamp": times, "step": t, "feeder": fid, "load_kw": observed,
            "clean_load_kw": clean, "pv_kw": pv, "ev_kw": ev*scale, "temperature_forecast": temp_fc,
            "anomaly_label": anomaly, "capacity_kw": capacity}))
    return pd.concat(frames, ignore_index=True)


def features(frame: pd.DataFrame) -> pd.DataFrame:
    """Strictly past loads; feature at t never uses observed load at t or later."""
    f = frame.copy().sort_values("timestamp")
    h = f.timestamp.dt.hour
    for k in (1,2,3):
        suffix = "" if k == 1 else str(k)
        f["hour_sin"+suffix] = np.sin(2*np.pi*k*h/24)
        f["hour_cos"+suffix] = np.cos(2*np.pi*k*h/24)
    f["weekend"] = (f.timestamp.dt.dayofweek >= 5).astype(int)
    f["cooling"] = np.maximum(f.temperature_forecast-21, 0)
    f["heating"] = np.maximum(13-f.temperature_forecast, 0)
    for lag in (1,24,168):
        f[f"lag{lag}"] = f.load_kw.shift(lag)
    f["rolling24"] = f.load_kw.shift(1).rolling(24).mean()
    return f.dropna(subset=FEATURES).reset_index(drop=True)


def metrics(y, pred) -> dict:
    return {"mae_kw": float(mean_absolute_error(y,pred)), "rmse_kw": float(np.sqrt(mean_squared_error(y,pred)))}


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, allow_nan=False)+"\n")


def run(out: Path, seed: int = SEED) -> dict:
    for folder in ("data", "results", "assets"):
        (out/folder).mkdir(parents=True,exist_ok=True)
    df = simulate(seed)
    raw_path = out/"data/synthetic_hourly.csv"
    df.to_csv(raw_path,index=False,float_format="%.8f")
    dataset_hash = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    demo = {"version":"1.0.0","seed":seed,"data_kind":"deterministic synthetic data",
            "dataset_sha256":dataset_hash,"feature_names":FEATURES,"feeders":[],
            "split":{"train_days":120,"calibration_days":30,"test_days":30,"warmup_hours":168},
            "interval":"90% calibration-residual band; time-series coverage is empirical, not guaranteed"}
    results=[]
    predictions=[]
    chain=[]
    for fid,name,scale,capacity in FEEDERS:
        f=features(df[df.feeder==fid])
        train=f[f.step<TRAIN_END]
        cal=f[(f.step>=TRAIN_END)&(f.step<CAL_END)]
        test=f[f.step>=CAL_END]
        model=make_pipeline(StandardScaler(), Ridge(alpha=6))
        model.fit(train[FEATURES],train.load_kw)
        p=model.predict(test[FEATURES])
        cp=model.predict(cal[FEATURES])
        residual=np.abs(cal.load_kw.to_numpy()-cp)
        # Finite sample calibration quantile. No exchangeability claim for time series.
        q_level=min(1,math.ceil((len(cal)+1)*.9)/len(cal))
        q=float(np.quantile(residual,q_level,method="higher"))
        threshold=float(np.quantile(residual,.99,method="higher"))
        detected=(np.abs(test.load_kw.to_numpy()-p)>threshold).astype(int)
        clean_mask=test.anomaly_label.to_numpy()==0
        hgb=HistGradientBoostingRegressor(max_iter=120,max_leaf_nodes=15,learning_rate=.07,early_stopping=False,random_state=seed)
        hgb.fit(train[FEATURES],train.load_kw)
        hp=hgb.predict(test[FEATURES])
        naive=test.lag24.to_numpy()
        comparison={label:metrics(test.load_kw.to_numpy()[clean_mask],pred[clean_mask]) for label,pred in [("Ridge",p),("Gradient boosting",hp),("Seasonal naive (24h)",naive)]}
        entry={"feeder":fid,"name":name,"n_train":len(train),"n_calibration":len(cal),"n_test":len(test),"n_clean_test":int(clean_mask.sum()),
               "forecast_clean_hours":comparison,"forecast_all_observed_hours":metrics(test.load_kw,p),
               "coverage_clean":float(np.mean(np.abs(test.load_kw.to_numpy()[clean_mask]-p[clean_mask])<=q)),
               "interval_half_width_kw":q,"anomaly_threshold_kw":threshold,
               "anomaly_precision":float(precision_score(test.anomaly_label,detected,zero_division=0)),
               "anomaly_recall":float(recall_score(test.anomaly_label,detected,zero_division=0)),
               "anomaly_f1":float(f1_score(test.anomaly_label,detected,zero_division=0)),
               "injected_hours":int(test.anomaly_label.sum()),"alert_hours":int(detected.sum())}
        results.append(entry)
        scaler,reg=model.steps[0][1],model.steps[1][1]
        exported={"algorithm":"StandardScaler + Ridge","alpha":6,"features":FEATURES,"mean":scaler.mean_.tolist(),"scale":scaler.scale_.tolist(),"coef":reg.coef_.tolist(),"intercept":float(reg.intercept_)}
        model_hash=digest(exported)
        write_json(out/f"results/model_{fid}.json",exported)
        rows=[]
        for j,(_,r) in enumerate(test.iterrows()):
            row={"timestamp":r.timestamp.isoformat().replace("+00:00","Z"),"actual":float(r.load_kw),"prediction":float(p[j]),"pv":float(r.pv_kw),"ev":float(r.ev_kw),
                 "label":int(r.anomaly_label),"features":[float(r[x]) for x in FEATURES]}
            if j >= len(test)-72: rows.append(row)
            predictions.append({"feeder":fid,**{k:v for k,v in row.items() if k!="features"},"alert":int(detected[j])})
        demo["feeders"].append({"id":fid,"name":name,"capacity":capacity,"model":exported,"model_sha256":model_hash,"metrics":entry,"rows":rows})
        payload={"schema":"gridledger.prediction.v1","feeder":fid,"timestamp":rows[-1]["timestamp"],"prediction_watts":round(rows[-1]["prediction"]*1000),
                 "model_sha256":model_hash,"dataset_sha256":dataset_hash,"anomaly":bool(detected[-1])}
        append(chain,payload)
    summary={"version":"1.0.0","seed":seed,"data":"synthetic; not operational utility data","forecast_horizon":"rolling one hour ahead", "environment":{"python":platform.python_version(),"numpy":np.__version__,"pandas":pd.__version__,"scikit_learn":sklearn.__version__},
             "split_steps":{"train_end_exclusive":TRAIN_END,"calibration_end_exclusive":CAL_END,"test_end_exclusive":N},"results":results}
    head=chain[-1]["hash"]
    assert verify(chain,head)[0]
    demo["chain"]=chain;demo["checkpoint"]=head
    write_json(out/"results/metrics.json",summary)
    pd.DataFrame(predictions).to_csv(out/"results/predictions.csv",index=False,float_format="%.8f")
    write_json(out/"results/ledger.json",{"records":chain,"checkpoint":head})
    write_json(out/"assets/demo-data.json",demo)
    (out/"assets/demo-data.js").write_text("window.GRIDLEDGER_DATA = "+json.dumps(demo,separators=(",",":"),allow_nan=False)+";\n")
    # This manifest owns the inference experiment. Independent audit and UI
    # artifacts have their own lifecycle and must not create stale cross-links.
    names = ["ledger.json", "metrics.json", "model_F01.json", "model_F02.json",
             "model_F03.json", "predictions.csv"]
    manifest={"schema":"gridledger.manifest.v1","files":{
        "results/"+name: hashlib.sha256((out/"results"/name).read_bytes()).hexdigest()
        for name in names}}
    manifest["files"]["data/synthetic_hourly.csv"]=dataset_hash
    write_json(out/"results/manifest.json",manifest)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out",type=Path,default=Path("."))
    p.add_argument("--seed",type=int,default=42)
    args=p.parse_args()
    result=run(args.out,args.seed)
    for x in result["results"]:
        print(x["feeder"],json.dumps({"forecast":x["forecast_clean_hours"],"anomaly_f1":x["anomaly_f1"]}))


if __name__ == "__main__": main()
