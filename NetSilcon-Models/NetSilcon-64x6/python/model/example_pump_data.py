"""
Write an EXAMPLE dataset for train_csv.py: pump vibration health, 16 sensor features -> 4 states.

    python3 example_pump_data.py                    -> data/pump_vibration.csv (20,000 rows)
    python3 example_pump_data.py --rows 5000 --out my.csv

The data is SYNTHETIC (made by simple rules plus noise). It shows the workflow, nothing more.
For a real product, record the same kind of table from your own machine.

Columns (16 inputs):
    rpm, current_a, temp_c, pressure_bar,
    band_1x, band_2x, band_3x, band_4x          vibration amplitude at 1x..4x running speed (mm/s)
    band_hf1 .. band_hf4                         high-frequency bands, where bearing damage shows (g)
    axial_1x, axial_2x                           axial vibration (mm/s)
    kurtosis, crest_factor                       shape of the vibration signal
Target column: state = normal | imbalance | misalignment | bearing
"""
import argparse
import csv
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
STATES = ["normal", "imbalance", "misalignment", "bearing"]
COLS = ["rpm", "current_a", "temp_c", "pressure_bar",
        "band_1x", "band_2x", "band_3x", "band_4x",
        "band_hf1", "band_hf2", "band_hf3", "band_hf4",
        "axial_1x", "axial_2x", "kurtosis", "crest_factor"]


def make(n, seed):
    rng = np.random.default_rng(seed)
    st = rng.integers(0, 4, n)
    sev = rng.uniform(0.2, 1.0, n)                    # how bad the fault is (0.2 = early, hard to see)
    rpm = rng.uniform(1400, 2950, n)
    load = rng.uniform(0.4, 1.0, n)
    cur = 4 + 8 * load * rpm / 2950 + rng.normal(0, 0.3, n)
    temp = 30 + 25 * load + rng.normal(0, 2, n)
    pres = 1.0 + 2.5 * load * (rpm / 2950) ** 2 + rng.normal(0, 0.1, n)
    b = {k: np.abs(rng.normal(v, v * 0.25, n)) for k, v in
         dict(band_1x=1.2, band_2x=0.5, band_3x=0.3, band_4x=0.2, band_hf1=0.05, band_hf2=0.04,
              band_hf3=0.03, band_hf4=0.02, axial_1x=0.4, axial_2x=0.2).items()}
    kurt = rng.normal(3.0, 0.25, n)
    crest = rng.normal(3.2, 0.3, n)
    m = st == 1                                         # imbalance: strong 1x, radial
    b["band_1x"][m] += 4.0 * sev[m] * (rpm[m] / 2950) ** 2
    m = st == 2                                         # misalignment: 2x and axial
    b["band_2x"][m] += 2.5 * sev[m]
    b["axial_1x"][m] += 1.5 * sev[m]
    b["axial_2x"][m] += 1.2 * sev[m]
    m = st == 3                                         # bearing: high-frequency energy, spiky signal, warmer
    for k, g in (("band_hf1", 0.6), ("band_hf2", 0.5), ("band_hf3", 0.35), ("band_hf4", 0.2)):
        b[k][m] += g * sev[m]
    kurt[m] += 3.0 * sev[m]
    crest[m] += 2.0 * sev[m]
    temp[m] += 6 * sev[m]
    X = np.column_stack([rpm, cur, temp, pres] + [b[c] for c in COLS[4:14]] + [kurt, crest])
    return X, st


def main():
    ap = argparse.ArgumentParser(description="synthetic pump vibration dataset (example only)")
    ap.add_argument("--rows", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "pump_vibration.csv"))
    a = ap.parse_args()
    X, st = make(a.rows, a.seed)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS + ["state"])
        for x, s in zip(X, st):
            w.writerow([f"{v:.4f}" for v in x] + [STATES[s]])
    print(f"wrote {a.rows} rows to {os.path.relpath(a.out)}  (synthetic example data, 16 inputs, "
          f"target column 'state': {', '.join(STATES)})")


if __name__ == "__main__":
    main()
