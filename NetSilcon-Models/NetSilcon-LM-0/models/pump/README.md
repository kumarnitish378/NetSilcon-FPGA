# LM-0 application: pump controller dialogue

- **Input:** the last 32 characters of the conversation (alphabet of 42 symbols).
- **Output:** the next character. Generating one character after another gives an answer line.
- **Format:** `q: <question>` then Enter. The model answers with `a: <answer>` and a newline.
- **Training data:** synthetic dialogues from `python/data/make_corpus.py`, covering 14 topics:
  status, pressure, flow, tank, motor temperature, start, stop, faults, schedule, greeting, help,
  name and run time. Numbers in the answers are random. The model has no sensor inputs, so the
  numbers it says are not real readings.
- **Training:** `python/model/train_lm.py --epochs 30`, seed 0. 30 % of the training windows start
  from a blank context, because the board starts a conversation that way. The int8 calibration was
  chosen on a validation slice of the training text; the test set was not used for it.
- **Model file:** `pump.json`, 27,834 parameters, CRC-32 `59993775`, shifts `9 7 7 6`.
  `float_params.npz` holds the float weights, used to re-quantize with `--load`.

## Results

| | |
|---|---|
| Test next-char accuracy, int8 | 94.01 % (float 94.18 %) |
| Same, from a blank context | 93.90 % |
| Corpus questions answered with a correct sentence | 13 / 13 |
| Differently worded questions answered well | 1 / 3 |
| Verilog vs Python | 802 golden vectors bit-exact; 392-character conversation identical |
| On the board | not run yet |

The full table of answers is in `../../results/train_report.md`.
