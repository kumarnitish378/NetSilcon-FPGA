# NetSilcon-FPGA: project summary for AI agents

Last updated: 2026-11-22. Author: Nitish Kumar Sharma. License: Apache-2.0 (root `LICENSE`, `NOTICE`).
Website: https://kumarnitish378.github.io/NetSilcon/ (source in the `website/` submodule).

## 1. Idea

A neural network whose **shape is fixed in hardware** and whose **numbers (weights, biases,
per-layer shifts) are loadable at run time** over UART with a CRC check. One bitstream does many
jobs of the same shape: upload a different model file, get a different product (like an op-amp
whose resistor values decide amplifier, filter or comparator). Target: sensor-level decisions on
edge devices; long-term goal a real chip (multi-project wafer). Today: working FPGA prototypes,
not silicon.

## 2. Repository layout

```
README.md, LICENSE, NOTICE
AGENTS.md, CLAUDE.md          -> point to Agent/
Agent/                        this folder (text summaries for agents)
media/                        demo and keynote videos (MP4)
tools/sync_website.py         copies model files into website/, prints model facts
website/                      git submodule: kumarnitish378/NetSilcon (Astro static site, GitHub Pages)
NetSilcon-Models/
  NetSilcon-6x4/              4 -> 6x4 -> 2 engine
  NetSilcon-64x6/             16 -> 64x6 -> 16 engine
  NetSilcon-LM-0/             character language model (32-char context, 42 symbols) on the 64x6 datapath
```

Every model folder has the same grouping (run all commands from inside the model folder):

```
README.md                  overview, quick start, results
models/<application>/      trained application: <application>.json + README.md
fpga/                      rtl/, board/ (top, UART, loader, .cst, .sdc), tb/, gen/ (built-in RAM
                           contents, golden vectors, *.vh), scripts/ (sim + build; creates fpga/sim, fpga/build)
                           64x6 also: probe/ (resource probe)
python/                    model/ (bit-exact reference, training), host/ (PC tool), rover_sim/, bench/
docs/                      protocol, architecture or test report, Gowin build guide (6x4: datasheet PDF, images/)
results/                   logs/ (hardware runs, .log + .csv), result summaries
```

## 3. Neuron maths (identical in Verilog and Python, both engines)

```
acc = bias16 + sum(x_i * w_i)          x, w int8; bias int16
if hidden layer: acc = max(acc, 0)     ReLU
v = (acc + 2^(s-1)) >>> s              arithmetic shift, round half up; s = 0 means no rounding constant
y = clamp(v, 0, 127)   hidden layers   (int8 input of the next layer)
y = clamp(v, -128, 127) output layer
```

Inputs to the chip are 0..127 (real value / range * 127). Classifiers: decision = argmax / y1 > y0.
Regression (rover): value = y / 127 in -1..+1.

## 4. The two engines (FPGA reference: Tang Nano 20K, GW2AR-LV18QN88C8/I7, 27 MHz)

| | NetSilcon-6x4 | NetSilcon-64x6 |
|---|---|---|
| Shape | 4 -> 6 -> 6 -> 6 -> 6 -> 2 | 16 -> 64 -> 64 -> 64 -> 64 -> 64 -> 64 -> 16 |
| Parameters | 170 = 144 w (int8) + 26 b (int16); 5 shifts (0..15) | 22,928 = 22,528 w + 400 b; 7 shifts (0..23) |
| Accumulator | 20-bit | 24-bit |
| Weights in | registers | 32 BSRAM SDPB 1K x 16, two banks (0 built-in, 1 upload) |
| Compute | 72 multipliers, 2 phases | 64 MAC lanes, 1 input broadcast per clock, 1 shared requantizer |
| Latency | 15 clocks = 0.556 us | 448 clocks = 16.6 us |
| Model image | 201 bytes + CRC-16/CCITT-FALSE | 23,335 bytes + CRC-32 (zlib.crc32) |
| Upload | 31 ms | 2.04 s |
| Resources | 49 % logic, 24/24 DSP, 1 BSRAM; Fmax 29.1 MHz | 35 % logic, 32/46 BSRAM, 16/24 DSP; Fmax 61.5 MHz |
| Top module | tangnano20k_uart | tangnano20k_ns64 |
| Host tool | python/host/netsilcon_host.py | python/host/ns64_host.py |

Pins (both): clock pin 4, UART TX 69 / RX 70 (USB-C, BL616 bridge), LEDs 15-20.

## 5. UART protocol (115200 8N1)

| Command | 6x4 | 64x6 |
|---|---|---|
| Inference | `A5 x0..x3` -> 5-byte reply | `A5 x0..x15` -> `5A y0..y15 argmax lat_lo lat_hi` (20 bytes) |
| Upload | `C3` + 201 B + CRC-16 (hi, lo) -> `3C status crc loads` | `C3` + 23,335 B + CRC-32 (LE) -> `3C status crc32 loads` (7 B) |
| Which model | `C5` -> source (0 built-in, 1 uploaded) + CRC | `C5` -> `5C crc32 source loads` |
| Link test (64x6) | | `D1 s d` stop bits / reply delay, `D2 n k` test pattern |

Upload status: 0 ok, 1 CRC error, 2 timeout, 3 (64x6) shift > 23. On any error the old model keeps
running. Full specs: `docs/protocol.md` / `docs/uart-protocol` on the website.

## 6. Results (all from logs in results/logs/)

**NetSilcon-6x4:** 3 trained jobs on one bitstream (motor fault 94.5 % int8, irrigation 97.4 %,
rover v2), 576/576 golden vectors bit-exact each; corrupted upload refused; HIL rover 9,600
decisions, 0 mismatches, also with 2 cm noise. Estimated vs STM32F407: about 25x faster,
24-36x less energy (MCU numbers are instruction counts + datasheet, not measured).

**NetSilcon-64x6:** simulation 1,200 vectors + 21,216 requantizer cases, 0 mismatches; board-level
UART sim 168 checks; mutation tests 11/11 caught; hardware 1,000 golden + 2,000 random + 200
stress vectors, 0 mismatches; latency 448 clocks every time; 31x fewer clock cycles than a laptop
CPU (i7-13650HX, C -O3, ~14,100 cycles; CPU wins in wall time at 27 MHz, break-even ~130 MHz).
Trained rover controller (16 LiDAR sectors -> speed, steering; CRC-32 3A81C867; 89.8 % int8 action
agreement): simulation 0/80 crashes, 46.9 m avg; 40 unseen worlds 0 crashes, 37.9 m (6x4: 33.3 m);
HIL 19,200 decisions, 0 mismatches, 8 drives 0 crashes 0 stuck. Supervisor and safety stop run on
the PC. Details: `NetSilcon-64x6/docs/test_report.md`.
Trained maze driver (same 16 inputs, right-hand rule; CRC-32 CA0156C9): simulation 72/80 unseen
mazes solved, 0 crashes (rover model 38/80); Verilog 1,200 vectors bit-exact; not run on hardware yet.
Details: `NetSilcon-64x6/models/maze/README.md`.

**NetSilcon-LM-0:** char-level LM, 32-char context x 8-dim embedding -> 256 -> 64 -> 64 -> 64 -> 42, 27,834 params,
model v2 CRC-32 8A7B9204, 2.9M chars synthetic pump dialogues, quantization-aware training. Answer grader:
96.2 % trained wordings, 53.1 % held-out wordings (v1 CRC 59993775: 24.6 % / 11.5 %). Icarus: 802 vectors
(42 logits + argmax) 0 mismatches; on-chip conversation 392/392 chars = Python; UART top 137/137 bytes;
mutation 8/8; 510 clocks/char. yosys+nextpnr: LUT4 33 %, BSRAM 33/46, MULT9X9 64/96, 140 MHz.
Not run on hardware, no Gowin EDA build yet. Details: `NetSilcon-LM-0/README.md`.

## 7. How to verify (no board needed)

```bash
cd NetSilcon-Models/NetSilcon-6x4  && bash fpga/scripts/run_all_tests.sh
cd NetSilcon-Models/NetSilcon-64x6 && python3 python/model/make_synthetic.py && bash fpga/scripts/run_sim_engine.sh
bash fpga/scripts/run_sim_top.sh && bash fpga/scripts/mutation_test.sh     # 64x6, a few minutes each
cd website && npm ci && npm run check && npm run build                      # website
```

With a board (Windows example, COM7):

```bash
python python/host/ns64_host.py COM7 --info | --test | --random 500 | --load models/rover/rover.json
python python/rover_sim/rover64.py --hil COM7 --unstick --runs 2
```

## 8. Known pitfalls (learned on hardware)

- Gowin EDA did not infer block RAM for a byte-enable RAM (RP0006, ~81,666 logic): use plain SDP RAM.
- Gowin compiles copies in `C:\fpga\gowin\<project>\src\`: copy changed sources there before building.
- pyserial on Windows calls SetCommState on every timeout change, which resets the BL616 bridge and
  damages replies: set the timeout once (see `Chip.read_exact` in the 64x6 host tool).
- Icarus: avoid SystemVerilog keywords (`ref`, `expect`) as names; `always @*` does not run at time 0.

## 9. Plans

- LM track: LM-0 on hardware, then LM-1 (command -> action + reply), LM-2 (sensor values as inputs).
- Next: model storage in flash, SPI, supervisor and safety stop in FPGA logic, real sensors,
  STM32 measurement, faster clock with the PLL, more FPGA boards (when funded).
- Working goal of the author: 2 new network architectures per month and 1 new trained model per
  week, each verified bit-exact on the FPGA before it is published.
