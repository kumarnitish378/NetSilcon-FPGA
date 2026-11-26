# Model index

Every trained model in this repository. Parameters = weights + biases (the layer shifts are counted separately); every model of a shape has the same count. Regenerate the facts with `python tools/sync_website.py`.

## NetSilcon-6x4 (4 inputs, 2 outputs, 170 parameters, 201-byte image, CRC-16)

| Application | File | CRC-16 | Golden vectors | Result |
|---|---|---|---|---|
| Motor / ESC fault detection | `models/motor_fault/motor_fault.json` (built into the bitstream) | 5496 | 576 | 94.5 % int8 accuracy; 576/576 bit-exact on FPGA |
| Irrigation controller | `models/irrigation/irrigation.json` | 8F33 | 576 | 97.4 % int8 accuracy; 576/576 bit-exact |
| Rover driver v2 (4 LiDAR corner sectors) | `models/rover/rover.json` | 295B | 576 | 91.5 % action agreement; HIL 9,600 decisions, 0 mismatches |
| Rover driver v1 | `models/rover/rover_v1.json` | F5C2 | 576 | 95.5 % agreement; drives worse in closed loop than v2 |

## NetSilcon-64x6 (16 inputs, 16 outputs, 22,928 parameters, 23,335-byte image, CRC-32)

| Application | File | CRC-32 | Golden vectors | Result |
|---|---|---|---|---|
| Rover controller (16 LiDAR sectors -> speed, steering) | `models/rover/rover.json` | 3A81C867 | 1000 | 89.8 % int8 action agreement; HIL 19,200 decisions, 0 mismatches; 8 drives 0 crashes |
| Maze driver (16 LiDAR sectors -> speed, steering, right-hand rule) | `models/maze/maze.json` | CA0156C9 | 1000 | Simulation: 72/80 unseen mazes solved, 0 crashes (rover model 38/80); Verilog 1,200 vectors bit-exact. Not run on hardware yet |
| Pump vibration health, EXAMPLE (synthetic data, 16 features -> 4 classes), `train_csv.py` | `models/pump_health/pump_health.json` | 6579E12F | 1000 | int8 95.2 % on 2,000 held-out rows (float 95.5 %); Verilog 1,200 vectors bit-exact. Not run on hardware yet |
| Synthetic test model (built into the bitstream) | `models/synthetic/synthetic.json` | 6F4225BF | 1000 | 1,000 golden + 2,000 random vectors, 0 mismatches |
| Stress test model (extreme weights and biases) | `models/stress/stress.json` | 732C18C9 | 200 | 200 vectors, 0 mismatches; proves the 24-bit accumulator |

Each model folder's `README.md` has inputs, outputs, training method and full results.
