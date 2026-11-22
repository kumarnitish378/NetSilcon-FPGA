# NetSilcon-64x6 UART protocol

115200 baud, 8N1, through the Tang Nano 20K's USB-C port (BL616 bridge; FPGA pin 69 = TX to PC,
70 = RX from PC). All multi-byte numbers are **little endian**. If a frame stalls for about 10 ms,
the FPGA drops it and waits for a new header.

Same headers as NetSilcon-6x4; the frames are longer.

## 1. Inference

| Direction | Bytes |
|---|---|
| PC → FPGA | `A5 x0 … x15` (17 bytes), each x = 0..127 |
| FPGA → PC | `5A y0 … y15 argmax lat_lo lat_hi` (20 bytes) |

- `y`: signed int8 outputs.
- `argmax`: index 0..15 of the largest y (the first one if several are equal, like `numpy.argmax`).
- `lat`: clocks from engine start to result, counted in hardware (448 in simulation).

## 2. Load a model

| Direction | Bytes |
|---|---|
| PC → FPGA | `C3`, 23,335-byte image, CRC-32 (4 bytes): 23,340 bytes, about 2.03 s at 115200 |
| FPGA → PC | `3C status crc32(4) loads` (7 bytes) |

Image:

| Bytes | Content |
|---|---|
| 0 – 22,527 | 22,528 weights, int8. Layer by layer; in a layer, neuron j, input i at `j × N_in + i` |
| 22,528 – 23,327 | 400 biases, int16, little endian, layer by layer |
| 23,328 – 23,334 | 7 layer shifts, 0..23 |

CRC-32: IEEE 802.3, identical to Python `zlib.crc32(image)`.

`status`: 0 = loaded, 1 = CRC error, 2 = timeout (frame incomplete), 3 = CRC good but a shift > 23.
For 1–3 the old model keeps running. `crc32` is what the FPGA computed over the bytes it received
(for status 2 it still shows the previous upload's value). `loads` = successful uploads since power-up.

The upload is written straight into the **inactive** RAM bank while the old model keeps running
(inference requests are not accepted while an upload is in progress). Only with a good CRC does the
FPGA flip the bank bit, in one clock, after any running inference finishes.

## 3. Which model is running?

| Direction | Bytes |
|---|---|
| PC → FPGA | `C5` |
| FPGA → PC | `5C crc32(4) source loads` (7 bytes) |

`source` 0 = built-in model (its CRC-32 is reported, so no extra computation is needed on the PC),
1 = uploaded.

## LEDs (active low)

| LED | Meaning |
|---|---|
| LED0 | heartbeat |
| LED1 | toggles on every answer |
| LED2 | upload in progress |
| LED3 | RAM bank 1 is active |
| LED4 | an uploaded model is running |
| LED5 | a frame error or failed upload has been seen (stays on until reset) |
