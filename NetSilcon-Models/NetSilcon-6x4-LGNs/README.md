# NetSilcon-6x4-LGNs

**A NetSilcon series that trains the circuit itself, not the weights.**

The classic NetSilcon-6x4 stores weights and biases and runs MAC operations.
This series keeps the same 4-input → 2-output interface but trains a **Logic Gate
Network (LGN)** on the host. Every node learns *which* 2-input gate it is (AND, XOR,
NAND, ... 16 choices). After training, the network is frozen into **pure combinational
Verilog**: no registers, no BSRAM, no multipliers, no weight memory. The wiring and the
gate types *are* the model.

Method after Petersen et al., *Deep Differentiable Logic Gate Networks* (NeurIPS 2022),
and LogicNets (Umuroglu et al., 2020). Implemented here from scratch in plain numpy.

## Pipeline

```
python/train.py          host training: soft gates -> frozen gate netlist (models/<name>/netlist.npz)
python/export_verilog.py netlist -> fpga/<name>/*.v  (continuous assigns only) + golden vectors + testbench
fpga/run_fpga_checks.sh  Icarus bit-exact test -> yosys synth_gowin -> nextpnr (GW2AR-18, Tang Nano 20K)
python/collect_results.py  every number in results/ is parsed from generated files
```

The hardware model:
```
4 x 8-bit sensors -> thermometer encoder (124 constant comparators)
  -> 4 logic layers of W gates (the "x4" of 6x4)
  -> GroupSum popcount per class -> argmax -> speed (2 bit), steer (3 bit)
```

## Exp-01: rover obstacle avoidance (synthetic teacher)

Inputs are 4 corner distance sensors FL, FR, RL, RR (0–255 cm). Outputs are speed
(stop/slow/medium/fast) and steer (hard-left/left/straight/right/hard-right).
The labels come from a hand-written rule set in `python/dataset.py`, so the data is synthetic.
There's 40k train and 8k test samples, and 4096 golden vectors for the Verilog.

### Measured results

| model | gates | speed acc | steer acc | both correct | Icarus vs Python | core LUT | core MUX2_LUTx | core ALU | core FF | core BSRAM | core DSP | Fmax (wrapper) | P&R LUT4 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| w180 | 720 | 90.00% | 83.33% | 74.51% | PASS 0/4096 | 875 | 341 | 326 | **0** | **0** | **0** | 89.76 MHz | 1604 / 20736 |
| w360 | 1440 | 90.39% | 89.40% | 80.49% | PASS 0/4096 | 1985 | 1050 | 388 | **0** | **0** | **0** | 46.59 MHz | 3025 / 20736 |
| w720 | 2880 | 91.67% | 90.76% | 82.91% | PASS 0/4096 | 3914 | 2086 | 465 | **0** | **0** | **0** | 37.25 MHz | 6007 / 20736 |
| w1440 | 5760 | 91.91% | 90.64% | 83.03% | PASS 0/4096 | 7385 | 3842 | 498 | **0** | **0** | **0** | 32.19 MHz | 10549 / 20736 |

The baseline is the weight-based MLP 4-6-6-6-6-9 (the NetSilcon-6x4 shape, 9 class outputs)
on the same data, with 219 parameters. Float: 90.24% both correct. int8: **87.22%** both correct
(speed 89.98%, steer 97.02%).

How to read the table:
- The *core* columns come from yosys `synth_gowin` of the LGN module alone.
- *Fmax* and *P&R LUT4* come from nextpnr on GW2AR-LV18QN88C8/I7 using `timing_wrapper.v`.
  That wrapper adds a 32-bit input shift register and a 5-bit output register (37 DFF)
  **only so the tools can time reg → core → reg**. The core itself has 0 FF.
- Accuracy is the hard (deployed) gate network on the test set, not the soft training model.
- These are open-source flow numbers (yosys/nextpnr). Gowin EDA numbers should be checked
  separately on Windows.

### What Exp-01 shows (honestly)

1. **The idea works end to end.** A circuit trained on the host became Verilog that matches
   Python bit-for-bit (0 mismatches on 4096 vectors in all 4 sizes), with **zero registers,
   zero BSRAM and zero DSP** in the core.
   **Not tested yet:** Gowin EDA build, programming the board, real sensors.
2. **It doesn't beat the weights version yet.** The best LGN gets 83.0% both-correct vs
   87.2% for the int8 MLP. Speed is similar (~91%). **Steering is the weak part** (~90.7%
   vs 97.0%).
3. **Width saturates around 720.** Going from 720 to 1440 gates/layer doubled the area
   and gave +0.1%. More gates is not the fix.
4. **Probable cause:** steering depends on FL − FR, a *comparison between two sensors*.
   With a thermometer encoder plus random 2-input wiring, the network has to rebuild
   a comparator out of scattered gates, and it does that poorly. The 8-cm threshold step
   also caps accuracy. The best possible with a bucket-midpoint oracle at step 8 is ~93%
   both-correct.
5. Delay grows with width because routing grows (89.8 MHz at w180 down to 32.2 MHz at w1440,
   reg-to-reg including the wrapper). That's still well above the board's 27 MHz clock,
   and the core has no clock at all.

### Next experiments in the series
- **Exp-02:** finer thermometer (step 4 / step 2) and a learnable-wiring LGN (choose inputs,
  not random). The aim is to close the steering gap.
- **Exp-03:** give the circuit a pair-wise comparator front-end (FL>FR+k bits). These are still pure
  combinational, and the test is whether "hint" features beat raw width.
- **Exp-04:** UART top for hardware-in-the-loop on the Tang Nano 20K, same as the NetSilcon-6x4
  host-script flow, logging to logs/.
- **Exp-05:** the same LGN flow on the existing NetSilcon-6x4 apps for a direct comparison.

## Run it (WSL Ubuntu)

```bash
sudo apt install iverilog
pip install numpy yowasp-yosys yowasp-nextpnr-himbaechel-gowin   # or native yosys/nextpnr
./run_all.sh                       # full pipeline, ~1 h on 2 CPU cores
# or one model:
cd python && python3 train.py --width 360 --epochs 80 --name exp01_w360
python3 export_verilog.py exp01_w360 && ../fpga/run_fpga_checks.sh exp01_w360
```

Every run writes `.log` (and `.csv` for training) into `results/logs/`.

Mutation test (breaks gates on purpose, the testbench must fail): `fpga/mutation_test.sh exp01_w180`.
Measured: 5/5 mutants caught for each of the 4 models.

### Gowin EDA check (Windows)
1. New project → device **GW2AR-LV18QN88C8/I7**.
2. Add `fpga/<model>/netsilcon_6x4_lgn_<model>.v`, `timing_wrapper.v`, and `tangnano20k.cst`
   (clk pin 4, din pin 88, dout pin 15 = LED0).
3. Set top module = `timing_wrapper`, then run Synthesize and Place & Route.
4. Note the resource report (LUT, ALU, REG, BSRAM, DSP) and the timing report. Expect REG = 37,
   all from the wrapper, and BSRAM/DSP = 0.

## Layout
```
python/   dataset.py  lgn.py  train.py  baseline_mlp.py  export_verilog.py  collect_results.py
models/   exp01_w*/netlist.npz  result.json            (frozen circuits)
fpga/     exp01_w*/  core .v, testbench, golden.hex, timing_wrapper.v, .cst, core_stat.txt, pnr.log
results/  summary.md  summary.csv  baseline_mlp.json
results/logs/  train_*.log/.csv  fpga_*.log  mutation_*.log
```

License: Apache-2.0, see the root [LICENSE](../../LICENSE).
