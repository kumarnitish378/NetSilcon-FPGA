"""NetSilcon-6x4 rover simulator (2D, top view).

A small Ackermann robot drives through a virtual world. Two sensor options:
    --sensors beams    4 single-point LiDARs (TFmini-S style) at the corners
    --sensors scanner  one 360-degree LiDAR, reduced to 4 corner sectors (recommended)
Every 50 ms:
    LiDAR (ray cast) -> q = round(d / 4 m * 127) -> the chip's int8 network (bit-exact)
    -> speed, steering -> fixed logic (predictive safety stop, 3-point-turn supervisor)
    -> motors (with acceleration / steering-rate limits)

Run:
    python rover_sim.py --sensors scanner --unstick    batch test: 20 random starts x 4 worlds
    python rover_sim.py --compare                      all sensor / supervisor combinations
    python rover_sim.py --map room --seconds 60 --trace trace.csv    one drive, saves the path

Hardware-in-the-loop (the REAL chip on the Tang Nano 20K drives the virtual rover):
    python rover_sim.py --hil COM7 --map clutter --view     one live drive, watch it in a window
    python rover_sim.py --hil COM7                           HIL batch: 2 drives x 60 s on every world
  The rover model is uploaded to the chip automatically if it is not running yet.
  Every chip answer is also checked against the Python model; the log goes to results/logs/hil/.
  Needs: pip install pyserial   (and matplotlib for --view)

No extra packages beyond numpy.
"""
import argparse
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")          # NetSilcon-6x4/
MODEL = os.path.join(ROOT, "models", "rover", "rover.json")

# ---------------------------------------------------------------- robot (small test rover)
LENGTH, WIDTH = 0.50, 0.40          # m, body
WHEELBASE = 0.35                    # m
MAX_STEER = math.radians(30)        # front-wheel angle at steering = 100 %
MAX_SPEED = 0.8                     # m/s at speed = 100 %
ACCEL = 1.0                         # m/s^2   (motors cannot change speed instantly)
STEER_RATE = math.radians(120)      # deg/s   (steering actuator speed)
DT = 0.05                           # s, control loop 20 Hz
RANGE = 4.0                         # m, network input range (readings beyond -> 4 m = clear)
SAFETY = 0.20                       # m, fixed safety layer distance (network sectors / beams)
SIDE_SAFETY = 0.10                  # m, scanner: any point this close in the moving half -> stop
OUTWARD = math.radians(10)          # LiDARs turned 10 deg outward

# sensor: (x forward, y left) on the body, pointing angle relative to heading
SENSORS = {
    "FL": (LENGTH / 2, WIDTH / 2, +OUTWARD),
    "FR": (LENGTH / 2, -WIDTH / 2, -OUTWARD),
    "RL": (-LENGTH / 2, WIDTH / 2, math.pi - OUTWARD),
    "RR": (-LENGTH / 2, -WIDTH / 2, -math.pi + OUTWARD),
}


# 360-degree scanner mode: the closest obstacle in each corner sector, measured from the BODY edge
SECTORS = {"FL": (0, 30), "FR": (-30, 0), "RL": (150, 180), "RR": (-180, -150)}   # degrees
SCAN_STEP = 2                                                                     # degrees between rays


def body_extent(phi):
    """distance from the body centre to the body edge in direction phi (rectangle)"""
    c, s = abs(math.cos(phi)), abs(math.sin(phi))
    return min((LENGTH / 2) / c if c > 1e-9 else 1e9, (WIDTH / 2) / s if s > 1e-9 else 1e9)


# ---------------------------------------------------------------- the chip's network (bit-exact)
class Chip:
    SIZES = [4, 6, 6, 6, 6, 2]

    def __init__(self, path=MODEL, model=None):
        m = model if model is not None else json.load(open(path))
        self.w, self.b, self.sh = m["weights"], m["biases"], m["shifts"]
        if "tests" in m:
            self.check(m["tests"])

    def run(self, q):
        """Exact integer math of rtl/nn_layer.v"""
        a, wi, bi = list(q), 0, 0
        for l in range(5):
            n_in, n_out = self.SIZES[l], self.SIZES[l + 1]
            out = []
            for j in range(n_out):
                acc = self.b[bi + j] + sum(a[i] * self.w[wi + j * n_in + i] for i in range(n_in))
                if l < 4:
                    acc = max(acc, 0)
                s = self.sh[l]
                y = (acc + ((1 << (s - 1)) if s else 0)) >> s
                out.append(min(max(y, 0), 127) if l < 4 else min(max(y, -128), 127))
            wi += n_in * n_out
            bi += n_out
            a = out
        return a

    def check(self, tests):
        bad = sum(self.run(t[:4]) != t[4:6] for t in tests)
        assert bad == 0, f"network does not match the golden vectors ({bad} mismatches)"


# ---------------------------------------------------------------- the REAL chip over USB serial (HIL)
def crc16(data, crc=0xFFFF):
    """CRC-16/CCITT-FALSE, same as board/ns_loader.v"""
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


class HilChip:
    """Sends the 4 inputs to NetSilcon on the Tang Nano 20K and returns its answer.
    Uses the same UART protocol as host/netsilcon_host.py. Also runs the Python model on
    every step and counts any difference (there should be none)."""

    def __init__(self, port, model_path=MODEL, log_path=None):
        import serial
        self.ref = Chip(model_path)
        m = json.load(open(model_path))
        img = bytes(v & 0xFF for v in m["weights"])
        for v in m["biases"]:
            img += bytes([v & 0xFF, (v >> 8) & 0xFF])
        img += bytes(m["shifts"])
        self.crc = crc16(img)
        self.name = m.get("title", os.path.basename(model_path))
        self.s = serial.Serial(port, 115200, timeout=0.5)
        import time
        time.sleep(0.1)
        self.s.reset_input_buffer()
        info = self._xfer(bytes([0xC5]), 0x5C)
        chip_crc = info[1] | (info[2] << 8)
        if info[3] != 1 or chip_crc != self.crc:
            print(f"Chip runs CRC {chip_crc:04X} (source {info[3]}), need {self.crc:04X}: uploading {self.name} ...")
            r = self._xfer(bytes([0xC3]) + img + bytes([self.crc >> 8, self.crc & 0xFF]), 0x3C, timeout=2.0)
            if r[1] != 0:
                raise RuntimeError(f"chip refused the model upload (status {r[1]})")
        print(f"HIL: real chip on {port} is running {self.name} [CRC {self.crc:04X}]")
        self.steps = self.mismatch = 0
        self.rtts, self.lats = [], set()
        self.log = open(log_path, "w") if log_path else None
        if self.log:
            self.log.write("step,q0,q1,q2,q3,chip_y0,chip_y1,python_y0,python_y1,match,latency_clocks,round_trip_ms\n")

    def _xfer(self, tx, header, timeout=0.5):
        self.s.timeout = timeout
        self.s.write(tx)
        r = self.s.read(5)
        if len(r) != 5 or r[0] != header:
            raise RuntimeError(f"bad/no reply from the board: {r.hex() if r else 'nothing'} "
                               "(milestone-2 bitstream loaded? serial monitor closed? right COM port?)")
        return r

    def run(self, q):
        import time
        t0 = time.perf_counter()
        r = self._xfer(bytes([0xA5] + list(q)), 0x5A)
        rtt = (time.perf_counter() - t0) * 1000
        y = [r[1] - 256 if r[1] > 127 else r[1], r[2] - 256 if r[2] > 127 else r[2]]
        ref = self.ref.run(q)
        self.steps += 1
        self.mismatch += ref != y
        self.rtts.append(rtt)
        self.lats.add(r[4])
        if self.log:
            self.log.write(f"{self.steps},{q[0]},{q[1]},{q[2]},{q[3]},{y[0]},{y[1]},{ref[0]},{ref[1]},"
                           f"{int(ref == y)},{r[4]},{rtt:.2f}\n")
        return y

    def summary(self):
        r = np.array(self.rtts) if self.rtts else np.zeros(1)
        return (f"HIL chip answers: {self.steps}   mismatches vs Python model: {self.mismatch}   "
                f"chip latency {sorted(self.lats)} clocks   USB round trip avg {r.mean():.1f} ms, max {r.max():.1f} ms")


# ---------------------------------------------------------------- worlds
def box(x0, y0, x1, y1):
    return [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]


def make_world(name, seed=0):
    """Returns (segments, circles, size). circles = (cx, cy, r)."""
    rng = np.random.default_rng(seed)
    segs, circ = [], []
    if name == "room":                                   # 8 x 6 m room with 4 pillars and a table
        segs += box(0, 0, 8, 6)
        circ += [(2.5, 2.0, 0.25), (5.5, 4.0, 0.25), (2.5, 4.2, 0.2), (6.0, 1.6, 0.2)]
        segs += box(3.6, 2.6, 4.6, 3.3)
        size = (8, 6)
    elif name == "corridor":                             # loop corridor 1.4 m wide + a dead-end branch
        segs += box(0, 0, 10, 7)
        segs += box(1.4, 1.4, 8.6, 5.6)                  # inner block -> ring corridor
        segs += [((10, 3.0), (10, 4.0))]
        size = (10, 7)
    elif name == "clutter":                              # warehouse floor with random boxes
        segs += box(0, 0, 9, 7)
        placed = []
        while len(placed) < 9:
            w, h = rng.uniform(0.4, 1.2, 2)
            x, y = rng.uniform(0.8, 9 - 0.8 - w), rng.uniform(0.8, 7 - 0.8 - h)
            if all(abs(x - px) > 1.4 or abs(y - py) > 1.4 for px, py in placed):
                placed.append((x, y))
                segs += box(x, y, x + w, y + h)
        for _ in range(4):
            circ.append((rng.uniform(1, 8), rng.uniform(1, 6), rng.uniform(0.1, 0.25)))
        size = (9, 7)
    elif name == "corner_trap":                          # room with a V-shaped trap and a narrow gap
        segs += box(0, 0, 8, 6)
        segs += [((5.0, 1.5), (7.0, 3.0)), ((7.0, 3.0), (5.0, 4.5))]   # V opening to the left
        segs += [((2.5, 0), (2.5, 2.2)), ((2.5, 3.0), (2.5, 6))]       # wall with a 0.8 m gap
        size = (8, 6)
    else:
        raise ValueError(name)
    return segs, circ, size


WORLDS = ["room", "corridor", "clutter", "corner_trap"]


# ---------------------------------------------------------------- geometry
def ray_cast(ox, oy, ang, segs, circ, max_d=12.0):
    dx, dy = math.cos(ang), math.sin(ang)
    best = max_d
    for (x1, y1), (x2, y2) in segs:
        ex, ey = x2 - x1, y2 - y1
        den = dx * ey - dy * ex
        if abs(den) < 1e-12:
            continue
        t = ((x1 - ox) * ey - (y1 - oy) * ex) / den
        u = ((x1 - ox) * dy - (y1 - oy) * dx) / den
        if 0 <= u <= 1 and 0 <= t < best:
            best = t
    for cx, cy, r in circ:
        fx, fy = ox - cx, oy - cy
        b = fx * dx + fy * dy
        c = fx * fx + fy * fy - r * r
        disc = b * b - c
        if disc >= 0:
            t = -b - math.sqrt(disc)
            if 0 <= t < best:
                best = t
    return best


_DEGS = np.arange(-180, 180, SCAN_STEP)                 # one full scan, every 2 degrees
_PHIS = np.radians(_DEGS)
_EXT = np.array([body_extent(p) for p in _PHIS])
_SECT_IDX = {k: np.where((_DEGS >= a0) & (_DEGS <= a1))[0] for k, (a0, a1) in SECTORS.items()}
_SECT_IDX["RL"] = np.where((_DEGS >= 150) | (_DEGS == -180))[0]          # 150..180 (180 = -180)
_FRONT = (_DEGS > -90) & (_DEGS < 90)
_GEOM = {}


def _geom(segs, circ):
    key = id(segs), id(circ), len(circ)
    if key not in _GEOM:
        S = np.array([[a[0], a[1], b[0], b[1]] for a, b in segs], dtype=float).reshape(-1, 4)
        C = np.array(circ, dtype=float).reshape(-1, 3)
        _GEOM.clear()
        _GEOM[key] = (S, C)
    return _GEOM[key]


def scan(ox, oy, th, segs, circ, max_d=12.0):
    """All scanner rays at once (numpy). Returns distances from the centre for _PHIS."""
    S, C = _geom(segs, circ)
    ang = th + _PHIS
    dx, dy = np.cos(ang)[:, None], np.sin(ang)[:, None]
    best = np.full(len(ang), max_d)
    if len(S):
        x1, y1, ex, ey = S[:, 0], S[:, 1], S[:, 2] - S[:, 0], S[:, 3] - S[:, 1]
        den = dx * ey - dy * ex
        with np.errstate(divide="ignore", invalid="ignore"):
            t = ((x1 - ox) * ey - (y1 - oy) * ex) / den
            u = ((x1 - ox) * dy - (y1 - oy) * dx) / den
        ok = (np.abs(den) > 1e-12) & (u >= 0) & (u <= 1) & (t >= 0)
        best = np.minimum(best, np.where(ok, t, max_d).min(1))
    if len(C):
        fx, fy = ox - C[:, 0], oy - C[:, 1]
        bb = fx * dx + fy * dy
        cc = fx * fx + fy * fy - C[:, 2] ** 2
        disc = bb * bb - cc
        with np.errstate(invalid="ignore"):
            t = -bb - np.sqrt(np.where(disc >= 0, disc, 0))
        ok = (disc >= 0) & (t >= 0)
        best = np.minimum(best, np.where(ok, t, max_d).min(1))
    return best


def body_corners(x, y, th):
    c, s = math.cos(th), math.sin(th)
    pts = []
    for bx, by in ((LENGTH / 2, WIDTH / 2), (LENGTH / 2, -WIDTH / 2), (-LENGTH / 2, -WIDTH / 2), (-LENGTH / 2, WIDTH / 2)):
        pts.append((x + bx * c - by * s, y + bx * s + by * c))
    return pts


def _seg_cross(p1, p2, p3, p4):
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = orient(p3, p4, p1), orient(p3, p4, p2)
    d3, d4 = orient(p1, p2, p3), orient(p1, p2, p4)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


def collides(x, y, th, segs, circ):
    pts = body_corners(x, y, th)
    edges = list(zip(pts, pts[1:] + pts[:1]))
    for a, b in segs:
        for p, q in edges:
            if _seg_cross(p, q, a, b):
                return True
    c, s = math.cos(th), math.sin(th)
    for cx, cy, r in circ:                                # circle vs rotated rectangle
        lx = (cx - x) * c + (cy - y) * s
        ly = -(cx - x) * s + (cy - y) * c
        px = min(max(lx, -LENGTH / 2), LENGTH / 2)
        py = min(max(ly, -WIDTH / 2), WIDTH / 2)
        if (lx - px) ** 2 + (ly - py) ** 2 < r * r:
            return True
    return False


# ---------------------------------------------------------------- one drive
class Rover:
    def __init__(self, chip, x, y, th, safety=True, noise=0.0, rng=None, sensors="beams", unstick=False):
        self.chip, self.x, self.y, self.th = chip, x, y, th
        self.v, self.delta = 0.0, 0.0
        self.safety, self.noise = safety, noise
        self.rng = rng or np.random.default_rng(0)
        self.sensors, self.unstick = sensors, unstick
        self.mode, self.timer, self.slow, self.side = "NET", 0.0, 0.0, 1.0
        self.points = np.zeros((0, 2))

    def sense(self, segs, circ):
        c, s = math.cos(self.th), math.sin(self.th)
        d = {}
        if self.sensors == "scanner":                     # one 360-degree LiDAR at the body centre
            clear = scan(self.x, self.y, self.th, segs, circ) - _EXT     # distance from the body edge
            for k, idx in _SECT_IDX.items():
                best = float(clear[idx].min())
                if self.noise:
                    best += self.rng.normal(0, self.noise)
                d[k] = max(0.0, best)
            # the fixed safety layer gets the whole scan: closest point in the front / rear half
            self.half = {"front": float(clear[_FRONT].min()), "rear": float(clear[~_FRONT].min())}
            r = clear + _EXT                              # scan points in the robot frame (x fwd, y left)
            near = r < 2.0
            self.points = np.stack([r[near] * np.cos(_PHIS[near]), r[near] * np.sin(_PHIS[near])], 1)
            return d
        for k, (bx, by, a) in SENSORS.items():
            ox, oy = self.x + bx * c - by * s, self.y + bx * s + by * c
            r = ray_cast(ox, oy, self.th + a, segs, circ)
            if self.noise:
                r = max(0.0, r + self.rng.normal(0, self.noise))
            d[k] = r
        return d

    def path_clear(self, speed, steer, horizon=0.4, margin=0.03):
        """Predict the next 0.4 s with this command; True if the body (+3 cm) touches no scan point."""
        if not len(self.points):
            return True
        v = math.copysign(max(abs(speed) * MAX_SPEED, 0.15), speed)
        delta = -steer * MAX_STEER
        x = y = th = 0.0
        P = self.points
        # points already inside the margin now may stay there (moving away from them is allowed);
        # a move is blocked if it touches the body itself or brings a NEW point inside the margin
        inside_now = (np.abs(P[:, 0]) < LENGTH / 2 + margin) & (np.abs(P[:, 1]) < WIDTH / 2 + margin)
        for _ in range(8):
            x += v * math.cos(th) * horizon / 8
            y += v * math.sin(th) * horizon / 8
            th += v / WHEELBASE * math.tan(delta) * horizon / 8
            c, s_ = math.cos(th), math.sin(th)
            lx = (P[:, 0] - x) * c + (P[:, 1] - y) * s_
            ly = -(P[:, 0] - x) * s_ + (P[:, 1] - y) * c
            in_margin = (np.abs(lx) < LENGTH / 2 + margin) & (np.abs(ly) < WIDTH / 2 + margin)
            touch = (np.abs(lx) < LENGTH / 2 + 0.005) & (np.abs(ly) < WIDTH / 2 + 0.005)
            if np.any((in_margin & ~inside_now) | touch):
                return False
        return True

    def step(self, segs, circ):
        d = self.sense(segs, circ)
        dist = [d["FL"], d["FR"], d["RL"], d["RR"]]
        q = [min(max(int(round(min(v, RANGE) / RANGE * 127)), 0), 127) for v in dist]
        y = self.chip.run(q)
        speed, steer = y[0] / 127, y[1] / 127
        guard = ""
        if self.unstick:                                  # fixed-logic supervisor: 3-point turn when stuck
            speed, steer, guard = self.supervisor(d, speed, steer)
        if self.safety:                                   # fixed logic, outside the network
            if self.sensors == "scanner":                 # predictive: would the body hit a scan point?
                if speed != 0 and not self.path_clear(speed, steer):
                    if self.path_clear(speed, 0.0):
                        steer, guard = 0.0, "straighten"  # turning would scrape, straight is fine
                    else:
                        speed, guard = 0.0, "front" if speed > 0 else "rear"
            else:
                if min(d["FL"], d["FR"]) < SAFETY and speed > 0:
                    speed, guard = 0.0, "front"
                if min(d["RL"], d["RR"]) < SAFETY and speed < 0:
                    speed, guard = 0.0, "rear"
        self.last = (speed, steer)
        # actuators with limited acceleration / steering rate
        v_cmd = speed * MAX_SPEED
        self.v += max(-ACCEL * DT, min(ACCEL * DT, v_cmd - self.v))
        d_cmd = -steer * MAX_STEER                        # steering + = right = clockwise
        self.delta += max(-STEER_RATE * DT, min(STEER_RATE * DT, d_cmd - self.delta))
        # kinematic bicycle model (rear axle at body centre for simplicity)
        self.x += self.v * math.cos(self.th) * DT
        self.y += self.v * math.sin(self.th) * DT
        self.th += self.v / WHEELBASE * math.tan(self.delta) * DT
        return dict(dist=dist, q=q, y=y, speed=speed, steer=steer, guard=guard)


def _supervisor(self, d, speed, steer):
    """NET: the network drives. If it commands ~zero speed for 0.8 s while there is room behind,
    run a 3-point turn: REVERSE 1.5 s with the wheels turned AWAY from the open side,
    then FORWARD 1.2 s turned TOWARD it, then give control back to the network."""
    front, rear = min(d["FL"], d["FR"]), min(d["RL"], d["RR"])
    if self.mode == "NET":
        # no progress: less than 10 cm net movement in the last 3 s (standing still OR dithering)
        self.hist = (getattr(self, "hist", []) + [(self.x, self.y)])[-int(3 / DT):]
        hx, hy = self.hist[0]
        self.slow = self.slow + DT if (len(self.hist) == int(3 / DT) and math.hypot(self.x - hx, self.y - hy) < 0.10) \
            or abs(self.v) < 0.02 and len(self.hist) > int(0.8 / DT) and math.hypot(self.x - self.hist[-16][0], self.y - self.hist[-16][1]) < 0.01 \
            else 0.0
        if self.slow >= 0.05:
            self.side = 1.0 if d["FR"] >= d["FL"] - 0.05 else -1.0     # +1: right side more open
            self.slow, self.hist = 0.0, []
            if rear > 0.25 and (rear >= front or front <= 0.25):
                self.mode, self.timer = "REVERSE", 1.5
            elif front > 0.25:
                self.mode, self.timer = "FORWARD", 1.2
        return speed, steer, ""
    self.timer -= DT
    if self.mode == "REVERSE":
        if self.timer <= 0 or rear < 0.2:
            self.mode, self.timer = "FORWARD", 1.2
        return -0.4, -self.side, "3pt-rev"
    if self.timer <= 0 or front < 0.2:
        self.mode = "NET"
    return 0.35, self.side, "3pt-fwd"


Rover.supervisor = _supervisor


def random_start(segs, circ, size, rng):
    for _ in range(1000):
        x, y = rng.uniform(0.6, size[0] - 0.6), rng.uniform(0.6, size[1] - 0.6)
        th = rng.uniform(-math.pi, math.pi)
        if not collides(x, y, th, segs, circ):
            ok = all(ray_cast(x, y, a, segs, circ) > 0.6 for a in np.linspace(0, 2 * math.pi, 12, endpoint=False))
            if ok:
                return x, y, th
    raise RuntimeError("no free start position")


def drive(chip, world, seconds=120, seed=0, safety=True, noise=0.0, trace=None, sensors="beams", unstick=False,
          collect=None, view=None):
    segs, circ, size = make_world(world, seed=1)
    rng = np.random.default_rng(seed)
    x, y, th = random_start(segs, circ, size, rng)
    r = Rover(chip, x, y, th, safety=safety, noise=noise, rng=rng, sensors=sensors, unstick=unstick)
    if view is not None:
        view.start(world, segs, circ, size)
    n = int(seconds / DT)
    path, crashed, stuck_events, guard_steps, travelled = [], False, 0, 0, 0.0
    slow_escapes = 0
    window = int(15 / DT)
    for k in range(n):
        px, py = r.x, r.y
        info = r.step(segs, circ)
        travelled += math.hypot(r.x - px, r.y - py)
        guard_steps += info["guard"] in ("front", "rear")
        if collect is not None:
            collect.append(info["dist"])
        path.append((k * DT, r.x, r.y, r.th, *info["dist"], *info["q"], *info["y"], info["guard"]))
        if view is not None:
            view.update(r, info, k * DT, travelled)
        if collides(r.x, r.y, r.th, segs, circ):
            crashed = True
            if view is not None:
                view.update(r, info, k * DT, travelled, crashed=True)
            break
        if k >= window and k % window == 0:               # last 15 s: moved < 0.3 m ...
            ox, oy = path[k - window][1], path[k - window][2]
            if math.hypot(r.x - ox, r.y - oy) < 0.3:
                turned = abs(np.ptp(np.unwrap([p[3] for p in path[k - window:k]])))
                if turned < math.radians(20):             # ... and turned < 20 deg -> really stuck
                    stuck_events += 1
                else:                                     # turning on the spot in a tight place
                    slow_escapes += 1
    if trace:
        with open(trace, "w") as fh:
            fh.write("t,x,y,heading,FL,FR,RL,RR,q0,q1,q2,q3,y_speed,y_steer,safety\n")
            for p in path:
                fh.write(",".join(f"{v:.3f}" if isinstance(v, float) else str(v) for v in p) + "\n")
    return dict(crashed=crashed, stuck=stuck_events, slow=slow_escapes, metres=travelled,
                seconds=len(path) * DT, guard=guard_steps * DT)


class LiveView:
    """Simple matplotlib window: world, rover, LiDAR sectors, path; paced to real time."""

    def __init__(self, realtime=True, every=2):
        import matplotlib.pyplot as plt
        self.plt, self.realtime, self.every = plt, realtime, every
        plt.ion()
        self.fig, self.ax = plt.subplots(figsize=(9, 7))

    def start(self, world, segs, circ, size):
        import time
        ax = self.ax
        ax.clear()
        for (x1, y1), (x2, y2) in segs:
            ax.plot([x1, x2], [y1, y2], color="#2b3645", lw=3)
        for cx, cy, rr in circ:
            ax.add_patch(self.plt.Circle((cx, cy), rr, color="#8a97a8"))
        ax.set_xlim(-0.2, size[0] + 0.2); ax.set_ylim(-0.2, size[1] + 0.2); ax.set_aspect("equal")
        ax.set_title(f"HIL: NetSilcon on the Tang Nano 20K drives the rover  |  world: {world}")
        self.trail, = ax.plot([], [], color="#2f56d9", lw=1, alpha=0.5)
        self.body = self.plt.Polygon([[0, 0]] * 4, closed=True, color="#2f56d9", alpha=0.9)
        ax.add_patch(self.body)
        self.rays = [ax.plot([], [], color=c, lw=2)[0] for c in ("#0f8f86", "#0f8f86", "#b0418f", "#b0418f")]
        self.text = ax.text(0.01, 0.01, "", transform=ax.transAxes, family="monospace", fontsize=9,
                            va="bottom", bbox=dict(facecolor="white", alpha=0.85, edgecolor="#d4dbe4"))
        self.xs, self.ys, self.n, self.t0 = [], [], 0, time.perf_counter()

    def update(self, r, info, t, metres, crashed=False):
        import time
        self.xs.append(r.x); self.ys.append(r.y); self.n += 1
        if self.n % self.every and not crashed:
            return
        self.trail.set_data(self.xs, self.ys)
        self.body.set_xy(body_corners(r.x, r.y, r.th))
        self.body.set_color("#c8322f" if crashed else "#2f56d9")
        dirs = {"FL": 15, "FR": -15, "RL": 165, "RR": -165}
        for line, (k, deg), d in zip(self.rays, dirs.items(), info["dist"]):
            a = r.th + math.radians(deg); L = min(d, RANGE) + body_extent(math.radians(deg))
            line.set_data([r.x, r.x + L * math.cos(a)], [r.y, r.y + L * math.sin(a)])
        mode = {"NET": "network", "REVERSE": "3-pt turn (rev)", "FORWARD": "3-pt turn (fwd)"}.get(r.mode, r.mode)
        self.text.set_text(f"t {t:5.1f} s   driven {metres:5.1f} m   {'CRASH' if crashed else mode}\n"
                           f"q in   {info['q']}\nchip   speed {info['y'][0]:4d}  steer {info['y'][1]:4d}"
                           f"{'   safety: ' + info['guard'] if info['guard'] in ('front', 'rear', 'straighten') else ''}")
        if self.realtime:                                  # keep simulated time = wall-clock time
            lag = (self.t0 + t) - time.perf_counter()
            if lag > 0:
                time.sleep(lag)
        self.plt.pause(0.001)


def batch(chip, runs=20, seconds=120, safety=True, noise=0.0, sensors="beams", unstick=False, collect=None):
    print(f"Batch test: {runs} random starts x {seconds:g} s per world | sensors: {sensors} | "
          f"un-stick supervisor {'ON' if unstick else 'OFF'} | safety layer {'ON' if safety else 'OFF'} | "
          f"noise {noise * 100:.0f} cm")
    print(f"{'world':12s} {'crashes':>8s} {'stuck':>6s} {'slow escape':>12s} {'avg metres':>11s} {'avg m/s':>8s} {'safety active':>14s}")
    tot = dict(crashed=0, stuck=0)
    for w in WORLDS:
        res = [drive(chip, w, seconds, seed=s, safety=safety, noise=noise, sensors=sensors, unstick=unstick,
                     collect=collect) for s in range(runs)]
        cr = sum(r["crashed"] for r in res)
        st = sum(r["stuck"] > 0 for r in res)
        sl = sum(r["slow"] > 0 and r["stuck"] == 0 for r in res)
        m = np.mean([r["metres"] for r in res])
        v = np.mean([r["metres"] / r["seconds"] for r in res])
        g = np.mean([r["guard"] / r["seconds"] for r in res]) * 100
        tot["crashed"] += cr
        tot["stuck"] += st
        print(f"{w:12s} {cr:5d}/{runs:<2d} {st:3d}/{runs:<2d} {sl:8d}/{runs:<2d} {m:11.1f} {v:8.2f} {g:12.1f} %")
    return tot


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", choices=WORLDS)
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-safety", action="store_true")
    ap.add_argument("--noise", type=float, default=0.0, help="sensor noise, metres (e.g. 0.02)")
    ap.add_argument("--trace", help="CSV file for the path (single drive)")
    ap.add_argument("--sensors", choices=["beams", "scanner"], default="beams",
                    help="beams = 4 single-point LiDARs, scanner = one 360-degree LiDAR -> 4 sectors")
    ap.add_argument("--unstick", action="store_true", help="enable the 3-point-turn supervisor")
    ap.add_argument("--no-unstick", action="store_true", help="with --hil: switch the supervisor off")
    ap.add_argument("--compare", action="store_true", help="run all 4 combinations")
    ap.add_argument("--model", default=MODEL, help="network file (default models/rover/rover.json)")
    ap.add_argument("--hil", metavar="PORT", help="hardware-in-the-loop: the real chip on this COM port drives")
    ap.add_argument("--view", action="store_true", help="show a live window (needs matplotlib)")
    ap.add_argument("--fast", action="store_true", help="with --view: do not slow down to real time")
    ap.add_argument("--collect", action="store_true",
                    help="save the sensor situations met while driving to visited_states.npy (training data)")
    a = ap.parse_args()
    if a.hil:
        import datetime
        os.makedirs(os.path.join(ROOT, "results", "logs", "hil"), exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_csv = os.path.join(ROOT, "results", "logs", "hil", f"{stamp}_hil.csv")
        chip = HilChip(a.hil, a.model, log_path=log_csv)
        sensors, unstick = "scanner", not a.no_unstick
        view = LiveView(realtime=not a.fast) if a.view else None
        lines = [f"HIL run {stamp}  port {a.hil}  model {chip.name} [CRC {chip.crc:04X}]  sensors {sensors}  "
                 f"supervisor {'ON' if unstick else 'OFF'}  safety {'OFF' if a.no_safety else 'ON'}  noise {a.noise}"]
        try:
            if a.map:
                res = drive(chip, a.map, a.seconds if a.seconds != 120 else 90, seed=a.seed,
                            safety=not a.no_safety, noise=a.noise, sensors=sensors, unstick=unstick, view=view)
                lines.append(f"{a.map}: crashed={res['crashed']} stuck={res['stuck']} driven {res['metres']:.1f} m "
                             f"in {res['seconds']:.1f} s")
            else:
                runs = a.runs if a.runs != 20 else 2
                secs = a.seconds if a.seconds != 120 else 60
                lines.append(f"{'world':12s} {'crashes':>8s} {'stuck':>6s} {'avg metres':>11s}")
                for w in WORLDS:
                    res = [drive(chip, w, secs, seed=s, safety=not a.no_safety, noise=a.noise, sensors=sensors,
                                 unstick=unstick, view=view) for s in range(runs)]
                    lines.append(f"{w:12s} {sum(r['crashed'] for r in res):5d}/{runs:<2d} "
                                 f"{sum(r['stuck'] > 0 for r in res):3d}/{runs:<2d} "
                                 f"{np.mean([r['metres'] for r in res]):11.1f}")
                    print(lines[-1])
        except KeyboardInterrupt:
            lines.append("stopped by user")
        lines.append(chip.summary())
        lines.append("RESULT: PASS - the real chip drove the rover and matched the Python model on every step"
                     if chip.mismatch == 0 and chip.steps else "RESULT: CHECK - see mismatches above")
        chip.log.close()
        text = "\n".join(lines)
        print(text)
        with open(log_csv.replace(".csv", ".log"), "w") as fh:
            fh.write(text + "\n")
        print(f"Log saved: {log_csv.replace('.csv', '.log')}\nData saved: {log_csv}")
        if view is not None:
            view.plt.ioff(); view.plt.show()
        sys.exit()
    chip = Chip(a.model)
    print(f"Network: {os.path.normpath(a.model)}  (golden vectors verified bit-exact)")
    if a.collect:
        states = []
        for sen in ("scanner", "beams"):
            batch(chip, a.runs, a.seconds, sensors=sen, unstick=True, collect=states)
        V = np.array(states)[::5]                         # every 5th step (0.25 s) is plenty
        np.save(os.path.join(HERE, "visited_states.npy"), V)
        print(f"saved {len(V)} visited situations to visited_states.npy")
        sys.exit()
    if a.map:
        r = drive(chip, a.map, a.seconds, seed=a.seed, safety=not a.no_safety, noise=a.noise, trace=a.trace,
                  sensors=a.sensors, unstick=a.unstick)
        print(r)
    elif a.compare:
        for sen in ("beams", "scanner"):
            for us in (False, True):
                batch(chip, a.runs, a.seconds, safety=not a.no_safety, noise=a.noise, sensors=sen, unstick=us)
                print()
    else:
        batch(chip, a.runs, a.seconds, safety=not a.no_safety, noise=a.noise, sensors=a.sensors, unstick=a.unstick)
