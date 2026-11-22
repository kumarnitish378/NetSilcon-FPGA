"""Synthetic BLDC motor data for the NetSilcon-6x4 fault detector.

Inputs (4):  phase current [A], supply voltage [V], speed [rpm], winding temperature [degC]
Output (2):  logits for [healthy, fault]

A sample is a FAULT when any of these happen (each needs a non-linear rule,
so the network has to learn more than a straight line):
  1. Mechanical bind  - current too high for the speed the motor is turning at
  2. Cooling failure  - temperature too high for the current flowing
  3. Supply sag       - voltage below 20 V while the motor is loaded
Replace this generator with real logs from your BLDC digital twin later.
"""
import numpy as np

# Fixed input ranges. The hardware sees  q = round(value / RANGE * 127), clipped to 0..127
RANGES = np.array([20.0, 30.0, 6000.0, 120.0])   # current A, voltage V, rpm, temp C
NAMES = ["current_A", "voltage_V", "speed_rpm", "temp_C"]

KV = 220.0          # rpm per volt (no-load)
R_TH = 2.2          # degC per A^2 heating coefficient (healthy cooling)


def make(n, seed=0):
    rng = np.random.default_rng(seed)
    V = rng.uniform(16, 28, n)                      # supply voltage
    load = rng.uniform(0.05, 0.95, n)               # mechanical load fraction
    amb = rng.uniform(20, 40, n)                    # ambient temperature

    I = 1.0 + 15.0 * load + rng.normal(0, 0.4, n)   # healthy current
    rpm = KV * V * (1 - 0.55 * load) + rng.normal(0, 60, n)
    T = amb + R_TH * I**2 * 0.18 + rng.normal(0, 1.5, n)

    fault = np.zeros(n, dtype=int)
    kind = rng.integers(0, 4, n)                    # 0 = healthy, 1..3 = fault type
    inject = rng.random(n) < 0.5                    # ~half the samples carry a fault

    m = inject & (kind == 1)                        # mechanical bind: speed collapses, current rises
    rpm[m] *= rng.uniform(0.25, 0.6, m.sum())
    I[m] *= rng.uniform(1.15, 1.4, m.sum())

    m = inject & (kind == 2)                        # cooling failure: hot for its current
    T[m] += rng.uniform(25, 50, m.sum())

    m = inject & (kind == 3)                        # supply sag under load
    V[m] = rng.uniform(12, 19, m.sum())
    rpm[m] = KV * V[m] * (1 - 0.55 * load[m]) + rng.normal(0, 60, m.sum())
    I[m] = np.maximum(I[m], 6 + rng.uniform(0, 6, m.sum()))

    fault[inject & (kind > 0)] = 1
    X = np.stack([I, V, rpm, T], axis=1)
    X = np.clip(X, 0, RANGES)
    return X, fault


def to_int8(X):
    """Real-world values -> the 0..127 integers the chip receives."""
    return np.clip(np.round(X / RANGES * 127), 0, 127).astype(np.int64)
