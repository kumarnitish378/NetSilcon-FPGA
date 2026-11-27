# LM-0 application: pump controller dialogue

- **Input:** the last 32 characters of the conversation (alphabet of 42 symbols).
- **Output:** the next character. Generating one character after another gives an answer line.
- **Format:** `q: <question>` then Enter. The model answers with `a: <answer>` and a newline.
- **Training data (v2):** synthetic dialogues from `python/data/make_corpus.py`, covering 13 topics:
  status, pressure, flow, tank, motor temperature, start, stop, faults, schedule, greeting, help,
  name and run time. There are 142 ways of asking, 27 of them held out for testing only, and 2.9 million
  training characters. Numbers in the answers are random. The model has no sensor inputs, so the
  numbers it says are not real readings.
- **Training:** `python/model/train_lm.py --epochs 16` (float), then 4 epochs of quantization-aware
  training with the exact integer maths, seed 0. 30 % of the training windows start
  from a blank context, because the board starts a conversation that way. The int8 calibration was
  chosen on a validation slice of the training text; the test set was not used for it.
- **Model file:** `pump.json`, 27,834 parameters, CRC-32 `8A7B9204`, shifts `9 6 6 6`.
  `float_params.npz` holds the float weights (`--load` re-runs calibration and QAT from them),
  and `qat_params.npz` the weights after QAT. `pump_v1.json` (CRC-32 `59993775`) is the first model, kept for comparison.

## Results

| | |
|---|---|
| Answer grader, trained wordings | **250 / 260 (96.2 %)** (v1: 24.6 %) |
| Answer grader, held-out wordings | **138 / 260 (53.1 %)** (v1: 11.5 %) |
| Test next-char accuracy, int8 | 91.22 % (float 91.96 %) |
| Verilog vs Python | see `../../results/logs/sim_*.log` |
| On the board | not run yet |

The full table of answers is in `../../results/train_report.md`.
