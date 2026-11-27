#!/bin/bash
# Icarus Verilog: LM-0 engine vs Python golden vectors, then a full on-chip conversation,
# then the UART board top. Run from anywhere (WSL Ubuntu):  bash fpga/scripts/run_sim.sh
set -e
cd "$(dirname "$0")/.."
mkdir -p sim ../results/logs
cp gen/*.mem gen/*.vh sim/
cd sim
LOG=../../results/logs/sim_$(date +%Y%m%d_%H%M%S).log
{
iverilog -g2012 -I../gen -o engine.vvp ../rtl/nslm_requant.v ../rtl/nslm_mem.v ../rtl/nslm_engine.v ../tb/tb_engine.v
vvp -n engine.vvp $@ | grep -E "RESULT|MISMATCH"
iverilog -g2012 -I../gen -o chat.vvp ../rtl/nslm_requant.v ../rtl/nslm_mem.v ../rtl/nslm_engine.v ../rtl/nslm_core.v ../tb/tb_chat.v
vvp -n chat.vvp | grep -E "RESULT|MISMATCH"
cmp chat_generated.txt ../gen/chat_expected.txt && echo "chat text == gen/chat_expected.txt (Python)"
if [ -f ../tb/tb_top.v ]; then
iverilog -g2012 -I../gen -o top.vvp ../rtl/nslm_requant.v ../rtl/nslm_mem.v ../rtl/nslm_engine.v ../rtl/nslm_core.v \
  ../board/ns_uart.v ../board/tangnano20k_lm.v ../tb/tb_top.v
vvp -n top.vvp | grep -E "RESULT|MISMATCH|>>"
fi
} 2>&1 | tee "$LOG"
echo "log: $LOG"
