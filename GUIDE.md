# NetSilcon user guide: from `git clone` to your own AI on FPGA

This guide takes you through everything, in order:

1. get the code and the tools
2. check that everything works **without a board** (simulation)
3. build the FPGA bitstream and program the Tang Nano 20K
4. talk to the network from your PC and run the ready-made applications
5. **train your own model** from a CSV table
6. test it at every level: Python, Verilog simulation, real hardware
7. use it from your own program (PC or microcontroller)
8. change the hardware itself (a new network shape)

Each step ends with a check, so you always know whether it worked. Every expected result
below was produced by the commands shown.

---

## 0. Which engine do you want?

NetSilcon has two engines. Both run on the same board. The **shape** of each network is fixed in
hardware; the **numbers** (weights, biases, shifts) are a file you upload.

| | NetSilcon-6x4 | NetSilcon-64x6 |
|---|---|---|
| Network | 4 inputs → 4 layers of 6 → 2 outputs | 16 inputs → 6 layers of 64 → 16 outputs |
| Parameters | 170 | 22,928 |
| Answer time | 15 clocks = 0.56 µs | 448 clocks = 16.6 µs |
| Model file / upload | 201 bytes, 31 ms | 23,335 bytes, about 2 s |
| Good for | small decisions from 4 readings | up to 16 readings in, up to 16 classes or values out |
| Folder | `NetSilcon-Models/NetSilcon-6x4/` | `NetSilcon-Models/NetSilcon-64x6/` |

**Rule of thumb:** start with NetSilcon-64x6 for a new job. Use 6x4 when 4 inputs and 2 outputs are
enough and you want the smallest, fastest design.

---

## 1. What you need

| Item | Needed for | Notes |
|---|---|---|
| A PC (Windows, Linux or macOS) | everything | Windows users: the test scripts are bash; run them in **WSL Ubuntu** (recommended) or Git Bash |
| Python 3.9+ with `numpy` | everything | `pyserial` too, for talking to the board |
| [Icarus Verilog](https://steveicarus.github.io/iverilog/) | simulation | Linux/WSL: `sudo apt install iverilog` |
| Sipeed Tang Nano 20K | hardware steps | FPGA Gowin GW2AR-18 (GW2AR-LV18QN88C8/I7), USB-C |
| Gowin EDA, Education edition (free) | building the bitstream | the tested path; open-source tools also work for 6x4 |

You can do sections 2, 5 and 6 (simulation, training, testing) with **no board at all**.

---

## 2. Get the code and the tools

```bash
git clone https://github.com/kumarnitish378/NetSilcon-FPGA.git
cd NetSilcon-FPGA
```

(`git clone --recursive` also fetches the website source into `website/`. You don't need it to use NetSilcon.)

Install the tools:

```bash
# Linux / WSL Ubuntu
sudo apt install iverilog python3-numpy python3-pip
pip install pyserial            # add --break-system-packages on newer Ubuntu, or use a venv

# Windows (for the PC tools that talk to the board)
pip install numpy pyserial
```

**Check:** `iverilog -V` prints a version, and `python3 -c "import numpy, serial"` prints nothing.

---

## 3. Check everything without a board (simulation)

Simulation runs the real Verilog on your PC and compares **every** answer with the Python model,
bit for bit. If this passes, the design is good before you touch hardware.

### NetSilcon-64x6

```bash
cd NetSilcon-Models/NetSilcon-64x6
python3 python/model/make_synthetic.py      # test models + RAM files (same files every time)
bash fpga/scripts/run_sim_engine.sh         # ~2 min
bash fpga/scripts/run_sim_top.sh            # whole board design over UART, uploads, bank swaps, ~3 min
```

**Check:** each ends with `RESULT: PASS`. The engine test prints
`latency start->done: 448..448 clocks (16.59 us at 27 MHz)`.

Optional, slower: `bash fpga/scripts/mutation_test.sh` and `mutation_test_loader.sh` insert deliberate
bugs into the design. Every bug must be caught; they end with `PASS (every mutation detected)`.

### NetSilcon-6x4

```bash
cd NetSilcon-Models/NetSilcon-6x4
bash fpga/scripts/run_all_tests.sh          # Windows without bash: fpga\scripts\run_sim.bat
```

**Check:** every test ends with `RESULT: PASS` (network vs Python, board self-test, live UART inference, model upload).

---

## 4. Put it on the board

### 4.1 Build the bitstream (Gowin EDA)

Full click-by-click instructions:
[NetSilcon-64x6 → `docs/gowin_build.md`](NetSilcon-Models/NetSilcon-64x6/docs/gowin_build.md) ·
[NetSilcon-6x4 → README, "Build and load"](NetSilcon-Models/NetSilcon-6x4/README.md#2-build-and-load-on-the-tang-nano-20k).
The short version for NetSilcon-64x6:

1. New project, device **GW2AR-LV18QN88C8/I7**.
2. Add `fpga/rtl/ns64_requant.v`, `ns64_wram.v`, `ns64_engine.v` and `fpga/board/ns_uart.v`,
   `ns64_uart_tx.v`, `ns64_loader.v`, `tangnano20k_ns64.v`, `tangnano20k_ns64.cst`, `tangnano20k.sdc`.
3. Copy `fpga/gen/wmem_00.mem` … `wmem_31.mem` next to the `.gprj` file (the built-in model).
4. Top module `tangnano20k_ns64`, include path `fpga/gen`.
5. Synthesize → Place & Route.

> Gowin **copies** the added files into its own `src/` folder. After you change a `.v` file in the
> repo, copy it again (or re-add it) before you synthesize.

**Check:** Place & Route finishes with no errors. Resources should be close to logic 35 %,
BSRAM 32 / 46, DSP 16 / 24.

### 4.2 Program the board

Gowin **Tools → Programmer**: cable *USB Debugger A*, 0.9 MHz, device GW2AR-18C,
operation **SRAM Program**, file `impl/pnr/<project>.fs`.

SRAM programming is lost at power-off; program again after unplugging. (Writing to the board's
flash keeps it, but it is slower to iterate with.)

**Check:** LED0 blinks (heartbeat).

### 4.3 Find the serial port

The Tang Nano 20K shows **two** USB devices: one for programming, one serial port for the network.
On Windows look in Device Manager → Ports (this guide uses `COM7`); on Linux it is usually
`/dev/ttyUSB1`. Settings: 115200 baud, 8N1 (the tools set this for you).

---

## 5. Talk to it from the PC

```bash
cd NetSilcon-Models/NetSilcon-64x6/python/host
python ns64_host.py COM7 --info        # which model is running?
python ns64_host.py COM7 --test        # 1,000 golden vectors, every answer checked
python ns64_host.py COM7 --random 500  # 500 random inputs vs the Python model
```

**Check:** `--info` says `chip runs: synthetic  CRC-32 6F4225BF  source=built-in`, and `--test` ends with
0 mismatches.

Upload a different model (about 2 s), and prove that a damaged upload is refused:

```bash
python ns64_host.py COM7 --load ../../models/rover/rover.json --corrupt   # expect: REFUSED - CRC error
python ns64_host.py COM7 --load ../../models/rover/rover.json             # expect: LOADED 3A81C867
python ns64_host.py COM7 --test                                           # rover golden vectors
```

Every run writes a `.log` and a `.csv` (one row per answer) to `results/logs/`.

For NetSilcon-6x4 the tool is `python/host/netsilcon_host.py` with the same idea
(`--info`, `--test`, `--load`, `--demo`, `--values` in real units).

---

## 6. Run the ready-made applications

| Application | Engine | Run it |
|---|---|---|
| Motor fault detector (built in) | 6x4 | `python netsilcon_host.py COM7 --demo` |
| Irrigation controller | 6x4 | `--load ../../models/irrigation/irrigation.json`, then `--demo` |
| Rover obstacle avoidance | 6x4 | `python/rover_sim/rover_sim.py --hil COM7 --map clutter --view` |
| Rover obstacle avoidance, 16 LiDAR slices | 64x6 | upload `rover.json`, then `python python/rover_sim/rover64.py --hil COM7 --unstick` |
| Pump vibration health (example, section 7) | 64x6 | `python python/host/app_example.py --model models/pump_health/pump_health.json --port COM7 --csv data/pump_vibration.csv` |

**Hardware in the loop (HIL)** means the PC simulates the robot and its sensor, but every driving
decision is made by the real FPGA. No board? Drop `--hil COM7` and the bit-exact Python model drives.
The rover simulator also runs in a browser: `NetSilcon-6x4/python/rover_sim/rover_simulator.html`.

---

## 7. Train your own model (NetSilcon-64x6)

You need one thing: **a table**. Each row is one moment; the columns are your sensor readings
(up to 16) and the answer you want (a class name, or numbers).

```
rpm,current_a,temp_c,...,crest_factor,state
2911.2,11.43,47.1,...,3.08,normal
1876.0,8.02,41.9,...,5.71,bearing
```

### 7.1 Worked example: pump vibration health

The repository includes a generator for **synthetic** example data (made by simple rules plus
noise, to show the workflow; for a real product, record the same table from your own machine):

```bash
cd NetSilcon-Models/NetSilcon-64x6
python3 python/model/example_pump_data.py
#   wrote 20000 rows to data/pump_vibration.csv (16 inputs, target 'state':
#   normal, imbalance, misalignment, bearing)

python3 python/model/train_csv.py data/pump_vibration.csv --name pump_health --target state
```

What you should see (about 5 seconds):

```
inputs (16 of 16): rpm, current_a, temp_c, pressure_bar, band_1x, ... kurtosis, crest_factor
target 'state': 4 classes ['bearing', 'imbalance', 'misalignment', 'normal']
training: 16000 rows, validation 2000, test 2000 (never used for training)
shifts [9, 7, 8, 8, 8, 8, 8]   CRC-32 6579E12F
test accuracy: float 95.5 %   int8 (= FPGA) 95.2 %   int8 agrees with float on 99.2 % of rows
confusion (rows = true class, columns = int8 prediction):
     bearing  imbalance misalignme     normal
         540          0          0          0   bearing
           0        421          0         51   imbalance
           0          0        507          0   misalignment
           0         45          0        436   normal
golden vectors: 1000  (independent slow model agrees on the first 50: yes)
saved models/pump_health/pump_health.json  (and README.md)
```

How to read it:

- **int8 (= FPGA)** is the accuracy the chip will really give, measured on 2,000 rows the network
  never saw. Here it is 95.2 % against 95.5 % for the float network, so converting to int8 cost very little.
- **The confusion table** shows where it goes wrong: some early, mild imbalance looks like normal
  running. Better or more data fixes that, not a bigger chip.
- **The model file** holds everything: weights, the CRC-32, how to scale each input, what each output
  means, and 1,000 golden test vectors.

### 7.2 Options

```bash
# choose the input columns yourself (max 16)
python3 python/model/train_csv.py data.csv --name x --target label --inputs a,b,c,d

# regression: predict numbers (up to 16 target columns)
python3 python/model/train_csv.py data.csv --name burn --target fuel_g_min --regress

# fix the input ranges (recommended for a real product: use the sensor's real limits)
python3 python/model/train_csv.py data.csv --name x --target label --ranges ranges.json
#   ranges.json: {"temp_c": [-20, 120], "rpm": [0, 3000]}

--epochs 60   --seed 2   --title "one-line description"
```

Regression reports the mean absolute error in real units for each target, float and int8.

### 7.3 How it works (one paragraph)

Each input is scaled to the chip's range 0..127 using its minimum and maximum. A normal float
network is trained (numpy, no GPU needed). Then each layer is converted to int8 weights, int16 biases and
a power-of-two **shift**, the same arithmetic the hardware does, so the Python result and the FPGA
result are **identical**, not just close. For a classifier, the decision is the largest of the first
C outputs (C = number of classes); unused outputs are always exactly 0.

### 7.4 Tips for a good model

- **Test on data the network never saw.** `train_csv.py` keeps 10 % aside automatically. For a real
  product, also test on a different day, machine or batch.
- **Balance the classes**, or the network learns to always say the common one.
- **Fix input ranges** (`--ranges`) to the real sensor limits, so a value outside the training data
  still lands in a sensible place.
- **A model that copies rules well can still behave badly in a loop.** For anything that drives
  something (a robot, a valve), test in closed loop, as the rover was (section 8.4).

### 7.5 Training for NetSilcon-6x4 (4 inputs, 2 outputs)

Add an entry to `NetSilcon-6x4/python/model/apps.py` (input names, units and ranges, output labels,
a data generator, demo scenarios; copy `IRRIGATION` as a template), then:

```bash
cd NetSilcon-Models/NetSilcon-6x4/python/model
python3 make_model.py <name>       # writes models/<name>/<name>.json with golden vectors
```

---

## 8. Test your model, level by level

Each level catches a different kind of mistake. Do them in order.

### 8.1 Python: the model file is consistent

`train_csv.py` already checked this: the CRC-32 matches the numbers, and an independent, slow
Python model agrees with the fast one. Any later tool that opens the file checks the CRC again.

### 8.2 Verilog simulation: the hardware gives the same answers (no board)

```bash
cd NetSilcon-Models/NetSilcon-64x6
bash fpga/scripts/run_sim_model.sh models/pump_health/pump_health.json     # ~1.5 min
```

Expected:

```
pump_health: CRC-32 6579E12F, shifts [9, 7, 8, 8, 8, 8, 8], 1000 golden vectors (bank 0: all, bank 1: first 200)
pump_health (bank 0): 1000 vectors, 0 mismatches
pump_health (bank 1): 200 vectors, total mismatches 0
latency start->done: 448..448 clocks (16.59 us at 27 MHz)
RESULT: PASS
```

This loads your model into the real Verilog engine (both RAM banks) and compares every golden vector.

### 8.3 Real hardware

```bash
cd python/host
python ns64_host.py COM7 --load ../../models/pump_health/pump_health.json   # LOADED 6579E12F, ~2 s
python ns64_host.py COM7 --test                                             # 1,000 vectors, expect 0 mismatches
```

The host tool recognises the model by its CRC-32: any `.json` under `models/` works.

### 8.4 The application: real inputs, real decisions

```bash
# without a board: the bit-exact Python model answers
python app_example.py --model ../../models/pump_health/pump_health.json --sim --csv ../../data/pump_vibration.csv --rows 8
# with the board: every chip answer is also checked against Python
python app_example.py --model ../../models/pump_health/pump_health.json --port COM7 --csv ../../data/pump_vibration.csv --rows 8
```

Expected (sim):

```
  bearing                                  (true: bearing)   0.19 ms
  misalignment                             (true: misalignment)   0.07 ms
  ...
8 of 8 rows correct
```

The time shown includes Python and, with `--port`, the USB round trip (about 15 ms on our PC). The chip
itself answers in 16.6 µs.

For controllers, add a closed-loop test: simulate the machine and let the chip drive it, as
`rover64.py --hil COM7` does for the rover. That is where rule-copying errors show up.

---

## 9. Use NetSilcon from your own program

`python/host/app_example.py` is short on purpose. Copy its three functions into your code:

| Function | What it does |
|---|---|
| `scale_inputs(model, values)` | real readings `{"temp_c": 48, ...}` → 16 chip inputs 0..127, using the ranges in the model file |
| `NetSilconChip(port).infer(q)` | sends `A5 x0..x15`, reads the 20-byte reply, returns 16 signed outputs |
| `decode(model, y)` | outputs → class name, or values in real units |

The wire protocol is tiny, so a **microcontroller** (STM32, ESP32, Arduino) can drive it too: any UART at
115200 baud, 8N1.

| Command | Send | Reply |
|---|---|---|
| Inference | `A5 x0 … x15` (each 0..127) | `5A y0 … y15 argmax lat_lo lat_hi` (20 bytes, y signed) |
| Which model? | `C5` | `5C crc32 (4 bytes, little endian) source loads` |
| Upload a model | `C3` + 23,335-byte image + CRC-32 | `3C status crc32 loads` (status 0 = loaded) |

Full details: [64x6 protocol](NetSilcon-Models/NetSilcon-64x6/docs/protocol.md) ·
[6x4 protocol](NetSilcon-Models/NetSilcon-6x4/docs/protocol.md).

> **Windows note.** Set the serial timeout **once** when you open the port and never change it.
> On Windows, each change re-initialises the board's USB bridge (BL616) and can damage replies that
> are arriving at that moment. That bug cost days; the tools here already avoid it.

---

## 10. Change the hardware (a new network shape)

Every change follows the same order. Don't skip a step:

1. **Python model first.** Write the exact integer maths (`python/model/ns64.py` is the pattern):
   forward pass, image format, CRC. This is the reference everything is compared with.
2. **Verilog.** `fpga/rtl/` (the engine) and `fpga/board/` (UART, loader, top level).
3. **Simulation.** Bit-exact against Python with golden vectors, plus edge cases (all 0, all 127,
   extreme weights; see `models/stress/`).
4. **Mutation tests.** Break the design on purpose (`fpga/scripts/mutation_test.sh`); every break
   must be caught, or the tests are too weak.
5. **Synthesis.** Gowin EDA: check resources and timing (Fmax above 27 MHz).
6. **Board.** Golden vectors over UART, damaged and interrupted uploads, then the application.
7. **Write down the numbers** with the log that proves each one (`results/`, `docs/test_report.md`).

The working rules for this project, including "never claim a number no log shows", are in
[`Agent/WORKING_RULES.md`](Agent/WORKING_RULES.md).

---

## 11. Troubleshooting

| Problem | Cause and fix |
|---|---|
| `iverilog: command not found` | install Icarus Verilog (section 2) |
| `RESULT: FAIL` in simulation | run the script again from the model folder; if it persists, open an issue with the log |
| `could not open port COM7` | wrong port (use the second USB serial device), or another program holds it (close serial monitors, Gowin programmer) |
| No reply / timeout | board not programmed since power-up (SRAM program is lost), or wrong bitstream (6x4 tool talking to a 64x6 board) |
| `REFUSED - CRC error` | the file was damaged or edited by hand. Regenerate it; the chip keeps the old model |
| `the running model is not in models/` | the chip runs a model whose `.json` isn't under `models/`. Copy the file there, or `--load` it again |
| LED5 lights right after programming | a stray byte from the USB bridge at start-up; harmless |
| Gowin build ignores your change | Gowin compiles its **copies** in `src/`; copy the changed files again |
| `readmemh` warnings in Gowin | the `wmem_XX.mem` files are not next to the `.gprj` file |
| Training accuracy good, chip accuracy bad | it can't be the chip if `--test` passes (bit-exact); check that your app scales inputs exactly as the model file says |

---

## 12. Command cheat sheet (NetSilcon-64x6, from its folder)

```bash
# simulate (no board)
python3 python/model/make_synthetic.py && bash fpga/scripts/run_sim_engine.sh
bash fpga/scripts/run_sim_top.sh

# train and test your own model
python3 python/model/example_pump_data.py
python3 python/model/train_csv.py data/pump_vibration.csv --name pump_health --target state
bash fpga/scripts/run_sim_model.sh models/pump_health/pump_health.json

# board
cd python/host
python ns64_host.py COM7 --info
python ns64_host.py COM7 --load ../../models/pump_health/pump_health.json
python ns64_host.py COM7 --test
python app_example.py --model ../../models/pump_health/pump_health.json --port COM7 --csv ../../data/pump_vibration.csv
```

---

## Next

- Docs and guides online: <https://kumarnitish378.github.io/NetSilcon/docs/>
- Have a job for a 16-input network? Suggest it on [LinkedIn](https://www.linkedin.com/in/nitish-kumar-sharma-21801013b/);
  good ideas become the next trained model.
- Found a problem? Open an issue on GitHub with the `.log` file from `results/logs/`.
