# Stress model (extreme numbers)

NetSilcon-64x6 test model `stress` (network 16 → 64×6 → 16, int8).

Weights only −128 / +127, biases at the int16 limits, shifts 0..17, layer-2 sums up to 1,008,128. Tests the 24-bit accumulator, the clamps and the shifter range. Uploaded at run time; verified on hardware (200 vectors, 0 mismatches).

| Item | Value |
|---|---|
| File | `stress.json` |
| Shifts | 0 15 13 1 17 9 7 |
| CRC-32 of the 23,335-byte image | 732C18C9 |
| Golden test vectors | 200 |

## Rebuild and upload

```bash
cd ../../model && python3 make_synthetic.py     # writes both test models and gen/
python3 ../host/ns64_host.py COM7 --load ../models/stress/stress.json
```
