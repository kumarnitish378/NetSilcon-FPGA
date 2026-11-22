# Working rules

How changes are made in NetSilcon. Agents follow these exactly.

## Order of work for any hardware change or new model

1. **Python model first.** A bit-exact integer reference (`python/model/`), with a self-check.
2. **Verilog** written to match it (`fpga/rtl`, `fpga/board`).
3. **Icarus Verilog testbenches** (`fpga/tb`, `fpga/scripts/run_sim_*.sh`): golden vectors from Python,
   0 mismatches. Add a mutation test when the logic is new: break it on purpose, the test must fail.
4. **Open-source synthesis** (yosys + nextpnr-himbaechel) as a resource and timing cross-check.
5. **Gowin EDA** V1.9.11.03 build (see `docs/gowin_build.md`); check timing and resources.
6. **Hardware** on the Tang Nano 20K with the host tool; every run writes `.log` + `.csv` to `results/logs/`.

A new trained model for an existing shape needs only steps 1, 3 (golden vectors in the model file)
and 6, plus a `models/<app>/README.md` with inputs, outputs, how it was trained and its results.

## Honest numbers

- Only claim what a log or a test output shows. Label numbers as measured, estimated or target.
- Say what was not tested (for example: rover supervisor runs on the PC, no real sensors yet).
- Keep comparisons fair: same network, same maths, state clocks and conditions.

## Files and folders

- One folder per application: `models/<app>/<app>.json` + `README.md`.
- A new network shape is a new folder `NetSilcon-Models/NetSilcon-<shape>/` with the same grouping
  (models, fpga, python, docs, results) and its own README; add it to the root README table and to
  `Agent/PROJECT_SUMMARY.md` and `Agent/MODEL_INDEX.md`.
- Back up before overwriting anything outside git. After copying files to another machine, verify
  sizes or checksums.

## Instructions for the human

When the user has to act (Gowin, programming the board, running the host tool), give numbered
step-by-step instructions with the exact commands and what output to expect.

## Git

- Commit only when asked. Clear messages: what changed and how it was verified.
- Commits made by an AI agent end with one footer line: `Claude | <session id>` (or the agent's
  name and session id), no other trailers.
- The website is a submodule: commit inside `website/` first, then commit the new submodule
  pointer in this repository.
