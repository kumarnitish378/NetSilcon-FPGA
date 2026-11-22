# NetSilcon-64x6 — Test Report

**Device:** Sipeed Tang Nano 20K (Gowin GW2AR-LV18QN88C8/I7), 27 MHz
**Design:** NetSilcon-64x6, int8 network 16 → 64 → 64 → 64 → 64 → 64 → 64 → 16
**Date of the first successful hardware test:** 22 November 2026
**Commits:** `77c9773` (first successful hardware test); this report and the CPU benchmark were added in the next commit
**Author:** Nitish Kumar Sharma

---

## 1. Summary

| Area | Result |
|---|---|
| Python int8 model | self-check PASS (two independent implementations agree, image round trip, all 23,335 byte addresses) |
| Engine vs Python model (simulation) | 1,200 vectors, **0 mismatches**; requantizer 21,216 values, 0 mismatches |
| Complete board design over UART (simulation) | 168 checks, **0 errors** |
| Mutation tests (deliberate bugs must be caught) | engine 6 / 6, loader and top 5 / 5 |
| Gowin EDA build | fits: logic 35 %, BSRAM 32 / 46, DSP 16 / 24; **Fmax 61.5 MHz** vs 27 MHz, 0 setup / 0 hold violations |
| **Hardware: built-in model** | 1,000 golden + 2,000 random vectors, **0 mismatches** |
| **Hardware: model upload** | stress model LOADED (CRC-32 732C18C9, 2.04 s), 200 vectors, **0 mismatches** |
| **Hardware: damaged upload** | refused with CRC error, old model kept and still exact |
| **Hardware: latency** | **448 clocks = 16.6 µs** at 27 MHz (hardware counter), every inference |
| **Hardware: UART link** | 4,000 replies, 0 damaged (after the host-tool fix in section 6.3) |
| **Clock cycles per inference** | FPGA **448** vs laptop CPU ≈ **14,100** (best C code): **31× fewer cycles** (section 8) |

Every hardware number in this report comes from a log file in `logs/` (index in section 10).

## 2. Test setup

| Item | Value |
|---|---|
| Board | Sipeed Tang Nano 20K, USB-C to the PC, onboard BL616 USB bridge ("USB Debugger A") |
| UART | COM7, 115200 baud 8N1, FPGA pin 69 = TX, pin 70 = RX |
| Programming | Gowin Programmer, USB Debugger A, 0.9 MHz, GW2AR-18C, SRAM Program |
| Bitstream | `C:\fpga\gowin\ns64\impl\pnr\ns64.fs`, top `tangnano20k_ns64`, built 22 Nov 2026 13:01 |
| FPGA tools | Gowin EDA V1.9.11.03 Education; yosys + nextpnr-himbaechel (open-source cross-check) |
| Simulation | Icarus Verilog 12 (Linux; the engine tests and mutation tests were re-run by the user in WSL Ubuntu with the same results) |
| Host PC | Windows 11 (10.0.26300), Python 3.14.4, pyserial 3.5 |
| Host tool | `host/ns64_host.py` (logs every run to `logs/` as `.log` + `.csv`) |

## 3. Design under test

- 64 MAC lanes (lane j = neuron j), one input value broadcast per clock.
- Weights and biases in 32 block RAMs (1K × 16, two lanes each), one shared read address,
  two banks (bank 0 = built-in model, bank 1 = upload slot).
- One shared requantizer fed by a 64 × 24-bit shift chain (ReLU, round, shift 0..23, clamp).
- Math: `acc = bias16 + Σ x·w` (24-bit), ReLU on hidden layers, `y = (acc + 2^(s−1)) >>> s`,
  clamp 0..127 (hidden) / −128..127 (output). Identical to `model/ns64.py`.
- Model upload over UART: 23,335-byte image + CRC-32, written into the inactive bank, swapped
  in one clock only if the CRC is good. Protocol: `docs/protocol.md`.

### Test models

| Model | Purpose | Shifts | CRC-32 |
|---|---|---|---|
| `models/synthetic/synthetic.json` (built into the bitstream) | random weights, shifts calibrated: ~30 % of hidden activations 0, < 1 % saturated, ~7 % of outputs at +127 / −128 | 7 9 8 8 8 8 7 | 6F4225BF |
| `models/stress/stress.json` | extreme numbers: weights only −128 / +127, biases ±32767 / −32768, layer-2 sums up to 1,008,128 | 0 15 13 1 17 9 7 | 732C18C9 |

## 4. Simulation results (Icarus Verilog)

| Test | Script | Result |
|---|---|---|
| Requantizer, every shift 0..23, ReLU on/off, corner values + random | `scripts/run_sim_engine.sh` | 21,216 values, 0 mismatches |
| Engine vs Python, synthetic model | same | 1,000 vectors, 0 mismatches, 448 clocks |
| Engine vs Python, stress model | same | 200 vectors, 0 mismatches |
| Engine mutation test (rounding, ReLU, bias high byte, layer shift, output clamp, last weight) | `scripts/mutation_test.sh` | 6 / 6 detected |
| Board top over UART: info, inference, damaged / interrupted / shift-24 uploads refused, two good uploads with bank swaps, stray bytes, D1/D2 link commands | `scripts/run_sim_top.sh` | 168 checks, 0 errors |
| Loader / top mutation test (ignore CRC, write active bank, bias bytes swapped, lane pair swapped, keep old shifts) | `scripts/mutation_test_loader.sh` | 5 / 5 detected |
| Link-only top (no engine, echo) | `tb/tb_linkonly.v` | PASS |

The first mutation run found a gap: no test model ever drove an output past ±127, so a broken
output clamp went unnoticed. Both models were changed so outputs saturate; the clamp bug is now caught.

## 5. Synthesis and implementation

### Gowin EDA (final build, top `tangnano20k_ns64`)

| Resource | Used | Available | % |
|---|---|---|---|
| Logic (LUT + ALU + RAM16) | 7,252 | 20,736 | 35 % |
| Registers | 5,399 | 15,750 | 35 % |
| BSRAM (SDPB) | 32 | 46 | 70 % |
| DSP (64 × MULT9X9) | 16 | 24 | 67 % |
| Max frequency | **61.5 MHz** | 27 MHz needed | PASS, 0 setup / 0 hold violations |

Warning PR1014 (clock on general routing) also appears in the working NetSilcon-6x4 build; timing passes.

### Open-source cross-check (yosys + nextpnr)

64 / 96 MULT9X9, 32 / 46 BSRAM, LUT4 8,159 (39 %), DFF 5,474 (35 %), nextpnr estimate 114 MHz.

## 6. Issues found and fixed

### 6.1 Gowin built the weight RAMs from logic (first Gowin run)

- **Symptom:** `ERROR (RP0006)`: 81,666 logic cells (76,164 LUTs + 648 SSRAM) > 20,736.
- **Cause:** the weight RAM used byte-enable writes. yosys mapped that to BSRAM, GowinSynthesis did not.
- **Fix:** plain simple-dual-port RAM (`syn_ramstyle = "block_ram"`); the loader now pairs the two
  lanes of a RAM word and writes full 16-bit words. Wire format unchanged.
- **Verified:** 32 BSRAM in Gowin; loader mutation test includes "lane pair swapped".

### 6.2 Gowin compiled old copies of the source files

- **Symptom:** the second Gowin run gave exactly the same numbers as the first.
- **Cause:** Gowin copies added files into `C:\fpga\gowin\ns64\src\` and compiles those copies.
- **Fix:** files copied into `src\`; `docs/gowin_build.md` now contains a copy step for every change.

### 6.3 UART replies damaged on the way to the PC (main issue)

**Symptom.** The engine always computed correctly, but some replies reached the PC with a byte
missing or with shifted bits: about 1 % of inference replies and 7–11 % of info replies.

**Investigation.** Each step was measured on the board, without retries:

| Step | Test | Result | Conclusion |
|---|---|---|---|
| 1 | Re-ask two "mismatching" inputs (`--values`) | chip gives the Python answer | computation is correct; replies are damaged in transport |
| 2 | Bit-level analysis of damaged replies | receiver missed a start bit and slipped | damage happens on the FPGA → PC path |
| 3 | 2 stop bits in the FPGA transmitter | no change | not stop bits |
| 4 | `--linktest 2000` (fixed replies, no retries) | info 7.2 %, inference 1.9 % damaged | short replies worse than long ones |
| 5 | Unplug / replug the board | info 11.2 %, inference 0.95 % | not long uptime |
| 6 | **NetSilcon-6x4 bitstream, same board / PC / cable / Python** | **0 / 4,000 damaged** | depends on the 64x6 setup |
| 7 | Sweep: stop bits × reply delay × reply type (`--linksweep`) | inference replies clean; 0.6 ms delay cut errors ~10× | timing-related |
| 8 | Sweep: request length × reply length (`--linksweep2`) | 3-byte requests 230 / 1,800, 7-byte 53 / 1,800, 19-byte 0 / 1,800 | **short requests** trigger it; reply length does not |
| 9 | Weight RAMs read only while computing (power) | 210 / 52 / 1 of 1,800 | not RAM power |
| 10 | Link-only build: engine and RAMs removed (5 % logic) | 218 / 83 / 0 of 1,800 | not the engine, not power |
| 11 | Code review: pins, project settings, RTL, **host code** | host tool changed the pyserial timeout before every read | **root cause** |
| 12 | Host tool fixed, same link-only build | **0 / 5,400** | fixed |
| 13 | Host tool fixed, real design | **0 / 4,000** link test; all tests 0 mismatches | confirmed |

Steps 3 and 9 were wrong hypotheses. Their FPGA changes were kept because they are harmless or
useful: an optional second stop bit (off at power-up) and lower idle power.

**Root cause.** `ns64_host.py` set `serial.timeout` before every read. In pyserial 3.5 on
Windows, every timeout change calls `_reconfigure_port()` → `SetCommState()`. The driver re-sends
the line settings to the BL616 USB bridge, which re-initialises its UART. This happened right
after each request was sent, so the reset hit the FPGA reply that was arriving at that moment.

This explains every measurement:
- Short requests are hit because the reply arrives while the reset is in progress; long requests
  (17–19 bytes, ≥ 1.5 ms on the wire) are still being sent when the reset happens.
- The damage is mostly in the first reply bytes.
- A 0.6 ms reply delay helped.
- FPGA-side changes made no difference.
- The NetSilcon-6x4 tools set the timeout only once, at open.

**Fix.** The timeout is set once when the port opens and never changed (`Chip.read_exact` loops
until a deadline instead). A simulated serial port that raises an error on any timeout change
after opening passes every host-tool mode, and the old version trips it immediately.

**Verified on the board:** link-only build 0 / 5,400 damaged; real design 0 / 4,000 damaged;
1,000 + 2,000 + 200 vectors, 0 mismatches, 0 link errors.

### 6.4 Testbench bug (simulation only)

The `tb_top` receive buffer held 20 bytes; a 21-byte pattern reply failed. The buffer was
enlarged to 64 bytes. This was not a design bug.

## 7. Final hardware results (22 Nov 2026, 13:02–13:10, fixed host tool)

| Run | Log | Result |
|---|---|---|
| Link sweep 2, link-only build | `20261122_125811_linksweep2` | 0 / 5,400 damaged |
| Link test | `20261122_130223_linktest` | info 0 / 2,000, inference 0 / 2,000 |
| Golden vectors, built-in model | `20261122_130908_test` | 1,000, **0 mismatches**, 0 link errors, 448 clocks, USB round trip 16.8 ms |
| Random inputs vs Python | `20261122_130933_random` | 2,000, **0 mismatches**, 0 link errors |
| Upload stress model | `20261122_131023_load` | LOADED, chip CRC-32 732C18C9, loads = 1, 2,039 ms |
| Golden vectors, uploaded model | `20261122_131039_test` | 200, **0 mismatches**, 0 link errors |

Earlier the same day (before the host fix; the results that did arrive were correct):

| Run | Log | Result |
|---|---|---|
| Damaged upload (one bit flipped) | `20261122_013457_load_corrupt` | REFUSED - CRC error, chip CRC-32 5C1BB492 (as predicted), old model kept |
| Old model after the refused upload | `20261122_013515_test` | 100 vectors, 0 mismatches |
| Upload synthetic model back | `20261122_013735_load` | LOADED 6F4225BF, loads = 2 (second bank swap) |

## 8. Performance: clock cycles required per inference

The network needs 22,528 int8 multiply-adds per inference. Compared by **clock cycles required**,
so that the result does not depend on how fast each chip is clocked.

**Measured (22 Nov 2026).** CPU runs: same bit-exact math in C (`bench/bench.c`), 1,000 golden
vectors with 0 wrong outputs, single thread, laptop Linux VM. CPU clock from Windows Task Manager
during the session: **4.09 GHz**.

| Implementation | Clock | Time per inference | **Cycles required** | Multiply-adds per cycle |
|---|---|---|---|---|
| **NetSilcon-64x6 on FPGA** | 27 MHz | 16.6 µs | **448** (hardware counter) | **50.3** |
| CPU i7-13650HX, C `-O3 -march=native` (SIMD) | 4.09 GHz | 3.45 µs | **≈ 14,100** | 1.6 |
| CPU i7-13650HX, C `-O2 -march=native` | 4.09 GHz | 7.5 µs | ≈ 30,700 | 0.73 |
| NumPy, batch of 1,000 / one input at a time | 4.09 GHz | 13.5 µs / 62.6 µs | ≈ 55,000 / 256,000 | — |
| Plain Python | 4.09 GHz | 3,023 µs | ≈ 12.4 million | — |

**Result.**

- **Cycles:** the FPGA engine needs **31× fewer clock cycles** than the best CPU code
  (14,100 ÷ 448), and 69× fewer than `-O2` code.
- **Clock:** the laptop CPU runs at a **151× higher clock** (4,090 MHz ÷ 27 MHz).
- **Wall-clock time:** 151 ÷ 31.5 ≈ 4.8×, so on this board the CPU finishes first (3.45 µs vs
  16.6 µs). This matches the measured ratio.

**Clock required to match or beat the CPU** (448 cycles):

| FPGA clock | Time per inference | Compared with the CPU (3.45 µs) |
|---|---|---|
| 27 MHz (tested) | 16.6 µs | CPU 4.8× faster |
| 61.5 MHz (Gowin Fmax, not tested) | 7.3 µs | CPU 2.1× faster |
| **130 MHz (break-even)** | 3.45 µs | equal |
| 500 MHz (typical small ASIC, assumption) | 0.9 µs | FPGA design 3.9× faster |
| 4.09 GHz (same clock as the CPU, thought experiment) | 0.11 µs | FPGA design 31× faster |

**Limits of this comparison.**

- The CPU clock during the benchmark was not logged. 4.09 GHz is the Task Manager reading from
  the same session. The chip's base clock is 2.6 GHz and its turbo up to about 4.9 GHz, which puts
  the CPU at 9,000–16,900 cycles, so the per-cycle advantage is **20–38×**.
- The CPU used one thread. 20 threads could run 20 inferences in parallel; the FPGA engine runs
  one at a time (it is not pipelined across inferences).
- Power was not measured. The Gowin estimate for the whole FPGA is about 0.26 W.
- Not yet compared with a microcontroller (STM32 with CMSIS-NN), which is the realistic
  alternative for an edge device.
- Over USB-UART the end-to-end time is about 16.5 ms, dominated by USB. The 448-cycle figure is
  what a sensor or MCU wired directly to the FPGA would see.

Raw numbers: `bench/results_2026-11-22.txt`. Reproduce: `cd bench && python3 make_net_h.py &&
gcc -O3 -march=native -o bench bench.c && ./bench`.

## 9. Not yet verified / open items

- On-chip self-test bitstream: not built. The host golden-vector test checks the same thing over USB.
- Higher clock with the PLL: not tried. Timing would allow about 61 MHz.
- Uploaded models live in block RAM and are lost at power-off; flash storage is not implemented.
- Throughput over UART is limited by USB (about 16.5 ms per round trip, against 16.6 µs on the chip).
- Replies have no checksum. With the fix no damage was seen, but the host can only detect damage
  that changes the reply length or header.
- Gowin's power estimate does not reflect the RAM read enable (still 129 mW for BSRAM); actual
  current was not measured.
- Pin 88 (MODE0) is held low in the 6x4 build and left at the default in the 64x6. It turned
  out unrelated to the link issue but is not yet aligned.
- No trained model yet: only the synthetic and stress test models have run.

## 10. How to reproduce

Simulation (WSL Ubuntu):

```bash
cd /mnt/c/fpga/NetSilcon-64x6
python3 model/make_synthetic.py
bash scripts/run_sim_engine.sh
bash scripts/mutation_test.sh
bash scripts/run_sim_top.sh
bash scripts/mutation_test_loader.sh
```

Hardware (after programming `ns64.fs`, Windows):

```
cd C:\fpga\NetSilcon-64x6\host
python ns64_host.py COM7 --info
python ns64_host.py COM7 --linktest 2000
python ns64_host.py COM7 --test
python ns64_host.py COM7 --random 2000
python ns64_host.py COM7 --load ..\models\stress\stress.json --corrupt
python ns64_host.py COM7 --load ..\models\stress\stress.json
python ns64_host.py COM7 --test
```

### Log index (`logs/`)

| Log | Command | Result |
|---|---|---|
| 013344, 013350 | `--info` | synthetic 6F4225BF built-in |
| 013408 | `--test` | stopped at vector 135: damaged reply (host-tool bug) |
| 013457 | `--load stress --corrupt` | refused, CRC error |
| 013515 | `--test --count 100` | 0 mismatches |
| 013527 | `--load stress` | stopped: damaged info reply |
| 013707 | `--load stress` | loaded 732C18C9 |
| 013726, 013746 | `--test`, `--random 500` | stopped: damaged reply |
| 013735 | `--load synthetic` | loaded 6F4225BF, loads = 2 |
| 014911, 014941 | `--test`, `--random 2000` (2 stop bits, retries) | 4 and 14 link errors; 2 transport mismatches |
| 015425, 015436 | `--values` (the two mismatching inputs) | Python answer, 0 mismatches |
| 015441, 020801 | `--linktest 2000` (before / after replug) | 7.2 % / 11.2 % info damaged |
| 021512_linktest6x4 | 6x4 bitstream | 0 / 4,000 damaged |
| 023047, 030419 | `--linksweep 300` | stop bits no effect; inference clean |
| 024513, 030013 | `--linksweep2 200` (before / after RAM read enable) | request length decides |
| 124625 | `--linksweep2 200`, link-only build, old host | 218 + 83 + 0 damaged |
| **125811** | `--linksweep2 200`, link-only build, **fixed host** | **0 / 5,400** |
| **130223 – 131039** | final runs, real design, fixed host | **all PASS** (section 7) |
