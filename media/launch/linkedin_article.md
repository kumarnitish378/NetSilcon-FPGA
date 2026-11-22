# I put a neural network on a small FPGA. Then I made it 135 times bigger.

*What I learned building NetSilcon: neural networks on FPGA with a fixed shape and loadable weights.*

Cover image: `04_two_engines.png`. Put `03_fpga_drove_rover.png` after the rover section and `01_cycles_31x.png` after the clock-cycle section.

---

Every device around us measures something: the current in a motor, the voltage of a battery cell, the distance to a wall. Very few of them can decide what those numbers mean, fast and on their own.

A microcontroller can run a small neural network, but it does it one instruction at a time. A fully custom chip is fast, but it can only ever do one job. I wanted something in between.

## The idea: fix the shape, load the numbers

Think of an op-amp. The same part becomes an amplifier, a filter or a comparator, depending on a few resistor values around it.

NetSilcon works the same way. The neural network's **shape** is built into the hardware: how many inputs, how many layers, how many neurons. The **numbers** (weights, biases and one scaling shift per layer) are loaded at run time over a serial cable, checked with a CRC, and swapped in only if the check passes.

One bitstream, many jobs.

## Version one: tiny on purpose

The first engine, NetSilcon-6x4, has 4 inputs, four hidden layers of 6 neurons and 2 outputs. That is 170 parameters (144 weights and 26 biases). It runs on a Sipeed Tang Nano 20K, a small Gowin FPGA board.

It answers in **15 clock cycles**, every single time. Without changing the hardware, it has been a motor-fault detector, an irrigation controller and a rover driver. Only the 201-byte model file changed. Each job matched the Python model on 576 out of 576 test vectors.

The question I kept hearing was fair: does this scale?

## Version two: NetSilcon-64x6

The new engine has 16 inputs, six hidden layers of 64 neurons and 16 outputs: **22,928 parameters** (22,528 weights and 400 biases), on the same board.

Wiring every neuron in parallel does not scale, so the design changed. The weights live in 32 block RAMs. Each clock, one input value is broadcast to 64 multiply-accumulate lanes, one lane per neuron. One shared unit then applies ReLU, rounding, the shift and clamping to all 64 results.

The surprise: the bigger network uses **less** of the FPGA's logic (35 %) than the small one, because it reuses the same 64 lanes for every layer.

A new model is 23,335 bytes. It uploads over USB in about 2 seconds into a second memory bank while the old model keeps running. The banks switch in one clock, and only after the CRC-32 checks out.

## The number I am proudest of, and the one I have to explain

NetSilcon-64x6 needs **448 clock cycles** per answer. My laptop CPU, running the same network in optimised C, needs about **14,100**. That is 31 times fewer cycles.

But the laptop runs at 4 GHz and the FPGA at 27 MHz. So the laptop still finishes first: 3.45 microseconds against 16.6.

Why do the cycles matter, then? Because cycles are what carry over to a real chip. The same design clocked at around 130 MHz would match the laptop. A custom chip at a few hundred MHz would beat it, at a tiny fraction of the power. That is the long-term direction.

## Its first job: driving a robot

I trained a rover controller for the new engine. It sees a 360° LiDAR scan as 16 sectors and decides speed and steering. It learned from hand-written driving rules, then from its own mistakes, using only randomly generated rooms.

Then the real FPGA drove. The PC simulated the room and the sensor; every scan went over USB to the board; the board's answer steered the rover.

- 19,200 decisions, 0 mismatches with the Python model
- 8 drives, 0 crashes, 0 times stuck
- In 40 rooms it had never seen, it drove 14 % further than the smaller engine's rover

The safety stop and a small supervisor still run on the PC. Moving them into the FPGA is next.

## Three lessons

1. **Write the Python model first.** Every hardware answer was compared bit for bit with an integer Python model. When the two disagree, you know exactly where to look.
2. **Try to break your own tests.** I changed the design on purpose in 11 ways (wrong rounding, missing ReLU, swapped bytes). The tests caught all 11.
3. **The bug is not always in the hardware.** Damaged replies over USB looked like an FPGA fault. The real cause was my PC script: changing a serial timeout on Windows briefly reset the board's USB bridge.

## What is next, and how you can help

NetSilcon is open source: Verilog, Python tools, trained models and every hardware log. The website explains it from idea to use: https://kumarnitish378.github.io/NetSilcon/

New network shapes and new trained models are coming, and support for more FPGA boards after that.

I want the next model to solve a real problem. If you have a decision that a device should make from up to 16 sensor readings, send me a message. The best ideas become the next trained model, published with its test results.

*Nitish Kumar Sharma, building NetSilcon*

#FPGA #EdgeAI #TinyML #Verilog #EmbeddedSystems #NeuralNetworks
