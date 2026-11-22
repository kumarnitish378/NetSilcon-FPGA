# Rover obstacle-avoidance controller (trained)

NetSilcon-64x6 application `rover`: a trained int8 network 16 → 64×6 → 16 that drives a
differential-drive rover through cluttered rooms using a 360° LiDAR scan.

It's the 64x6 version of the NetSilcon-6x4 rover. The 6x4 rover sees 4 corner sectors. This
one sees 16 sectors all the way round.

| Item | Value |
|---|---|
| File | `rover.json` (upload over UART; no FPGA rebuild) |
| Shape | 16 → 64 → 64 → 64 → 64 → 64 → 64 → 16, int8 weights, int16 biases |
| Parameters | **22,928** (22,528 int8 weights + 400 int16 biases) + 7 layer shifts |
| Shifts | 7 7 6 6 5 6 4 |
| CRC-32 of the 23,335-byte image | **3A81C867** |
| Golden test vectors | 1000 (5 edge cases + 995 held-out scans) |
| Verilog check | engine testbench, 1000/1000 vectors bit-exact, 448 clocks |
| **Hardware (Tang Nano 20K)** | uploaded in 2.04 s; golden test 1000/1000; **HIL 19,200 inferences, 0 mismatches**, 8 drives 0 crashes, 0 stuck, 48.1 m per drive |
| Action agreement with teacher (held-out scans) | float 92.7 %, **int8 89.8 %** |

## Inputs and outputs

**Inputs x0..x15:** the LiDAR scan split into 16 sectors of 22.5°. Each sector gives the
smallest distance from the rover's body edge. 0–4 m maps to 0..127, so one step is about
3.1 cm.

| Input | Sector centre | Input | Sector centre |
|---|---|---|---|
| S00 | −168.75° (behind) | S08 | +11.25° (ahead, left) |
| S01 | −146.25° | S09 | +33.75° |
| S02 | −123.75° | S10 | +56.25° |
| S03 | −101.25° | S11 | +78.75° |
| S04 | −78.75° (right) | S12 | +101.25° (left) |
| S05 | −56.25° | S13 | +123.75° |
| S06 | −33.75° | S14 | +146.25° |
| S07 | −11.25° (ahead, right) | S15 | +168.75° (behind) |

**Outputs:**
- y0 = speed × 127 (−1 … +1, negative means reverse).
- y1 = steering × 127 (positive turns left).
- y2..y15 are unused. Their weights and biases are zero, so they are always exactly 0.

## How it was made

1. **Teacher.** A hand-written rule driver (`python/rover_sim/rover64.py`, `teacher()`):
   - It scores the open gaps ahead.
   - It steers towards the best gap.
   - It slows down, and reverses, as the space in front closes.
   - It pushes away from close side walls.
2. **Data.**
   - Random collision-free poses in randomly generated worlds (training seeds 0…). The
     standard test maps and the unseen-test seeds (900000+) are never used.
   - Plus 2 rounds of DAgger: the network drives with the supervisor, and the teacher labels
     the states the network actually visits.
   - Total: 221,400 scans.
3. **Training.** Numpy MLP with Adam and a cosine learning rate, 100 epochs. Loss weights:
   speed 1, steering 1.5, unused outputs 0.05.
4. **Quantization.**
   - Post-training, one scale per layer: weights × 127/max|W|.
   - int16 biases.
   - Each layer's shift comes from the 99.99 % activation quantile.
   - The last layer is scaled so the output equals the value × 127.

The network runs inside the same controller as the 6x4 rover:
- a fixed-logic supervisor (3-point turn when it's boxed in), using 4 corner sectors of the
  same scan;
- a predictive safety stop that checks the path ahead before every move.

## Simulation results (2026-11-22, `results/results_rover64.txt`)

The safety stop is on in every run. Each drive lasts 120 s.

| Driver | Test set | Crashes | Stuck | Avg distance |
|---|---|---|---|---|
| **64x6 network + supervisor** | 4 standard worlds × 20 starts = 80 drives | **0/80** | **0/80** | 46.9 m |
| 64x6 network, no supervisor | same 80 drives | 0/80 | 68/80 | 13.0 m |
| 64x6 network + supervisor, 2 cm sensor noise | same 80 drives | 0/80 | 0/80 | 46.4 m |
| Teacher rules + supervisor (reference) | same 80 drives | 0/80 | 0/80 | 47.7 m |
| 6x4 rover v2 (4 sectors) + supervisor | same 80 drives | 0/80 | 0/80 | 49.2 m |
| 6x4 rover v2, no supervisor | same 80 drives | 0/80 | 72/80 | 11.9 m |
| **64x6 network + supervisor** | 40 unseen random worlds | **0/40** | 1/40 | **37.9 m** |
| Teacher rules + supervisor (reference) | same 40 worlds | 0/40 | 0/40 | 38.2 m |
| 6x4 rover v2 + supervisor | same 40 worlds | 0/40 | 0/40 | 33.3 m |

What the table shows:
- **The network matches its teacher.** It's within 2 % of the teacher's distance on both test
  sets, with 0 crashes.
- **Standard worlds:** the 6x4 rover drives slightly further (49.2 m vs 46.9 m). Those 4
  worlds are the ones the 6x4 was tuned on.
- **Unseen random worlds:** the 64x6 drives 14 % further than the 6x4 (37.9 m vs 33.3 m). It
  was stuck once in 40 drives; the 6x4 was never stuck.
- **Without the supervisor,** both networks avoid crashes but often get stuck. Neither network
  has any memory, so in a dead end they swing back and forth.
- **The safety stop counts:** 0 crashes is measured with the safety stop on. It is not a
  property of the network alone.

## Hardware-in-the-loop result (Tang Nano 20K, 2026-11-22)

The simulator sent every scan to the board over UART. The FPGA's speed and steering drove the
simulated rover. Command: `rover64.py --hil COM7 --unstick --runs 2` (4 standard worlds × 2 starts
× 120 s). Summary: `results/results_hil64.txt`.

| Check | Result |
|---|---|
| Upload | LOADED, chip CRC-32 3A81C867, 2.04 s (`results/logs/20261122_151939_load.log`) |
| Golden test | 1000/1000, 0 mismatches, 0 link errors (`results/logs/20261122_151950_test.*`) |
| HIL inferences | **19,200, 0 mismatches** with the Python model (`results/logs/20261122_152042_hil64.csv.gz`) |
| Chip latency | 448 clocks = 16.6 µs on every step |
| USB round trip | 15.3 ms average, 17.8 ms maximum (the 20 Hz loop allows 50 ms) |
| Unused outputs y2..y15 | 0 in every answer |
| Repeatability | a second HIL run (15:13) gave identical inputs and outputs for all 19,200 steps |

**How the drives turned out.** The HIL log records the network's inputs and outputs, not
crashes or distance. So the same 8 drives were replayed with the bit-exact Python model. The
replay produced the same 19,200 inputs and outputs as the board, so these results are what the
FPGA drove:

| World | Crashes | Stuck | Avg distance |
|---|---|---|---|
| room | 0/2 | 0/2 | 57.0 m |
| corridor | 0/2 | 0/2 | 56.1 m |
| clutter | 0/2 | 0/2 | 34.7 m |
| corner_trap | 0/2 | 0/2 | 44.9 m |
| **Total** | **0/8** | **0/8** | **48.1 m per drive** |

The supervisor and the safety stop run on the PC in this test, beside the simulator. Only the
network runs on the FPGA.

## Rebuild

```bash
cd ../../python/model
python3 train_rover.py --fresh --dagger 2      # dataset, training, DAgger, quantize, writes rover.json
cd ../rover_sim
python3 eval_rover64.py                         # writes results/results_rover64.txt (about 15 min)
python3 rover64.py --map room --runs 2          # simulated drives with the int8 model
```

## Upload and test on the board (normal ns64 bitstream)

```bash
python python/host/ns64_host.py COM7 --load models/rover/rover.json   # expect LOADED, CRC-32 3A81C867
python python/host/ns64_host.py COM7 --test                           # 1000 golden vectors
python python/rover_sim/rover64.py --hil COM7 --unstick --runs 2      # simulator drives, the FPGA decides
```

In HIL mode the simulator sends every scan to the board. It checks each answer against the
bit-exact Python model and logs it to `results/logs/hil/<time>_hil64.csv`.
