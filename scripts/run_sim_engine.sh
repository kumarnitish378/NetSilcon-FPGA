#!/bin/bash
# Icarus Verilog: requantizer unit test + engine vs Python golden vectors.
# Run from anywhere (WSL Ubuntu):  bash scripts/run_sim_engine.sh
set -e
cd "$(dirname "$0")/.."
mkdir -p sim/engine
cp gen/*.mem sim/engine/
cp gen/tb/wmem_*.mem sim/engine/      # testbench RAMs: bank 0 synthetic, bank 1 stress
cd sim/engine
iverilog -g2012 -o requant.vvp ../../rtl/ns64_requant.v ../../tb/tb_requant.v
vvp -n requant.vvp | tee requant.log
iverilog -g2012 -I../../gen -o engine.vvp \
  ../../rtl/ns64_requant.v ../../rtl/ns64_wram.v ../../rtl/ns64_engine.v ../../tb/tb_engine.v
vvp -n engine.vvp | tee engine.log
