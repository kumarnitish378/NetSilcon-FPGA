#!/bin/bash
# Simulate model loading over UART: built-in -> bad upload -> irrigation -> interrupted -> motor again.
set -e
cd "$(dirname "$0")/.."
mkdir -p sim && cp gen/*.mem sim/ && cd sim
python3 ../scripts/make_tb_load.py
iverilog -g2005 -I ../gen -o load.vvp ../tb/tb_load.v ../board/tangnano20k_uart.v ../board/ns_uart.v ../board/ns_loader.v ../rtl/netsilcon_top.v ../rtl/nn_layer.v
vvp -n load.vvp | grep -v finish
