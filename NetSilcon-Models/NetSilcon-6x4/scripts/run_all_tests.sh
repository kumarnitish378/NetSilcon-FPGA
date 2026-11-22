#!/bin/bash
# Every simulation test in one go (needs Icarus Verilog + Python 3 with numpy).
set -e
cd "$(dirname "$0")"
echo "######## 1. Network vs Python model (PHASES=1 and 2) + board self-test"; bash run_sim.sh | grep -E "=====|Mismatches|Latency|RESULT|PASS"
echo "######## 2. Live UART inference";                                        bash run_sim_uart.sh | grep -E "Frames|mismatches|Latency|RESULT"
echo "######## 3. Model upload over UART (CRC, timeout, 3 models)";             bash run_sim_load.sh | grep -E "^[0-9]|load reply|vectors|RESULT"
