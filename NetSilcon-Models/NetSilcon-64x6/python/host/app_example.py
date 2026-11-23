"""
Use a NetSilcon-64x6 model inside your own program: real sensor values in, a decision out.

    # no board: the bit-exact Python model answers (same numbers as the FPGA)
    python app_example.py --model ../../models/pump_health/pump_health.json --sim --csv ../../data/pump_vibration.csv --rows 10

    # the real FPGA answers (upload the model first with ns64_host.py --load)
    python app_example.py --model ../../models/pump_health/pump_health.json --port COM7 --csv ../../data/pump_vibration.csv --rows 10

    # one reading, given by column name
    python app_example.py --model ../../models/pump_health/pump_health.json --sim --set rpm=2900 band_1x=5.2 temp_c=48

Copy the three functions below (scale_inputs, decode, NetSilconChip) into your own code; that is all
an application needs. The model file says how each input is scaled and what each output means.
"""
import argparse
import csv
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "model"))
import ns64  # noqa: E402


def scale_inputs(model, values):
    """values: {column name: real value}. Returns the 16 chip inputs 0..127."""
    q = [0] * 16
    for k, inp in enumerate(model["inputs"]):
        if inp["name"].startswith("unused"):
            continue
        r = inp["range"]
        lo, hi = (r if isinstance(r, list) else [0.0, float(r)])   # rover files store just the maximum
        k = inp.get("index", k)
        v = values.get(inp["name"], (lo + hi) / 2)          # a missing reading -> middle of its range
        q[k] = int(min(127, max(0, round((float(v) - lo) / (hi - lo) * 127))))
    return q


def decode(model, y):
    """y: the chip's 16 signed outputs. Returns the decision in plain words / real units."""
    if model.get("kind") == "classification":
        c = model["classes"]
        k = max(range(len(c)), key=lambda i: y[i])
        return c[k], {c[i]: y[i] for i in range(len(c))}
    out = {}
    for t in model.get("targets", []):
        lo, hi = t["range"]
        out[t["name"]] = lo + (y[t["index"]] / 127 + 1) / 2 * (hi - lo)
    if not out:                                             # e.g. the rover: outputs are value x 127
        out = {name: y[k] / 127 for k, name in enumerate(model["outputs"]) if not name.startswith("unused")}
    return out, None


class NetSilconChip:
    """Minimal UART client: A5 + 16 inputs -> 5A + 16 outputs + argmax + latency (20 bytes)."""

    def __init__(self, port):
        import serial                                       # pip install pyserial
        self.s = serial.Serial(port, 115200, timeout=0.1)   # set once, never changed (see ns64_host.py)
        time.sleep(0.05)
        self.s.reset_input_buffer()

    def crc(self):
        self.s.write(b"\xC5")
        r = self._read(7)
        return int.from_bytes(r[1:5], "little")

    def infer(self, q):
        self.s.write(bytes([0xA5] + q))
        r = self._read(20)
        if r[0] != 0x5A:
            raise IOError(f"bad reply {r.hex()}")
        return [b - 256 if b > 127 else b for b in r[1:17]]

    def _read(self, n, timeout=1.0):
        buf, end = b"", time.perf_counter() + timeout
        while len(buf) < n and time.perf_counter() < end:
            buf += self.s.read(n - len(buf))
        if len(buf) != n:
            raise IOError(f"expected {n} bytes, got {len(buf)}")
        return buf


class PythonModel:
    """Same answers as the FPGA, bit for bit (model/ns64.py)."""

    def __init__(self, model):
        self.net = ns64.from_json(model)

    def infer(self, q):
        return self.net.forward(q)[0].tolist()


def main():
    ap = argparse.ArgumentParser(description="NetSilcon-64x6 application example")
    ap.add_argument("--model", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--port", help="serial port of the board, e.g. COM7 or /dev/ttyUSB1")
    g.add_argument("--sim", action="store_true", help="no board: use the bit-exact Python model")
    ap.add_argument("--csv", help="read readings from a CSV file (columns named like the model inputs)")
    ap.add_argument("--rows", type=int, default=10)
    ap.add_argument("--set", nargs="+", metavar="NAME=VALUE", help="one reading by column name")
    a = ap.parse_args()

    model = json.load(open(a.model))
    net = PythonModel(model)
    engine = net if a.sim else NetSilconChip(a.port)
    if not a.sim:
        crc = engine.crc()
        want = int(model["crc32"], 16)
        print(f"chip runs CRC-32 {crc:08X}" + ("" if crc == want else
              f"  - NOT this model ({want:08X}). Upload it first: python ns64_host.py {a.port} --load {a.model}"))
        if crc != want:
            sys.exit(1)
    print(f"model: {model['title']}  ({'Python, bit-exact' if a.sim else 'FPGA ' + a.port})")

    readings = []
    if a.set:
        readings.append(({k: float(v) for k, v in (s.split("=", 1) for s in a.set)}, None))
    if a.csv:
        with open(a.csv, newline="") as f:
            for i, row in enumerate(csv.DictReader(f)):
                if i == a.rows:
                    break
                truth = next((row[k] for k in row if k not in {x["name"] for x in model["inputs"]}), None)
                readings.append(({k: float(v) for k, v in row.items() if k in {x["name"] for x in model["inputs"]}}, truth))
    if not readings:
        sys.exit("give --csv or --set")

    right = 0
    for values, truth in readings:
        q = scale_inputs(model, values)
        t0 = time.perf_counter()
        y = engine.infer(q)
        ms = (time.perf_counter() - t0) * 1000
        if not a.sim and y != net.infer(q):                 # every chip answer is checked
            print("  MISMATCH with the Python model!")
        decision, scores = decode(model, y)
        if isinstance(decision, dict):
            shown = ", ".join(f"{k} = {v:.4g}" for k, v in decision.items())
        else:
            shown = decision
            right += truth == decision
        print(f"  {shown:<40s}" + (f" (true: {truth})" if truth else "") + f"   {ms:.2f} ms")
    if model.get("kind") == "classification" and any(t for _, t in readings):
        print(f"{right} of {sum(1 for _, t in readings if t)} rows correct")


if __name__ == "__main__":
    main()
