#!/bin/bash
# Open-source build for the Tang Nano 20K: Yosys -> nextpnr-himbaechel -> gowin_pack (Apicula)
#   pip install yowasp-yosys yowasp-nextpnr-himbaechel-gowin apycula
#   bash fpga/scripts/build_opensource.sh      -> build/nslm.fs + resource/timing summary
set -e
cd "$(dirname "$0")/.."
mkdir -p build ../results/logs && cp gen/*.mem build/ && cd build
SRC="../rtl/nslm_requant.v ../rtl/nslm_mem.v ../rtl/nslm_engine.v ../rtl/nslm_core.v ../board/ns_uart.v ../board/tangnano20k_lm.v"
yowasp-yosys -q -l synth.log -p "read_verilog -I../gen $SRC; synth_gowin -family gw2a -top tangnano20k_lm -json lm.json"
yowasp-nextpnr-himbaechel-gowin --json lm.json --write lm_pnr.json \
  --device GW2AR-LV18QN88C8/I7 --vopt family=GW2A-18C --vopt cst=../board/tangnano20k_lm.cst --freq 27 > pnr.log 2>&1
{ grep -A26 "Device utilisation" pnr.log | grep -E "LUT4|ALU|DFF|BSRAM|MULT|IOB" | grep -vE ": +0/"; grep "Max frequency" pnr.log | tail -1; } | tee resources_opensource.txt
cp resources_opensource.txt ../../results/logs/resources_opensource_$(date +%Y%m%d_%H%M%S).txt
if command -v gowin_pack >/dev/null; then gowin_pack -d GW2A-18C -o nslm.fs lm_pnr.json && echo "Bitstream: fpga/build/nslm.fs"; fi
