"""Evaluate maze drivers on 80 test mazes (seeds 1000+, never used in training). Simulation only.

    python eval_maze.py                     # maze model, rover model, teacher, wall follower
    python eval_maze.py --drivers maze      # only the maze model
    python eval_maze.py --model other.json  # a different maze model file
"""
import argparse
import json
import time

import numpy as np

from maze_sim import make_maze, run, r6, ns64, MazeNet, RightmostGap, WallFollower

SETS = ((4, 4, 1.6, 300), (6, 6, 1.6, 600), (8, 8, 1.6, 900), (6, 6, 1.2, 600))   # nx, ny, corridor m, time limit s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--drivers', default='maze,rover,teacher,wall')
    ap.add_argument('--model', default=None, help='maze model file (default models/maze/maze.json)')
    ap.add_argument('-n', type=int, default=20, help='mazes per set')
    a = ap.parse_args()
    maze = MazeNet(ns64.from_json(json.load(open(a.model))) if a.model else None)
    all_d = {'maze': maze, 'rover': r6.Chip64(), 'teacher': RightmostGap(), 'wall': WallFollower()}
    drivers = [all_d[k] for k in a.drivers.split(',')]
    tot = {d.name: [0, 0] for d in drivers}
    for nx, ny, cell, secs in SETS:
        print(f'maze {nx}x{ny} cells, {cell} m corridors, {a.n} mazes, limit {secs} s, start (0,0) -> exit ({nx-1},{ny-1})', flush=True)
        for d in drivers:
            t0 = time.time()
            res = [run(d, *make_maze(nx, ny, cell, 1000 + s)[:1], nx, ny, cell, secs, s) for s in range(a.n)]
            ok = [r for r in res if r['ok']]; cr = sum(r['crash'] for r in res)
            tot[d.name][0] += len(ok); tot[d.name][1] += cr
            print(f'  {d.name:42s} solved {len(ok):2d}/{a.n}  crashes {cr}  '
                  f'avg time if solved {np.mean([r["t"] for r in ok]) if ok else float("nan"):6.1f} s  '
                  f'avg cells visited {np.mean([r["cov"] for r in res]) * 100:5.1f} %  ({time.time() - t0:.0f} s)', flush=True)
    print('total')
    for name, (ok, cr) in tot.items():
        print(f'  {name:42s} solved {ok:2d}/{a.n * len(SETS)}  crashes {cr}')


if __name__ == '__main__':
    main()
