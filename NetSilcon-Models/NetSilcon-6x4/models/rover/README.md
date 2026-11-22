# Rover driver v2 (speed + steering)

NetSilcon-6x4 application `rover` (network 4 → 6 → 6 → 6 → 6 → 2, int8).

Drives the 2D rover simulator in `rover_sim/`, also in hardware-in-the-loop with the real FPGA (9,600 decisions, 0 mismatches). `rover.json` is v2 (used by default), `rover_v1.json` the first version. v2 copies its training rules less exactly than v1 but drives better in closed loop; results in the main README and `rover_sim/batch_results.txt`.

| Item | Value |
|---|---|
| Files | `rover.json`, `rover_v1.json` |
| Kind | regression |
| int8 accuracy (vs training rules) | 91.5 % |
| Shifts | 8 6 6 5 4 |
| CRC-16 of the 201-byte image | 295B |
| Golden test vectors | 576 |

## Inputs

| # | Name | Unit | Range (scaled to 0..127) |
|---|---|---|---|
| x0 | FL | m | 0 – 4.0 |
| x1 | FR | m | 0 – 4.0 |
| x2 | RL | m | 0 – 4.0 |
| x3 | RR | m | 0 – 4.0 |

## Outputs

y0 = speed, y1 = steering

Regression: value = y / 127 (−1 … +1).

## Rebuild and upload

```bash
cd ../../model && python make_model.py rover      # writes models/rover/rover.json
python ../host/netsilcon_host.py COM7 --load ../models/rover/rover.json
```
