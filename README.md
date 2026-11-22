# NetSilcon

**One fixed neural-network shape in hardware. Load new numbers and it does a new job.**

Repository: **NetSilcon-FPGA**, the FPGA prototypes of the NetSilcon engines. The NetSilcon
website lives in the separate `NetSilcon` repository.

NetSilcon is a family of small neural-network inference engines for edge devices, prototyped on
a **Sipeed Tang Nano 20K** FPGA (Gowin GW2AR-18). In every model the network **shape** is built
into the logic, and everything else (weights, biases, per-layer shifts) is **loadable at run time**
over UART with a CRC check. One bitstream can therefore do many jobs of the same shape: like an
op-amp, which becomes an amplifier, a filter or a comparator depending on a few resistor values.

| | General processor | NetSilcon | Fully hardwired |
|---|---|---|---|
| Network shape | anything | **fixed** | fixed |
| Weights, biases, shifts | anything | **loadable** | fixed |
| Speed | instruction by instruction | dataflow | dataflow |
| Jobs per chip | many | **many** (same shape) | one |

> **Status:** working FPGA prototypes, verified on real hardware. Not a fabricated chip.

## Models

| | [NetSilcon-6x4](NetSilcon-Models/NetSilcon-6x4/) | [NetSilcon-64x6](NetSilcon-Models/NetSilcon-64x6/) |
|---|---|---|
| Network | 4 → 6 → 6 → 6 → 6 → 2 | 16 → 64 → 64 → 64 → 64 → 64 → 64 → 16 |
| Parameters | 144 weights, 26 biases, 5 shifts | 22,528 weights, 400 biases, 7 shifts |
| Model size (upload) | 201 bytes, CRC-16 | 23,335 bytes, CRC-32 |
| Where the weights live | registers | 32 block RAMs, two banks |
| Compute | 72 multipliers, all neurons in parallel | 64 MAC lanes, one input per clock |
| **Latency (measured)** | **15 clocks = 0.56 µs** at 27 MHz | **448 clocks = 16.6 µs** at 27 MHz |
| Hardware vs Python int8 model | bit-exact, 576 / 576 vectors per app | bit-exact, 3,200 vectors |
| Model upload (measured) | 31 ms | 2.04 s |
| FPGA resources (Gowin EDA) | logic 49 %, DSP 24 / 24, BSRAM 1 | logic 35 %, DSP 16 / 24, BSRAM 32 / 46 |
| Max clock (Gowin timing) | 29.1 MHz | 61.5 MHz |
| Applications run | motor fault, irrigation, rover (incl. hardware-in-the-loop) | rover controller (trained, 16 LiDAR sectors, incl. hardware-in-the-loop), synthetic and stress test models |
| Details | [README](NetSilcon-Models/NetSilcon-6x4/README.md), [benchmarks](NetSilcon-Models/NetSilcon-6x4/docs/benchmarks.md) | [README](NetSilcon-Models/NetSilcon-64x6/README.md), [test report](NetSilcon-Models/NetSilcon-64x6/docs/test_report.md) |

### Shared by all models

- **Neuron math:** `acc = bias + Σ x·w` (int8 × int8), ReLU on hidden layers,
  `y = (acc + 2^(s−1)) >>> s`, clamp to 0..127 (hidden) or −128..127 (output).
- **Bit-exact Python reference** for every model, and testbenches that compare the hardware
  against it vector by vector.
- **UART protocol family:** `A5` inference, `C3` model upload, `C5` "which model is running?"
- **Safe updates:** a damaged or interrupted upload is refused and the running model keeps working.
- **Same board and pins:** Tang Nano 20K, 27 MHz clock on pin 4, UART on pins 69 / 70, LEDs on 15–20.

## Repository layout

```
LICENSE, NOTICE            Apache License 2.0 (applies to everything in this repository)
README.md                  this overview
NetSilcon-Models/
  NetSilcon-6x4/           4 → 6×4 → 2 engine: rtl, board, tb, model, models/<app>/, host,
                           rover_sim, bench, scripts, docs
  NetSilcon-64x6/          16 → 64×6 → 16 engine: rtl, board, tb, model, models/<app>/, host,
                           bench, probe, scripts, docs (test report), logs
```

Each model folder is a complete project with its own README, quick start, tests and hardware logs.
Run its scripts from inside that folder, for example:

```bash
cd NetSilcon-Models/NetSilcon-64x6
bash scripts/run_sim_engine.sh
```

### Applications: one folder per job

Each model folder keeps its trained applications in `models/<application>/`: the loadable model
file (`<application>.json`: weights, biases, shifts, CRC, golden vectors) and a `README.md`
(inputs, outputs, accuracy, how it was made). Every application of a model runs on the **same
bitstream**; uploading its file gives the chip a new job.

```
NetSilcon-6x4/models/    motor_fault/   irrigation/   rover/ (v2 + v1)
NetSilcon-64x6/models/   rover/         synthetic/    stress/ (test models)
```

The host tools find models in all subfolders, so a new application only needs its own folder.

### Adding a new model (new network shape)

Create `NetSilcon-Models/NetSilcon-<shape>/` with the same structure (`rtl/`, `board/`, `tb/`,
`model/` with a bit-exact Python reference, `models/<application>/`, `host/`, `scripts/`, `docs/`,
`README.md`), add it to the table above, and link the root `LICENSE` from its README.

## Roadmap

1. Store the uploaded model in flash and load it at power-up with a CRC check
2. Safety stop and supervisor in FPGA logic beside the 6x4 network, then HIL of the complete controller
3. Measure the microcontroller comparison on a real STM32 (so far: emulated instruction counts)
4. Run NetSilcon-64x6 faster with the PLL (Gowin timing allows about 61 MHz)
5. Long term: tape out on a shared multi-project wafer

## License

[Apache License 2.0](LICENSE). Copyright 2026 Nitish Kumar Sharma.
