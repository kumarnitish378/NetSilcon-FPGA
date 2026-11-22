# UART protocol

115200 baud, 8 data bits, no parity, 1 stop bit, through the Tang Nano 20K's USB-C port
(BL616 USB-serial bridge; FPGA pins 69 = TX to PC, 70 = RX from PC).
Every reply is exactly **5 bytes**. If more than about 10 ms passes in the middle of a
frame, the FPGA drops the partial frame and waits for a new header, so it can never get stuck.

## 1. Inference

| Direction | Bytes |
|---|---|
| PC → FPGA | `A5 x0 x1 x2 x3` |
| FPGA → PC | `5A y0 y1 flags latency` |

- `x0..x3`: inputs, each 0..127. Convert real values with `q = round(value / range × 127)`.
- `y0`, `y1`: outputs, signed int8.
- `flags` bit 0: `1` when `y1 > y0` (the decision bit for classifiers).
- `latency`: clocks from the last input byte to the answer, counted in hardware (15 clocks).

## 2. Load a model

| Direction | Bytes |
|---|---|
| PC → FPGA | `C3`, then the 201-byte image, then the CRC-16 (high byte, low byte): 204 bytes in all |
| FPGA → PC | `3C status crc_lo crc_hi loads` |

The image:

| Bytes | Content |
|---|---|
| 0 – 143 | 144 weights, int8. Layer by layer; inside a layer, neuron `j`, input `i` at `j × N_in + i` |
| 144 – 195 | 26 biases, int16, low byte first |
| 196 – 200 | 5 layer shifts, 0..15 |

CRC: CRC-16/CCITT-FALSE (polynomial 0x1021, initial value 0xFFFF, no reflection, no final
XOR) over the 201 image bytes.

`status`: `0` = loaded, `1` = CRC error, `2` = timeout (frame incomplete). For 1 and 2 the
old model keeps running. `loads` counts the successful uploads since power-up.

## 3. Which model is running?

| Direction | Bytes |
|---|---|
| PC → FPGA | `C5` |
| FPGA → PC | `5C crc_lo crc_hi source loads` |

`source`: `0` = the built-in model from the bitstream (the CRC then reads `0000`; the host
tool computes the built-in CRC itself from `fpga/gen/`), `1` = an uploaded model (the CRC is its
CRC-16).

## LEDs (active low)

| LED | Meaning |
|---|---|
| LED0 | heartbeat |
| LED1 | toggles on every answer |
| LED2 | last answer: `y1 ≤ y0` |
| LED3 | last answer: `y1 > y0` |
| LED4 | an uploaded model is running |
| LED5 | a frame error or CRC error has been seen (stays on until reset) |

LED5 may light at start-up if the USB bridge sends a stray byte while the FPGA
configures. This is harmless.
