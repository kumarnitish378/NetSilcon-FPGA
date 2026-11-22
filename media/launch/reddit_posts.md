# Reddit posts

Read each subreddit's rules first (r/MachineLearning needs the [P] tag). Post as yourself, one subreddit per day, r/FPGA first, and stay to answer comments.
Replace `[GitHub link]` with https://github.com/kumarnitish378/NetSilcon-FPGA once the repo is public.

---

## r/FPGA

**Title:** Open-source int8 NN engine on a Tang Nano 20K: 22,528 weights in BRAM, 448 cycles/inference, bit-exact vs Python, loadable over UART

I've been building NetSilcon, a neural network engine where the shape is fixed in RTL and the weights/biases/shifts are loadable at run time. Second engine just passed on hardware, so I'd like feedback from people who know this better than me.

NetSilcon-64x6 (16 → 64×6 → 16, 22,928 parameters, GW2AR-18 at 27 MHz):

- 64 MAC lanes, one input broadcast per clock, weights in 32 SDPB 1K×16 BRAMs (two lanes per 16-bit word), one shared requantizer (ReLU, round half up, shift 0..23, clamp)
- 448 cycles per inference, measured with a hardware counter
- Model upload: 23,335 bytes + CRC-32 over UART into the inactive bank, bank flip in one clock only on a good CRC
- Gowin: 35 % logic, 32/46 BSRAM, 16/24 DSP, Fmax 61.5 MHz
- Verification: 1,200 vectors in Icarus, 168 board-level UART checks, 11/11 mutation tests caught, 3,200 vectors on the FPGA, 0 mismatches

Two things that bit me: Gowin built my byte-enable RAM out of ~81k logic cells instead of BSRAM (fixed with plain SDP RAM + lane pairing), and "FPGA reply corruption" turned out to be pyserial resetting the BL616 USB bridge on every timeout change.

Questions: would you pipeline across inferences or across layers next? Anyone run something similar on Gowin with the PLL above 60 MHz?

Code, logs, test report: [GitHub link]. Write-up: https://kumarnitish378.github.io/NetSilcon/netsilcon-64x6/

---

## r/embedded

**Title:** A small FPGA as a "decision co-processor" next to an MCU: 15-cycle NN inference, model swapped from a 201-byte file

Embedded engineer here (drones and Linux BSP by day). I've been prototyping NetSilcon: a small neural-network engine that sits next to a microcontroller and makes one sensor-level decision very fast, with a model you can replace over UART.

- NetSilcon-6x4: 4 inputs → 2 outputs, 170 parameters, 15 clock cycles (0.556 µs at 27 MHz), 576/576 bit-exact per model. The same bitstream has been a motor-fault detector, an irrigation controller and a rover driver.
- Against an STM32F407 on the same int8 network my estimate is ~25× faster and 24–36× less energy per inference, but that MCU number is instruction counts + datasheet, not a bench measurement yet. Measuring it on a real board is next.
- NetSilcon-64x6: 16 inputs, 22,928 parameters, 448 cycles, drove a simulated rover from the real board for 19,200 decisions with 0 mismatches.

What I'd love to hear: which decisions in your products would you trust to a tiny fixed-latency network? And would SPI or UART be your interface of choice for something like this?

Everything is open source: https://kumarnitish378.github.io/NetSilcon/

---

## r/MachineLearning

**Title:** [P] Bit-exact int8 MLPs on a small FPGA with run-time loadable weights (DAgger-trained rover controller, 19,200 HIL decisions)

A hardware-side project that may interest people working on quantization or edge deployment.

- Fixed-shape int8 MLP engines on FPGA; weights, int16 biases and one power-of-two shift per layer are uploaded at run time with a CRC.
- Post-training quantization with per-layer scale 127/max|W| and shifts chosen from the 99.99th-percentile activation; the hardware is bit-exact with a numpy integer reference.
- Controller: 16 LiDAR sectors → speed and steering, 16 → 64×6 → 16 (22,928 parameters). Trained on a rule-based teacher, then 2 rounds of DAgger, only on procedurally generated rooms (221k samples). Float 92.7 % / int8 89.8 % action agreement with the teacher.
- Closed loop with the real FPGA: 19,200 decisions, 0 mismatches vs the reference; 0 crashes in 8 runs. On 40 unseen rooms it covers 37.9 m per run vs 38.2 m for the teacher.
- Honest limit: without the hand-written supervisor the memoryless policy gets stuck in dead ends (68/80 runs), same as the smaller model.

Curious whether anyone has tried adding a tiny recurrent state to a policy like this without giving up fixed latency.

Details and results: https://kumarnitish378.github.io/NetSilcon/netsilcon-64x6/
