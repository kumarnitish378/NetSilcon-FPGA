"""Train the NetSilcon-64x6 maze model: imitation of the RightmostGap teacher + DAgger.

Inputs: the 16 LiDAR sectors (same as the rover model). Outputs: y0 speed x127, y1 steering x127,
y2..y15 = 0. Training mazes use seeds 20000+ (teacher) and 30000+ (DAgger); the test mazes in
eval_maze.py (seeds 1000+) are never used.

    python train_maze.py --mazes 60 --rounds 2 --epochs 40 --dagger-mazes 40 --out maze.json
"""
import argparse
import json
import os
import sys
import time

import numpy as np

from maze_sim import make_maze, start_rover, rs, r6, ns64, MazeNet, RightmostGap, ROOT

sys.path.insert(0, os.path.join(ROOT, "python", "model"))
import train_rover as tr  # noqa: E402  (numpy MLP + int8 quantization, shared with the rover model)

TEACHER = RightmostGap(T=1.0, side=0.35)


class Recorder:
    """Drives with the teacher (student=None) or with the student network; every step is labelled
    with the teacher's action for the scan the rover actually saw."""

    def __init__(self, student):
        self.student, self.X, self.Y = student, [], []

    def run(self, q):
        sp, st = TEACHER.act(np.array(q) / 127 * r6.RANGE)
        self.X.append(list(q)); self.Y.append([sp, st])
        if self.student is None:
            return [int(round(sp * 127)), int(round(st * 127))] + [0] * 14
        return self.student.run(q)[:2] + [0] * 14


def episode(nx, ny, cell, seed, secs, student=None):
    segs, _ = make_maze(nx, ny, cell, seed)
    rec = Recorder(student)
    rov = start_rover(rec, segs, cell, seed)
    for _ in range(int(secs / rs.DT)):
        rov.step(segs, [])
        if rs.collides(rov.x, rov.y, rov.th, segs, []) or (int(rov.x // cell), int(rov.y // cell)) == (nx - 1, ny - 1):
            break
    return np.array(rec.X), np.array(rec.Y)


def maze_set(n, seed0, rng):
    """n random mazes: 4..7 x 4..7 cells, corridor 1.2 / 1.4 / 1.6 / 1.8 m."""
    out = []
    for i in range(n):
        nx = int(rng.integers(4, 8)); ny = int(rng.integers(4, 8)); cell = float(rng.choice([1.2, 1.4, 1.6, 1.8]))
        out.append((nx, ny, cell, seed0 + i))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--mazes', type=int, default=60, help='teacher mazes')
    ap.add_argument('--rounds', type=int, default=2, help='DAgger rounds')
    ap.add_argument('--epochs', type=int, default=40)
    ap.add_argument('--dagger-mazes', type=int, default=40, help='mazes per DAgger round')
    ap.add_argument('--out', default='maze.json')
    a = ap.parse_args()

    rng = np.random.default_rng(7); t0 = time.time()
    X, Y = [], []
    for nx, ny, cell, sd in maze_set(a.mazes, 20000, rng):
        xs, ys = episode(nx, ny, cell, sd, 400); X.append(xs); Y.append(ys)
    X = np.vstack(X); Y = np.vstack(Y)
    print(f'teacher data: {len(X)} steps ({time.time() - t0:.0f} s)', flush=True)
    for r in range(a.rounds + 1):
        perm = rng.permutation(len(X)); nte = len(X) // 10; te, trn = perm[:nte], perm[nte:]
        mlp = tr.MLP(np.random.default_rng(64)); mlp.train(X[trn] / 127.0, Y[trn], epochs=a.epochs, rng=rng)
        net = tr.quantize(mlp, X[trn][:20000])
        qo = net.forward(X[te])[:, :2] / 127.0
        print(f'round {r}: int8 MAE speed {np.abs(qo[:, 0] - Y[te, 0]).mean():.3f} '
              f'steer {np.abs(qo[:, 1] - Y[te, 1]).mean():.3f}  shifts {net.S} ({time.time() - t0:.0f} s)', flush=True)
        if r == a.rounds:
            break
        nX, nY = [], []
        for nx, ny, cell, sd in maze_set(a.dagger_mazes, 30000 + 1000 * r, rng):
            xs, ys = episode(nx, ny, cell, sd, 400, student=MazeNet(net)); nX.append(xs); nY.append(ys)
        X = np.vstack([X] + nX); Y = np.vstack([Y] + nY)
        print(f'DAgger round {r + 1}: total {len(X)} steps', flush=True)

    edge = np.array([[0] * 16, [127] * 16, [64] * 16])
    Xg = np.vstack([edge, X[te][:997]]).astype(np.int64); Yg = net.forward(Xg)
    d = ns64.to_json(net, 'maze', 'Maze driver (right-hand rule, 16 LiDAR sectors -> speed, steering)', {
        'kind': 'regression',
        'inputs': [dict(name=f'S{k:02d}', unit='m', range=4.0) for k in range(16)],
        'input_note': '16 LiDAR sectors of 22.5 deg, 0..127 = 0..4 m clear (same as the rover model)',
        'teacher': 'right-most open direction rule (expert3.RightmostGap, T=1.0 m, side=0.35 m) + 3-point-turn helper at dead ends',
        'outputs': ['speed', 'steering'] + [f'unused{k}' for k in range(2, 16)],
        'training': dict(samples=int(len(X)), epochs=a.epochs, dagger_rounds=a.rounds,
                         mazes='seeds 20000+ (expert), 30000+ (DAgger); test mazes 1000+ never used'),
        'test_vectors': [{'x': x.tolist(), 'y': y.tolist()} for x, y in zip(Xg, Yg)]})
    json.dump(d, open(a.out, 'w'), separators=(',', ':'))
    print(f'saved {a.out}  CRC-32 {d["crc32"]}')


if __name__ == '__main__':
    main()
