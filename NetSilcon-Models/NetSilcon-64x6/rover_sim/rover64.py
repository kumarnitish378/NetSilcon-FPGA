"""NetSilcon-64x6 rover simulator: the 64x6 network drives the rover with a 16-sector LiDAR view.

Reuses the NetSilcon-6x4 simulator (../../NetSilcon-6x4/rover_sim/rover_sim.py) for the worlds,
ray casting, collision check, robot physics, the predictive safety stop and the 3-point-turn
supervisor. New here:
    - 16 inputs: the 360-degree scan split into 16 sectors of 22.5 degrees; each input is the
      closest obstacle in that sector, measured from the BODY edge, 0..4 m -> 0..127
    - the 64x6 network (bit-exact int8 model from model/ns64.py), outputs y0 = speed, y1 = steering
    - a teacher (driving rules on the 16 sectors) and random worlds for training and for testing
      on worlds the network has never seen

Sector k covers [-180 + 22.5 k, -180 + 22.5 (k + 1)) degrees, 0 deg = straight ahead, + = left.
So k = 7 and 8 look straight ahead, k = 0 and 15 straight back, k = 12 left, k = 3 right.

Run:
    python rover64.py --teacher                    the teacher rules drive (reference)
    python rover64.py                              the network (models/rover/rover.json) drives
    python rover64.py --unstick                    ... with the 3-point-turn supervisor
    python rover64.py --unseen 40                  ... on 40 random worlds never used in training
    python rover64.py --hil COM7 --map room        the REAL FPGA drives (hardware-in-the-loop)
"""
import argparse
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "..", "NetSilcon-6x4", "rover_sim"))
sys.path.insert(0, os.path.join(ROOT, "model"))
import rover_sim as rs  # noqa: E402  (the NetSilcon-6x4 simulator: worlds, physics, safety, supervisor)
import ns64  # noqa: E402

MODEL = os.path.join(ROOT, "models", "rover", "rover.json")
RANGE = rs.RANGE                                    # 4 m
N_SECT = 16
_DEGS = rs._DEGS                                    # -180 .. 178, every 2 degrees
SECT16 = [np.where((_DEGS >= -180 + 22.5 * k) & (_DEGS < -180 + 22.5 * (k + 1)))[0] for k in range(N_SECT)]
ANG16 = np.radians(-180 + 11.25 + 22.5 * np.arange(N_SECT))      # sector centre angles


def sectors16(clear):
    """clear: scan distances from the body edge (len(_DEGS)) -> 16 sector minima, metres, clipped 0..4"""
    return np.clip(np.array([clear[i].min() for i in SECT16]), 0.0, RANGE)


def quantize_inputs(d16):
    return [min(max(int(round(min(v, RANGE) / RANGE * 127)), 0), 127) for v in d16]


# ---------------------------------------------------------------- teacher: the driving rules to learn
BLOCK, SLOW = 0.6, 2.0


def teacher(D):
    """D: (n, 16) sector distances from the body edge, metres. Returns (n, 2): speed, steering (-1..+1).
    All parts are smooth ramps, so a network can learn them.
      speed   : from the clearance ahead (sectors 7, 8, and 6, 9 a little relaxed):
                >= 2 m full, 0.6 m creep, below 0.45 m reverse (scaled by the room behind), no stop zone
      heading : soft-argmax over the front half (sectors 4..11): prefers the most open direction,
                with a penalty for large turns; + slight right bias ("keep right")
      steering: towards that heading, stronger the closer the obstacles ahead, plus a push away
                from anything very close at the sides; reversed when driving backwards
    Steering + = right (clockwise), as in the 6x4 rover."""
    D = np.minimum(np.asarray(D, dtype=float), RANGE)
    ahead = np.minimum.reduce([D[:, 7], D[:, 8], D[:, 6] + 0.15, D[:, 9] + 0.15])
    behind = np.minimum.reduce([D[:, 0], D[:, 15], D[:, 1] + 0.15, D[:, 14] + 0.15])
    # gap score of each front-half direction: own distance, limited by the neighbours (gap width)
    idx = np.arange(4, 12)
    own = D[:, idx]
    nb = np.minimum(D[:, idx - 1], D[:, idx + 1])
    score = np.minimum(own, nb + 0.5) - 0.45 * np.abs(np.degrees(ANG16[idx])) / 90.0
    score = score + 0.1 * (ANG16[idx] < 0)                         # "keep right" when choices are equal
    # sharp soft-argmax: two equally good gaps (left and right) must not average to "straight ahead"
    w = np.exp(8.0 * (score - score.max(1, keepdims=True)))
    heading = (w * ANG16[idx]).sum(1) / w.sum(1)                   # radians, + = left
    best_open = np.minimum(own.max(1), RANGE)
    room = np.clip((ahead - 0.45) / 0.3, 0, 1)                   # the bonus needs real room ahead
    front = ahead + room * 0.5 * np.clip(best_open - ahead - 0.2, 0, 0.5)  # an open side counts a little
    # no flat zero zone: blocked -> reverse, a little room -> creep forward (a stop in between
    # would also stop the steering, and the robot would stand still in front of the obstacle)
    speed = np.interp(front, [0.3, 0.42, 0.48, BLOCK, SLOW], [-0.4, -0.3, 0.12, 0.15, 1.0])
    rear_room = np.clip((behind - 0.25) / 0.35, 0, 1)
    speed = np.where(speed < 0, speed * rear_room, speed)
    side = np.clip(-np.degrees(heading) / 40.0, -1, 1)             # + = turn right
    near = np.minimum.reduce([D[:, k] for k in range(5, 11)])
    strength = np.clip((2.5 - near) / (2.5 - BLOCK), 0.15, 1.0)
    left_close = np.clip((0.45 - np.minimum(D[:, 10], D[:, 11])) / 0.45, 0, 1)
    right_close = np.clip((0.45 - np.minimum(D[:, 4], D[:, 5])) / 0.45, 0, 1)
    push = 0.6 * (left_close - right_close)                        # obstacle left -> steer right
    direction = np.clip(speed / 0.15, -1, 1)
    steer = np.clip(side * strength + push, -1, 1) * direction
    return np.stack([speed, steer], 1)


# ---------------------------------------------------------------- drivers (same interface: run(q16) -> y)
class Chip64:
    """The 64x6 network, bit-exact int8 math of the FPGA (model/ns64.py)."""

    def __init__(self, path=MODEL, model=None):
        d = model if model is not None else json.load(open(path))
        self.net = ns64.from_json(d)
        self.name, self.crc = d.get("title", d.get("name", "?")), self.net.crc32()
        if "test_vectors" in d:
            X = np.array([v["x"] for v in d["test_vectors"]])
            Y = np.array([v["y"] for v in d["test_vectors"]])
            bad = int((self.net.forward(X) != Y).any(1).sum())
            assert bad == 0, f"network does not match its golden vectors ({bad} mismatches)"

    def run(self, q):
        return [int(v) for v in self.net.forward(np.array(q))[0]]


class TeacherChip:
    """The teacher rules in place of the network (reference driver)."""
    name, crc = "teacher rules", 0

    def run(self, q):
        D = np.array(q, dtype=float)[None, :] / 127 * RANGE
        s = teacher(D)[0]
        return [int(round(s[0] * 127)), int(round(s[1] * 127))] + [0] * 14


class HilChip64:
    """The REAL FPGA over USB serial (ns64 protocol). Every answer is checked against the Python model."""

    def __init__(self, port, path=MODEL, log_path=None):
        sys.path.insert(0, os.path.join(ROOT, "host"))
        import ns64_host
        self.ref = Chip64(path)
        self.name, self.crc = self.ref.name, self.ref.crc
        self.chip = ns64_host.Chip(port)
        crc, src, loads, _ = self.chip.info()
        if crc != self.crc:
            d = json.load(open(path))
            net = ns64.from_json(d)
            img = net.image()
            frame = img + net.crc32().to_bytes(4, "little")
            st, chip_crc, loads, dt, _ = self.chip.load(frame)
            print(f"uploaded {d['name']} to the chip: status {st}, CRC {chip_crc:08X}, {dt:.1f} s")
            assert st == 0 and chip_crc == self.crc, "upload failed"
        self.steps, self.mismatch, self.rt = 0, 0, []
        self.log = open(log_path, "w") if log_path else None
        if self.log:
            self.log.write("step,q," + ",".join(f"y{i}" for i in range(16)) + ",python_match,latency,round_trip_ms\n")

    def run(self, q):
        y, am, lat, rt, raw, retries = self.chip.infer(q)
        ok = y == self.ref.run(q)
        self.steps += 1
        self.mismatch += not ok
        self.rt.append(rt)
        if self.log:
            self.log.write(f"{self.steps},{' '.join(map(str, q))},{','.join(map(str, y))},{int(ok)},{lat},{rt:.2f}\n")
        return y

    def summary(self):
        return (f"HIL chip answers: {self.steps}   mismatches vs Python model: {self.mismatch}   "
                f"link errors: {self.chip.link_errors}   USB round trip avg {np.mean(self.rt):.1f} ms, "
                f"max {np.max(self.rt):.1f} ms")


# ---------------------------------------------------------------- the rover with 16 sectors
class Rover64(rs.Rover):
    def sense(self, segs, circ):
        clear = rs.scan(self.x, self.y, self.th, segs, circ) - rs._EXT
        d16 = sectors16(clear)
        if self.noise:
            d16 = np.clip(d16 + self.rng.normal(0, self.noise, N_SECT), 0, RANGE)
        self.d16 = d16
        # the 4 corner sectors of the 6x4 scanner mode: used by the supervisor and the logs only
        d = {k: max(0.0, float(clear[idx].min())) for k, idx in rs._SECT_IDX.items()}
        self.half = {"front": float(clear[rs._FRONT].min()), "rear": float(clear[~rs._FRONT].min())}
        r = clear + rs._EXT
        near = r < 2.0
        self.points = np.stack([r[near] * np.cos(rs._PHIS[near]), r[near] * np.sin(rs._PHIS[near])], 1)
        return d

    def step(self, segs, circ):
        d = self.sense(segs, circ)
        q = quantize_inputs(self.d16)
        y = self.chip.run(q)
        speed, steer = y[0] / 127, y[1] / 127
        guard = ""
        if self.unstick:
            speed, steer, guard = self.supervisor(d, speed, steer)
        if self.safety:
            if speed != 0 and not self.path_clear(speed, steer):
                if self.path_clear(speed, 0.0):
                    steer, guard = 0.0, "straighten"
                else:
                    speed, guard = 0.0, "front" if speed > 0 else "rear"
        self.last = (speed, steer)
        rs_ = rs
        v_cmd = speed * rs_.MAX_SPEED
        self.v += max(-rs_.ACCEL * rs_.DT, min(rs_.ACCEL * rs_.DT, v_cmd - self.v))
        d_cmd = -steer * rs_.MAX_STEER
        self.delta += max(-rs_.STEER_RATE * rs_.DT, min(rs_.STEER_RATE * rs_.DT, d_cmd - self.delta))
        self.x += self.v * math.cos(self.th) * rs_.DT
        self.y += self.v * math.sin(self.th) * rs_.DT
        self.th += self.v / rs_.WHEELBASE * math.tan(self.delta) * rs_.DT
        return dict(d16=self.d16, q=q, y=y, speed=speed, steer=steer, guard=guard)


# ---------------------------------------------------------------- random worlds (training and unseen tests)
def random_world(seed):
    """A random room 6..10 x 5..8 m with 3..9 boxes, 0..5 pillars and sometimes an inner wall with a gap."""
    rng = np.random.default_rng(seed)
    W, H = rng.uniform(6, 10), rng.uniform(5, 8)
    segs, circ = rs.box(0, 0, W, H), []
    placed = []
    for _ in range(rng.integers(3, 10)):
        for _try in range(30):
            w, h = rng.uniform(0.3, 1.4, 2)
            x, y = rng.uniform(0.7, W - 0.7 - w), rng.uniform(0.7, H - 0.7 - h)
            if all(abs(x - px) > 1.3 or abs(y - py) > 1.3 for px, py in placed):
                placed.append((x, y))
                segs += rs.box(x, y, x + w, y + h)
                break
    for _ in range(rng.integers(0, 6)):
        circ.append((rng.uniform(0.8, W - 0.8), rng.uniform(0.8, H - 0.8), rng.uniform(0.08, 0.3)))
    if rng.random() < 0.4:                                     # inner wall with a 0.8..1.4 m gap
        xw, gap = rng.uniform(2, W - 2), rng.uniform(0.8, 1.4)
        g0 = rng.uniform(0.5, H - 0.5 - gap)
        segs += [((xw, 0), (xw, g0)), ((xw, g0 + gap), (xw, H))]
    return segs, circ, (W, H)


def world(name):
    if name.startswith("rand"):
        return random_world(int(name[4:]))
    return rs.make_world(name, seed=1)


# ---------------------------------------------------------------- one drive / batch
def drive(chip, world_name, seconds=120, seed=0, safety=True, noise=0.0, unstick=False, collect=None):
    segs, circ, size = world(world_name)
    rng = np.random.default_rng(seed)
    x, y, th = rs.random_start(segs, circ, size, rng)
    r = Rover64(chip, x, y, th, safety=safety, noise=noise, rng=rng, sensors="scanner", unstick=unstick)
    n = int(seconds / rs.DT)
    path, crashed, stuck, travelled = [], False, 0, 0.0
    window = int(15 / rs.DT)
    for k in range(n):
        px, py = r.x, r.y
        info = r.step(segs, circ)
        travelled += math.hypot(r.x - px, r.y - py)
        if collect is not None:
            collect.append(info["d16"].copy())
        path.append((r.x, r.y, r.th))
        if rs.collides(r.x, r.y, r.th, segs, circ):
            crashed = True
            break
        if k >= window and k % window == 0:                      # same "stuck" test as the 6x4 simulator
            ox, oy, _ = path[k - window]
            if math.hypot(r.x - ox, r.y - oy) < 0.3:
                turned = abs(np.ptp(np.unwrap([p[2] for p in path[k - window:k]])))
                if turned < math.radians(20):
                    stuck += 1
    return dict(crashed=crashed, stuck=stuck, metres=travelled, seconds=len(path) * rs.DT)


def batch(chip, worlds, runs=20, seconds=120, safety=True, noise=0.0, unstick=False, collect=None, quiet=False):
    rows, tot = [], dict(crashed=0, stuck=0, drives=0, metres=0.0)
    for w in worlds:
        res = [drive(chip, w, seconds, seed=s, safety=safety, noise=noise, unstick=unstick, collect=collect)
               for s in range(runs)]
        cr, st = sum(r["crashed"] for r in res), sum(r["stuck"] > 0 for r in res)
        m = float(np.mean([r["metres"] for r in res]))
        rows.append((w, cr, st, m))
        tot["crashed"] += cr
        tot["stuck"] += st
        tot["drives"] += runs
        tot["metres"] += m * runs
        if not quiet:
            print(f"  {w:12s} crashes {cr:3d}/{runs:<3d} stuck {st:3d}/{runs:<3d} avg {m:5.1f} m")
    tot["avg_m"] = tot["metres"] / tot["drives"]
    return rows, tot


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--teacher", action="store_true", help="the teacher rules drive instead of the network")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--map", help="one world (room, corridor, clutter, corner_trap, randNNN)")
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--unstick", action="store_true", help="3-point-turn supervisor ON")
    ap.add_argument("--noise", type=float, default=0.0)
    ap.add_argument("--unseen", type=int, metavar="N", help="test on N random worlds never used in training")
    ap.add_argument("--hil", metavar="PORT", help="the real FPGA drives (hardware-in-the-loop)")
    a = ap.parse_args()
    if a.hil:
        import datetime
        os.makedirs(os.path.join(HERE, "logs"), exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        chip = HilChip64(a.hil, a.model, log_path=os.path.join(HERE, "logs", f"{stamp}_hil64.csv"))
    else:
        chip = TeacherChip() if a.teacher else Chip64(a.model)
    worlds = [a.map] if a.map else (
        [f"rand{900000 + i}" for i in range(a.unseen)] if a.unseen else rs.WORLDS)
    runs = a.runs if not a.unseen else 1
    print(f"driver: {chip.name} | {len(worlds)} world(s) x {runs} start(s) x {a.seconds:g} s | "
          f"supervisor {'ON' if a.unstick else 'OFF'} | noise {a.noise * 100:.0f} cm")
    rows, tot = batch(chip, worlds, runs, a.seconds, noise=a.noise, unstick=a.unstick, quiet=bool(a.unseen))
    print(f"TOTAL: {tot['drives']} drives, crashes {tot['crashed']}, stuck {tot['stuck']}, "
          f"avg {tot['avg_m']:.1f} m per drive")
    if a.hil:
        print(chip.summary())
        chip.log.close()
