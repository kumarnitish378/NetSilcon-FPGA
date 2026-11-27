"""
Baseline: weight-based NetSilcon-6x4 shape (4 -> 6-6-6-6 -> heads) trained on the SAME
dataset, so LGN accuracy can be compared with the classic weights approach.
Float32 training, then the accuracy with weights quantized to int8 (per-layer scale).
Outputs: 4 speed logits + 5 steer logits (the 6x4 core is unchanged; only the output
layer is 9 wide instead of 2 so it is a classification comparison).
"""
import json, os, numpy as np
import dataset as D

rng = np.random.default_rng(0)
s_tr, sp_tr, st_tr = D.make(40000, 1)
s_te, sp_te, st_te = D.make(8000, 2)
X_tr = s_tr / 255.0; X_te = s_te / 255.0
sizes = [4, 6, 6, 6, 6, 9]
W = [rng.normal(0, np.sqrt(2 / a), (a, b)) for a, b in zip(sizes[:-1], sizes[1:])]
B = [np.zeros(b) for b in sizes[1:]]
mW = [np.zeros_like(w) for w in W]; vW = [np.zeros_like(w) for w in W]
mB = [np.zeros_like(b) for b in B]; vB = [np.zeros_like(b) for b in B]

def sm(x):
    e = np.exp(x - x.max(1, keepdims=True)); return e / e.sum(1, keepdims=True)

def fwd(x, W, B):
    hs = [x]
    for i, (w, b) in enumerate(zip(W, B)):
        x = x @ w + b
        if i < len(W) - 1: x = np.maximum(x, 0)
        hs.append(x)
    return hs

def acc(W, B):
    o = fwd(X_te, W, B)[-1]
    p, s = o[:, :4].argmax(1), o[:, 4:].argmax(1)
    return (p == sp_te).mean(), (s == st_te).mean(), ((p == sp_te) & (s == st_te)).mean()

t = 0
for ep in range(150):
    idx = rng.permutation(len(X_tr))
    lr = 0.01 * (0.5 * (1 + np.cos(np.pi * ep / 150)))
    for i in range(0, len(idx), 128):
        b = idx[i:i + 128]; hs = fwd(X_tr[b], W, B); o = hs[-1]; n = len(b)
        g = np.zeros_like(o)
        p = sm(o[:, :4]); p[np.arange(n), sp_tr[b]] -= 1; g[:, :4] = p / n
        q = sm(o[:, 4:]); q[np.arange(n), st_tr[b]] -= 1; g[:, 4:] = q / n
        t += 1
        for L in reversed(range(len(W))):
            gw = hs[L].T @ g; gb = g.sum(0)
            g = g @ W[L].T
            if L > 0: g = g * (hs[L] > 0)
            for P, G, m, v in ((W, gw, mW, vW), (B, gb, mB, vB)):
                m[L] = 0.9 * m[L] + 0.1 * G; v[L] = 0.999 * v[L] + 0.001 * G * G
                P[L] -= lr * (m[L] / (1 - 0.9 ** t)) / (np.sqrt(v[L] / (1 - 0.999 ** t)) + 1e-8)

fa = acc(W, B)
Wq = [np.round(w / (np.abs(w).max() / 127)) * (np.abs(w).max() / 127) for w in W]
qa = acc(Wq, B)
res = dict(model="MLP 4-6-6-6-6-9 (weights)", params=int(sum(w.size for w in W) + sum(b.size for b in B)),
           float_speed=fa[0], float_steer=fa[1], float_both=fa[2],
           int8_speed=qa[0], int8_steer=qa[1], int8_both=qa[2])
res = {k: (float(v) if isinstance(v, np.floating) else v) for k, v in res.items()}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
json.dump(res, open(os.path.join(ROOT, "results", "baseline_mlp.json"), "w"), indent=2)
print(json.dumps(res, indent=2))
