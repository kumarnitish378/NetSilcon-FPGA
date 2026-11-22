# Results log

All hardware runs use a Sipeed Tang Nano 20K at 27 MHz, connected to a Windows 11 PC over
USB (COM7, 115200 baud). The raw logs are in [`results/logs/`](../results/logs/).

## 1. Built-in model on the board (self-test)

The self-test bitstream runs all 576 golden vectors inside the FPGA and prints over UART:

```
NetSilcon-6x4: PASS err=0x0000 n=0x240
```

`n = 0x240` = 576 vectors, `err = 0` mismatches.

## 2. Live inference and model upload

| Run | Log | Result |
|---|---|---|
| Upload irrigation with one CRC bit flipped | [01](../results/logs/01_irrigation_corrupt_upload_refused.log) | `REFUSED - CRC error`, motor model still running, 64/64 vectors match |
| Upload irrigation | [02](../results/logs/02_irrigation_upload.log) | `LOADED (chip CRC 8F33)`, in 31.2 ms |
| Irrigation demo, 21 scenarios | [03](../results/logs/03_irrigation_demo.log) | every answer matches the Python model |
| Irrigation, 576 golden vectors | [04](../results/logs/04_irrigation_576_vectors.log) | 0 mismatches, latency 15 clocks |
| Upload rover v1 | [05](../results/logs/05_rover_v1_upload.log) | `LOADED (chip CRC F5C2)` |
| Rover v1 demo, 24 scenarios | [06](../results/logs/06_rover_v1_demo.log) | every answer matches |
| Rover v2, 576 golden vectors | [07](../results/logs/07_rover_v2_576_vectors.log) | 0 mismatches, latency 15 clocks |

Each round trip takes about 17 ms. Almost all of that is USB serial: the chip itself
answers in 0.56 µs.

## 3. Hardware in the loop: the real FPGA drives the simulated rover

The PC simulates the world, the LiDAR, the physics and the fixed logic. The FPGA computes
speed and steering every 50 ms.

| Run | Log | Chip answers | Mismatches | Crashes | Stuck | USB round trip |
|---|---|---|---|---|---|---|
| No sensor noise | [08](../results/logs/08_hil_rover_v2.log) | 9,600 | 0 | 0 / 8 | 0 / 8 | avg 16.2 ms, max 18.8 ms |
| ±2 cm sensor noise | [09](../results/logs/09_hil_rover_v2_noise_2cm.log) | 9,600 | 0 | 0 / 8 | 0 / 8 | avg 15.5 ms, max 19.5 ms |

No step came near the 50 ms control period.

## 4. Simulation (Icarus Verilog)

- Network vs Python int8 model: 576 / 576 for `PHASES = 1` and `PHASES = 2`.
- Live UART top: 40 frames bit-exact, correct fault flag and latency, recovers after junk bytes.
- Model upload: built-in → CRC error refused → irrigation loaded → interrupted upload refused →
  motor model reloaded, all bit-exact. A mutation test (one shift register disabled) makes 17 of
  20 vectors fail, so the test really checks the shift path.

## 5. Rover in simulation

See the table in the main [README](../README.md#rover-simulator-and-hardware-in-the-loop) and
[`results/rover_batch_results.txt`](../results/rover_batch_results.txt).
