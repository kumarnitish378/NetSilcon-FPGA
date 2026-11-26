"""NetSilcon-64x6 maze simulation (simulation only).

Perfect mazes (one path between any two cells), the same rover, LiDAR, safety stop and
3-point-turn supervisor as the rover model (python/rover_sim/rover64.py), and the drivers
that were compared:

  MazeNet        the trained int8 maze model (models/maze/maze.json), bit-exact
  RightmostGap   the teacher: right-hand rule from the 16 LiDAR sectors only
  WallFollower   a quick hand-written right-wall follower (baseline)
  r6.Chip64()    the rover model (models/rover/rover.json), for comparison

The rover starts in cell (0, 0); it solves the maze when its centre enters the exit cell
(nx-1, ny-1).
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")                       # NetSilcon-64x6/
sys.path.insert(0, os.path.join(ROOT, "python", "rover_sim"))
sys.path.insert(0, os.path.join(ROOT, "python", "model"))
import rover64 as r6  # noqa: E402
import ns64  # noqa: E402

rs = r6.rs                                                   # the NetSilcon-6x4 simulator (physics, collisions)
MAZE_MODEL = os.path.join(ROOT, "models", "maze", "maze.json")
ANG = [math.radians(-180 + 22.5 * k + 11.25) for k in range(16)]   # sector centre angles


def make_maze(nx, ny, cell, seed):
    """Perfect maze by recursive backtracker. Returns (wall segments, open-sides map)."""
    rng = np.random.default_rng(seed)
    E = {(x, y): {'N', 'S', 'E', 'W'} for x in range(nx) for y in range(ny)}
    D = {'N': (0, 1), 'S': (0, -1), 'E': (1, 0), 'W': (-1, 0)}
    O = {'N': 'S', 'S': 'N', 'E': 'W', 'W': 'E'}
    st, seen = [(0, 0)], {(0, 0)}
    while st:
        c = st[-1]
        nb = [(d, (c[0] + D[d][0], c[1] + D[d][1])) for d in D]
        nb = [(d, n) for d, n in nb if n in E and n not in seen]
        if not nb:
            st.pop()
            continue
        d, n = nb[rng.integers(len(nb))]
        E[c].discard(d); E[n].discard(O[d]); seen.add(n); st.append(n)
    segs = []
    for (x, y), w in E.items():
        x0, y0, x1, y1 = x * cell, y * cell, (x + 1) * cell, (y + 1) * cell
        if 'S' in w: segs.append(((x0, y0), (x1, y0)))
        if 'W' in w: segs.append(((x0, y0), (x0, y1)))
        if 'N' in w and y == ny - 1: segs.append(((x0, y1), (x1, y1)))
        if 'E' in w and x == nx - 1: segs.append(((x1, y0), (x1, y1)))
    return segs, E


def start_rover(driver, segs, cell, seed):
    """Rover in the centre of cell (0, 0), facing the first open direction."""
    x = y = cell / 2
    for th in (0.0, math.pi / 2, math.pi, -math.pi / 2):
        if not rs.collides(x, y, th, segs, []):
            break
    return r6.Rover64(driver, x, y, th, safety=True, noise=0.0, rng=np.random.default_rng(seed),
                      sensors='scanner', unstick=True)


def run(driver, segs, nx, ny, cell, seconds, seed, trace=False):
    """Drive until the exit, a crash or the time limit. Returns a result dict."""
    getattr(driver, 'reset', lambda: None)()
    rov = start_rover(driver, segs, cell, seed)
    cells, pts, res = set(), [], 'timeout'
    k = 0
    for k in range(int(seconds / rs.DT)):
        rov.step(segs, [])
        if trace and k % 4 == 0:
            pts.append([round(rov.x, 3), round(rov.y, 3), round(rov.th, 3)])
        if rs.collides(rov.x, rov.y, rov.th, segs, []):
            res = 'crash'
            break
        c = (int(rov.x // cell), int(rov.y // cell)); cells.add(c)
        if c == (nx - 1, ny - 1):
            res = 'solved'
            break
    out = dict(ok=res == 'solved', crash=res == 'crash', result=res, t=k * rs.DT, cov=len(cells) / (nx * ny))
    if trace:
        out['points'] = pts
    return out


class RightmostGap:
    """Teacher. Right-hand rule from the 16 LiDAR sectors only: steer toward the right-most open
    direction (sectors 3..12). At a dead end it stops, and the 3-point-turn supervisor turns the rover."""
    name = 'right-hand rule from LiDAR (teacher)'

    def __init__(self, T=1.0, side=0.35, k0=3, k1=12, gain=1.4):
        self.T, self.side, self.k0, self.k1, self.g = T, side, k0, k1, gain

    def act(self, d):
        front = min(d[7], d[8])
        for k in range(self.k0, self.k1 + 1):
            if d[k] > self.T and min(d[k - 1], d[k + 1]) > self.side:
                a = ANG[k]
                sp = max(0.2, 0.55 * math.cos(a))
                sp = min(sp, 0.25) if front < 0.45 else sp
                return sp, float(np.clip(-a * self.g / (math.pi / 4), -1, 1))
        return 0.0, 0.0

    def run(self, q):
        sp, st = self.act(np.array(q) / 127 * r6.RANGE)
        return [int(round(sp * 127)), int(round(st * 127))] + [0] * 14


class WallFollower:
    """Quick hand-written baseline with the same 16 sectors: keep the wall on the right."""
    name = 'right-hand wall follower (quick baseline)'

    def run(self, q):
        d = np.array(q) / 127 * r6.RANGE
        front = min(d[7], d[8]); right = min(d[3], d[4]); fr = min(d[5], d[6])
        if front < 0.45: sp, st = 0.25, -1.0
        elif right > 1.0 and fr > 0.6: sp, st = 0.45, 0.9
        else: sp, st = 0.6, float(np.clip(2.0 * (right - 0.45), -1, 1))
        return [int(round(sp * 127)), int(round(st * 127))] + [0] * 14


class MazeNet:
    """The trained maze model: 16 quantized LiDAR sectors in, y0 speed and y1 steering out (x127)."""
    name = 'NetSilcon-64x6 maze model'

    def __init__(self, net=None):
        self.net = net if net is not None else ns64.from_json(json.load(open(MAZE_MODEL)))

    def run(self, q):
        return self.net.forward(np.array([q]))[0].tolist()
