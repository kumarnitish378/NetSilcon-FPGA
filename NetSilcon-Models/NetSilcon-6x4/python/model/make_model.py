"""Build a loadable model file for NetSilcon-6x4:  models/<name>/<name>.json

    python make_model.py irrigation     train + quantize the irrigation app
    python make_model.py motor_fault    package the BUILT-IN motor model from gen/
                                        (no retraining, so its CRC matches the bitstream)

The .json holds everything the host needs:
  weights (144 int8), biases (26 int16), shifts (5), the CRC-16 of the 201-byte
  image the chip receives, input names/units/ranges, output labels, demo
  scenarios and golden test vectors computed with the bit-exact integer model.

Upload it to the running chip with:
    python ../host/netsilcon_host.py COM7 --load ../../models/irrigation/irrigation.json
"""
import json
import os
import sys

import numpy as np

from apps import APPS

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")          # NetSilcon-6x4/
GEN = os.path.join(ROOT, "fpga", "gen")
OUT = os.path.join(ROOT, "models")
SIZES = [4, 6, 6, 6, 6, 2]
L = 5
ACC_MAX = (1 << 19) - 1


# --------------------------------------------------------------------------- shared helpers
def crc16(data, crc=0xFFFF):
    """CRC-16/CCITT-FALSE, same as board/ns_loader.v"""
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def image(w, b, sh):
    """The 201 bytes the chip receives: 144 weights, 26 biases (low byte first), 5 shifts."""
    out = bytes(v & 0xFF for v in w)
    for v in b:
        out += bytes([v & 0xFF, (v >> 8) & 0xFF])
    return out + bytes(sh)


def int_forward(Wq, bq, shifts, xq):
    """Bit-exact integer model of rtl/nn_layer.v. xq: (n, 4) ints 0..127."""
    a = np.asarray(xq, dtype=np.int64)
    for l in range(L):
        acc = a @ Wq[l].T + bq[l]
        assert np.abs(acc).max() <= ACC_MAX, f"layer {l + 1} overflows the 20-bit accumulator"
        hidden = l < L - 1
        if hidden:
            acc = np.maximum(acc, 0)
        s = shifts[l]
        y = (acc + ((1 << (s - 1)) if s else 0)) >> s
        a = np.clip(y, 0, 127) if hidden else np.clip(y, -128, 127)
    return a


def to_q(X, ranges):
    return np.clip(np.round(X / np.asarray(ranges) * 127), 0, 127).astype(np.int64)


def split(w_all, b_all):
    Wq, bq, wi, bi = [], [], 0, 0
    for l in range(L):
        n_in, n_out = SIZES[l], SIZES[l + 1]
        Wq.append(np.array(w_all[wi:wi + n_in * n_out], dtype=np.int64).reshape(n_out, n_in))
        bq.append(np.array(b_all[bi:bi + n_out], dtype=np.int64))
        wi += n_in * n_out
        bi += n_out
    return Wq, bq


# --------------------------------------------------------------------------- quantization (same method as quantize.py)
def quantize(Wf, bf, xcal, exact_output=False):
    """exact_output=True (regression): the last layer is scaled so that chip output = value * 127."""
    s_in = 1.0 / 127.0
    Wq, bq, shifts = [], [], []
    a = xcal.astype(np.int64)
    for l in range(L):
        s_w = np.abs(Wf[l]).max() / 127.0
        if exact_output and l == L - 1:
            # need s_in * s_w * 2^s = 1/127 ; pick the largest s that keeps |W| <= 127
            s_fix = int(np.floor(np.log2(1.0 / (np.abs(Wf[l]).max() * s_in))))
            s_fix = min(max(s_fix, 0), 15)
            s_w = 1.0 / (127.0 * s_in * 2 ** s_fix)
        W = np.clip(np.round(Wf[l] / s_w), -127, 127).astype(np.int64)
        b = np.round(bf[l] / (s_in * s_w)).astype(np.int64)
        assert np.abs(b).max() <= 32767, f"layer {l + 1} bias does not fit int16"
        acc = a @ W.T + b
        hidden = l < L - 1
        # scale for 99.5 % of real inputs; the rare extremes clamp at 127 (like TFLite calibration)
        # output layer: 90th percentile -> typical scores use the full int8 range; very
        # confident answers saturate at +-127, which never changes the decision
        peak = np.percentile(np.maximum(acc, 0), 99.5) if hidden else np.percentile(np.abs(acc), 90)
        s = max(0, int(np.ceil(np.log2(max(peak, 1) / 127.0))))
        if exact_output and l == L - 1:
            s = s_fix
        assert s <= 15, "shift does not fit 4 bits"
        Wq.append(W); bq.append(b); shifts.append(s)
        y = ((np.maximum(acc, 0) if hidden else acc) + ((1 << (s - 1)) if s else 0)) >> s
        a = np.clip(y, 0, 127) if hidden else np.clip(y, -128, 127)
        s_in = s_in * s_w * (2 ** s)
    return Wq, bq, shifts


def train_regression(X, Y, epochs=600, lr=3e-3, batch=128, seed=42):
    """Same network and Adam optimiser as train.py, but mean-squared-error on 2 continuous outputs."""
    rng = np.random.default_rng(seed)
    Ws = [rng.normal(0, np.sqrt(2.0 / SIZES[i]), (SIZES[i + 1], SIZES[i])) for i in range(L)]
    bs = [np.full(SIZES[i + 1], 0.05) for i in range(L)]
    params = Ws + bs
    m = [np.zeros_like(p) for p in params]
    v = [np.zeros_like(p) for p in params]
    t = 0
    for ep in range(epochs):
        idx = rng.permutation(len(X))
        for s0 in range(0, len(X), batch):
            bi = idx[s0:s0 + batch]
            acts, pre = [X[bi]], []
            a = X[bi]
            for l in range(L):
                z = a @ Ws[l].T + bs[l]
                pre.append(z)
                a = z if l == L - 1 else np.maximum(z, 0)
                acts.append(a)
            g = 2 * (a - Y[bi]) / len(bi)
            gW, gb = [None] * L, [None] * L
            for l in reversed(range(L)):
                gW[l] = g.T @ acts[l]
                gb[l] = g.sum(0)
                if l > 0:
                    g = (g @ Ws[l]) * (pre[l - 1] > 0)
            t += 1
            lr_t = lr * (0.1 if ep > epochs * 0.8 else 1.0)          # fine-tune at the end
            for i, (pp, gg) in enumerate(zip(params, gW + gb)):
                m[i] = 0.9 * m[i] + 0.1 * gg
                v[i] = 0.999 * v[i] + 0.001 * gg * gg
                pp -= lr_t * (m[i] / (1 - 0.9 ** t)) / (np.sqrt(v[i] / (1 - 0.999 ** t)) + 1e-8)
        if ep % 100 == 0 or ep == epochs - 1:
            print(f"epoch {ep:4d}  mean abs error {np.abs(float_net(Ws, bs, X) - Y).mean():.4f}")
    return Ws, bs


def float_net(Ws, bs, x):
    a = x
    for l in range(L):
        z = a @ Ws[l].T + bs[l]
        a = z if l == L - 1 else np.maximum(z, 0)
    return a


def rover_action(y, stop=0.08, turn=0.25):
    """(speed, steer) in -1..1 -> action name, used for the agreement score."""
    sp, st = y[..., 0], y[..., 1]
    move = np.where(np.abs(sp) < stop, "STOP", np.where(sp > 0, "FWD", "REV"))
    side = np.where(np.abs(st) < turn, "", np.where(st > 0, "-R", "-L"))
    return np.where(move == "STOP", "STOP", np.char.add(move.astype(str), side.astype(str)))


def from_gen():
    s8 = lambda v: v - 256 if v > 127 else v
    s16 = lambda v: v - 65536 if v > 32767 else v
    w = [s8(int(l, 16)) for l in open(os.path.join(GEN, "weights.mem")) if l.strip()]
    b = [s16(int(l, 16)) for l in open(os.path.join(GEN, "biases.mem")) if l.strip()]
    import re
    sh = [int(m) for m in re.findall(r"SHIFT\d\s*=\s*(\d+)", open(os.path.join(GEN, "netsilcon_params.vh")).read())]
    return w, b, sh


# --------------------------------------------------------------------------- main
def build(name):
    app = APPS[name]
    ranges = [i["range"] for i in app["inputs"]]
    Xte, yte = app["make"](4000, seed=2)
    xte = to_q(Xte, ranges)

    regression = app.get("kind") == "regression"
    if regression:
        Xtr, Ytr = app["make"](30000, seed=1)
        xtr = to_q(Xtr, ranges)
        # small networks depend on their random start: train 3, keep the best on held-out data
        Xva, Yva = app["make"](4000, seed=3)
        xva = to_q(Xva, ranges) / 127.0
        best = None
        for sd in (42, 7, 123):
            print(f"--- training run, seed {sd}")
            Ws_, bs_ = train_regression(xtr / 127.0, Ytr, epochs=1200, seed=sd)
            e = np.abs(float_net(Ws_, bs_, xva) - Yva).mean()
            print(f"    validation mean abs error {e:.4f}")
            if best is None or e < best[0]:
                best = (e, Ws_, bs_)
        _, Ws, bs = best
        print(f"Float model mean abs error: {np.abs(float_net(Ws, bs, xte / 127.0) - yte).mean():.4f}")
        Wq, bq, shifts = quantize(Ws, bs, xtr, exact_output=True)
        w_all = [int(v) for W in Wq for v in W.reshape(-1)]
        b_all = [int(v) for b in bq for v in b]
    elif name == "motor_fault":
        w_all, b_all, shifts = from_gen()                 # exactly the built-in bitstream model
        Wq, bq = split(w_all, b_all)
    else:
        sys.path.insert(0, HERE)
        from train import train, forward
        Xtr, ytr = app["make"](20000, seed=1)
        xtr = to_q(Xtr, ranges)
        Ws, bs = train(xtr / 127.0, ytr)
        acc_f = (forward(Ws, bs, xte / 127.0)[0][-1].argmax(1) == yte).mean()
        print(f"Float model test accuracy: {acc_f * 100:.2f}%")
        Wq, bq, shifts = quantize(Ws, bs, xtr)
        w_all = [int(v) for W in Wq for v in W.reshape(-1)]
        b_all = [int(v) for b in bq for v in b]

    out = int_forward(Wq, bq, shifts, xte)
    if regression:
        # "accuracy" = same driving action as the rules; also report the mean error in % of full scale
        acc_i = (rover_action(out / 127.0) == rover_action(yte)).mean()
        mae = np.abs(out / 127.0 - yte).mean(0)
        print(f"Int8 chip model: action agreement {acc_i * 100:.2f}%  mean abs error "
              f"speed {mae[0] * 100:.1f}%  steering {mae[1] * 100:.1f}% of full scale")
    else:
        acc_i = ((out[:, 1] > out[:, 0]).astype(int) == yte).mean()

    rng = np.random.default_rng(7)
    vin = np.concatenate([xte[:512], [[0, 0, 0, 0], [127] * 4], rng.integers(0, 128, (62, 4))])
    vout = int_forward(Wq, bq, shifts, vin)
    img = image(w_all, b_all, shifts)
    model = dict(
        format="netsilcon-6x4 model v1",
        name=name, title=app["title"], kind=app.get("kind", "classifier"),
        inputs=app["inputs"], outputs=app["outputs"],
        accuracy_int8=round(float(acc_i), 4),
        weights=[int(v) for v in w_all], biases=[int(v) for v in b_all], shifts=[int(s) for s in shifts],
        crc16=f"{crc16(img):04X}",
        demo=app["demo"],
        tests=[[int(v) for v in x] + [int(y[0]), int(y[1])] for x, y in zip(vin, vout)],
    )
    os.makedirs(os.path.join(OUT, name), exist_ok=True)          # one folder per application
    path = os.path.join(OUT, name, f"{name}.json")
    with open(path, "w") as fh:
        json.dump(model, fh, indent=1)
    print(f"{app['title']}: int8 accuracy {acc_i * 100:.2f}%  shifts {shifts}  CRC {model['crc16']}")
    print(f"Saved {os.path.normpath(path)}  ({len(img)}-byte image, {len(vin)} test vectors)")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in APPS:
        sys.exit(f"usage: python make_model.py <{'|'.join(APPS)}>")
    build(sys.argv[1])
