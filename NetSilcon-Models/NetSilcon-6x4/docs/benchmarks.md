# Latency and power: the same network on five kinds of hardware

The network: NetSilcon-6x4's motor-fault model (4 → 6 → 6 → 6 → 6 → 2, 170 int8 parameters,
201 bytes). Every platform computes the same bit-exact int8 math, **one inference at a time**
(batch 1), which is how a sensor-side decision is used.

Each row says how its numbers were obtained. **Measured** means run on real hardware here;
**estimate** means derived from a datasheet or published figures, with the method shown.

| Hardware | Example | Latency per inference | Power while running | Energy per inference |
|---|---|---|---|---|
| **NetSilcon-6x4 (FPGA)** | Tang Nano 20K, GW2AR-18 at 27 MHz | **0.56 µs** (measured, 15 clocks) | **0.14 W** whole FPGA (Gowin estimate) | **≈ 78 nJ** |
| Microcontroller | STM32F407 (Cortex-M4) at 168 MHz | 14 – 21 µs (estimate) | 0.13 W (ST datasheet) | ≈ 1.8 – 2.8 µJ |
| Laptop CPU | Intel Core i7-13650HX, 1 thread | **0.115 µs** (measured) | 10 – 55 W (estimate) | ≈ 1.2 – 6.4 µJ |
| Edge GPU | NVIDIA Jetson Orin Nano | ≥ 20 µs per call (estimate) | 7 – 25 W (NVIDIA power modes) | ≥ 140 µJ |
| Edge NPU | Google Coral USB Accelerator (Edge TPU) | slower than a small CPU at this size (published study) | 2 W at full speed, plus the host (datasheet) | higher than a small CPU |

**What this shows**

- **Energy:** NetSilcon gives the same answer for about **24 – 36× less energy than a
  microcontroller** and **15 – 82× less than a laptop CPU**, while sitting in a part small enough
  to place next to the microcontroller on a PCB.
- **Speed:** at this tiny size **a laptop CPU is about 5× faster** than NetSilcon at 27 MHz. It
  also draws tens of watts and needs an operating system. NetSilcon is about **25 – 38× faster
  than the microcontroller** that would normally sit in the device.
- **Determinism:** NetSilcon took exactly 15 clocks on every one of the 9,600 hardware-in-the-loop
  decisions. A CPU or microcontroller adds jitter from caches, interrupts and the operating system.
- **GPUs and NPUs are built for big models.** For a 200-byte network the cost of starting the
  accelerator and moving data to it is far larger than the math itself.

**Where an ASIC would start from.** The network logic itself is estimated by Gowin at 10.6 mW
dynamic power while producing 13.5 million inferences per second, which is **≈ 0.8 nJ per
inference** for the network alone. Most of the 0.14 W above is the FPGA's static power, which a
dedicated chip would not carry. This is a tool estimate, not a measurement of a chip.

## How each number was obtained

**NetSilcon-6x4.** Latency measured on the board: the FPGA counts clocks from input to answer
and reports 15 on every inference (`results/logs/`). Power from the Gowin EDA V1.9.11.03 power
analysis of the routed design (default toggle rate 12.5 %, 25 °C): 139.5 mW total, of which
122.8 mW static and 16.7 mW dynamic; the network block is 10.6 mW dynamic. Energy =
139.5 mW × 0.556 µs.

**Microcontroller.** The same C code ([`python/bench/net.h`](../python/bench/net.h)) compiled for Cortex-M4
(`zig cc -target thumb-freestanding-eabihf -mcpu=cortex_m4 -O2`) and run in the Unicorn
emulator ([`python/bench/emu_m4.py`](../python/bench/emu_m4.py)): 576 / 576 vectors bit-exact, **2,327
instructions** for one inference. Cycles estimated at 1.0 – 1.5 cycles per instruction →
2,300 – 3,500 cycles → 14 – 21 µs at 168 MHz. ST's CMSIS-NN library could be faster. Power:
STM32F407 datasheet, Table 20, run mode at 168 MHz from flash, all peripherals disabled:
40 mA typical at 3.3 V = 132 mW.

**Laptop CPU.** [`python/bench/bench_cpu.c`](../python/bench/bench_cpu.c) compiled with `gcc -O2
-march=native`, one thread, best of 5 × 20 million inferences, on an Intel Core i7-13650HX
(run inside a Linux VM on Windows 11): **115.4 ns**, 576 / 576 bit-exact. Power was not measured;
Intel lists 55 W base power for the whole processor (157 W maximum turbo). A single busy core
draws less, so 10 – 55 W is used as a range.

**Edge GPU.** Not measured. NVIDIA's CUDA Graphs documentation lists the costs of launching
work on a GPU: runtime processing 5 – 20 µs, driver operations 5 – 15 µs, hardware submission
1 – 5 µs (plus 10 – 100 µs when called from Python). For a network this small, those costs, plus
copying inputs and results, dominate, so ≥ 20 µs per call is a conservative estimate. Power:
Jetson Orin Nano power modes of 7 W and 15 W (25 W in Super mode). Energy ≥ 7 W × 20 µs.

**Edge NPU.** Not measured. The Coral USB Accelerator datasheet gives 4 TOPS at 2 W, powered by
5 V over USB. A published evaluation of the Edge TPU found that a Cortex-A53 CPU was faster and
more energy-efficient than the Edge TPU for feed-forward models up to 136 KiB. This network is
0.2 KiB.

## Sources

- [Gowin power analysis summary](../results/logs/gowin_power_summary.txt) (from the routed design)
- [STM32F407 datasheet (ST)](https://www.st.com/resource/zh/datasheet/stm32f407vg.pdf), Table 20
- [Intel Core i7-13650HX specifications (Intel)](https://www.intel.com/content/www/us/en/products/sku/232101/x/specifications.html)
- [CUDA Graphs introduction (NVIDIA)](https://docs.nvidia.com/dl-cuda-graph/cuda-graph-basics/introduction.html)
- [JetPack 6.2 Super Mode for Jetson Orin Nano (NVIDIA)](https://developer.nvidia.com/blog/nvidia-jetpack-6-2-brings-super-mode-to-nvidia-jetson-orin-nano-and-jetson-orin-nx-modules)
- [Coral USB Accelerator datasheet (Google)](https://coral.ai/static/files/Coral-USB-Accelerator-datasheet.pdf)
- [Exploring Edge TPU for Network Intrusion Detection in IoT (arXiv:2103.16295)](https://arxiv.org/pdf/2103.16295)
