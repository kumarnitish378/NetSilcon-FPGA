# NetSilcon-LM-0

**A character-level language model that runs entirely on the Tang Nano 20K FPGA.**
You type a question into a serial terminal, and the FPGA writes the answer itself, one character
per model step, with no PC in the loop.

```
q: hello.
a: hello. how can i help?
q: is the pump running?
a: status: running.
q: motor temp?
a: motor temperature: 27 degrees.
```

LM-0 is the first step towards *talking to any device*: every device gets a small language model
trained on its own world, not a general chatbot. Its only goal is to prove that a language model
can run inside the NetSilcon engine, bit-exact, in real time.

> **Status, measured (27 Nov 2026):** Python int8 model ⇄ Verilog bit-exact (802 golden vectors,
> all 42 logits), a full 14-question conversation generated on-chip identical to Python (392
> characters), the UART board top identical to Python (129 bytes), mutation tests 8/8 caught, and
> open-source synthesis + place & route for GW2AR-18. The `.fs` bitstream is built.
> **Not done yet:** Gowin EDA build, running on the real board, power measurement.

## The model

| | |
|---|---|
| Alphabet | 42 symbols: newline, space, `: , . ?`, a-z, 0-9 |
| Context | the last 32 characters |
| Embedding | 8 values (0..127) per symbol → 32 × 8 = 256 inputs |
| Network | 256 → 64 → 64 → 64 → 42, ReLU, int8 weights, int16 biases, one shift per layer |
| Output | 42 int8 logits, next character = argmax (first one on ties), greedy |
| Parameters | **27,834** (336 embedding + 27,264 weights + 234 biases), CRC-32 `59993775` |
| Neuron maths | identical to NetSilcon-64x6: `acc = bias + Σ x·w` (24-bit), ReLU, `(acc + 2^(s-1)) >>> s`, clamp |

The hardware is the verified NetSilcon-64x6 datapath (64 MAC lanes, weights in block RAM, one shared
requantizer) with a 256-input first layer streamed from an embedding ROM, a 32-symbol context shift
register, and a running argmax. After each step the chosen character is shifted into the context,
so the chip generates text by itself (autoregressive).

## Results

### Language model (`results/train_report.md`)

Corpus: **synthetic** pump-controller dialogues (`python/data/make_corpus.py`), 605k training chars,
75k test chars.

| | next-char accuracy (test) |
|---|---|
| float | 94.18 % |
| **int8 (what the FPGA runs)** | **94.01 %** |
| int8, every conversation starting from a blank context (like the board) | 93.90 % |

Not 100 %, because the numbers in the answers (pressure, flow, ...) are random in the corpus.

- All 13 questions worded as in the corpus get a correct sentence.
- Of 3 questions worded differently ("is the pump working?", "what is the water pressure?",
  "hi pump."), 1 is answered well and 2 come out broken. A 27k-parameter model trained on templates
  does not generalise far.
- **LM-0 has no sensor inputs:** the numbers it says are made up by the model. Real values are the LM-2 step.

### Hardware (simulation + open-source tools)

| Check | Result | Log |
|---|---|---|
| Engine vs Python int8, all 42 logits + argmax | 802 / 802 vectors, 0 mismatches | `results/logs/sim_*.log` |
| Full conversation generated on-chip (context carries over) | 392 / 392 chars identical to Python | same |
| Board top over UART (upper case, CR and CR LF input, echo, 3 answers) | 129 / 129 bytes identical | same |
| Mutation tests (rounding, ReLU, ties, embedding order, context order, base address, bias, output ReLU) | 8 / 8 caught | `results/logs/mutation_*.log` |
| Latency per character | **510 clocks** (measured in simulation) | same |
| Resources, yosys + nextpnr, GW2AR-18 | LUT4 7,046 (33 %), ALU 2,000 (12 %), DFF 4,640 (29 %), BSRAM 33 / 46, MULT9X9 64 / 96 | `results/logs/resources_opensource_*.txt` |
| Timing, nextpnr | 140 MHz max, PASS at 27 MHz (Gowin EDA timing not checked yet) | same |

At 27 MHz, 510 clocks per character works out to about **52,900 characters per second** (computed
from the measured clock count, not measured on the board). The UART at 115200 baud carries about 11,500
characters per second, so on the board the serial link is the limit, not the model.

## Run it

All commands from inside `NetSilcon-Models/NetSilcon-LM-0` (WSL Ubuntu for the simulation).

```bash
python3 python/data/make_corpus.py        # corpus (already in the repo)
python3 python/model/nslm.py              # self-check of the reference model
python3 python/model/train_lm.py --epochs 30     # ~5 min, writes models/pump/pump.json
python3 python/model/make_gen.py          # RAM/ROM contents + golden vectors -> fpga/gen/
bash fpga/scripts/run_sim.sh              # engine, chat and UART top (Icarus), ~3 min
bash fpga/scripts/mutation_test.sh        # ~5 min
bash fpga/scripts/build_opensource.sh     # yosys + nextpnr + gowin_pack -> fpga/build/nslm.fs
```

Re-quantize without training again: `python3 python/model/train_lm.py --load`.

### On the board

1. Program the Tang Nano 20K with the bitstream: Gowin EDA build (below), or the open-source
   `fpga/build/nslm.fs` with `openFPGALoader -b tangnano20k fpga/build/nslm.fs` (the open-source
   bitstream is built but has not been tried on the board).
2. Find the COM port of the board (Device Manager, the second "USB Serial Port").
3. Run `python python/host/lm_chat.py --port COM5 --test`. Expected:
   `RESULT hardware chat: 14/14 answers identical to the Python int8 model`.
   It logs every answer and the time per answer to `results/logs/hw_chat_*.log` and `.csv`.
4. Or open any serial terminal at 115200 8N1 and type `q: is the pump running?` then Enter.
   LED0 lights while the FPGA is answering.

The conversation context lives on the board. Reprogram (or power-cycle) the board before `--test`,
so that both start from a blank context.

### Gowin EDA build

1. New project, device **GW2AR-LV18QN88C8/I7**, e.g. `C:\fpga\gowin\nslm` (separate from the 6x4 and 64x6 projects).
2. Add files from `fpga\`: `rtl\nslm_requant.v`, `rtl\nslm_mem.v`, `rtl\nslm_engine.v`, `rtl\nslm_core.v`,
   `board\ns_uart.v`, `board\tangnano20k_lm.v`, `board\tangnano20k_lm.cst`, `board\tangnano20k.sdc`.
3. Top module `tangnano20k_lm`. Add `fpga\gen` to the include path (for `nslm_model.vh`), and make
   the `.mem` files from `fpga\gen` visible to synthesis, the same way as for NetSilcon-64x6
   (see `../NetSilcon-64x6/docs/gowin_build.md`, section 3).
4. Synthesize, then Place & Route. Check that **BSRAM = 33** (32 weight RAMs + 1 embedding ROM).
   If the weight RAMs were built from LUTs, the `syn_ramstyle` attribute was not taken.
   Also check that timing passes at 27 MHz.

## Layout

```
python/data/    make_corpus.py, pump_train.txt, pump_test.txt
python/model/   nslm.py (bit-exact reference), train_lm.py, make_gen.py
python/host/    lm_chat.py (board chat + check against Python, logs)
models/pump/    pump.json (int8 model, CRC-32 59993775), float_params.npz
fpga/rtl/       nslm_engine.v, nslm_requant.v, nslm_mem.v, nslm_core.v
fpga/board/     tangnano20k_lm.v, ns_uart.v, tangnano20k_lm.cst, tangnano20k.sdc
fpga/tb/        tb_engine.v, tb_chat.v, tb_top.v
fpga/gen/       generated RAM/ROM contents and golden vectors
fpga/scripts/   run_sim.sh, mutation_test.sh, build_opensource.sh
results/        train_report.md, logs/
```

## Next steps

- **LM-0 on hardware:** Gowin build, `lm_chat.py --test`, and power measured with a USB meter.
- **LM-1:** command in → device action + short reply out (the answer drives an output pin).
- **LM-2:** sensor values as extra inputs, so the device answers with real numbers.
- More capacity: the 64x6 lane RAMs have room for about 1,000 words per lane, which allows a longer
  context or more layers.

License: Apache-2.0, see the root [LICENSE](../../LICENSE).
