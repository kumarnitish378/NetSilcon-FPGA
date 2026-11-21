"""Train the NetSilcon-6x4 network: 4 -> 6 -> 6 -> 6 -> 6 -> 2  (ReLU in hidden layers).

Pure numpy, no PyTorch needed. Run:  python train.py
Writes float weights to model/float_weights.npz
"""
import numpy as np
from data import make, to_int8

SIZES = [4, 6, 6, 6, 6, 2]
rng = np.random.default_rng(42)


def init():
    Ws, bs = [], []
    for i in range(len(SIZES) - 1):
        Ws.append(rng.normal(0, np.sqrt(2.0 / SIZES[i]), (SIZES[i + 1], SIZES[i])))
        bs.append(np.full(SIZES[i + 1], 0.05))     # small positive bias keeps ReLUs alive
    return Ws, bs


def forward(Ws, bs, x):
    acts, pre = [x], []
    a = x
    for l, (W, b) in enumerate(zip(Ws, bs)):
        z = a @ W.T + b
        pre.append(z)
        a = z if l == len(Ws) - 1 else np.maximum(z, 0)
        acts.append(a)
    return acts, pre


def train(X, y, epochs=400, lr=3e-3, batch=128):
    Ws, bs = init()
    params = Ws + bs
    m = [np.zeros_like(p) for p in params]
    v = [np.zeros_like(p) for p in params]
    t = 0
    n = len(X)
    for ep in range(epochs):
        idx = rng.permutation(n)
        for s in range(0, n, batch):
            bi = idx[s:s + batch]
            xb, yb = X[bi], y[bi]
            acts, pre = forward(Ws, bs, xb)
            logits = acts[-1]
            p = np.exp(logits - logits.max(1, keepdims=True))
            p /= p.sum(1, keepdims=True)
            g = p.copy()
            g[np.arange(len(yb)), yb] -= 1
            g /= len(yb)
            gW, gb = [None] * len(Ws), [None] * len(Ws)
            for l in reversed(range(len(Ws))):
                gW[l] = g.T @ acts[l]
                gb[l] = g.sum(0)
                if l > 0:
                    g = (g @ Ws[l]) * (pre[l - 1] > 0)
            grads = gW + gb
            t += 1
            for i, (pp, gg) in enumerate(zip(params, grads)):
                m[i] = 0.9 * m[i] + 0.1 * gg
                v[i] = 0.999 * v[i] + 0.001 * gg * gg
                pp -= lr * (m[i] / (1 - 0.9**t)) / (np.sqrt(v[i] / (1 - 0.999**t)) + 1e-8)
        if ep % 50 == 0 or ep == epochs - 1:
            acc = (forward(Ws, bs, X)[0][-1].argmax(1) == y).mean()
            print(f"epoch {ep:4d}  train accuracy {acc*100:5.1f}%")
    return Ws, bs


if __name__ == "__main__":
    Xtr, ytr = make(20000, seed=1)
    Xte, yte = make(4000, seed=2)
    # Train on exactly what the chip sees: inputs already quantized to 0..127, then /127
    xtr = to_int8(Xtr) / 127.0
    xte = to_int8(Xte) / 127.0
    Ws, bs = train(xtr, ytr)
    acc = (forward(Ws, bs, xte)[0][-1].argmax(1) == yte).mean()
    print(f"\nFloat model test accuracy: {acc*100:.2f}%")
    np.savez("float_weights.npz", *Ws, *bs)
