#!/bin/bash
# Run the PHASES=2 simulation with waveform recording, then open GTKWave.
set -e
cd "$(dirname "$0")/.."
mkdir -p sim && cp gen/*.mem sim/ && cd sim
iverilog -g2005 -I ../gen -P tb_netsilcon.PHASES=2 -s tb_netsilcon -s dump_waves \
  -o waves.vvp ../tb/tb_netsilcon.v ../tb/dump_waves.v ../rtl/netsilcon_top.v ../rtl/nn_layer.v
vvp -n waves.vvp | grep -E "RESULT|Mismatch"
echo "Waveform written: fpga/sim/netsilcon.vcd"
command -v gtkwave >/dev/null && gtkwave netsilcon.vcd &
