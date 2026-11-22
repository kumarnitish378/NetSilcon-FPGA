#!/bin/bash
# Simulate NetSilcon-6x4 against the Python golden vectors (both modes) and the board self-test.
set -e
cd "$(dirname "$0")/.."
mkdir -p sim && cp gen/*.mem sim/ && cd sim
for P in 1 2; do
  echo "===== PHASES=$P"
  iverilog -g2005 -I ../gen -P tb_netsilcon.PHASES=$P -o n$P.vvp ../tb/tb_netsilcon.v ../rtl/netsilcon_top.v ../rtl/nn_layer.v
  vvp -n n$P.vvp | grep -v finish
done
echo "===== Board self-test (Tang Nano 20K top)"
iverilog -g2005 -I ../gen -o board.vvp ../tb/tb_board.v ../board/tangnano20k_selftest.v ../rtl/netsilcon_top.v ../rtl/nn_layer.v
vvp -n board.vvp | grep -v finish
