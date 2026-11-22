"""
Build the hardware test models for NetSilcon-64x6 and the files the Verilog needs.

    python make_synthetic.py            (no arguments; fixed seeds, same output every time)

Models (models/*.json, each with its CRC-32 and golden vectors):
    synthetic  random int8 weights, biases and shifts CALIBRATED so most activations land
               between 0 and 127 (a random network would otherwise sit at 0 or 127 and test
               very little). Built into the bitstream (block-RAM bank 0).
    stress     extreme numbers: weights only -128/+127, biases at the int16 limits, shifts
               0..23. Tests the accumulator width, the clamps and the shifter range.

Files in gen/:
    wmem_00.mem .. wmem_31.mem   initial contents of the 32 weight RAMs (built-in = synthetic)
    tb/wmem_XX.mem               testbench version: bank 0 synthetic, bank 1 stress
    ns64_builtin.vh              built-in shifts and CRC-32
    test_in.mem / test_out.mem   synthetic golden vectors (one vector per line, x0 = lowest byte)
    stress_in.mem / stress_out.mem
    num_vectors.vh
    model_report.txt             activation statistics per layer, self-check results
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ns64  # noqa: E402
from ns64 import NL, SIZES, Net  # noqa: E402

ROOT = os.path.join(HERE, "..")
GEN = os.path.join(ROOT, "gen")
MODELS = os.path.join(ROOT, "models")
N_VEC = 1000
report = []


def say(s=""):
    print(s)
    report.append(s)


def make_inputs(rng, n):
    """Edge cases first, then a mix of uniform, sparse and low/high-biased random inputs."""
    edge = [np.zeros(16), np.full(16, 127), np.tile([0, 127], 8), np.tile([127, 0], 8),
            np.arange(16) * 8 + 7, 127 - np.arange(16) * 8]
    for k in range(4):
        v = np.zeros(16)
        v[k * 5] = 127
        edge.append(v)
    edge = np.array(edge, dtype=np.int64)
    m = n - len(edge)
    u = rng.integers(0, 128, size=(m // 2, 16))
    sp = rng.integers(0, 128, size=(m // 4, 16)) * (rng.random((m // 4, 16)) < 0.3)
    sk = (rng.random((m - m // 2 - m // 4, 16)) ** 3 * 127.99).astype(np.int64)
    return np.vstack([edge, u, sp, sk]).astype(np.int64)


def make_synthetic(seed=6464):
    rng = np.random.default_rng(seed)
    calib = rng.integers(0, 128, size=(4000, 16)).astype(np.int64)
    a = calib
    W, B, S = [], [], []
    for l in range(NL):
        n_in, n_out = SIZES[l], SIZES[l + 1]
        w = np.clip(np.round(rng.normal(0, 45, size=(n_out, n_in))), -128, 127).astype(np.int64)
        # make sure the extreme codes appear somewhere in every layer
        w.flat[rng.integers(0, w.size)] = -128
        w.flat[rng.integers(0, w.size)] = 127
        pre = a @ w.T
        hidden = l < NL - 1
        if hidden:
            # bias so that about 30 % of each neuron's calibration inputs end up below zero
            b = -np.quantile(pre, 0.30, axis=0)
        else:
            b = -np.median(pre, axis=0)        # centre the outputs around 0
        b = np.clip(np.round(b + rng.normal(0, 200, n_out)), -32768, 32767).astype(np.int64)
        acc = pre + b
        if hidden:
            top = np.quantile(np.maximum(acc, 0), 0.97)
        else:
            top = np.quantile(np.abs(acc), 0.90)  # ~5-10 % of outputs hit +127 / -128: tests the clamp
        s = 0
        while s < ns64.SHIFT_MAX and (top + (1 << s >> 1)) / (1 << s) > 127:
            s += 1
        W.append(w)
        B.append(b)
        S.append(s)
        net_l = Net(W + [np.zeros((SIZES[k + 1], SIZES[k]))
                         for k in range(l + 1, NL)],
                    B + [np.zeros(SIZES[k + 1]) for k in range(l + 1, NL)],
                    S + [0] * (NL - l - 1))
        a = net_l.forward(calib, trace=True)[1][l]
    return Net(W, B, S)


def make_stress(seed=99):
    rng = np.random.default_rng(seed)
    W = [np.where(rng.random((SIZES[l + 1], SIZES[l])) < 0.5, -128, 127).astype(np.int64)
         for l in range(NL)]
    B = [np.where(rng.random(SIZES[l + 1]) < 0.5, -32768, 32767).astype(np.int64)
         for l in range(NL)]
    # layer 1: neurons 0..47 always output 127 (weights +127, bias +32767, shift 0)
    W[0][:48] = 127
    B[0][:48] = 32767
    # layer 2: all weights +127 on half the neurons, -128 on the rest -> |acc| near the
    # worst case 64*127*128 + 32768 = 1,073,152 (22 bits signed)
    W[1][:32] = 127
    W[1][32:] = -128
    B[1][:32] = 32767
    B[1][32:] = -32768
    S = [0, 15, 13, 1, 17, 9, 7]   # shifts 0..23 are also tested exhaustively in tb_requant
    return Net(W, B, S)


def stats(net, X, title):
    y, acts, accs = net.forward(X, trace=True)
    say(f"--- {title}: shifts {net.S}, CRC-32 {net.crc32():08X}")
    say("layer  |acc| max  acc bits   zero %   sat %   between %   distinct values")
    for l in range(NL):
        a, acc = acts[l], accs[l]
        hidden = l < NL - 1
        amax = int(np.abs(acc).max())
        bits = int(amax).bit_length() + 1
        zero = (a == 0).mean() * 100
        sat = ((a == 127) | (a == -128)).mean() * 100
        mid = 100 - sat - (zero if hidden else 0)
        say(f"  L{l + 1}   {amax:9d}   {bits:4d}     {zero:6.1f}  {sat:6.1f}    {mid:6.1f}      "
            f"{len(np.unique(a)):4d}")
    return y


def hexvec(v):
    return "".join(f"{int(b) & 0xFF:02x}" for b in reversed(list(v)))


def write_vectors(prefix, X, Y):
    with open(os.path.join(GEN, f"{prefix}_in.mem"), "w") as f:
        f.writelines(hexvec(x) + "\n" for x in X)
    with open(os.path.join(GEN, f"{prefix}_out.mem"), "w") as f:
        f.writelines(hexvec(y) + "\n" for y in Y)


def self_check(net, X, Y, name):
    ok = True
    # 1. vectorised model == independent plain-Python model
    for k in range(0, len(X), 25):
        if list(Y[k]) != net.forward_slow(X[k]):
            say(f"  FAIL {name}: numpy and plain-Python models differ at vector {k}")
            ok = False
    # 2. image round trip
    n2 = Net.from_image(net.image())
    if n2.image() != net.image() or not np.array_equal(n2.forward(X), Y):
        say(f"  FAIL {name}: image round trip")
        ok = False
    # 3. image_address() puts every byte where lane_columns() expects it
    col = net.lane_columns()
    img = net.image()
    for k, byte in enumerate(img):
        kind, a, word = ns64.image_address(k)
        if kind == "s":
            if net.S[a] != byte:
                ok = False
        elif col[a, word] != byte:
            say(f"  FAIL {name}: image byte {k} -> lane {a} word {word}")
            ok = False
            break
    say(f"  self-check {name}: {'PASS' if ok else 'FAIL'} "
        f"(numpy vs plain Python on {len(range(0, len(X), 25))} vectors, image round trip, "
        f"{len(img)} byte addresses)")
    return ok


def main():
    os.makedirs(GEN, exist_ok=True)
    os.makedirs(MODELS, exist_ok=True)
    say(f"NetSilcon-64x6 shape {SIZES}: {ns64.N_W} weights, {ns64.N_B} biases, {NL} shifts, "
        f"image {ns64.IMG_BYTES} bytes, {ns64.WORDS_PER_BANK} RAM words per lane per bank")
    rng = np.random.default_rng(2026)
    all_ok = True

    syn = make_synthetic()
    X = make_inputs(rng, N_VEC)
    Y = stats(syn, X, "synthetic")
    all_ok &= self_check(syn, X, Y, "synthetic")
    say(f"  output classes (argmax) used: {len(np.unique(Y.argmax(axis=1)))} of 16")

    st = make_stress()
    Xs = make_inputs(np.random.default_rng(7), 200)
    Ys = stats(st, Xs, "stress")
    all_ok &= self_check(st, Xs, Ys, "stress")

    # ---- models/*.json
    for net, name, title, Xv, Yv in ((syn, "synthetic", "Synthetic hardware test model", X, Y),
                                      (st, "stress", "Stress model (extreme numbers)", Xs, Ys)):
        d = ns64.to_json(net, name, title, {
            "kind": "test",
            "test_vectors": [{"x": x.tolist(), "y": y.tolist()} for x, y in zip(Xv, Yv)]})
        with open(os.path.join(MODELS, f"{name}.json"), "w") as f:
            json.dump(d, f, separators=(",", ":"))

    # ---- gen/ for the Verilog
    rams = ns64.ram_images(syn)
    for r in range(ns64.N_RAM):
        with open(os.path.join(GEN, f"wmem_{r:02d}.mem"), "w") as f:
            f.writelines(f"{v:04x}\n" for v in rams[r])
    # testbench RAM contents: bank 0 = synthetic, bank 1 = stress
    os.makedirs(os.path.join(GEN, "tb"), exist_ok=True)
    rams_tb = ns64.ram_images(syn, st)
    for r in range(ns64.N_RAM):
        with open(os.path.join(GEN, "tb", f"wmem_{r:02d}.mem"), "w") as f:
            f.writelines(f"{v:04x}\n" for v in rams_tb[r])

    def packed(net):
        sh = 0
        for l in range(NL):
            sh |= net.S[l] << (5 * l)
        return sh
    with open(os.path.join(GEN, "ns64_builtin.vh"), "w") as f:
        f.write("// generated by model/make_synthetic.py - do not edit\n")
        f.write(f"localparam [34:0] BUILTIN_SHIFTS = 35'h{packed(syn):09x};  // 5 bits per layer, L1 lowest: {syn.S}\n")
        f.write(f"localparam [31:0] BUILTIN_CRC32  = 32'h{syn.crc32():08x};\n")
        f.write(f"localparam [34:0] STRESS_SHIFTS  = 35'h{packed(st):09x};  // testbench only: {st.S}\n")
    write_vectors("test", X, Y)
    write_vectors("stress", Xs, Ys)
    with open(os.path.join(GEN, "num_vectors.vh"), "w") as f:
        f.write(f"localparam N_VEC = {len(X)};\nlocalparam N_STRESS = {len(Xs)};\n")

    say(f"RESULT: {'PASS' if all_ok else 'FAIL'}")
    with open(os.path.join(GEN, "model_report.txt"), "w") as f:
        f.write("\n".join(report) + "\n")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
