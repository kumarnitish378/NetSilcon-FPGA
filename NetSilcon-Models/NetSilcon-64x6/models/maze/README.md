# Maze driver (trained)

NetSilcon-64x6 application `maze`: a trained int8 network 16 → 64×6 → 16 that drives the
simulated rover out of mazes it has never seen, using the right-hand rule.

It is the second model for the same network shape and the same inputs as the
[rover model](../rover/README.md). Only the model file is different.

| Item | Value |
|---|---|
| File | `maze.json` (upload over UART; no FPGA rebuild) |
| Shape | 16 → 64 → 64 → 64 → 64 → 64 → 64 → 16, int8 weights, int16 biases |
| Parameters | **22,928** (22,528 int8 weights + 400 int16 biases) + 7 layer shifts |
| Shifts | 7 7 7 7 4 5 6 |
| CRC-32 of the 23,335-byte image | **CA0156C9** |
| Golden test vectors | 1000 (3 edge cases + 997 held-out scans) |
| Verilog check | `fpga/scripts/run_sim_model.sh models/maze/maze.json`: 1,200 vectors, 0 mismatches, 448 clocks |
| int8 error vs teacher (held-out scans) | speed 0.011, steering 0.012 (mean absolute, on −1…+1) |
| **Hardware** | **not run on the board yet** |

## Inputs and outputs

Same as the rover model:
- **Inputs x0..x15:** the 360° LiDAR scan as 16 sectors of 22.5°, smallest clear distance from
  the body edge, 0–4 m → 0..127. Sector table: [rover README](../rover/README.md#inputs-and-outputs).
- **Outputs:** y0 = speed × 127, y1 = steering × 127 (positive turns left). y2..y15 are unused
  and always 0.

## How it was made

1. **Teacher** (`python/maze_sim/maze_sim.py`, `RightmostGap`). The right-hand rule, from the
   16 sectors only: steer toward the right-most open direction (sectors S03..S12, more than 1.0 m
   clear, both neighbours more than 0.35 m). So: turn right if you can, else straight, else
   left. At a dead end it outputs (0, 0) and the fixed 3-point-turn supervisor turns the rover.
   The model file's `teacher` field calls it `expert3.RightmostGap`, its name in the scratch
   script it was first written in; the rule is the same.
2. **Data.** The teacher drives 60 random mazes (4–7 × 4–7 cells, corridors 1.2–1.8 m, seeds
   20000+), then 2 rounds of DAgger with 40 mazes each (seeds 30000+): the network drives, the
   teacher labels the scans the network actually sees. 488,509 scans in total.
3. **Training and quantization.** The same numpy MLP and int8 quantization as the rover model
   (`python/model/train_rover.py`), 40 epochs per round.

**Lesson from the first attempt.** A teacher that used the maze map and the rover's exact
position (cell by cell right-hand rule) was not learnable: the network solved 4 of 20 small
mazes (6 of 20 without the two extra memory inputs that were tried). The network cannot see the
map, so identical scans carried different labels. A teacher that decides from the same 16
inputs the network sees can be copied almost exactly.

## Simulation results (2026-11-27, `results/results_maze64.txt`)

80 test mazes (seeds 1000+, never used in training), safety stop and 3-point-turn supervisor on,
start in cell (0, 0), solved when the rover reaches the opposite corner cell.

| Mazes | Maze model | Teacher (LiDAR rule) | Rover model | Quick wall follower |
|---|---|---|---|---|
| 4 × 4, 1.6 m, 300 s | **20/20** | 20/20 | 12/20 | 16/20 |
| 6 × 6, 1.6 m, 600 s | **19/20** | 20/20 | 12/20 | 12/20 |
| 8 × 8, 1.6 m, 900 s | **18/20** | 20/20 | 6/20, 1 crash | 10/20 |
| 6 × 6, 1.2 m, 600 s | **15/20** | 12/20 | 8/20 | 4/20, 2 crashes |
| **Total** | **72/80, 0 crashes** | 72/80, 0 crashes | 38/80, 1 crash | 42/80, 2 crashes |

What the table shows:
- The maze model matches its teacher (72/80 each). It loses a few big mazes to the time limit
  and wins a few narrow ones.
- The rover model avoids obstacles but has no rule for where to go; it finds the exit about
  half the time.
- All 8 failures of the maze model are timeouts, not crashes; 5 of them are in the 1.2 m
  corridors, where the rover barely fits through a turn.
- The model explores; it does not find the shortest route. It has no memory or map.
- The 3-point-turn supervisor and the safety stop are fixed logic beside the network, as in
  the rover tests.

## Rebuild and test

```bash
cd ../../python/maze_sim
python3 train_maze.py --out maze.json        # about 7 min; reproduces CRC-32 CA0156C9
python3 eval_maze.py                         # 80 mazes, 4 drivers (about 15 min)
python3 eval_maze.py --drivers maze          # only the maze model
cd ../..
bash fpga/scripts/run_sim_model.sh models/maze/maze.json   # Verilog vs Python, no board
```

## Upload and test on the board (normal ns64 bitstream)

```bash
python python/host/ns64_host.py COM7 --load models/maze/maze.json
python python/host/ns64_host.py COM7 --test
```

Try it in the browser: the website's [maze simulator](https://kumarnitish378.github.io/NetSilcon/playground/#maze)
runs this file with the same integer maths.
