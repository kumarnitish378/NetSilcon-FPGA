"""
Train a NetSilcon-64x6 model from your own CSV table and write models/<name>/<name>.json.

The network shape is fixed by the hardware: 16 inputs -> 6 hidden layers of 64 -> 16 outputs.
You choose what the inputs and outputs mean.

    # classification: one target column with up to 16 classes
    python3 train_csv.py ../../data/pump_vibration.csv --name pump_health --target state

    # regression: up to 16 numeric target columns
    python3 train_csv.py flights.csv --name burn_rate --target fuel_g_per_min --regress

    # pick the input columns yourself (default: every column that is not a target, at most 16)
    python3 train_csv.py data.csv --name x --target label --inputs a,b,c,d

What it does:
  1. reads the CSV, splits it 80 % train / 10 % validation / 10 % test (fixed seed)
  2. scales every input to the chip's range 0..127 using the training data's min and max
     (or the ranges you give with --ranges ranges.json: {"column": [lo, hi], ...})
  3. trains the float network (numpy, Adam; softmax for classes, mean squared error for values)
  4. converts it to int8 weights, int16 biases and 7 shifts, bit-exact with model/ns64.py and
     the FPGA, and reports float vs int8 results on the test split it never trained on
  5. writes models/<name>/<name>.json (weights, CRC-32, input scaling, output meaning,
     1,000 golden test vectors) and models/<name>/README.md

Then: fpga/scripts/run_sim_model.sh models/<name>/<name>.json   (Verilog, no board)
      python ns64_host.py COM7 --load ../../models/<name>/<name>.json   (upload, ~2 s)
      python ns64_host.py COM7 --test                                    (bit-exact check)
      python app_example.py --model ../../models/<name>/<name>.json ...  (use it)

Decisions: for a classifier, the class is the largest of the first C outputs (C = number of
classes). Outputs C..15 are unused and always 0. For regression, output k is value_k scaled to
-1..+1 (times 127); the JSON stores the range to convert it back.
"""
import argparse
import csv
import datetime
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")          # NetSilcon-64x6/
sys.path.insert(0, HERE)
import ns64  # noqa: E402

SIZES = ns64.SIZES
NL = ns64.NL
ACC_LIMIT = (1 << (ns64.ACC_BITS - 1)) - 1


# ---------------------------------------------------------------- data
def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    head, body = [h.strip() for h in rows[0]], [r for r in rows[1:] if r and any(c.strip() for c in r)]
    cols = {h: [r[i].strip() for r in body] for i, h in enumerate(head)}
    return head, cols, len(body)


def as_float(name, vals):
    try:
        return np.array([float(v) for v in vals])
    except ValueError:
        sys.exit(f"column '{name}' is not numeric (example value: '{vals[0]}'). "
                 f"Only the classification target may hold text.")


# ---------------------------------------------------------------- float network
class MLP:
    def __init__(self, rng):
        self.W = [rng.normal(0, math.sqrt(2.0 / SIZES[l]), (SIZES[l], SIZES[l + 1])) for l in range(NL)]
        self.b = [np.full(SIZES[l + 1], 0.01 if l < NL - 1 else 0.0) for l in range(NL)]

    def forward(self, X):
        acts, a = [X], X
        for l in range(NL):
            z = a @ self.W[l] + self.b[l]
            a = np.maximum(z, 0) if l < NL - 1 else z
            acts.append(a)
        return a, acts

    def loss_grad(self, out, T, kind, n_out):
        """Returns (loss, d loss / d out). Only the first n_out outputs carry targets;
        the rest are pulled gently to 0 so they stay quiet."""
        g = np.zeros_like(out)
        if kind == "classify":
            z = out[:, :n_out] - out[:, :n_out].max(1, keepdims=True)
            p = np.exp(z)
            p /= p.sum(1, keepdims=True)
            loss = -np.log(p[np.arange(len(T)), T] + 1e-12).mean()
            p[np.arange(len(T)), T] -= 1
            g[:, :n_out] = p / len(T)
        else:
            e = out[:, :n_out] - T
            loss = (e * e).mean()
            g[:, :n_out] = 2 * e / e.size
        g[:, n_out:] = 0.02 * out[:, n_out:] / len(out)
        return loss, g

    def train(self, X, T, kind, n_out, epochs, rng, Xv=None, Tv=None, batch=256, lr=2e-3, log=print):
        params = self.W + self.b
        m = [np.zeros_like(p) for p in params]
        v = [np.zeros_like(p) for p in params]
        t, n = 0, len(X)
        best, best_params = None, None
        for ep in range(epochs):
            perm = rng.permutation(n)
            lr_ep = lr * 0.5 * (1 + math.cos(math.pi * ep / epochs))
            for i in range(0, n, batch):
                idx = perm[i:i + batch]
                out, acts = self.forward(X[idx])
                _, g = self.loss_grad(out, T[idx], kind, n_out)
                gW, gb = [None] * NL, [None] * NL
                for l in range(NL - 1, -1, -1):
                    gW[l] = acts[l].T @ g
                    gb[l] = g.sum(0)
                    if l:
                        g = (g @ self.W[l].T) * (acts[l] > 0)
                t += 1
                for k, (p, gr) in enumerate(zip(params, gW + gb)):
                    m[k] = 0.9 * m[k] + 0.1 * gr
                    v[k] = 0.999 * v[k] + 0.001 * gr * gr
                    p -= lr_ep * (m[k] / (1 - 0.9 ** t)) / (np.sqrt(v[k] / (1 - 0.999 ** t)) + 1e-8)
            if Xv is not None:
                vl, _ = self.loss_grad(self.forward(Xv)[0], Tv, kind, n_out)
                if best is None or vl < best:                       # keep the best validation epoch
                    best, best_params = vl, [p.copy() for p in params]
                if ep % 10 == 0 or ep == epochs - 1:
                    log(f"  epoch {ep:3d}  validation loss {vl:.4f}")
        if best_params is not None:
            for p, q in zip(params, best_params):
                p[...] = q


# ---------------------------------------------------------------- int8 conversion (bit-exact with ns64)
def quantize(mlp, Xq_calib, out_scale, n_out):
    """Float network (input = q/127) -> ns64.Net. Hidden layers use the full int8 weight range and
    the smallest shift that keeps 99.99 % of activations in 0..127. The output layer is scaled so
    chip output = out_scale x float output, with outputs n_out..15 forced to exactly 0."""
    S_prev, a = 127.0, Xq_calib.astype(np.int64)
    W_int, B_int, S = [], [], []
    for l in range(NL):
        Wf, bf = mlp.W[l].T.copy(), mlp.b[l].copy()
        last = l == NL - 1
        if last:
            Wf[n_out:], bf[n_out:] = 0, 0
            s = ns64.SHIFT_MAX
            while s > 0:
                K = out_scale * (1 << s) / S_prev
                w = np.clip(np.round(Wf * K), -128, 127).astype(np.int64)
                b = np.round(K * S_prev * bf)
                acc = a @ w.T + np.clip(b, -32768, 32767).astype(np.int64)
                if (np.abs(Wf).max() * K <= 127 and np.abs(b).max() <= 32767
                        and np.abs(acc).max() < ACC_LIMIT // 2):
                    break
                s -= 1
            b = np.clip(b, -32768, 32767).astype(np.int64)
            acc = a @ w.T + b
        else:
            K = 127.0 / max(np.abs(Wf).max(), 1e-9)
            b_real = K * S_prev * bf
            while np.abs(b_real).max() > 32767:            # bias must fit int16
                K *= 0.5
                b_real = K * S_prev * bf
            w = np.clip(np.round(Wf * K), -128, 127).astype(np.int64)
            b = np.round(b_real).astype(np.int64)
            acc = np.maximum(a @ w.T + b, 0)
            top = np.quantile(acc, 0.9999) if acc.size else 1
            s = 0
            while s < ns64.SHIFT_MAX and (top + (1 << s >> 1)) / (1 << s) > 127:
                s += 1
            S_prev = K * S_prev / (1 << s)
        W_int.append(w)
        B_int.append(b)
        S.append(int(s))
        rnd = (1 << s >> 1)
        a = np.clip((acc + rnd) >> s, -128 if last else 0, 127)
    return ns64.Net(W_int, B_int, S)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="train a NetSilcon-64x6 model from a CSV table")
    ap.add_argument("csv")
    ap.add_argument("--name", required=True, help="model name: models/<name>/<name>.json")
    ap.add_argument("--target", required=True, help="target column(s), comma separated")
    ap.add_argument("--regress", action="store_true", help="numeric targets (default: one class column)")
    ap.add_argument("--inputs", help="input columns, comma separated (default: all others, max 16)")
    ap.add_argument("--ranges", help="JSON file {column: [lo, hi]} to fix input/target ranges")
    ap.add_argument("--title", help="one-line description stored in the model file")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    if not a.name.replace("_", "").replace("-", "").isalnum():
        sys.exit("--name: use letters, digits, '_' or '-' only")

    out_dir = os.path.join(ROOT, "models", a.name)
    os.makedirs(out_dir, exist_ok=True)
    report = []

    def log(s=""):
        print(s)
        report.append(s)

    head, cols, n = read_csv(a.csv)
    targets = [t.strip() for t in a.target.split(",")]
    for t in targets:
        if t not in cols:
            sys.exit(f"target column '{t}' not found. Columns: {', '.join(head)}")
    inputs = [c.strip() for c in a.inputs.split(",")] if a.inputs else [h for h in head if h not in targets]
    missing = [c for c in inputs if c not in cols]
    if missing:
        sys.exit(f"input column(s) not found: {missing}")
    if len(inputs) > 16:
        sys.exit(f"{len(inputs)} input columns, the chip has 16. Choose with --inputs.")
    kind = "regress" if a.regress else "classify"
    if kind == "classify" and len(targets) != 1:
        sys.exit("classification uses exactly one target column")
    if kind == "regress" and len(targets) > 16:
        sys.exit("at most 16 regression targets")
    ranges = json.load(open(a.ranges)) if a.ranges else {}
    log(f"NetSilcon-64x6 train_csv  {datetime.date.today()}  data {os.path.basename(a.csv)}: {n} rows")
    log(f"inputs ({len(inputs)} of 16): {', '.join(inputs)}")

    # ---- inputs -> 0..127
    rng = np.random.default_rng(a.seed)
    perm = rng.permutation(n)
    n_te = n_va = max(1, n // 10)
    te, va, tr = perm[:n_te], perm[n_te:n_te + n_va], perm[n_te + n_va:]
    Xr = np.column_stack([as_float(c, cols[c]) for c in inputs])
    in_meta = []
    Xq = np.zeros((n, 16), dtype=np.int64)              # unused inputs stay 0
    for k, c in enumerate(inputs):
        lo, hi = ranges.get(c, (float(Xr[tr, k].min()), float(Xr[tr, k].max())))
        if hi <= lo:
            hi = lo + 1.0
        Xq[:, k] = np.clip(np.round((Xr[:, k] - lo) / (hi - lo) * 127), 0, 127)
        in_meta.append(dict(index=k, name=c, range=[round(lo, 6), round(hi, 6)]))
    X = Xq / 127.0

    # ---- targets
    if kind == "classify":
        labels = cols[targets[0]]
        classes = sorted(set(labels))
        if len(classes) > 16:
            sys.exit(f"{len(classes)} classes, the chip has 16 outputs")
        T = np.array([classes.index(v) for v in labels])
        n_out = len(classes)
        log(f"target '{targets[0]}': {n_out} classes {classes}")
        counts = {c: int((T[tr] == i).sum()) for i, c in enumerate(classes)}
        log(f"training rows per class: {counts}")
    else:
        Yr = np.column_stack([as_float(t, cols[t]) for t in targets])
        out_meta = []
        T = np.zeros_like(Yr)
        for k, t in enumerate(targets):
            lo, hi = ranges.get(t, (float(Yr[tr, k].min()), float(Yr[tr, k].max())))
            if hi <= lo:
                hi = lo + 1.0
            T[:, k] = np.clip((Yr[:, k] - lo) / (hi - lo) * 2 - 1, -1, 1)
            out_meta.append(dict(index=k, name=t, range=[round(lo, 6), round(hi, 6)]))
        n_out = len(targets)
        log(f"targets: {', '.join(targets)} (each scaled to -1..+1)")

    # ---- train
    log(f"training: {len(tr)} rows, validation {len(va)}, test {len(te)} (never used for training)")
    mlp = MLP(rng)
    mlp.train(X[tr], T[tr], kind, n_out, a.epochs, rng, X[va], T[va], log=log)
    fz = mlp.forward(X[te])[0][:, :n_out]

    # ---- int8
    if kind == "classify":
        zc = np.abs(mlp.forward(X[tr][:20000])[0][:, :n_out])
        out_scale = 110.0 / max(np.quantile(zc, 0.999), 1e-6)   # logits -> int8 with headroom
    else:
        out_scale = 127.0                                          # value -1..+1 -> -127..127
    net = quantize(mlp, Xq[tr][:20000], out_scale, n_out)
    qy = net.forward(Xq[te])
    log(f"shifts {net.S}   CRC-32 {net.crc32():08X}")

    result = {}
    if kind == "classify":
        acc_f = float((fz.argmax(1) == T[te]).mean())
        pq = qy[:, :n_out].argmax(1)
        acc_q = float((pq == T[te]).mean())
        agree = float((pq == fz.argmax(1)).mean())
        log(f"test accuracy: float {acc_f * 100:.1f} %   int8 (= FPGA) {acc_q * 100:.1f} %   "
            f"int8 agrees with float on {agree * 100:.1f} % of rows")
        log("confusion (rows = true class, columns = int8 prediction):")
        log("  " + " ".join(f"{c[:10]:>10s}" for c in classes))
        for i, c in enumerate(classes):
            log(f"  " + " ".join(f"{int(((T[te] == i) & (pq == j)).sum()):10d}" for j in range(n_out))
                + f"   {c}")
        result = dict(test_accuracy_float=round(acc_f, 4), test_accuracy_int8=round(acc_q, 4))
    else:
        for k, m in enumerate(out_meta):
            lo, hi = m["range"]
            to_real = lambda u: lo + (u + 1) / 2 * (hi - lo)   # noqa: E731
            real = Yr[te, k]
            mae_f = float(np.abs(to_real(fz[:, k]) - real).mean())
            mae_q = float(np.abs(to_real(qy[:, k] / 127.0) - real).mean())
            log(f"test MAE '{m['name']}': float {mae_f:.4g}   int8 (= FPGA) {mae_q:.4g}   (range {lo:g}..{hi:g})")
            result[f"test_mae_int8_{m['name']}"] = round(mae_q, 6)
    log(f"unused outputs y{n_out}..y15: max |y| = {int(np.abs(qy[:, n_out:]).max()) if n_out < 16 else 0}")

    # ---- golden vectors: edge cases + real test rows, outputs from the bit-exact model
    edge = np.array([[0] * 16, [127] * 16, [64] * 16] + [[127 if j < len(inputs) else 0 for j in range(16)]])
    Xg = np.vstack([edge, Xq[te][:996]]).astype(np.int64)
    Yg = net.forward(Xg)
    ok = all(net.forward_slow(x) == y.tolist() for x, y in zip(Xg[:50], Yg[:50]))
    log(f"golden vectors: {len(Xg)}  (independent slow model agrees on the first 50: {'yes' if ok else 'NO'})")

    extra = {
        "kind": "classification" if kind == "classify" else "regression",
        "inputs": in_meta + [dict(index=k, name=f"unused{k}", range=[0, 1]) for k in range(len(inputs), 16)],
        "input_scaling": "q = clip(round((value - lo) / (hi - lo) * 127), 0, 127)",
        "trained_with": "python/model/train_csv.py",
        "data": dict(file=os.path.basename(a.csv), rows=n, train=len(tr), validation=len(va), test=len(te),
                     seed=a.seed, epochs=a.epochs),
        "result": result,
        "test_vectors": [{"x": x.tolist(), "y": y.tolist()} for x, y in zip(Xg, Yg)],
    }
    if kind == "classify":
        extra["outputs"] = classes + [f"unused{k}" for k in range(n_out, 16)]
        extra["classes"] = classes
        extra["decision"] = f"class = argmax(y[0..{n_out - 1}])"
    else:
        extra["outputs"] = [m["name"] for m in out_meta] + [f"unused{k}" for k in range(n_out, 16)]
        extra["targets"] = out_meta
        extra["decision"] = "value_k = lo + (y_k / 127 + 1) / 2 * (hi - lo)"
    title = a.title or f"{a.name} ({len(inputs)} inputs -> {n_out} {'classes' if kind == 'classify' else 'values'})"
    d = ns64.to_json(net, a.name, title, extra)
    path = os.path.join(out_dir, f"{a.name}.json")
    with open(path, "w") as f:
        json.dump(d, f, separators=(",", ":"))
    with open(os.path.join(out_dir, "README.md"), "w") as f:
        f.write(f"# {a.name}\n\n{title}\n\nTrained with `python/model/train_csv.py` on `{os.path.basename(a.csv)}`.\n\n"
                f"CRC-32 `{d['crc32']}` · shifts `{' '.join(map(str, net.S))}`\n\n```\n" + "\n".join(report) + "\n```\n")
    log(f"saved {os.path.relpath(path, ROOT)}  (and README.md)")


if __name__ == "__main__":
    main()
