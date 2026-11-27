"""
Train NetSilcon-LM-0 on the pump dialogue corpus, convert it to int8 (bit-exact with nslm.py),
and write the model file + report.

  1. float model: embedding (42 x 8, kept in 0..1) -> 256 -> 64 -> 64 -> 64 -> 42, ReLU, softmax CE
  2. int8: same per-layer scheme as NetSilcon-64x6 (int8 weights, int16 biases, one shift per layer)
  3. measures next-char accuracy (float and int8) and answers to test questions
usage: python train_lm.py [--epochs 8]  -> models/pump/pump.json, results/train_report.md, results/logs/
"""
import argparse, json, os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nslm

ap = argparse.ArgumentParser()
ap.add_argument("--epochs", type=int, default=8)
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--load", action="store_true", help="skip training, load models/pump/float_params.npz")
args = ap.parse_args()
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
LOGD = os.path.join(ROOT, "results", "logs"); os.makedirs(LOGD, exist_ok=True)
stamp = time.strftime("%Y%m%d_%H%M%S")
logf = open(os.path.join(LOGD, f"train_pump_{stamp}.log"), "w")
csvf = open(os.path.join(LOGD, f"train_pump_{stamp}.csv"), "w"); csvf.write("epoch,loss,val_acc_float\n")
def log(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); logf.write(s + "\n"); logf.flush()


def windows(text, blank_frac=0.0, rng=None):
    """All (context, next char) pairs. blank_frac of them get everything before the current
    'q:' line replaced by newlines, the state the FPGA starts a conversation in."""
    ids = np.array([0] * nslm.CTX + nslm.encode(text), dtype=np.int64)
    n = len(ids) - nslm.CTX
    idx = np.arange(n)[:, None] + np.arange(nslm.CTX)[None, :]
    X = ids[idx].copy()
    if blank_frac:
        # absolute index where the current dialogue ("q: ...") starts, for every position
        starts = np.zeros(len(ids), dtype=np.int64); cur = 0
        for k in range(nslm.CTX, len(ids)):
            if ids[k] == nslm.CH2I["q"] and ids[k - 1] == 0 and (k + 1 < len(ids) and ids[k + 1] == nslm.CH2I[":"]):
                cur = k
            starts[k] = cur
        tgt = np.arange(n) + nslm.CTX                     # absolute index of the predicted char
        qs = starts[np.maximum(tgt - 1, 0)]
        qs = np.where(ids[tgt] == nslm.CH2I["q"], tgt, qs)  # predicting a new 'q': blank all before it
        m = rng.random(n) < blank_frac
        X[m[:, None] & (idx < qs[:, None])] = 0
    return X, ids[nslm.CTX:]


tr_txt = open(os.path.join(ROOT, "python", "data", "pump_train.txt")).read()
te_txt = open(os.path.join(ROOT, "python", "data", "pump_test.txt")).read()
rng0 = np.random.default_rng(args.seed + 7)
Xtr, Ytr = windows(tr_txt, 0.3, rng0); Xte, Yte = windows(te_txt)
XteB, YteB = windows(te_txt, 1.0, rng0)   # every test window starts from a blank context
log(f"train {len(Ytr)} chars, test {len(Yte)} chars, params ~{nslm.V*8 + sum(a*b+b for a,b in zip(nslm.SIZES[:-1], nslm.SIZES[1:]))}")

rng = np.random.default_rng(args.seed)
S = nslm.SIZES
P = {"E": rng.uniform(0.2, 0.8, (nslm.V, nslm.EMB))}
for l in range(nslm.NL):
    P[f"W{l}"] = rng.normal(0, np.sqrt(2 / S[l]), (S[l], S[l + 1]))
    P[f"b{l}"] = np.zeros(S[l + 1])
M = {k: np.zeros_like(v) for k, v in P.items()}; Vv = {k: np.zeros_like(v) for k, v in P.items()}


def fwd(ctx):
    E = np.clip(P["E"], 0, 1)
    h = E[ctx].reshape(len(ctx), -1); hs = [h]
    for l in range(nslm.NL):
        h = h @ P[f"W{l}"] + P[f"b{l}"]
        if l < nslm.NL - 1: h = np.maximum(h, 0)
        hs.append(h)
    return hs


def softmax(z):
    e = np.exp(z - z.max(1, keepdims=True)); return e / e.sum(1, keepdims=True)


FP = os.path.join(ROOT, "models", "pump", "float_params.npz"); os.makedirs(os.path.dirname(FP), exist_ok=True)
if args.load:
    P = dict(np.load(FP)); log("loaded float parameters", FP)
t = 0; B = 256
for ep in range(1, (0 if args.load else args.epochs) + 1):
    perm = rng.permutation(len(Ytr)); tl = 0; nb = 0
    lr = 2e-3 * 0.5 * (1 + np.cos(np.pi * (ep - 1) / args.epochs))
    for i in range(0, len(perm), B):
        b = perm[i:i + B]; ctx = Xtr[b]; y = Ytr[b]; n = len(b)
        hs = fwd(ctx); p = softmax(hs[-1])
        tl += -np.log(p[np.arange(n), y] + 1e-9).mean(); nb += 1
        g = p; g[np.arange(n), y] -= 1; g /= n
        G = {}
        for l in reversed(range(nslm.NL)):
            G[f"W{l}"] = hs[l].T @ g; G[f"b{l}"] = g.sum(0)
            g = g @ P[f"W{l}"].T
            if l > 0: g = g * (hs[l] > 0)
        gE = np.zeros_like(P["E"])
        np.add.at(gE, ctx.reshape(-1), g.reshape(n * nslm.CTX, nslm.EMB))
        G["E"] = gE
        t += 1
        for k in P:
            M[k] = 0.9 * M[k] + 0.1 * G[k]; Vv[k] = 0.999 * Vv[k] + 0.001 * G[k] ** 2
            P[k] -= lr * (M[k] / (1 - 0.9 ** t)) / (np.sqrt(Vv[k] / (1 - 0.999 ** t)) + 1e-8)
        P["E"] = np.clip(P["E"], 0, 1)
    acc = (fwd(Xte)[-1].argmax(1) == Yte).mean()
    log(f"epoch {ep} loss {tl/nb:.4f} test next-char accuracy (float) {acc*100:.2f}%")
    csvf.write(f"{ep},{tl/nb:.5f},{acc:.5f}\n"); csvf.flush()

if not args.load: np.savez(FP, **P)
# ------------------------------------------------------------------ int8 conversion
def quantize(calib_ctx, q_act=0.9999, w_clip=1.0, q_out=0.999):
    Eq = np.clip(np.round(P["E"] * 127), 0, 127).astype(np.int64)
    a = Eq[calib_ctx].reshape(len(calib_ctx), -1)
    S_prev = 127.0; W_int, B_int, SH = [], [], []
    for l in range(nslm.NL):
        Wf, bf = P[f"W{l}"].T, P[f"b{l}"]; last = l == nslm.NL - 1
        if not last:
            K = 127.0 / max(np.quantile(np.abs(Wf), w_clip), 1e-9)
            w = np.clip(np.round(Wf * K), -128, 127).astype(np.int64); b_real = K * S_prev * bf
            while np.abs(b_real).max() > 32767:
                K *= 0.5; w = np.clip(np.round(Wf * K), -128, 127).astype(np.int64); b_real = K * S_prev * bf
            b = np.round(b_real).astype(np.int64)
            acc = np.maximum(a @ w.T + b, 0); top = np.quantile(acc, q_act)
            s = 0
            while s < nslm.SHIFT_MAX and (top + (1 << s >> 1)) / (1 << s) > 127: s += 1
            S_prev = K * S_prev / (1 << s)
        else:
            # logits -> int8: scale so 99.9 % of |logit| <= 110, weights must fit int8
            zf = fwd(calib_ctx)[-1]
            target = 110.0 / max(np.quantile(np.abs(zf), q_out), 1e-6)   # int8 per float logit
            s = nslm.SHIFT_MAX
            while s > 0 and np.abs(Wf).max() * target * (1 << s) / S_prev > 127: s -= 1
            K = target * (1 << s) / S_prev
            w = np.clip(np.round(Wf * K), -128, 127).astype(np.int64)
            b = np.clip(np.round(K * S_prev * bf), -32768, 32767).astype(np.int64)
            acc = a @ w.T + b
        W_int.append(w); B_int.append(b); SH.append(s)
        a = np.clip((acc + (1 << s >> 1)) >> s, 0 if not last else -128, 127)
    return nslm.LM(Eq, W_int, B_int, SH)


# calibration search on a VALIDATION slice of the training text (the test set is not used)
calib = Xtr[rng.choice(len(Ytr), 20000, replace=False)]
vi = rng.choice(len(Ytr), 30000, replace=False); Xv, Yv = Xtr[vi], Ytr[vi]
best = None
for q_act in (0.99, 0.995, 0.999, 0.9999):
    for w_clip in (1.0, 0.9999, 0.999):
        for q_out in (0.99, 0.999):
            cand = quantize(calib, q_act, w_clip, q_out)
            va = (cand.forward(Xv).argmax(1) == Yv).mean()
            log(f"  calib q_act={q_act} w_clip={w_clip} q_out={q_out}: validation int8 acc {va*100:.2f}%")
            if best is None or va > best[0]: best = (va, cand, (q_act, w_clip, q_out))
lm = best[1]; log(f"chosen calibration {best[2]} (validation {best[0]*100:.2f}%)")
acc_f = (fwd(Xte)[-1].argmax(1) == Yte).mean()
yq = lm.forward(Xte); acc_q = (yq.argmax(1) == Yte).mean()
agree = (yq.argmax(1) == fwd(Xte)[-1].argmax(1)).mean()
log(f"int8: shifts {lm.S}  params {lm.params()}  CRC-32 {lm.crc32():08X}")
log(f"test next-char accuracy: float {acc_f*100:.2f}%  int8 {acc_q*100:.2f}%  (int8 vs float agreement {agree*100:.2f}%)")
acc_qb = (lm.forward(XteB).argmax(1) == YteB).mean()
log(f"test next-char accuracy, conversation started from a blank context: int8 {acc_qb*100:.2f}%")

QUESTIONS = ["is the pump running?", "what is the pressure?", "flow rate?", "how full is the tank?",
             "motor temp?", "start the pump.", "stop the pump.", "any faults?", "next run?", "hello.",
             "what can you do?", "who are you?", "run time today?",
             # not in the corpus with this wording:
             "is the pump working?", "what is the water pressure?", "hi pump."]
qa = []
for qtext in QUESTIONS:
    ans, _ = lm.generate(f"q: {qtext}\n", max_chars=60)
    qa.append((qtext, ans.rstrip("\n")))
    log(f"  q: {qtext}\n  -> {ans.rstrip()}")

mdir = os.path.join(ROOT, "models", "pump"); os.makedirs(mdir, exist_ok=True)
json.dump(lm.to_json("pump", dict(test_acc_float=float(acc_f), test_acc_int8=float(acc_q), test_acc_int8_blank=float(acc_qb),
                                  epochs=args.epochs, seed=args.seed, qa=qa)),
          open(os.path.join(mdir, "pump.json"), "w"))
rep = ["# LM-0 pump model: training report (auto-generated by train_lm.py)", "",
       f"- corpus: synthetic pump dialogues, train {len(Ytr):,} chars, test {len(Yte):,} chars",
       f"- parameters: {lm.params():,} (embedding 336 + weights + biases), shifts {lm.S}, CRC-32 `{lm.crc32():08X}`",
       f"- test next-char accuracy: float {acc_f*100:.2f} %, **int8 {acc_q*100:.2f} %**, int8 vs float {agree*100:.2f} %",
       f"- test next-char accuracy when every conversation starts from a blank context (as on the FPGA): int8 {acc_qb*100:.2f} %",
       "", "## Answers of the int8 model (greedy, same as the FPGA)", "", "| question | answer |", "|---|---|"]
rep += [f"| {q} | {a} |" for q, a in qa]
open(os.path.join(ROOT, "results", "train_report.md"), "w").write("\n".join(rep) + "\n")
log("wrote models/pump/pump.json and results/train_report.md")
