"""
Train one NetSilcon-6x4-LGN model on the host and save the frozen gate netlist.

usage: python train.py --width 360 --depth 4 --epochs 60 --name exp01_w360
"""
import argparse, json, os, time, csv
import numpy as np
import dataset as D
from lgn import LGN, GATE_NAMES

ap = argparse.ArgumentParser()
ap.add_argument("--width", type=int, default=360)
ap.add_argument("--depth", type=int, default=4)
ap.add_argument("--epochs", type=int, default=60)
ap.add_argument("--batch", type=int, default=128)
ap.add_argument("--lr", type=float, default=0.05)
ap.add_argument("--tau", type=float, default=None)
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--name", default=None)
args = ap.parse_args()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
name = args.name or f"exp01_w{args.width}_d{args.depth}"
mdir = os.path.join(ROOT, "models", name)
ldir = os.path.join(ROOT, "results", "logs")
os.makedirs(mdir, exist_ok=True); os.makedirs(ldir, exist_ok=True)
stamp = time.strftime("%Y%m%d_%H%M%S")
logf = open(os.path.join(ldir, f"train_{name}_{stamp}.log"), "w")
def log(*a):
    s = " ".join(str(x) for x in a); print(s); logf.write(s + "\n"); logf.flush()

s_tr, sp_tr, st_tr = D.make(40000, seed=1)
s_te, sp_te, st_te = D.make(8000, seed=2)
X_tr, X_te = D.encode(s_tr), D.encode(s_te)
heads = [D.N_SPEED, D.N_STEER]
group = args.width // sum(heads)
tau = args.tau or max(1.0, group / 6)
net = LGN(X_tr.shape[1], args.width, args.depth, heads, tau, args.seed)
log(f"[{name}] in_bits={X_tr.shape[1]} width={args.width} depth={args.depth} "
    f"group={group} tau={tau:.2f} gates={args.width*args.depth}")

rng = np.random.default_rng(args.seed + 100)
t, best, best_state = 0, -1, None
hist = []
for ep in range(1, args.epochs + 1):
    idx = rng.permutation(len(X_tr)); tl = 0; nb = 0
    lr = args.lr * (0.5 * (1 + np.cos(np.pi * (ep - 1) / args.epochs)))  # cosine
    for i in range(0, len(idx), args.batch):
        b = idx[i:i + args.batch]
        sc = net.forward(X_tr[b])
        tl += net.loss_backward(sc, [sp_tr[b], st_tr[b]]); nb += 1
        t += 1
        for L in net.layers: L.adam(lr, t)
    (hp, hs), _ = net.hard_forward(X_te)
    acc_sp = (hp == sp_te).mean(); acc_st = (hs == st_te).mean()
    both = ((hp == sp_te) & (hs == st_te)).mean()
    hist.append((ep, tl / nb, acc_sp, acc_st, both))
    log(f"ep {ep:3d} loss {tl/nb:.4f}  HARD test: speed {acc_sp*100:.2f}%  "
        f"steer {acc_st*100:.2f}%  both {both*100:.2f}%")
    if both > best:
        best = both
        best_state = [(L.logits.copy()) for L in net.layers]

for L, lg in zip(net.layers, best_state): L.logits = lg
(hp, hs), _ = net.hard_forward(X_te)
res = dict(name=name, width=args.width, depth=args.depth, group=group, tau=tau,
           in_bits=int(X_tr.shape[1]), gates_total=args.width * args.depth,
           test_speed_acc=float((hp == sp_te).mean()),
           test_steer_acc=float((hs == st_te).mean()),
           test_both_acc=float(((hp == sp_te) & (hs == st_te)).mean()),
           epochs=args.epochs, seed=args.seed)
gate_hist = np.bincount(np.concatenate([L.gates() for L in net.layers]), minlength=16)
res["gate_histogram"] = {GATE_NAMES[i]: int(c) for i, c in enumerate(gate_hist)}
np.savez(os.path.join(mdir, "netlist.npz"),
         thresh=D.THRESH, heads=np.array(heads), group=group,
         **{f"ia{i}": L.ia for i, L in enumerate(net.layers)},
         **{f"ib{i}": L.ib for i, L in enumerate(net.layers)},
         **{f"g{i}": L.gates() for i, L in enumerate(net.layers)})
json.dump(res, open(os.path.join(mdir, "result.json"), "w"), indent=2)
with open(os.path.join(ldir, f"train_{name}_{stamp}.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["epoch", "loss", "speed_acc", "steer_acc", "both_acc"])
    w.writerows(hist)
log("FINAL", json.dumps(res))
