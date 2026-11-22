"""
Evaluate the NetSilcon-64x6 rover controller in simulation and compare it with the NetSilcon-6x4
rover (v2) and with the teacher rules, under identical conditions. Writes results_rover64.txt.

    python3 eval_rover64.py            (about 15 minutes)

Standard test: the 4 worlds of the 6x4 simulator x 20 random starts x 120 s = 80 drives.
Unseen test : 40 random worlds (seeds 900000+) never used in training, 1 start each, 120 s.
"Stuck" uses the 6x4 simulator's rule: in some 15 s window the robot moved < 0.3 m and turned < 20 deg.
"""
import datetime
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rover64 as r6  # noqa: E402
import rover_sim as rs  # noqa: E402

OUT = os.path.join(HERE, "results_rover64.txt")
lines = []


def say(s=""):
    print(s, flush=True)
    lines.append(s)


def row(label, tot, secs):
    say(f"{label:52s} {tot['crashed']:3d}/{tot['drives']:<3d} {tot['stuck']:3d}/{tot['drives']:<3d} "
        f"{tot['avg_m']:7.1f}   ({secs:.0f} s)")


def six_by_four(unstick, noise=0.0):
    """The 6x4 rover v2 in its own simulator (scanner mode), same worlds, starts and duration."""
    chip = rs.Chip(os.path.join(HERE, "..", "..", "NetSilcon-6x4", "models", "rover", "rover.json"))
    tot = dict(crashed=0, stuck=0, drives=0, metres=0.0)
    for w in rs.WORLDS:
        res = [rs.drive(chip, w, 120, seed=s, sensors="scanner", unstick=unstick, noise=noise) for s in range(20)]
        tot["crashed"] += sum(r["crashed"] for r in res)
        tot["stuck"] += sum(r["stuck"] > 0 for r in res)
        tot["drives"] += 20
        tot["metres"] += sum(r["metres"] for r in res)
    tot["avg_m"] = tot["metres"] / tot["drives"]
    return tot


def six_by_four_unseen(worlds, unstick=True):
    """The 6x4 rover v2 (4 corner sectors of the same scanner) in the random worlds, 1 start each."""
    import math
    chip = rs.Chip(os.path.join(HERE, "..", "..", "NetSilcon-6x4", "models", "rover", "rover.json"))
    tot = dict(crashed=0, stuck=0, drives=0, metres=0.0)
    for w in worlds:
        segs, circ, size = r6.world(w)
        rng = np.random.default_rng(0)
        x, y, th = rs.random_start(segs, circ, size, rng)
        r = rs.Rover(chip, x, y, th, safety=True, rng=rng, sensors="scanner", unstick=unstick)
        path, crashed, stuck, m = [], False, 0, 0.0
        win = int(15 / rs.DT)
        for k in range(int(120 / rs.DT)):
            px, py = r.x, r.y
            r.step(segs, circ)
            m += math.hypot(r.x - px, r.y - py)
            path.append((r.x, r.y, r.th))
            if rs.collides(r.x, r.y, r.th, segs, circ):
                crashed = True
                break
            if k >= win and k % win == 0:
                ox, oy, _ = path[k - win]
                if math.hypot(r.x - ox, r.y - oy) < 0.3 and \
                        abs(np.ptp(np.unwrap([p[2] for p in path[k - win:k]]))) < math.radians(20):
                    stuck += 1
        tot["crashed"] += crashed
        tot["stuck"] += stuck > 0
        tot["drives"] += 1
        tot["metres"] += m
    tot["avg_m"] = tot["metres"] / tot["drives"]
    return tot


def main():
    net = r6.Chip64()
    say(f"NetSilcon-64x6 rover controller evaluation  {datetime.datetime.now().isoformat(timespec='seconds')}")
    say(f"model: models/rover/rover.json  CRC-32 {net.crc:08X}  (golden vectors verified bit-exact)")
    say("network inputs: 16 LiDAR sectors; safety stop ON in every run")
    say("")
    say(f"{'driver / setup':52s} {'crashes':>7s} {'stuck':>7s} {'avg m':>7s}")
    say("standard test: 4 worlds x 20 starts x 120 s = 80 drives (none of these worlds used in training)")
    t = time.time(); _, tot = r6.batch(net, rs.WORLDS, 20, 120, unstick=True, quiet=True); row("64x6 network + supervisor", tot, time.time() - t)
    t = time.time(); _, tot = r6.batch(net, rs.WORLDS, 20, 120, unstick=False, quiet=True); row("64x6 network, no supervisor", tot, time.time() - t)
    t = time.time(); _, tot = r6.batch(net, rs.WORLDS, 20, 120, unstick=True, noise=0.02, quiet=True); row("64x6 network + supervisor, 2 cm sensor noise", tot, time.time() - t)
    t = time.time(); _, tot = r6.batch(r6.TeacherChip(), rs.WORLDS, 20, 120, unstick=True, quiet=True); row("teacher rules + supervisor (reference)", tot, time.time() - t)
    t = time.time(); tot = six_by_four(True); row("6x4 rover v2 (4 sectors) + supervisor", tot, time.time() - t)
    t = time.time(); tot = six_by_four(False); row("6x4 rover v2 (4 sectors), no supervisor", tot, time.time() - t)
    say("")
    say("unseen test: 40 random worlds never used in training x 1 start x 120 s")
    unseen = [f"rand{900000 + i}" for i in range(40)]
    t = time.time(); _, tot = r6.batch(net, unseen, 1, 120, unstick=True, quiet=True); row("64x6 network + supervisor", tot, time.time() - t)
    t = time.time(); _, tot = r6.batch(r6.TeacherChip(), unseen, 1, 120, unstick=True, quiet=True); row("teacher rules + supervisor (reference)", tot, time.time() - t)
    t = time.time(); tot = six_by_four_unseen(unseen); row("6x4 rover v2 (4 sectors) + supervisor", tot, time.time() - t)
    with open(OUT, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()
