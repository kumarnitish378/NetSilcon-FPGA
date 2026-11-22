"""
NetSilcon-6x4 PC host: talk to the neural network running on the Tang Nano 20K.

Install once:   pip install pyserial

Usage (COM7 = the board's port, see Device Manager -> Ports):
    python netsilcon_host.py COM7 --info                         which model is running?
    python netsilcon_host.py COM7 --load ../models/irrigation/irrigation.json   give the chip a new job
    python netsilcon_host.py COM7 --load ../models/irrigation/irrigation.json --corrupt
                                                                  send a damaged model on purpose:
                                                                  the chip must refuse it
    python netsilcon_host.py COM7 --values 25 35 40 30           one reading in real units
                                                                  (rover: FL FR RL RR in metres)
    python netsilcon_host.py COM7 --demo                         the model's demo scenarios
    python netsilcon_host.py COM7 --test                         all golden vectors, bit-exact
    python netsilcon_host.py COM7 --interactive                  type readings one by one

The script first asks the chip which model it is running (by CRC) and then uses that
model's input names, units, labels, demo and test vectors from models/<app>/*.json.
For every answer it also runs the same int8 model in Python and shows whether the
FPGA result matches it exactly.

Models: one folder per application in models/: motor_fault/ (the built-in one), irrigation/, rover/.
Make new ones with  model/make_model.py.

Every run is recorded in host/logs/ :
    <date_time>_<mode>.log   everything shown on screen + setup details + any error
    <date_time>_<mode>.csv   one row per inference: inputs, raw bytes sent/received,
                             FPGA answer, Python answer, match, latency, round-trip time
"""
import argparse
import csv
import datetime
import glob
import hashlib
import json
import os
import platform
import re
import sys
import time
import traceback

try:
    import serial
except ImportError:
    sys.exit("pyserial is missing. Run:  pip install pyserial")

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.join(HERE, "..", "gen")
MODELS = os.path.join(HERE, "..", "models")
SIZES = [4, 6, 6, 6, 6, 2]
CLOCK_MHZ = 27.0


# ------------------------------------------------------------------ model math (bit-exact copy of the hardware)
def s8(v):  return v - 256 if v > 127 else v
def s16(v): return v - 65536 if v > 32767 else v


def model_int8(x, w, b, sh):
    """Bit-exact integer reference of rtl/nn_layer.v"""
    a, wi, bi = list(x), 0, 0
    for l in range(5):
        n_in, n_out = SIZES[l], SIZES[l + 1]
        out = []
        for j in range(n_out):
            acc = b[bi + j] + sum(a[i] * w[wi + j * n_in + i] for i in range(n_in))
            if l < 4:
                acc = max(acc, 0)
            s = sh[l]
            y = (acc + ((1 << (s - 1)) if s else 0)) >> s
            out.append(min(max(y, 0), 127) if l < 4 else min(max(y, -128), 127))
        wi += n_in * n_out
        bi += n_out
        a = out
    return a


def crc16(data, crc=0xFFFF):
    """CRC-16/CCITT-FALSE, same as board/ns_loader.v"""
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def image(w, b, sh):
    """The 201 bytes the chip receives: 144 weights, 26 biases (low byte first), 5 shifts."""
    out = bytes(v & 0xFF for v in w)
    for v in b:
        out += bytes([v & 0xFF, (v >> 8) & 0xFF])
    return out + bytes(sh)


class Model:
    def __init__(self, d, path):
        self.d, self.path = d, path
        self.name, self.title = d["name"], d["title"]
        self.w, self.b, self.sh = d["weights"], d["biases"], d["shifts"]
        assert len(self.w) == 144 and len(self.b) == 26 and len(self.sh) == 5, "wrong model shape"
        assert all(-128 <= v <= 127 for v in self.w) and all(-32768 <= v <= 32767 for v in self.b)
        assert all(0 <= s <= 15 for s in self.sh)
        self.img = image(self.w, self.b, self.sh)
        self.crc = crc16(self.img)
        self.names = [i["name"] for i in d["inputs"]]
        self.units = [i["unit"] for i in d["inputs"]]
        self.ranges = [float(i["range"]) for i in d["inputs"]]
        self.labels = d["outputs"]

    @property
    def regression(self):
        return self.d.get("kind") == "regression"

    def ref(self, q):
        return model_int8(q, self.w, self.b, self.sh)

    def to_q(self, values):
        return [min(max(int(round(v / r * 127)), 0), 127) for v, r in zip(values, self.ranges)]

    def short(self):
        return f"{self.title} [{self.name}, CRC {self.crc:04X}]"


def load_model_file(path):
    with open(path, encoding="utf-8") as fh:
        m = Model(json.load(fh), path)
    if "crc16" in m.d and int(m.d["crc16"], 16) != m.crc:
        raise ValueError(f"{path}: numbers do not match the CRC stored in the file (file edited or damaged)")
    return m


def all_models():
    out = []
    for p in sorted(glob.glob(os.path.join(MODELS, "**", "*.json"), recursive=True)):
        try:
            out.append(load_model_file(p))
        except Exception as e:                       # a broken file must not stop the others
            print(f"(skipping {os.path.basename(p)}: {e})")
    return out


def builtin_crc():
    """CRC of the model compiled into the bitstream (gen/*.mem + netsilcon_params.vh)."""
    w = [s8(int(l, 16)) for l in open(os.path.join(GEN, "weights.mem")) if l.strip()]
    b = [s16(int(l, 16)) for l in open(os.path.join(GEN, "biases.mem")) if l.strip()]
    sh = [int(m) for m in re.findall(r"SHIFT\d\s*=\s*(\d+)", open(os.path.join(GEN, "netsilcon_params.vh")).read())]
    return crc16(image(w, b, sh))


# ------------------------------------------------------------------ run log
class RunLog:
    def __init__(self, mode, port):
        d = os.path.join(HERE, "logs")
        os.makedirs(d, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base = os.path.join(d, f"{stamp}_{mode}")
        self.log_path, self.csv_path = base + ".log", base + ".csv"
        self.log = open(self.log_path, "w", encoding="utf-8")
        self.csvf = open(self.csv_path, "w", newline="", encoding="utf-8")
        self.csv = csv.writer(self.csvf)
        self.csv.writerow(["time", "mode", "model", "in0", "in1", "in2", "in3", "q0", "q1", "q2", "q3",
                           "tx_hex", "rx_hex", "y0", "y1", "flag", "latency_clocks",
                           "ref_y0", "ref_y1", "match", "round_trip_ms"])
        self.mode = mode
        self._stdout = sys.stdout
        sys.stdout = self                        # tee: screen + log file
        files = {}
        for f in ("weights.mem", "biases.mem", "netsilcon_params.vh"):
            try:
                files[f] = hashlib.md5(open(os.path.join(GEN, f), "rb").read()).hexdigest()[:12]
            except OSError:
                files[f] = "MISSING"
        self.write_only(f"NetSilcon-6x4 host run  {datetime.datetime.now().isoformat(timespec='seconds')}\n"
                        f"mode={mode} port={port} python={platform.python_version()} "
                        f"pyserial={getattr(serial, '__version__', '?')} os={platform.platform()}\n"
                        f"built-in model files (md5): {files}\n{'-' * 70}\n")

    def write(self, text):
        self.log.write(text)                     # log first, so it is never lost
        self.log.flush()
        try:
            self._stdout.write(text)
        except (OSError, ValueError):
            pass

    def flush(self):
        try:
            self._stdout.flush()
        except (OSError, ValueError):
            pass

    def write_only(self, text):
        self.log.write(text)
        self.log.flush()

    def row(self, model, values, q, tx, rx, y0, y1, flag, lat, ref, rtt):
        v = list(values) if values else ["", "", "", ""]
        self.csv.writerow([datetime.datetime.now().isoformat(timespec="milliseconds"), self.mode, model.name,
                           *v, *q, tx.hex(), rx.hex(), y0, y1, int(flag), lat, ref[0], ref[1],
                           int(ref == [y0, y1]), f"{rtt:.3f}"])
        self.csvf.flush()

    def close(self):
        self.write(f"\nLog saved:  {self.log_path}\nData saved: {self.csv_path}\n")
        sys.stdout = self._stdout
        self.log.close()
        self.csvf.close()


LOG = None


# ------------------------------------------------------------------ serial protocol
class NetSilcon:
    def __init__(self, port):
        self.s = serial.Serial(port, 115200, timeout=0.5)
        time.sleep(0.1)
        self.s.reset_input_buffer()

    def _xfer(self, tx, header, what, timeout=0.5):
        self.s.timeout = timeout
        t0 = time.perf_counter()
        self.s.write(tx)
        r = self.s.read(5)
        rtt = (time.perf_counter() - t0) * 1000
        if len(r) != 5 or r[0] != header:
            if LOG:
                LOG.write_only(f"ERROR ({what}): sent {tx[:8].hex()}.. got {r.hex() if r else 'nothing'}\n")
            raise RuntimeError(f"bad/no reply to {what}: {r.hex() if r else 'nothing'} "
                               "(is the new tangnano20k_uart bitstream loaded? is any Serial Monitor closed?)")
        return r, rtt

    def infer(self, q, model, values=None):
        tx = bytes([0xA5] + list(q))
        r, rtt = self._xfer(tx, 0x5A, "inference")
        y0, y1, flag, lat = s8(r[1]), s8(r[2]), bool(r[3] & 1), r[4]
        self.last_rtt = rtt
        if LOG:
            LOG.row(model, values, q, tx, r, y0, y1, flag, lat, model.ref(q), rtt)
        return y0, y1, flag, lat

    def info(self):
        r, _ = self._xfer(bytes([0xC5]), 0x5C, "info")
        return dict(crc=r[1] | (r[2] << 8), source=r[3], loads=r[4])

    def load(self, model, corrupt=False):
        crc = model.crc ^ (0x0001 if corrupt else 0)          # --corrupt: one wrong bit in the CRC
        tx = bytes([0xC3]) + model.img + bytes([crc >> 8, crc & 0xFF])
        r, rtt = self._xfer(tx, 0x3C, "load", timeout=2.0)
        return dict(status=r[1], crc=r[2] | (r[3] << 8), loads=r[4], ms=rtt, tx=tx)


def running_model(dev):
    """Ask the chip which model it runs and find the matching models/<app>/*.json."""
    inf = dev.info()
    crc = builtin_crc() if inf["source"] == 0 else inf["crc"]
    where = "built into the bitstream" if inf["source"] == 0 else "uploaded"
    for m in all_models():
        if m.crc == crc:
            print(f"Chip is running: {m.short()}  ({where}, uploads since power-up: {inf['loads']})")
            return m
    raise RuntimeError(f"chip runs a model with CRC {crc:04X} ({where}) that is not in models/. "
                       "Load a known one with --load, or rebuild models/motor_fault/motor_fault.json with make_model.py")


def drive_action(speed, steer, stop=0.08, turn=0.25):
    """speed/steer in -1..1 -> FWD, FWD-L, FWD-R, REV, REV-L, REV-R or STOP (same as make_model.py)"""
    if abs(speed) < stop:
        return "STOP"
    return ("FWD" if speed > 0 else "REV") + ("" if abs(steer) < turn else ("-R" if steer > 0 else "-L"))


def show(dev, model, values):
    q = model.to_q(values)
    y0, y1, flag, lat = dev.infer(q, model, values)
    ref = model.ref(q)
    ok = (ref == [y0, y1])
    txt = "  ".join(f"{n}={v:g}{u}" for n, v, u in zip(model.names, values, model.units))
    l0, l1 = model.labels
    if model.regression:              # continuous outputs: chip value / 127 = -1..+1
        sp, st = y0 / 127, y1 / 127
        print(f"{txt}\n  -> {drive_action(sp, st):6s} {l0} {sp * 100:+5.0f}%  {l1} {st * 100:+5.0f}% "
              f"({'right' if st > 0.05 else 'left' if st < -0.05 else 'straight'})  "
              f"| chip latency {lat} clocks ({lat / CLOCK_MHZ:.2f} us) | round trip {dev.last_rtt:.1f} ms "
              f"| Python model {'MATCH' if ok else 'MISMATCH ' + str(ref)}")
        return ok
    print(f"{txt}\n  -> {model.labels[1] if flag else model.labels[0]:8s} scores {l0}={y0:4d} {l1}={y1:4d}  "
          f"| chip latency {lat} clocks ({lat / CLOCK_MHZ:.2f} us) | round trip {dev.last_rtt:.1f} ms "
          f"| Python model {'MATCH' if ok else 'MISMATCH ' + str(ref)}")
    return ok


def run_tests(dev, model, limit=None):
    tests = model.d["tests"][:limit] if limit else model.d["tests"]
    bad, lats, t0 = 0, set(), time.perf_counter()
    for k, t in enumerate(tests):
        q, exp = t[:4], t[4:6]
        y0, y1, _, lat = dev.infer(q, model)
        lats.add(lat)
        if [y0, y1] != exp or model.ref(q) != exp:
            bad += 1
            if bad <= 5:
                print(f"MISMATCH #{k}: in={q} got {y0},{y1} expected {exp[0]},{exp[1]}")
    dt = time.perf_counter() - t0
    print(f"Vectors: {len(tests)}  mismatches: {bad}  chip latency: {sorted(lats)} clocks  "
          f"total {dt:.2f} s ({dt / len(tests) * 1000:.2f} ms per round trip, limited by USB serial)")
    return bad


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description="NetSilcon-6x4 live inference + model update host")
    ap.add_argument("port", help="serial port, e.g. COM7 (Windows) or /dev/ttyUSB1 (Linux)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--values", nargs=4, type=float, metavar="X", help="4 readings in real units")
    g.add_argument("--test", action="store_true", help="run all golden vectors of the running model")
    g.add_argument("--interactive", action="store_true")
    g.add_argument("--demo", action="store_true", help="demo scenarios of the running model")
    g.add_argument("--info", action="store_true", help="which model is the chip running?")
    g.add_argument("--load", metavar="MODEL.json", help="upload a new model into the chip")
    ap.add_argument("--corrupt", action="store_true", help="with --load: send a wrong CRC on purpose")
    a = ap.parse_args()
    if a.corrupt and not a.load:
        ap.error("--corrupt only works together with --load")

    global LOG
    mode = next(m for m in ("values", "test", "interactive", "demo", "info", "load") if getattr(a, m))
    if mode == "load" and a.corrupt:
        mode = "load_corrupt"
    LOG = RunLog(mode, a.port)
    try:
        run(a)
    except KeyboardInterrupt:
        print("\nStopped by user.")
    except Exception:
        LOG.write_only(traceback.format_exc())
        print("ERROR:", sys.exc_info()[1])
    finally:
        LOG.close()


def run(a):
    dev = NetSilcon(a.port)

    if a.load:
        new = load_model_file(a.load)
        print(f"Before: ", end="")
        try:
            old = running_model(dev)
        except RuntimeError as e:
            old = None
            print(e)
        print(f"Uploading {new.short()}\n  file {os.path.normpath(new.path)}, int8 accuracy "
              f"{new.d.get('accuracy_int8', 0) * 100:.2f}%, shifts {new.sh}")
        if a.corrupt:
            print("  --corrupt: the CRC sent is deliberately wrong by one bit")
        res = dev.load(new, corrupt=a.corrupt)
        LOG.write_only(f"load frame ({len(res['tx'])} bytes): {res['tx'].hex()}\n")
        print(f"  sent {len(res['tx'])} bytes, chip answered after {res['ms']:.1f} ms: ", end="")
        if res["status"] == 0:
            print(f"LOADED  (chip CRC {res['crc']:04X}, uploads since power-up: {res['loads']})")
            if res["crc"] != new.crc:
                print(f"  WARNING: chip CRC {res['crc']:04X} differs from file CRC {new.crc:04X}")
        else:
            print({1: "REFUSED - CRC error", 2: "REFUSED - timeout (frame incomplete)"}.get(res["status"], "?")
                  + ".  The old model keeps running.")
        print("After:  ", end="")
        now = running_model(dev)
        print("Quick check of the running model (64 golden vectors):")
        bad = run_tests(dev, now, limit=64)
        if a.corrupt:
            ok = res["status"] == 1 and (old is None or now.crc == old.crc) and bad == 0
            print("RESULT:", "PASS - damaged model refused, old model untouched" if ok else "FAIL")
        else:
            ok = res["status"] == 0 and now.crc == new.crc and bad == 0
            print("RESULT:", f"PASS - the chip is now running: {new.title}" if ok else "FAIL")
        return

    model = running_model(dev)

    if a.info:
        print(f"Inputs : " + ", ".join(f"{n} [{u}] 0..{r:g}" for n, u, r in zip(model.names, model.units, model.ranges)))
        if model.regression:
            print(f"Outputs: y0 = {model.labels[0]}, y1 = {model.labels[1]}  (continuous, chip value / 127 = -1..+1)")
        else:
            print(f"Outputs: y0 = {model.labels[0]}, y1 = {model.labels[1]}  (decision {model.labels[1]} if y1 > y0)")
        print(f"Shifts : {model.sh}")

    elif a.values:
        show(dev, model, a.values)

    elif a.test:
        bad = run_tests(dev, model)
        print("RESULT:", "PASS - live hardware matches the Python int8 model" if bad == 0 else "FAIL")

    elif a.interactive:
        print("Enter: " + " ".join(f"{n}_{u}" for n, u in zip(model.names, model.units)) + "   (empty line to quit)")
        while True:
            line = input("> ").strip()
            if not line:
                break
            try:
                vals = [float(v) for v in line.split()]
                if len(vals) != 4:
                    raise ValueError
                show(dev, model, vals)
            except ValueError:
                print("type 4 numbers")

    elif a.demo:
        bad = 0
        for i, sc in enumerate(model.d.get("demo", []), 1):
            print(f"\n=== {i}. {sc['title']} ===")
            for row in sc["rows"]:
                bad += not show(dev, model, row)
        print(f"\nRESULT: {'PASS - every answer matches the Python model' if bad == 0 else f'FAIL ({bad} mismatches)'}")


if __name__ == "__main__":
    main()
