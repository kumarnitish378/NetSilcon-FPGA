# NetSilcon-64x6

> Part of the [NetSilcon](../../README.md) family. Smaller model: [NetSilcon-6x4](../NetSilcon-6x4/).

A larger NetSilcon engine for the Sipeed Tang Nano 20K (GW2AR-18):
**16 → 64 → 64 → 64 → 64 → 64 → 64 → 16**, int8. The shape is fixed in hardware.
The weights (22,528), biases (400) and per-layer shifts (7) live in block RAM and
are loadable over UART with a CRC-32 (23,335-byte model), verified on hardware.

Same neuron math as [NetSilcon-6x4](../NetSilcon-6x4/):

```
acc = bias16 + Σ x_i · w_i            int8 × int8, 24-bit signed accumulator
hidden layers: acc = max(acc, 0)      ReLU
y = (acc + 2^(s−1)) >>> s             s = 0..23, one loadable shift per layer
y = clamp 0..127 (hidden) / −128..127 (output)
```

## Status

| Step | State | Result |
|---|---|---|
| 0. Resource probe (64 MACs + 32 BSRAM) | open-source done, **Gowin pending** | yosys/nextpnr: 64/96 MULT9X9, 32/46 BSRAM, byte enables + init files inferred. See `probe/README_probe.md` |
| 1. Python bit-exact model | done | `model/ns64.py`. Self-check PASS |
| 2. Engine RTL + Icarus | done (simulation) | 1,000 synthetic + 200 stress vectors, **0 mismatches**, **448 clocks = 16.6 µs at 27 MHz**. Requantizer 21,216 values, 0 mismatches. Mutation test 6/6 |
| 3. UART top + loader (CRC-32, two banks) | done (simulation) | `tb_top` over the real UART pins: 152 checks, 0 errors (info, inference, damaged / interrupted / shift-24 uploads refused with the old model still exact, two good uploads with bank swaps). Loader mutation test 5/5 (incl. lanes of a pair swapped) |
| 4. Host tool | written, tested against a simulated port only | `host/ns64_host.py`, logs to `logs/` |
| 5a. Open-source synthesis of the full design | done | see table below; bitstream builds |
| 5b. Gowin EDA synthesis + timing | **done** | Logic 7,091/20,736 (35 %), registers 5,318 (34 %), BSRAM 32/46 (SDPB), DSP 16/24 = 64 MULT9X9. **Fmax 58.6 MHz vs 27 MHz, 0 setup / 0 hold violations.** 1st try had failed (byte-enable RAM built from LUTs); fixed with plain SDP RAM + lane-pair loader. Reports: `docs/gowin_reports/` |
| 6. Hardware | **done (22 Nov 2026)** | Built-in model: 1,000 golden + 2,000 random vectors, **0 mismatches**. Stress model uploaded (CRC-32 732C18C9, 2.04 s): 200 vectors, 0 mismatches. Damaged upload refused, old model kept. Latency **448 clocks = 16.6 µs** (hardware counter). Link test 4,000 replies, 0 damaged. Logs: `logs/2026112213*` |
| On-chip self-test bitstream | not started | |

### UART link problem (found and fixed, 22 Nov 2026)

The first hardware runs lost or garbled about 1 % (inference) to 11 % (info) of the replies.
Cause: the host tool changed the pyserial `timeout` before every read. On Windows each change
calls `SetCommState`, the driver re-sends the line settings to the board's USB bridge (BL616) and
it re-initialises its UART, damaging the FPGA reply that was arriving. Fix: the timeout is set
once when the port opens (`Chip.read_exact`). The 6x4 tools never changed the timeout, which is
why the 6x4 was clean. FPGA changes made during the hunt and kept: UART transmitter with optional
2 stop bits (`D1`, power-up = 1 stop bit like the 6x4), test patterns (`D2`), weight RAMs read only
while computing (power), and a link-only build (`board/tangnano20k_ns64_linkonly.v`).

### Full design, open-source flow (yosys + nextpnr-himbaechel, `scripts/build_opensource.sh`)

| Resource | Used | Available | |
|---|---|---|---|
| LUT4 (incl. 2,012 ALU) | 8,142 | 20,736 | 39 % |
| DFF | 5,467 | 15,552 | 35 % |
| BSRAM | 32 | 46 | 69 % |
| MULT9X9 | 64 | 96 | 66 % |
| Max frequency (nextpnr estimate) | 107.5 MHz | 27 MHz needed | |

The logic is above my earlier estimate of 4–5K LUTs. nextpnr's frequency is an estimate; only
Gowin's timing report and a hardware run count.

## How the engine works

- 64 MAC lanes, lane j = neuron j. One input value is broadcast per clock; every lane adds
  `x × w` with its own weight.
- 32 block RAMs (1K × 16, two lanes each) share **one read address**. Each lane's column holds,
  per layer: bias low byte, bias high byte, then its weights. Two banks: bank 0 = built-in model,
  bank 1 = upload slot (an upload will flip the bank only if its CRC-32 is good).
- At the end of a layer the 64 sums are copied in one clock into a 64 × 24-bit shift chain that
  feeds **one** shared requantizer (ReLU, round, shift, clamp). Its output is the next layer's
  input stream, so the next layer starts immediately. One barrel shifter instead of 64.
- Per layer: N_in + 4 clocks. Total (16+4) + 6 × (64+4) + 20 = **448 clocks**.

## Run the tests (WSL Ubuntu)

```bash
cd /mnt/c/fpga/NetSilcon-64x6
python3 model/make_synthetic.py        # models/<name>/<name>.json + gen/ (fixed seeds, same files every time)
bash scripts/run_sim_engine.sh         # requantizer + engine vs Python, ~2 min. Ends: RESULT: PASS
bash scripts/mutation_test.sh          # 6 deliberate bugs, each must be caught (~1.5 min)
bash scripts/run_sim_top.sh            # whole board design over UART, uploads, bank swaps (~2.5 min)
bash scripts/mutation_test_loader.sh   # 4 deliberate loader/top bugs, each must be caught (~10 min)
```

Needs `python3-numpy` and `iverilog` (`sudo apt install iverilog python3-numpy`).

## Test models

| Model | Purpose | Shifts | CRC-32 |
|---|---|---|---|
| [`models/synthetic/`](models/synthetic/) (built into bank 0) | random weights, shifts calibrated so ~30 % of hidden activations are 0, <1 % saturate, the rest in between; ~7 % of outputs hit +127/−128 | 7 9 8 8 8 8 7 | 6F4225BF |
| [`models/stress/`](models/stress/) | weights only −128/+127, biases at ±32767/−32768, layer-2 sums up to 1,008,128 (21 bits) | 0 15 13 1 17 9 7 | 732C18C9 |

Activation statistics per layer: `gen/model_report.txt`.

## Layout

```
rtl/      ns64_engine.v, ns64_requant.v, ns64_wram.v
board/    tangnano20k_ns64.v (UART top), ns64_loader.v (CRC-32, two banks), ns_uart.v (from 6x4),
          tangnano20k_ns64.cst, tangnano20k.sdc
host/     ns64_host.py (PC tool: info, inference, upload, golden/random tests, logs)
docs/     protocol.md, gowin_build.md
tb/       tb_engine.v, tb_requant.v, tb_top.v
model/    ns64.py (reference math, image, CRC-32, RAM layout), make_synthetic.py
models/   synthetic.json, stress.json
gen/      wmem_00..31.mem (built-in RAM contents), tb/ (testbench RAMs), golden vectors, *.vh
scripts/  run_sim_engine.sh, run_sim_top.sh, mutation_test*.sh, make_tb_load.py, build_opensource.sh
probe/    step-0 resource probe
logs/     host-tool runs (later)
```

[Apache License 2.0](../../LICENSE). Copyright 2026 Nitish Kumar Sharma.
