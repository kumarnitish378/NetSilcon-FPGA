# Synthetic hardware test model

NetSilcon-64x6 test model `synthetic` (network 16 → 64×6 → 16, int8).

Random int8 weights with biases and shifts calibrated so most activations fall between 0 and 127: about 30 % of hidden activations are 0, under 1 % saturate, about 7 % of outputs hit +127 / −128. Built into the NetSilcon-64x6 bitstream (weight-RAM bank 0). Not a trained model: it exists to prove the hardware is bit-exact.

| Item | Value |
|---|---|
| File | `synthetic.json` |
| Shifts | 7 9 8 8 8 8 7 |
| CRC-32 of the 23,335-byte image | 6F4225BF |
| Golden test vectors | 1000 |

## Rebuild and upload

```bash
cd ../../model && python3 make_synthetic.py     # writes both test models and gen/
python3 ../host/ns64_host.py COM7 --load ../models/synthetic/synthetic.json
```
