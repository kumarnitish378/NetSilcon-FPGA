"""
NetSilcon-64x6: bit-exact integer reference model, model image, CRC-32 and
block-RAM layout. Every other script (generator, host tool, testbench files)
imports this file, so the math lives in exactly one place.

Network shape (fixed in hardware): 16 -> 64 -> 64 -> 64 -> 64 -> 64 -> 64 -> 16

Neuron math (identical to NetSilcon-6x4, wider accumulator and shift):
    acc = bias16 + sum_i x_i * w_ji        int8 x int8, 24-bit signed accumulator
    hidden layers: acc = max(acc, 0)       ReLU
    y = (acc + 2^(s-1)) >> s               arithmetic shift, s = 0..23 (2^(s-1) = 0 for s = 0)
    y = clamp 0..127 (hidden) or -128..127 (output)

Inputs are 0..127. Weights int8, biases int16, one shift per layer.

Model image (the bytes sent after the C3 header, 23,335 bytes):
    22,528 weights   int8, layer by layer; inside a layer neuron j, input i at j*N_in + i
       400 biases    int16, little endian, layer by layer, neuron order
         7 shifts    0..23
    followed on the wire by CRC-32 (zlib / IEEE 802.3) of the image, little endian.

Block-RAM layout (what the loader writes and the engine reads):
    Lane j (= neuron j) owns one 8-bit memory column. For every layer l it holds
        word base[l] + 0 : bias low byte
        word base[l] + 1 : bias high byte
        word base[l] + 2 + i : weight from input i
    base = [0, 18, 84, 150, 216, 282, 348], 414 words per bank.
    In the output layer only lanes 0..15 are used (the rest stay 0).
    32 RAMs of 1K x 16: RAM b holds lane 2b in bits 7:0 and lane 2b+1 in bits 15:8.
    RAM address = bank * 512 + word.  Bank 0 = built-in model, bank 1 = upload slot.
"""
import zlib

import numpy as np

SIZES = [16, 64, 64, 64, 64, 64, 64, 16]
NL = len(SIZES) - 1                                     # 7 layers
LANES = 64
N_W = sum(SIZES[l] * SIZES[l + 1] for l in range(NL))    # 22,528
N_B = sum(SIZES[1:])                                     # 400
IMG_BYTES = N_W + 2 * N_B + NL                           # 23,335
SHIFT_MAX = 23
ACC_BITS = 24

BASE = []
_a = 0
for _l in range(NL):
    BASE.append(_a)
    _a += 2 + SIZES[_l]
WORDS_PER_BANK = _a                                      # 414
BANK_WORDS = 512
N_RAM = LANES // 2                                       # 32
RAM_DEPTH = 1024


# --------------------------------------------------------------------- model container
class Net:
    """W[l]: int array (N_out, N_in), B[l]: int array (N_out,), S: list of 7 shifts."""

    def __init__(self, W, B, S):
        assert len(W) == NL and len(B) == NL and len(S) == NL
        self.W = [np.asarray(w, dtype=np.int64) for w in W]
        self.B = [np.asarray(b, dtype=np.int64) for b in B]
        self.S = [int(s) for s in S]
        for l in range(NL):
            assert self.W[l].shape == (SIZES[l + 1], SIZES[l]), f"layer {l} weight shape"
            assert self.B[l].shape == (SIZES[l + 1],), f"layer {l} bias shape"
            assert self.W[l].min() >= -128 and self.W[l].max() <= 127
            assert self.B[l].min() >= -32768 and self.B[l].max() <= 32767
            assert 0 <= self.S[l] <= SHIFT_MAX

    # ---- vectorised reference (numpy, int64: no overflow possible)
    def forward(self, X, trace=False):
        """X: (N, 16) ints 0..127. Returns (N, 16) outputs, and per-layer activations if trace."""
        a = np.asarray(X, dtype=np.int64)
        if a.ndim == 1:
            a = a[None, :]
        assert a.min() >= 0 and a.max() <= 127, "inputs must be 0..127"
        acts, accs = [], []
        for l in range(NL):
            acc = a @ self.W[l].T + self.B[l]
            accs.append(acc)
            assert np.abs(acc).max() < (1 << (ACC_BITS - 1)), "24-bit accumulator overflow"
            hidden = l < NL - 1
            if hidden:
                acc = np.maximum(acc, 0)
            s = self.S[l]
            y = (acc + ((1 << (s - 1)) if s else 0)) >> s    # numpy >> on int64 = arithmetic
            a = np.clip(y, 0, 127) if hidden else np.clip(y, -128, 127)
            acts.append(a)
        return (a, acts, accs) if trace else a

    # ---- plain-Python reference, written independently, used to cross-check forward()
    def forward_slow(self, x):
        a = [int(v) for v in x]
        for l in range(NL):
            out = []
            for j in range(SIZES[l + 1]):
                acc = int(self.B[l][j])
                for i in range(SIZES[l]):
                    acc += a[i] * int(self.W[l][j, i])
                if l < NL - 1 and acc < 0:
                    acc = 0
                s = self.S[l]
                if s:
                    acc += 1 << (s - 1)
                y = acc >> s
                lo = 0 if l < NL - 1 else -128
                out.append(min(max(y, lo), 127))
            a = out
        return a

    # ---- wire image + CRC
    def image(self):
        out = bytearray()
        for l in range(NL):
            out += (self.W[l].reshape(-1) & 0xFF).astype(np.uint8).tobytes()
        for l in range(NL):
            for v in self.B[l]:
                v = int(v) & 0xFFFF
                out += bytes([v & 0xFF, v >> 8])
        out += bytes(self.S)
        assert len(out) == IMG_BYTES
        return bytes(out)

    def crc32(self):
        return zlib.crc32(self.image()) & 0xFFFFFFFF

    @staticmethod
    def from_image(img):
        assert len(img) == IMG_BYTES
        p, W, B = 0, [], []
        for l in range(NL):
            n = SIZES[l] * SIZES[l + 1]
            w = np.frombuffer(img[p:p + n], dtype=np.int8).astype(np.int64)
            W.append(w.reshape(SIZES[l + 1], SIZES[l]))
            p += n
        for l in range(NL):
            b = np.frombuffer(img[p:p + 2 * SIZES[l + 1]], dtype="<i2").astype(np.int64)
            B.append(b)
            p += 2 * SIZES[l + 1]
        return Net(W, B, list(img[p:p + NL]))

    # ---- block-RAM contents
    def lane_columns(self):
        """(LANES, WORDS_PER_BANK) uint8: what each lane's column holds for one bank."""
        col = np.zeros((LANES, WORDS_PER_BANK), dtype=np.uint8)
        for l in range(NL):
            for j in range(SIZES[l + 1]):
                b = int(self.B[l][j]) & 0xFFFF
                col[j, BASE[l]] = b & 0xFF
                col[j, BASE[l] + 1] = b >> 8
                col[j, BASE[l] + 2:BASE[l] + 2 + SIZES[l]] = self.W[l][j] & 0xFF
        return col


def image_address(k):
    """Where wire-image byte k goes: ('w', lane, word) / ('b', lane, word) / ('s', layer, 0)."""
    if k < N_W:
        for l in range(NL):
            n = SIZES[l] * SIZES[l + 1]
            if k < n:
                j, i = divmod(k, SIZES[l])
                return ("w", j, BASE[l] + 2 + i)
            k -= n
    k -= N_W
    if k < 2 * N_B:
        for l in range(NL):
            n = 2 * SIZES[l + 1]
            if k < n:
                j, byte = divmod(k, 2)
                return ("b", j, BASE[l] + byte)
            k -= n
    k -= 2 * N_B
    return ("s", k, 0)


def ram_images(bank0, bank1=None):
    """32 lists of 1024 16-bit words for the RAMs. bank1=None -> upload slot all zero."""
    rams = np.zeros((N_RAM, RAM_DEPTH), dtype=np.uint16)
    for bank, net in ((0, bank0), (1, bank1)):
        if net is None:
            continue
        col = net.lane_columns().astype(np.uint16)
        for r in range(N_RAM):
            rams[r, bank * BANK_WORDS:bank * BANK_WORDS + WORDS_PER_BANK] = \
                col[2 * r] | (col[2 * r + 1] << 8)
    return rams


def to_json(net, name, title, extra=None):
    d = {
        "name": name, "title": title,
        "shape": SIZES,
        "weights": [net.W[l].tolist() for l in range(NL)],
        "biases": [net.B[l].tolist() for l in range(NL)],
        "shifts": net.S,
        "image_bytes": IMG_BYTES,
        "crc32": f"{net.crc32():08X}",
    }
    if extra:
        d.update(extra)
    return d


def from_json(d):
    net = Net(d["weights"], d["biases"], d["shifts"])
    if "crc32" in d and int(d["crc32"], 16) != net.crc32():
        raise ValueError("numbers do not match the CRC-32 stored in the file")
    return net
