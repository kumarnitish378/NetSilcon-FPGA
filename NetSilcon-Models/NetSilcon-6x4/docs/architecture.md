# Architecture

## Idea

A microcontroller runs a neural network by fetching and decoding instructions, so even a tiny
network costs it thousands of clock cycles. A fully hardwired network is fast, but it can only
ever do one job. NetSilcon sits between the two:

| | General processor | NetSilcon | Fully hardwired |
|---|---|---|---|
| Network shape | anything | **fixed** (4→6→6→6→6→2) | fixed |
| Weights, biases, shifts | anything | **loadable** | fixed |
| Speed | slow (instructions) | fast (pure dataflow) | fast |
| Jobs per chip | many | **many** (same shape) | one |

A useful comparison is an op-amp: one fixed circuit becomes an amplifier, a filter or a
comparator depending on a few resistor values. Here the weights play the role of the resistors.

## Number format

- Inputs: unsigned 0..127, carried in 8-bit signed lanes.
- Weights: int8. Biases: int16.
- Accumulator: 20-bit signed, enough for the worst case `32767 + 6 × 127 × 127 = 129,541`.
- After each layer: round, arithmetic shift right by the layer's shift `s`, then clamp
  (hidden layers 0..127 after ReLU, output layer −128..127).
- The quantizer ([`python/model/make_model.py`](../python/model/make_model.py)) chooses one power-of-two
  shift per layer. For regression models it scales the last layer so that the chip's output
  is exactly `value × 127`.

## Pipeline

Each layer ([`fpga/rtl/nn_layer.v`](../fpga/rtl/nn_layer.v)) has one multiply-accumulate tree per
neuron, so all neurons of a layer work at the same time. With `PHASES = 2` each neuron has
`N_in / 2` multipliers and uses them on two consecutive clocks:

| Clock | Work |
|---|---|
| 1 | first half of the products + bias → partial sum register |
| 2 | second half of the products + partial sum → full sum register |
| 3 | ReLU, round, shift, clamp → output register |

There are 5 layers, so the latency is 5 × 3 = **15 clocks**. A new input can enter every
2 clocks. The output register stage (clock 3) was added when the shifts became loadable. It
keeps the slowest path (multiply → add) separate from the variable shifter, so the design
still meets 27 MHz in Gowin EDA, with 2.7 ns of slack.

## Model loader

[`fpga/board/ns_loader.v`](../fpga/board/ns_loader.v):

1. Bytes after the `C3` header go into a 201-byte **staging RAM**, which maps to one block
   RAM. The CRC-16 is computed on the fly.
2. After 203 bytes (image + CRC), the remainder must be zero. If it is not, the loader
   replies "CRC error" and the running model is untouched.
3. If the CRC is good, the loader copies the staging RAM into the network's parameter
   registers through the `param_*` write port: 201 clocks = 7.4 µs.
4. If 10 ms pass without a byte, the upload is abandoned (status "timeout").

In a future ASIC the staging RAM becomes on-chip flash, loaded at power-up with the same
CRC check.

## What "programmable" costs

When nothing could write the weights (the first self-test build), synthesis turned them into
constants and the design used **21 %** of the FPGA's logic. With weights, biases and shifts
truly writable, it uses **49 %**. That difference is the measured silicon cost of making the
network programmable instead of hardwired.

## Resource use (Gowin EDA V1.9.11.03, GW2AR-LV18QN88C8/I7)

| Resource | Used | Available | |
|---|---|---|---|
| Logic (LUT + ALU) | 9,991 | 20,736 | 49 % |
| Registers | 3,319 | 15,750 | 22 % |
| DSP (MULTADDALU18X18) | 24 | 24 | 100 % (holds the 72 multipliers) |
| Block RAM | 1 | 46 | 3 % (staging RAM) |
| Max frequency | 29.1 MHz | 27 MHz needed | PASS |
