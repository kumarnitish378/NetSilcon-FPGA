"""
NetSilcon-LM-0: bit-exact integer reference of a character-level language model.
Every other script (training, generators, testbench files) imports this file.

Model (fixed in hardware):
    context  : the last CTX = 32 characters, alphabet of V = 42 symbols (index 0 = newline)
    embedding: E[c] = 8 values 0..127 per symbol  -> 32 x 8 = 256 inputs
    network  : 256 -> 64 -> 64 -> 64 -> 42        (64 MAC lanes, like NetSilcon-64x6)
    output   : 42 signed int8 logits, next char = argmax (first one on ties)

Input order: x[8*p + d] = E[ctx[p]][d], p = 0 is the OLDEST character, p = 31 the newest.

Neuron math (identical to NetSilcon-64x6):
    acc = bias16 + sum_i x_i * w_ji        int8 x int8, 24-bit signed accumulator
    hidden layers: acc = max(acc, 0)       ReLU
    y = (acc + 2^(s-1)) >> s               arithmetic shift, s = 0..23 (2^(s-1) = 0 for s = 0)
    y = clamp 0..127 (hidden) or -128..127 (output)

Block-RAM layout: lane j (= neuron j) owns one 8-bit column; for layer l
    word BASE[l] + 0 / + 1 : bias low / high byte,  word BASE[l] + 2 + i : weight from input i
    BASE = [0, 258, 324, 390], 456 words. 32 RAMs of 512 x 16, RAM r = lanes 2r (bits 7:0), 2r+1.
"""
import zlib
import numpy as np

ALPHABET = "\n :,.?abcdefghijklmnopqrstuvwxyz0123456789"
V = len(ALPHABET)                       # 42
CTX, EMB = 32, 8
SIZES = [CTX * EMB, 64, 64, 64, V]      # 256 -> 64 -> 64 -> 64 -> 42
NL = len(SIZES) - 1
LANES = 64
SHIFT_MAX, ACC_BITS = 23, 24
BASE = []
_a = 0
for _l in range(NL):
    BASE.append(_a); _a += 2 + SIZES[_l]
WORDS = _a                              # 456
N_RAM, RAM_DEPTH = LANES // 2, 512
CH2I = {c: i for i, c in enumerate(ALPHABET)}


def encode(text):
    return [CH2I[c] for c in text]


def decode(ids):
    return "".join(ALPHABET[i] for i in ids)


class LM:
    """E: (V, EMB) 0..127, W[l]: (N_out, N_in) int8, B[l]: int16, S: shifts."""

    def __init__(self, E, W, B, S):
        self.E = np.asarray(E, dtype=np.int64)
        self.W = [np.asarray(w, dtype=np.int64) for w in W]
        self.B = [np.asarray(b, dtype=np.int64) for b in B]
        self.S = [int(s) for s in S]
        assert self.E.shape == (V, EMB) and self.E.min() >= 0 and self.E.max() <= 127
        for l in range(NL):
            assert self.W[l].shape == (SIZES[l + 1], SIZES[l])
            assert self.W[l].min() >= -128 and self.W[l].max() <= 127
            assert self.B[l].min() >= -32768 and self.B[l].max() <= 32767
            assert 0 <= self.S[l] <= SHIFT_MAX

    def inputs(self, ctx):
        """ctx: (N, 32) symbol ids -> (N, 256) inputs"""
        ctx = np.asarray(ctx, dtype=np.int64)
        return self.E[ctx].reshape(len(ctx), -1)

    def forward(self, ctx):
        """(N, 32) contexts -> (N, 42) int8 logits"""
        a = self.inputs(ctx)
        for l in range(NL):
            acc = a @ self.W[l].T + self.B[l]
            assert np.abs(acc).max() < (1 << (ACC_BITS - 1)), "24-bit accumulator overflow"
            hidden = l < NL - 1
            if hidden: acc = np.maximum(acc, 0)
            s = self.S[l]
            y = (acc + ((1 << (s - 1)) if s else 0)) >> s
            a = np.clip(y, 0, 127) if hidden else np.clip(y, -128, 127)
        return a

    def forward_slow(self, ctx):
        """plain-Python reference, written independently, to cross-check forward()"""
        a = []
        for c in ctx:
            a += [int(v) for v in self.E[c]]
        for l in range(NL):
            out = []
            for j in range(SIZES[l + 1]):
                acc = int(self.B[l][j])
                for i in range(SIZES[l]):
                    acc += a[i] * int(self.W[l][j, i])
                if l < NL - 1 and acc < 0: acc = 0
                s = self.S[l]
                if s: acc += 1 << (s - 1)
                y = acc >> s
                out.append(min(max(y, 0 if l < NL - 1 else -128), 127))
            a = out
        return a

    def generate(self, prompt, max_chars=80, ctx=None, stop="\n"):
        """Push the prompt, then greedy argmax one char at a time (exactly what the FPGA does)."""
        ctx = list(ctx) if ctx is not None else [0] * CTX
        for c in encode(prompt):
            ctx = ctx[1:] + [c]
        out = []
        for _ in range(max_chars):
            y = self.forward(np.array([ctx]))[0]
            c = int(np.argmax(y))
            out.append(c); ctx = ctx[1:] + [c]
            if ALPHABET[c] == stop: break
        return decode(out), ctx

    # ---------------------------------------------------------------- memories
    def lane_columns(self):
        col = np.zeros((LANES, WORDS), dtype=np.uint8)
        for l in range(NL):
            for j in range(SIZES[l + 1]):
                b = int(self.B[l][j]) & 0xFFFF
                col[j, BASE[l]] = b & 0xFF
                col[j, BASE[l] + 1] = b >> 8
                col[j, BASE[l] + 2:BASE[l] + 2 + SIZES[l]] = self.W[l][j] & 0xFF
        return col

    def ram_images(self):
        col = self.lane_columns().astype(np.uint16)
        rams = np.zeros((N_RAM, RAM_DEPTH), dtype=np.uint16)
        for r in range(N_RAM):
            rams[r, :WORDS] = col[2 * r] | (col[2 * r + 1] << 8)
        return rams

    def emb_image(self):
        """embedding ROM, 64 x 8 entries (symbol*8 + d), 512 bytes"""
        m = np.zeros(64 * EMB, dtype=np.uint8)
        m[:V * EMB] = self.E.reshape(-1)
        return m

    def image(self):
        out = bytearray(self.E.astype(np.uint8).tobytes())
        for l in range(NL): out += (self.W[l].reshape(-1) & 0xFF).astype(np.uint8).tobytes()
        for l in range(NL):
            for v in self.B[l]:
                v = int(v) & 0xFFFF; out += bytes([v & 0xFF, v >> 8])
        return bytes(out + bytes(self.S))

    def crc32(self):
        return zlib.crc32(self.image()) & 0xFFFFFFFF

    def params(self):
        return int(self.E.size + sum(w.size for w in self.W) + sum(b.size for b in self.B))

    # ---------------------------------------------------------------- json
    def to_json(self, name, extra=None):
        d = dict(name=name, alphabet=ALPHABET, ctx=CTX, emb=EMB, shape=SIZES,
                 embedding=self.E.tolist(), weights=[w.tolist() for w in self.W],
                 biases=[b.tolist() for b in self.B], shifts=self.S,
                 params=self.params(), crc32=f"{self.crc32():08X}")
        if extra: d.update(extra)
        return d

    @staticmethod
    def from_json(d):
        return LM(d["embedding"], d["weights"], d["biases"], d["shifts"])


if __name__ == "__main__":
    # self-check: forward() vs forward_slow() on a random model
    rng = np.random.default_rng(0)
    W = [rng.integers(-128, 128, (SIZES[l + 1], SIZES[l])) for l in range(NL)]
    B = [rng.integers(-3000, 3000, SIZES[l + 1]) for l in range(NL)]
    m = LM(rng.integers(0, 128, (V, EMB)), W, B, [12, 12, 12, 13])
    ctx = rng.integers(0, V, (20, CTX))
    fast = m.forward(ctx)
    for k in range(20):
        assert list(fast[k]) == m.forward_slow(list(ctx[k])), k
    print(f"self-check OK: forward == forward_slow on 20 random contexts; params {m.params()}, words/lane {WORDS}")
