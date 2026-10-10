"""Pinned UCI electricity source, conservative clock QC and hourly conversion."""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

import numpy as np
import pandas as pd

from .audit import DataContractError, atomic_json

SOURCE_URL = "https://archive.ics.uci.edu/static/public/321/electricityloaddiagrams20112014.zip"
SOURCE_PAGE = "https://archive.ics.uci.edu/dataset/321/electricityloaddiagrams20112014"
SOURCE_DOI = "10.24432/C58C86"
ARCHIVE_SHA256 = "f6c4d0e0df12ecdb9ea008dd6eef3518adb52c559d04a9bac2e1b81dcfc8d4e1"
MEMBER = "LD2011_2014.txt"
METERS = tuple(f"MT_{n:03d}" for n in range(1, 21))
START, END = "2013-01-01", "2015-01-01"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def dst_dates(years) -> list[pd.Timestamp]:
    """Last Sundays in March/October, flagged in the provider's local clock."""
    dates = []
    for year in sorted(set(years)):
        for month in (3, 10):
            last = pd.Timestamp(year=year, month=month, day=calendar.monthrange(year, month)[1])
            dates.append(last - pd.Timedelta(days=(last.dayofweek + 1) % 7))
    return dates


def dst_mask(index: pd.DatetimeIndex) -> np.ndarray:
    return np.asarray(index.normalize().isin(dst_dates(index.year)), dtype=bool)


def quarter_to_hour(frame: pd.DataFrame) -> pd.DataFrame:
    """Left-labelled mean kW; four timestamped samples are required per hour.

    A row labelled t represents the four source labels in [t, t+1h).
    It is available only at t+1h. We do not infer an unprovided UTC clock.
    """
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is not None:
        raise DataContractError("Source must use a timezone-naive provider clock.")
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise DataContractError("Source timestamps must be unique and ordered.")
    if not np.all(frame.index.diff()[1:] == pd.Timedelta(minutes=15)):
        raise DataContractError("Source must have an uninterrupted 15-minute cadence.")
    values = frame.to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise DataContractError("Source readings must be finite, nonnegative kW.")
    resampler = frame.resample("h", closed="left", label="left")
    hourly = resampler.mean()
    return hourly.where(resampler.count().eq(4))


def prepare(root: Path, archive: Path) -> dict:
    archive_hash = sha256(archive)
    if archive_hash != ARCHIVE_SHA256:
        raise DataContractError("UCI archive SHA-256 mismatch; do not silently change the benchmark source.")
    with zipfile.ZipFile(archive) as bundle:
        # Read the named member only, without extracting platform metadata.
        with bundle.open(MEMBER) as stream:
            raw = pd.read_csv(stream, sep=";", decimal=",", usecols=[0, *range(1, 21)])
        with bundle.open(MEMBER) as stream:
            member_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    raw.index = pd.DatetimeIndex(pd.to_datetime(raw.iloc[:, 0], errors="raise"))
    raw = raw.iloc[:, 1:]
    if tuple(raw.columns) != METERS or len(raw) != 140256:
        raise DataContractError("Unexpected source schema or observation count.")
    hourly = quarter_to_hour(raw)
    hourly = hourly.loc[(hourly.index >= START) & (hourly.index < END)]
    if hourly.isna().any().any() or len(hourly) != 17520:
        raise DataContractError("The fixed 2013–2014 extract must contain complete hourly observations.")
    hourly.index.name = "timestamp"
    output = root / "data/uci_hourly.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    hourly.to_csv(output, float_format="%.10f", lineterminator="\n")
    first_train = hourly.loc[hourly.index < "2014-01-01"]
    activations = {}
    for meter in METERS:
        positive = first_train.index[first_train[meter] > 0]
        if not len(positive):
            raise DataContractError(f"{meter}: no positive reading in the first training window.")
        activations[meter] = positive[0].isoformat()
    report = {
        "schema": "gridledger.uci-source.v2", "dataset": "ElectricityLoadDiagrams20112014",
        "creator": "Artur Trindade", "doi": SOURCE_DOI, "source_page": SOURCE_PAGE,
        "download_url": SOURCE_URL, "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "archive_bytes": archive.stat().st_size, "archive_sha256": archive_hash,
        "member": MEMBER, "member_sha256": member_hash,
        "source_quarter_hour_rows": len(raw), "source_total_meters": 370,
        "selection": "MT_001–MT_020 in source order; fixed cohort, no test-score selection",
        "meters": list(METERS), "start_inclusive": START, "end_exclusive": END,
        "hourly_rows_per_meter": len(hourly), "hourly_meter_observations": len(hourly) * len(METERS),
        "hourly_csv_sha256": sha256(output),
        "aggregation": "Arithmetic mean of four quarter-hour kW readings per left-labelled source-clock hour. kWh per quarter = kW / 4.",
        "clock": "Timezone-naive Portuguese provider clock; 96 slots per day even on DST transitions. No UTC conversion.",
        "provider_missing_values": "Provider reports none. Initial zero runs can encode clients not yet created; later zeros are retained.",
        "dst_policy": "Exclude whole March/October transition days from targets; treat their historical inputs as unavailable. Also exclude origin-to-target windows crossing those dates.",
        "dst_dates": [d.date().isoformat() for d in dst_dates(hourly.index.year)],
        "dst_hours_per_meter": int(dst_mask(hourly.index).sum()),
        "activation_policy": "Exclude the initial zero run up to the first positive 2013 training reading; retain all subsequent zero readings. First-training rule only.",
        "activation_from_first_training": activations,
        "quality": {m: {"zero_hours": int(hourly[m].eq(0).sum()),
                        "pre_activation_hours": int((hourly.index < activations[m]).sum()),
                        "nonfinite_hours": int((~np.isfinite(hourly[m])).sum())} for m in METERS},
        "hash_note": "Archive hash pinned from the official UCI download; this is a project pin, not a separately published provider checksum.",
    }
    atomic_json(root / "data/uci_source.json", report)
    return report


def load_hourly(root: Path) -> tuple[pd.DataFrame, dict]:
    path = root / "data/uci_hourly.csv"
    source = json.loads((root / "data/uci_source.json").read_text())
    if sha256(path) != source["hourly_csv_sha256"]:
        raise DataContractError("Hourly UCI extract does not match the source manifest.")
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    if tuple(frame.columns) != METERS or len(frame) != 17520:
        raise DataContractError("Unexpected cohort or hourly row count.")
    expected = pd.date_range(START, END, freq="h", inclusive="left")
    if not frame.index.equals(expected):
        raise DataContractError("Hourly timestamps must match the fixed provider-clock grid.")
    if not np.isfinite(frame.to_numpy()).all() or (frame < 0).any().any():
        raise DataContractError("Hourly source must contain finite nonnegative readings.")
    return frame, source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--cache", type=Path, default=Path(".cache/gridledger"))
    parser.add_argument("--archive", type=Path, help="Use an already downloaded official archive")
    args = parser.parse_args()
    archive = args.archive or args.cache / "electricityloaddiagrams20112014.zip"
    if not archive.exists():
        archive.parent.mkdir(parents=True, exist_ok=True)
        temporary = archive.with_suffix(".part")
        print("Downloading the official UCI archive (~249 MiB).", flush=True)
        urllib.request.urlretrieve(SOURCE_URL, temporary)
        if sha256(temporary) != ARCHIVE_SHA256:
            temporary.unlink()
            raise DataContractError("Downloaded archive SHA-256 mismatch.")
        temporary.replace(archive)
    report = prepare(args.root, archive)
    print(json.dumps({"hourly_meter_observations": report["hourly_meter_observations"],
                      "meters": len(report["meters"]), "source_hash_verified": True}))


if __name__ == "__main__":
    main()
