#!/bin/bash
# Simulate the live-UART design: PC-style frames in, replies checked against the Python model.
set -e
cd "$(dirname "$0")/.."
mkdir -p sim && cp gen/*.mem sim/ && cd sim
iverilog -g2005 -I ../gen -o uart.vvp ../tb/tb_uart.v ../board/tangnano20k_uart.v ../board/ns_uart.v ../board/ns_loader.v ../rtl/netsilcon_top.v ../rtl/nn_layer.v
vvp -n uart.vvp | grep -v finish
