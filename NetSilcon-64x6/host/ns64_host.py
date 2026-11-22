"""
NetSilcon-64x6 PC host: talk to the 16 -> 64x6 -> 16 network on the Tang Nano 20K.

Install once:   pip install pyserial numpy

Usage (COM7 = the board's serial port):
    python ns64_host.py COM7 --info                               which model is running?
    python ns64_host.py COM7 --test                               golden vectors of the running model
    python ns64_host.py COM7 --test --count 200                   only the first 200
    python ns64_host.py COM7 --random 500                         500 random inputs vs the Python model
    python ns64_host.py COM7 --values 0 10 20 ... (16 numbers)    one inference, inputs 0..127
    python ns64_host.py COM7 --load ../models/stress.json --corrupt   damaged upload: must be REFUSED
    python ns64_host.py COM7 --load ../models/stress.json         upload a model (about 2 s)
    python ns64_host.py COM7 --linksweep 300                      link diagnosis: every combination of
                                                                  1/2 stop bits x reply delay x reply type
                                                                  (needs the bitstream with D1/D2 commands)
    python ns64_host.py COM7 --linksweep2 200                     link diagnosis 2: request length (0/4/16
                                                                  ignored 00 bytes sent first) x reply length
                                                                  (D2 counting pattern, 1..8 and 20 bytes)
    python ns64_host.py COM7 --linktest 2000                      UART link only: N info replies (7 bytes,
                                                                  always the same) + N replies of ONE fixed
                                                                  inference (20 bytes, always the same);
                                                                  counts every damaged reply, no retries

The tool first asks the chip which model it runs (C5, by CRC-32) and finds that model
in models/*.json. Every chip answer is compared with the bit-exact Python model in
model/ns64.py.

Every run is recorded in logs/ (next to this folder):
    <date_time>_<mode>.log   everything shown on screen + setup details + any error
    <date_time>_<mode>.csv   one row per inference: inputs, raw reply, chip and Python outputs,
                             match, argmax, latency, round-trip time
"""
import argparse
import collections
import csv
import datetime
import glob
import json
import os
import platform
import sys
import time
import traceback
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "model"))
import numpy as np  # noqa: E402
import ns64  # noqa: E402

try:
    import serial
except ImportError:
    sys.exit("pyserial is missing. Run:  pip install pyserial")

MODELS = os.path.join(ROOT, "models")
LOGS = os.path.join(ROOT, "logs")
CLOCK_MHZ = 27.0
STATUS = {0: "LOADED", 1: "REFUSED - CRC error", 2: "REFUSED - timeout (frame incomplete)",
          3: "REFUSED - a shift is larger than 23"}


# ------------------------------------------------------------------ logging
class Log:
    def __init__(self, mode):
        os.makedirs(LOGS, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.base = os.path.join(LOGS, f"{stamp}_{mode}")
        self.f = open(self.base + ".log", "w", encoding="utf-8")
        self.csvf = None
        self.w = None

    def __call__(self, s=""):
        print(s)
        self.f.write(s + "\n")
        self.f.flush()

    def row(self, d):
        if self.w is None:
            self.csvf = open(self.base + ".csv", "w", newline="", encoding="utf-8")
            self.w = csv.DictWriter(self.csvf, fieldnames=list(d.keys()))
            self.w.writeheader()
        self.w.writerow(d)
        self.csvf.flush()

    def close(self):
        self.f.close()
        if self.csvf:
            self.csvf.close()


# ------------------------------------------------------------------ models
def load_models():
    out = {}
    for p in sorted(glob.glob(os.path.join(MODELS, "*.json"))):
        try:
            d = json.load(open(p, encoding="utf-8"))
            net = ns64.from_json(d)
            out[net.crc32()] = (d, net, p)
        except Exception as e:                       # one broken file must not stop the others
            print(f"(skipping {os.path.basename(p)}: {e})")
    return out


# ------------------------------------------------------------------ chip protocol
class Chip:
    def __init__(self, port):
        # The timeout is set ONCE here and never changed afterwards (see read_exact).
        self.s = serial.Serial(port, 115200, bytesize=8, parity="N", stopbits=1, timeout=0.1)
        time.sleep(0.05)
        self.s.reset_input_buffer()
        self.link_errors = 0

    def read_exact(self, n, timeout):
        """Read n bytes or give up after `timeout` seconds. NEVER changes self.s.timeout:
        on Windows every timeout change calls SetCommState, the driver re-sends the line
        settings to the board's USB bridge (BL616) and it re-initialises its UART, which
        damaged FPGA replies that were arriving at that moment (found 22 Nov 2026)."""
        buf, deadline = b"", time.perf_counter() + timeout
        while len(buf) < n and time.perf_counter() < deadline:
            buf += self.s.read(n - len(buf))            # returns early when the bytes are there
        return buf

    def _read(self, n, timeout):
        r = self.read_exact(n, timeout)
        if len(r) != n:
            raise IOError(f"expected {n} reply bytes, got {len(r)}: {r.hex()}")
        return r

    def info(self, log=None, tries=3):
        """C5 is read-only, so a damaged reply can safely be asked again. Every retry is logged."""
        for t in range(1, tries + 1):
            self.s.write(b"\xC5")
            try:
                r = self._read(7, 1.0)
                if r[0] != 0x5C:
                    raise IOError(f"bad info reply {r.hex()}")
                return int.from_bytes(r[1:5], "little"), r[5], r[6], r
            except IOError as e:
                if log:
                    log(f"  WARNING: info attempt {t}/{tries} failed ({e}); flushing and asking again")
                if t == tries:
                    raise
                time.sleep(0.05)
                self.s.reset_input_buffer()

    def infer(self, x, log=None, tries=3):
        """An inference changes nothing on the chip, so a reply damaged on the way to the PC
        (wrong length, wrong header, argmax > 15) is asked again. self.link_errors counts them;
        they are reported separately from wrong answers (mismatches)."""
        assert len(x) == 16 and all(0 <= v <= 127 for v in x)
        for t in range(1, tries + 1):
            t0 = time.perf_counter()
            self.s.write(bytes([0xA5] + [int(v) for v in x]))
            try:
                r = self._read(20, 1.0)
                if r[0] != 0x5A or r[17] > 15:
                    raise IOError(f"bad inference reply {r.hex()}")
            except IOError as e:
                self.link_errors += 1
                if log:
                    log(f"  LINK ERROR (attempt {t}/{tries}): {e}; flushing and asking again")
                if t == tries:
                    raise
                time.sleep(0.05)
                self.s.reset_input_buffer()
                continue
            rt = (time.perf_counter() - t0) * 1000
            y = [b - 256 if b > 127 else b for b in r[1:17]]
            return y, r[17], int.from_bytes(r[18:20], "little"), rt, r, t - 1

    def load(self, frame):
        t0 = time.perf_counter()
        self.s.write(b"\xC3" + frame)
        r = self._read(7, 10.0)
        dt = time.perf_counter() - t0
        if r[0] != 0x3C:
            raise IOError(f"bad load reply {r.hex()}")
        return r[1], int.from_bytes(r[2:6], "little"), r[6], dt, r


# ------------------------------------------------------------------ actions
def show_info(chip, models, log):
    crc, src, loads, raw = chip.info(log)
    name = models[crc][0]["name"] if crc in models else "UNKNOWN (not in models/)"
    log(f"chip runs: {name}  CRC-32 {crc:08X}  source={'uploaded' if src else 'built-in'}  "
        f"uploads since power-up={loads}   raw {raw.hex()}")
    return crc


def run_inferences(chip, net, inputs, log, label, expected=None):
    bad, lats, rts = 0, [], []
    for k, x in enumerate(inputs):
        y, am, lat, rt, raw, retries = chip.infer(x, log)
        ref = expected[k] if expected is not None else net.forward(np.array(x))[0].tolist()
        ref = [int(v) for v in ref]
        ref_am = int(np.argmax(ref))
        ok = (y == ref) and (am == ref_am)
        bad += not ok
        lats.append(lat)
        rts.append(rt)
        log.row({"label": label, "index": k, "inputs": " ".join(map(str, x)), "reply_hex": raw.hex(),
                 "chip_y": " ".join(map(str, y)), "python_y": " ".join(map(str, ref)),
                 "chip_argmax": am, "python_argmax": ref_am, "match": int(ok),
                 "latency_clocks": lat, "round_trip_ms": f"{rt:.2f}", "link_retries": retries})
        if not ok and bad <= 5:
            log(f"  MISMATCH #{k}: x={x}\n     chip   {y} argmax {am}\n     python {ref} argmax {ref_am}")
        if (k + 1) % 100 == 0:
            log(f"  ... {k + 1}/{len(inputs)} done, {bad} mismatches")
    log(f"{label}: {len(inputs)} inferences, {bad} mismatches")
    log(f"link errors (replies damaged between FPGA and PC, asked again): {chip.link_errors}")
    if lats:
        log(f"chip latency {min(lats)}..{max(lats)} clocks = {max(lats) / CLOCK_MHZ:.2f} us at "
            f"{CLOCK_MHZ:.0f} MHz;  USB round trip avg {sum(rts) / len(rts):.1f} ms, max {max(rts):.1f} ms")
    log(f"RESULT: {'PASS' if bad == 0 else 'FAIL'}")
    return bad == 0


def do_load(chip, path, corrupt, log):
    d = json.load(open(path, encoding="utf-8"))
    net = ns64.from_json(d)
    img = net.image()
    crc = zlib.crc32(img) & 0xFFFFFFFF
    frame = bytearray(img + crc.to_bytes(4, "little"))
    log(f"model {d['name']}: {len(img)} image bytes, CRC-32 {crc:08X}, frame {len(frame) + 1} bytes")
    if corrupt:
        frame[12345] ^= 0x10
        log("  --corrupt: flipped bit 4 of byte 12345 (a layer-2 weight). The chip must refuse it.")
    st, chip_crc, loads, dt, raw = chip.load(bytes(frame))
    log(f"chip reply: {STATUS.get(st, f'status {st}')}  chip CRC-32 {chip_crc:08X}  loads={loads}  "
        f"time {dt * 1000:.0f} ms   raw {raw.hex()}")
    ok = (st == 1) if corrupt else (st == 0 and chip_crc == crc)
    log(f"RESULT: {'PASS' if ok else 'FAIL'}"
        + (" (refused as expected)" if corrupt and ok else ""))
    return ok


def link_test(chip, n, log):
    """Measure the FPGA -> PC link alone. The same request is sent n times; the chip must give
    the same bytes every time (the model does not change), so any difference is transport damage."""
    log(f"link test: {n} x C5 (7-byte reply) and {n} x one fixed inference (20-byte reply), no retries")
    results = {}
    for kind, req, nbytes in (("info", b"\xC5", 7), ("inference", bytes([0xA5] + [64] * 16), 20)):
        ref, bad, short, empty, t0 = None, 0, 0, 0, time.perf_counter()
        for k in range(n):
            chip.s.write(req)
            r = chip.read_exact(nbytes, 0.3)
            if ref is None and len(r) == nbytes:
                ref = r
            ok = (r == ref)
            if not ok:
                bad += 1
                short += 0 < len(r) < nbytes
                empty += len(r) == 0
                if bad <= 15:
                    log(f"  {kind} #{k}: {len(r)} bytes {r.hex(' ')}   expected {ref.hex(' ') if ref else '?'}")
                time.sleep(0.05)
                chip.s.reset_input_buffer()
            log.row({"kind": kind, "index": k, "bytes": len(r), "reply_hex": r.hex(), "ok": int(ok)})
        dt = time.perf_counter() - t0
        results[kind] = bad
        log(f"{kind}: {n} replies of {nbytes} bytes, {bad} damaged ({short} short, {empty} missing, "
            f"{bad - short - empty} same length but wrong) = {bad / n * 100:.2f} % of replies, "
            f"{bad / (n * nbytes) * 1e6:.0f} per million bytes;  reference reply {ref.hex(' ') if ref else '?'};  "
            f"{dt:.1f} s")
    log(f"RESULT: {'PASS (no damaged replies)' if sum(results.values()) == 0 else 'LINK ERRORS SEEN'}")
    return sum(results.values()) == 0


def link_sweep(chip, n, log):
    """Find what damages FPGA -> PC replies: for each setting (stop bits, wait before reply) send
    each kind of request n times without retries and count replies that differ from the first good one."""
    def setcfg(stop2, dly):
        for _ in range(5):
            chip.s.reset_input_buffer()
            chip.s.write(bytes([0xD1, stop2, dly]))
            r = chip.read_exact(3, 0.3)
            if r == bytes([0x1D, stop2, dly]):
                return True
            time.sleep(0.05)
        raise IOError(f"D1 {stop2} {dly} not acknowledged (last reply {r.hex(' ')}) - old bitstream?")

    tests = [("info C5", b"\xC5", 7), ("inference", bytes([0xA5] + [64] * 16), 20),
             ("pattern 5 x 00", bytes([0xD2, 5, 0]), 6), ("pattern 7 counting", bytes([0xD2, 7, 2]), 8),
             ("pattern 20 counting", bytes([0xD2, 20, 2]), 21), ("pattern 64 counting", bytes([0xD2, 64, 2]), 65),
             ("pattern 20 x 55", bytes([0xD2, 20, 3]), 21)]
    settings = [(0, 0), (1, 0), (0, 8), (1, 8), (0, 64)]
    log(f"link sweep: {len(settings)} settings x {len(tests)} reply types x {n} requests, no retries")
    log("setting: s = stop bits - 1, d = wait d*256 clocks (9.5 us per step) before every reply")
    table = []
    for stop2, dly in settings:
        setcfg(stop2, dly)
        row = []
        for name, req, nb in tests:
            if req[0] == 0xD2:          # exact expected pattern
                pat = {0: [0] * req[1], 1: [255] * req[1], 2: list(range(req[1])), 3: [0x55] * req[1]}[req[2]]
                ref = bytes([0x2D] + pat)
            else:                       # majority of 5 replies (a single damaged one cannot win)
                votes = collections.Counter()
                for _ in range(5):
                    chip.s.write(req); votes[chip.read_exact(nb, 0.3)] += 1
                    time.sleep(0.01)
                ref = votes.most_common(1)[0][0]
                chip.s.reset_input_buffer()
            bad = 0
            for k in range(n):
                chip.s.write(req)
                r = chip.read_exact(nb, 0.3)
                ok = r == ref
                if not ok:
                    bad += 1
                    time.sleep(0.05)
                    chip.s.reset_input_buffer()
                log.row({"stop_bits": stop2 + 1, "wait_clocks": dly * 256, "reply": name, "index": k,
                         "bytes": len(r), "reply_hex": r.hex(), "ok": int(ok)})
            row.append(bad)
            log(f"  {stop2 + 1} stop, wait {dly * 256:5d} clk | {name:20s} ({nb:2d} B): {bad:4d} / {n} damaged")
        table.append(row)
    setcfg(0, 0)
    log("")
    log("damaged replies out of " + str(n) + " per cell")
    log(f"{'setting':22s}" + "".join(f"{t[0][:14]:>16s}" for t in tests))
    for (stop2, dly), row in zip(settings, table):
        log(f"{f'{stop2 + 1} stop, wait {dly * 256} clk':22s}" + "".join(f"{b:16d}" for b in row))
    log("chip set back to 1 stop bit, no wait (power-up setting)")
    log(f"RESULT: {'PASS (no damaged replies)' if sum(map(sum, table)) == 0 else 'LINK ERRORS SEEN'}")
    return sum(map(sum, table)) == 0


def link_sweep2(chip, n, log):
    """Does the damage depend on the REQUEST length or the REPLY length? The FPGA ignores 00 bytes
    outside a frame, so P zero bytes in front of a D2 request make the request longer without
    changing the reply. Every reply is compared with the exact expected bytes."""
    chip.s.reset_input_buffer()
    chip.s.write(bytes([0xD1, 0, 0]))                    # 1 stop bit, no wait (power-up setting)
    log(f"D1 0 0 -> {chip.read_exact(3, 0.3).hex(' ')} (expected 1d 00 00)")
    pads = [0, 4, 16]
    lens = [1, 2, 3, 4, 5, 6, 7, 8, 20]                  # reply bytes incl. the 2D header
    log(f"link sweep 2: padding {pads} x reply length {lens} x {n} requests, no retries")
    table = {}
    for p in pads:
        for L in lens:
            req = bytes(p) + bytes([0xD2, L - 1, 2])
            exp = bytes([0x2D] + list(range(L - 1)))
            bad, first = 0, collections.Counter()
            for k in range(n):
                chip.s.write(req)
                r = chip.read_exact(L, 0.3)
                ok = r == exp
                if not ok:
                    bad += 1
                    pos = next((i for i in range(min(len(r), L)) if r[i] != exp[i]), min(len(r), L))
                    first[pos] += 1
                    time.sleep(0.05)
                    chip.s.reset_input_buffer()
                log.row({"pad": p, "reply_len": L, "index": k, "bytes": len(r), "reply_hex": r.hex(), "ok": int(ok)})
            table[(p, L)] = bad
            log(f"  pad {p:2d} + 3-byte request, reply {L:2d} B: {bad:4d} / {n} damaged   "
                f"first wrong byte at {dict(sorted(first.items()))}")
    log("")
    log(f"damaged replies out of {n}   (rows: zero bytes sent before the request; columns: reply length)")
    log(f"{'request':>16s}" + "".join(f"{L:6d}B" for L in lens))
    for p in pads:
        log(f"{f'{p + 3} bytes':>16s}" + "".join(f"{table[(p, L)]:7d}" for L in lens))
    log(f"RESULT: {'PASS (no damaged replies)' if sum(table.values()) == 0 else 'LINK ERRORS SEEN'}")
    return sum(table.values()) == 0


def main():
    ap = argparse.ArgumentParser(description="NetSilcon-64x6 host")
    ap.add_argument("port")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--info", action="store_true")
    g.add_argument("--test", action="store_true")
    g.add_argument("--random", type=int, metavar="N")
    g.add_argument("--values", type=int, nargs=16, metavar="X")
    g.add_argument("--load", metavar="MODEL.json")
    g.add_argument("--linktest", type=int, metavar="N")
    g.add_argument("--linksweep", type=int, metavar="N")
    g.add_argument("--linksweep2", type=int, metavar="N")
    ap.add_argument("--corrupt", action="store_true")
    ap.add_argument("--count", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()

    mode = ("info" if a.info else "test" if a.test else "random" if a.random else
            "values" if a.values else "linktest" if a.linktest else "linksweep" if a.linksweep else "linksweep2" if a.linksweep2 else
            ("load_corrupt" if a.corrupt else "load"))
    log = Log(mode)
    log(f"NetSilcon-64x6 host  {datetime.datetime.now().isoformat(timespec='seconds')}  "
        f"port {a.port}  Python {platform.python_version()}  {platform.platform()}")
    log(f"command: {' '.join(sys.argv)}")
    ok = False
    try:
        models = load_models()
        chip = Chip(a.port)
        crc = show_info(chip, models, log)
        if a.linktest:
            ok = link_test(chip, a.linktest, log)
        elif a.linksweep:
            ok = link_sweep(chip, a.linksweep, log)
        elif a.linksweep2:
            ok = link_sweep2(chip, a.linksweep2, log)
        elif a.load:
            ok = do_load(chip, a.load, a.corrupt, log)
            show_info(chip, models, log)
        else:
            if crc not in models:
                raise RuntimeError("the running model is not in models/ - cannot compare")
            d, net, _ = models[crc]
            if a.info:
                ok = True
            elif a.test:
                tv = d["test_vectors"][:a.count] if a.count else d["test_vectors"]
                ok = run_inferences(chip, net, [v["x"] for v in tv], log, f"{d['name']} golden",
                                    [v["y"] for v in tv])
            elif a.random:
                rng = np.random.default_rng(a.seed)
                xs = rng.integers(0, 128, size=(a.random, 16)).tolist()
                ok = run_inferences(chip, net, xs, log, f"{d['name']} random seed {a.seed}")
            else:
                ok = run_inferences(chip, net, [a.values], log, f"{d['name']} values")
                log(f"inputs {a.values}")
    except Exception as e:
        log(f"ERROR: {e}")
        log(traceback.format_exc())
    log(f"log files: {log.base}.log" + (f" and {log.base}.csv" if log.w else ""))
    log.close()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
