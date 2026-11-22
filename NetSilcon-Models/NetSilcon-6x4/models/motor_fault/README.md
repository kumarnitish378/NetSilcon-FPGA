# BLDC motor fault detector

NetSilcon-6x4 application `motor_fault` (network 4 → 6 → 6 → 6 → 6 → 2, int8).

Built into the NetSilcon-6x4 bitstream (the model that runs after power-up).

| Item | Value |
|---|---|
| Files | `motor_fault.json` |
| Kind | classifier |
| int8 accuracy (vs training rules) | 94.5 % |
| Shifts | 8 5 6 6 6 |
| CRC-16 of the 201-byte image | 5496 |
| Golden test vectors | 576 |

## Inputs

| # | Name | Unit | Range (scaled to 0..127) |
|---|---|---|---|
| x0 | current | A | 0 – 20.0 |
| x1 | voltage | V | 0 – 30.0 |
| x2 | speed | rpm | 0 – 6000.0 |
| x3 | temp | C | 0 – 120.0 |

## Outputs

y0 = HEALTHY, y1 = FAULT

Classifier decision: `y1 > y0`.

## Rebuild and upload

```bash
cd ../../python/model && python make_model.py motor_fault      # writes models/motor_fault/motor_fault.json
python ../host/netsilcon_host.py COM7 --load ../../models/motor_fault/motor_fault.json
```
