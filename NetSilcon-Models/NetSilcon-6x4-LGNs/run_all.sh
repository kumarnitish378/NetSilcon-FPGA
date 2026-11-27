#!/usr/bin/env bash
# Full Exp-01 pipeline (WSL Ubuntu): train -> export -> Icarus -> yosys -> nextpnr -> summary
# needs: python3 + numpy, iverilog, yosys, nextpnr-himbaechel (gowin)  (or the yowasp-* pip versions)
set -euo pipefail
cd "$(dirname "$0")/python"
python3 baseline_mlp.py
for W in 180 360 720 1440; do
  python3 train.py --width $W --depth 4 --epochs 80 --name exp01_w$W
  python3 export_verilog.py exp01_w$W
  ../fpga/run_fpga_checks.sh exp01_w$W
done
python3 collect_results.py
