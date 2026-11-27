"""
Differentiable Logic Gate Network (LGN) in plain numpy.
Idea after Petersen et al. (NeurIPS 2022, "Deep Differentiable Logic Gate Networks").

Every node has 2 fixed (random) input wires and learns WHICH of the 16 two-input
gates it should be. During training each node is a soft mix of all 16 gates
(real-valued relaxation). After training each node is frozen to its best gate,
giving a pure gate netlist -> combinational Verilog, no weights stored anywhere.

Each relaxed gate is  g(a,b) = c0 + c1*a + c2*b + c3*a*b
"""
import numpy as np

GATE_NAMES = ["FALSE", "AND", "A_AND_NOT_B", "A", "NOT_A_AND_B", "B", "XOR", "OR",
              "NOR", "XNOR", "NOT_B", "A_OR_NOT_B", "NOT_A", "NOT_A_OR_B", "NAND", "TRUE"]
#            c0  c1  c2  c3
COEF = np.array([
    [0, 0, 0, 0],    # FALSE
    [0, 0, 0, 1],    # AND
    [0, 1, 0, -1],   # A & ~B
    [0, 1, 0, 0],    # A
    [0, 0, 1, -1],   # ~A & B
    [0, 0, 1, 0],    # B
    [0, 1, 1, -2],   # XOR
    [0, 1, 1, -1],   # OR
    [1, -1, -1, 1],  # NOR
    [1, -1, -1, 2],  # XNOR
    [1, 0, -1, 0],   # ~B
    [1, 0, -1, 1],   # A | ~B
    [1, -1, 0, 0],   # ~A
    [1, -1, 0, 1],   # ~A | B
    [1, 0, 0, -1],   # NAND
    [1, 0, 0, 0],    # TRUE
], dtype=np.float32)

# Verilog expression for each gate, a/b are wire names
VEXPR = ["1'b0", "{a} & {b}", "{a} & ~{b}", "{a}", "~{a} & {b}", "{b}", "{a} ^ {b}",
         "{a} | {b}", "~({a} | {b})", "~({a} ^ {b})", "~{b}", "{a} | ~{b}", "~{a}",
         "~{a} | {b}", "~({a} & {b})", "1'b1"]


def hard_gate(k, a, b):
    """exact boolean evaluation of gate k on 0/1 uint8 arrays"""
    c = COEF[k]
    return (c[0] + c[1] * a + c[2] * b + c[3] * a * b).astype(np.uint8)


def softmax(x):
    e = np.exp(x - x.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)


class Layer:
    def __init__(self, n_in, n_out, rng):
        # wiring: spread inputs so every previous node is used where possible
        perm = np.concatenate([rng.permutation(n_in) for _ in range(2 * n_out // n_in + 2)])
        self.ia = perm[:n_out].copy()
        self.ib = perm[n_out:2 * n_out].copy()
        same = self.ia == self.ib
        self.ib[same] = (self.ib[same] + 1) % n_in
        self.n_in, self.n_out = n_in, n_out
        self.logits = rng.normal(0, 1, size=(n_out, 16)).astype(np.float32)
        # Adam state
        self.m = np.zeros_like(self.logits)
        self.v = np.zeros_like(self.logits)

    def forward(self, x):
        self.x = x
        self.p = softmax(self.logits)            # (W,16)
        self.C = self.p @ COEF                   # (W,4)
        a, b = x[:, self.ia], x[:, self.ib]
        self.a, self.b = a, b
        C = self.C
        return C[:, 0] + C[:, 1] * a + C[:, 2] * b + C[:, 3] * a * b

    def backward(self, g):
        a, b, C = self.a, self.b, self.C
        # grad wrt C (summed over batch)
        dC = np.stack([g.sum(0), (g * a).sum(0), (g * b).sum(0), (g * a * b).sum(0)], 1)
        dp = dC @ COEF.T                         # (W,16)
        p = self.p
        self.grad = p * (dp - (dp * p).sum(1, keepdims=True))
        ga = g * (C[:, 1] + C[:, 3] * b)
        gb = g * (C[:, 2] + C[:, 3] * a)
        gx = np.zeros_like(self.x)
        # scatter-add back to the previous layer
        np.add.at(gx.T, self.ia, ga.T)
        np.add.at(gx.T, self.ib, gb.T)
        return gx

    def adam(self, lr, t, b1=0.9, b2=0.999, eps=1e-8):
        self.m = b1 * self.m + (1 - b1) * self.grad
        self.v = b2 * self.v + (1 - b2) * self.grad ** 2
        mh = self.m / (1 - b1 ** t)
        vh = self.v / (1 - b2 ** t)
        self.logits -= lr * mh / (np.sqrt(vh) + eps)

    def gates(self):
        return self.logits.argmax(1)


class LGN:
    """n_in bits -> L logic layers of width W -> GroupSum heads"""

    def __init__(self, n_in, width, depth, heads, tau, seed):
        rng = np.random.default_rng(seed)
        self.heads = heads                      # e.g. [4,5]
        n_cls = sum(heads)
        assert width % n_cls == 0, "last layer width must divide into class groups"
        self.group = width // n_cls
        self.tau = tau
        self.layers = []
        n = n_in
        for _ in range(depth):
            self.layers.append(Layer(n, width, rng))
            n = width

    def forward(self, x):
        for L in self.layers:
            x = L.forward(x)
        self.last = x
        B = len(x)
        s = x.reshape(B, -1, self.group).sum(2) / self.tau   # (B, n_cls)
        return s

    def loss_backward(self, scores, ys):
        """softmax-CE per head, ys: list of label arrays"""
        B = len(scores)
        g = np.zeros_like(scores)
        loss, off = 0.0, 0
        for h, y in zip(self.heads, ys):
            sl = scores[:, off:off + h]
            p = softmax(sl)
            loss += -np.log(p[np.arange(B), y] + 1e-9).mean()
            d = p.copy()
            d[np.arange(B), y] -= 1
            g[:, off:off + h] = d / B
            off += h
        # back through GroupSum
        gx = np.repeat(g / self.tau, self.group, axis=1)
        for L in reversed(self.layers):
            gx = L.backward(gx)
        return loss

    # ---------- hard (deployed) model, bit-exact reference for the Verilog ----------
    def hard_forward(self, xb):
        x = xb.astype(np.uint8)
        for L in self.layers:
            G = L.gates()
            a, b = x[:, L.ia], x[:, L.ib]
            c = COEF[G]
            x = (c[:, 0] + c[:, 1] * a + c[:, 2] * b + c[:, 3] * a * b).astype(np.uint8)
        cnt = x.reshape(len(x), -1, self.group).sum(2).astype(np.int32)
        outs, off = [], 0
        for h in self.heads:
            outs.append(cnt[:, off:off + h].argmax(1))   # argmax: ties -> lowest index
            off += h
        return outs, cnt
