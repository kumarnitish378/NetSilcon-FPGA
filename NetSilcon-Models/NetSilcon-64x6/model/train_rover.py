"""
Train the NetSilcon-64x6 rover controller and write models/rover/rover.json (bit-exact int8).

    python3 train_rover.py                 data from random worlds -> train -> quantize -> save
    python3 train_rover.py --dagger 2      + 2 rounds: the network drives in random training worlds,
                                           the teacher labels every situation it met, retrain

Network 16 -> 64 -> 64 -> 64 -> 64 -> 64 -> 64 -> 16 (ReLU), fixed by the hardware.
    inputs : 16 LiDAR sectors (22.5 deg each), distance from the body edge 0..4 m -> q = 0..127
    outputs: y0 = speed x 127, y1 = steering x 127 (value -1..+1); y2..y15 = 0 (unused)
    target : the teacher rules in rover_sim/rover64.py (smooth, 16 sectors)
Training data comes ONLY from randomly generated worlds (seeds 0..99999). The four standard test
worlds (room, corridor, clutter, corner_trap) and the "unseen" test worlds (seeds 900000+) are
never used for training.

Quantization (bit-exact with model/ns64.py and the FPGA): ReLU networks are scale-free per layer,
so each layer uses the full int8 range for its weights (K = 127 / max|W|), biases become int16, and
the per-layer shift s is the smallest that keeps 99.99 % of the activations in 0..127. The last
layer is scaled so the chip's output is exactly value x 127.
"""
import argparse
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "rover_sim"))
import ns64  # noqa: E402
import rover64 as r6  # noqa: E402
import rover_sim as rs  # noqa: E402

SIZES = ns64.SIZES
OUT_DIR = os.path.join(ROOT, "models", "rover")
VISITED = os.path.join(ROOT, "rover_sim", "visited64.npy")


# ---------------------------------------------------------------- data
def random_poses(n_worlds, per_world, seed0, rng):
    """Real 16-sector scans at random collision-free poses in random worlds (near obstacles too)."""
    X = []
    for w in range(n_worlds):
        segs, circ, (W, H) = r6.random_world(seed0 + w)
        got = 0
        for _ in range(per_world * 20):
            x, y, th = rng.uniform(0.3, W - 0.3), rng.uniform(0.3, H - 0.3), rng.uniform(-math.pi, math.pi)
            if rs.collides(x, y, th, segs, circ):
                continue
            clear = rs.scan(x, y, th, segs, circ) - rs._EXT
            X.append(r6.sectors16(clear))
            got += 1
            if got == per_world:
                break
    return np.array(X)


def make_dataset(rng, n_worlds=600, per_world=250):
    t = time.time()
    X = random_poses(n_worlds, per_world, 0, rng)
    print(f"random-world poses: {len(X)} scans from {n_worlds} worlds ({time.time() - t:.0f} s)")
    if os.path.exists(VISITED):
        V = np.load(VISITED)
        print(f"plus {len(V)} situations the network met while driving (DAgger)")
        X = np.vstack([X, V])
    return X


def to_q(D):
    return np.clip(np.round(np.minimum(D, r6.RANGE) / r6.RANGE * 127), 0, 127)


# ---------------------------------------------------------------- float network (numpy, Adam)
class MLP:
    def __init__(self, rng):
        self.W, self.b = [], []
        for l in range(ns64.NL):
            n_in, n_out = SIZES[l], SIZES[l + 1]
            self.W.append(rng.normal(0, math.sqrt(2.0 / n_in), (n_in, n_out)))
            self.b.append(np.full(n_out, 0.01 if l < ns64.NL - 1 else 0.0))

    def forward(self, X):
        acts = [X]
        a = X
        for l in range(ns64.NL):
            z = a @ self.W[l] + self.b[l]
            a = np.maximum(z, 0) if l < ns64.NL - 1 else z
            acts.append(a)
        return a, acts

    def train(self, X, Y, epochs=60, batch=256, lr=2e-3, rng=None, wsteer=1.5):
        params = self.W + self.b
        m = [np.zeros_like(p) for p in params]
        v = [np.zeros_like(p) for p in params]
        t = 0
        n = len(X)
        lw = np.zeros(SIZES[-1])
        lw[0], lw[1] = 1.0, wsteer                     # only y0, y1 carry targets; y2..y15 -> 0
        lw[2:] = 0.05
        T = np.zeros((n, SIZES[-1]))
        T[:, :2] = Y
        for ep in range(epochs):
            perm = rng.permutation(n)
            lr_ep = lr * (0.5 * (1 + math.cos(math.pi * ep / epochs)))       # cosine schedule
            tot = 0.0
            for i in range(0, n, batch):
                idx = perm[i:i + batch]
                out, acts = self.forward(X[idx])
                err = (out - T[idx]) * lw
                tot += float((err * (out - T[idx])).sum())
                g = 2 * err / len(idx)
                grads_W, grads_b = [None] * ns64.NL, [None] * ns64.NL
                for l in range(ns64.NL - 1, -1, -1):
                    grads_W[l] = acts[l].T @ g
                    grads_b[l] = g.sum(0)
                    if l:
                        g = (g @ self.W[l].T) * (acts[l] > 0)
                grads = grads_W + grads_b
                t += 1
                for k, (p, gr) in enumerate(zip(params, grads)):
                    m[k] = 0.9 * m[k] + 0.1 * gr
                    v[k] = 0.999 * v[k] + 0.001 * gr * gr
                    p -= lr_ep * (m[k] / (1 - 0.9 ** t)) / (np.sqrt(v[k] / (1 - 0.999 ** t)) + 1e-8)
            if ep % 10 == 0 or ep == epochs - 1:
                print(f"  epoch {ep:3d}  loss {tot / n:.5f}")


# ---------------------------------------------------------------- quantization (bit-exact with ns64)
def quantize(mlp, Xq_calib):
    """Float network (input = q / 127) -> ns64.Net with int8 weights, int16 biases, shifts."""
    S_prev = 127.0                              # activation scale of the input: q = x * 127
    a = Xq_calib.astype(np.int64)
    W_int, B_int, S = [], [], []
    for l in range(ns64.NL):
        Wf, bf = mlp.W[l].T, mlp.b[l]          # (n_out, n_in)
        last = l == ns64.NL - 1
        if not last:
            K = 127.0 / max(np.abs(Wf).max(), 1e-9)
            w = np.clip(np.round(Wf * K), -128, 127).astype(np.int64)
            b_real = K * S_prev * bf
            # if a bias would not fit int16, use smaller weights
            while np.abs(b_real).max() > 32767:
                K *= 0.5
                w = np.clip(np.round(Wf * K), -128, 127).astype(np.int64)
                b_real = K * S_prev * bf
            b = np.round(b_real).astype(np.int64)
            acc = np.maximum(a @ w.T + b, 0)
            top = np.quantile(acc, 0.9999) if acc.size else 1
            s = 0
            while s < ns64.SHIFT_MAX and (top + (1 << s >> 1)) / (1 << s) > 127:
                s += 1
            S_prev = K * S_prev / (1 << s)
        else:
            # output scale must be exactly 127 (value x 127): K = 127 * 2^s / S_prev, |w| <= 127
            s = ns64.SHIFT_MAX
            while s > 0 and np.abs(Wf).max() * 127 * (1 << s) / S_prev > 127:
                s -= 1
            K = 127.0 * (1 << s) / S_prev
            w = np.clip(np.round(Wf * K), -128, 127).astype(np.int64)
            b = np.clip(np.round(K * S_prev * bf), -32768, 32767).astype(np.int64)
            w[2:], b[2:] = 0, 0                 # y2..y15 are not used: exactly 0 on the chip
            acc = a @ w.T + b
        W_int.append(w)
        B_int.append(b)
        S.append(s)
        rnd = (1 << s >> 1)
        a = np.clip((acc + rnd) >> s, 0 if not last else -128, 127)
    return ns64.Net(W_int, B_int, S)


def report(name, pred, Y):
    """pred, Y: (n, 2) values -1..+1. Mean abs error and 'action agreement' like the 6x4 report:
    same sign of speed (forward / reverse / ~stop) and steering within 0.2."""
    e = np.abs(pred - Y)
    agree = (np.sign(np.round(pred[:, 0] * 5)) == np.sign(np.round(Y[:, 0] * 5))) & (e[:, 1] < 0.2)
    print(f"  {name:28s} speed MAE {e[:, 0].mean():.3f}  steering MAE {e[:, 1].mean():.3f}  "
          f"action agreement {agree.mean() * 100:5.1f} %")
    return float(agree.mean())


# ---------------------------------------------------------------- DAgger: situations met while driving
def dagger(net_json, rounds_worlds, rng):
    chip = r6.Chip64(model=net_json)
    met = []
    for k in range(rounds_worlds):
        r6.drive(chip, f"rand{int(rng.integers(0, 99999))}", seconds=60, seed=int(rng.integers(0, 1000)),
                 unstick=True, collect=met)
    met = np.array(met)
    old = np.load(VISITED) if os.path.exists(VISITED) else np.zeros((0, 16))
    allv = np.vstack([old, met])
    np.save(VISITED, allv)
    print(f"DAgger: drove {rounds_worlds} random training worlds, {len(met)} new situations (total {len(allv)})")


def build(args):
    rng = np.random.default_rng(args.seed)
    D = make_dataset(rng, args.worlds, args.per_world)
    Y = r6.teacher(D)
    Xq = to_q(D)
    X = Xq / 127.0
    n_test = len(X) // 10
    perm = rng.permutation(len(X))
    te, tr = perm[:n_test], perm[n_test:]
    mlp = MLP(rng)
    print(f"training on {len(tr)} samples, testing on {len(te)}")
    mlp.train(X[tr], Y[tr], epochs=args.epochs, rng=rng)
    fpred = mlp.forward(X[te])[0][:, :2]
    report("float network vs teacher", fpred, Y[te])
    net = quantize(mlp, Xq[tr][:20000])
    qout = net.forward(Xq[te].astype(np.int64))
    acc_q = report("int8 (FPGA) vs teacher", qout[:, :2] / 127.0, Y[te])
    report("int8 vs float network", qout[:, :2] / 127.0, fpred)
    print(f"  shifts {net.S}   unused outputs y2..y15: max |y| = {int(np.abs(qout[:, 2:]).max())}")
    # golden vectors: 1000 real situations from the test split + edge cases
    edge = np.array([[0] * 16, [127] * 16] + [[127] * 7 + [10, 10] + [127] * 7] +
                    [[20] * 16] + [[127 if k in (3, 4, 5) else 15 for k in range(16)]])
    Xg = np.vstack([edge, Xq[te][:995]]).astype(np.int64)
    Yg = net.forward(Xg)
    d = ns64.to_json(net, "rover", "Rover controller (16 LiDAR sectors -> speed, steering)", {
        "kind": "regression",
        "inputs": [dict(name=f"S{k:02d}", unit="m", range=r6.RANGE,
                        angle_deg=[-180 + 22.5 * k, -180 + 22.5 * (k + 1)]) for k in range(16)],
        "outputs": ["speed", "steering"] + [f"unused{k}" for k in range(2, 16)],
        "teacher": "rover_sim/rover64.py teacher()",
        "training": dict(samples=int(len(tr)), worlds=f"random worlds seeds 0..99999 ({args.worlds} for poses)",
                         dagger_states=int(len(D) - args.worlds * args.per_world) if os.path.exists(VISITED) else 0,
                         epochs=args.epochs),
        "accuracy_int8": round(acc_q, 4),
        "test_vectors": [{"x": x.tolist(), "y": y.tolist()} for x, y in zip(Xg, Yg)],
    })
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "rover.json")
    with open(path, "w") as f:
        json.dump(d, f, separators=(",", ":"))
    print(f"saved {os.path.relpath(path, ROOT)}  CRC-32 {d['crc32']}  ({len(Xg)} golden vectors)")
    return d


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--worlds", type=int, default=600)
    ap.add_argument("--per-world", type=int, default=250)
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--seed", type=int, default=64)
    ap.add_argument("--dagger", type=int, default=0, help="rounds of drive-and-relabel")
    ap.add_argument("--dagger-worlds", type=int, default=40)
    ap.add_argument("--fresh", action="store_true", help="delete the collected DAgger situations first")
    a = ap.parse_args()
    if a.fresh and os.path.exists(VISITED):
        os.remove(VISITED)
    d = build(a)
    for r in range(a.dagger):
        print(f"=== DAgger round {r + 1}")
        dagger(d, a.dagger_worlds, np.random.default_rng(1000 + r))
        d = build(a)
