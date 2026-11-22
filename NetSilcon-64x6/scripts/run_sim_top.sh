#!/bin/bash
# Icarus Verilog: the complete board design over its UART pins (inference, info,
# damaged / interrupted / bad-shift uploads, good uploads, bank swaps).
#   bash scripts/run_sim_top.sh            (~ a few minutes)
set -e
cd "$(dirname "$0")/.."
python3 scripts/make_tb_load.py
mkdir -p sim/top
cp gen/*.mem sim/top/                   # built-in RAM contents (bank 0 synthetic, bank 1 empty)
cp gen/tb/up_*.mem gen/tb/*_amax.mem sim/top/
cd sim/top
iverilog -g2012 -I../../gen -I../../gen/tb -o top.vvp \
  ../../rtl/ns64_requant.v ../../rtl/ns64_wram.v ../../rtl/ns64_engine.v \
  ../../board/ns_uart.v ../../board/ns64_uart_tx.v ../../board/ns64_loader.v ../../board/tangnano20k_ns64.v ../../tb/tb_top.v
vvp -n top.vvp | tee top.log
