# Smart irrigation controller

NetSilcon-6x4 application `irrigation` (network 4 → 6 → 6 → 6 → 6 → 2, int8).

Uploaded at run time; verified on hardware: 576 / 576 golden vectors bit-exact, a corrupted upload refused (see `docs/results.md`).

| Item | Value |
|---|---|
| Files | `irrigation.json` |
| Kind | classifier |
| int8 accuracy (vs training rules) | 97.4 % |
| Shifts | 7 6 7 7 5 |
| CRC-16 of the 201-byte image | 8F33 |
| Golden test vectors | 576 |

## Inputs

| # | Name | Unit | Range (scaled to 0..127) |
|---|---|---|---|
| x0 | soil | % | 0 – 100.0 |
| x1 | air_temp | C | 0 – 50.0 |
| x2 | humidity | % | 0 – 100.0 |
| x3 | sunlight | % | 0 – 100.0 |

## Outputs

y0 = SKIP, y1 = WATER

Classifier decision: `y1 > y0`.

## Rebuild and upload

```bash
cd ../../model && python make_model.py irrigation      # writes models/irrigation/irrigation.json
python ../host/netsilcon_host.py COM7 --load ../models/irrigation/irrigation.json
```
