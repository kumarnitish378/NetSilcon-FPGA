# pump_health

Pump vibration health (synthetic example data): 16 features -> normal / imbalance / misalignment / bearing

Trained with `python/model/train_csv.py` on `pump_vibration.csv`.

CRC-32 `6579E12F` · shifts `9 7 8 8 8 8 8`

```
NetSilcon-64x6 train_csv  2026-11-23  data pump_vibration.csv: 20000 rows
inputs (16 of 16): rpm, current_a, temp_c, pressure_bar, band_1x, band_2x, band_3x, band_4x, band_hf1, band_hf2, band_hf3, band_hf4, axial_1x, axial_2x, kurtosis, crest_factor
target 'state': 4 classes ['bearing', 'imbalance', 'misalignment', 'normal']
training rows per class: {'bearing': 3980, 'imbalance': 3969, 'misalignment': 3988, 'normal': 4063}
training: 16000 rows, validation 2000, test 2000 (never used for training)
  epoch   0  validation loss 0.1769
  epoch  10  validation loss 0.1313
  epoch  20  validation loss 0.1195
  epoch  30  validation loss 0.1199
  epoch  39  validation loss 0.1206
shifts [9, 7, 8, 8, 8, 8, 8]   CRC-32 6579E12F
test accuracy: float 95.5 %   int8 (= FPGA) 95.2 %   int8 agrees with float on 99.2 % of rows
confusion (rows = true class, columns = int8 prediction):
     bearing  imbalance misalignme     normal
         540          0          0          0   bearing
           0        421          0         51   imbalance
           0          0        507          0   misalignment
           0         45          0        436   normal
unused outputs y4..y15: max |y| = 0
golden vectors: 1000  (independent slow model agrees on the first 50: yes)
```
