#!/bin/bash
# Open-source build for the Tang Nano 20K: Yosys -> nextpnr-himbaechel -> gowin_pack (Apicula)
#   pip install yowasp-yosys yowasp-nextpnr-himbaechel-gowin apycula
#   bash scripts/build_opensource.sh            -> build/ns64_uart.fs + resource/timing summary
set -e
cd "$(dirname "$0")/.."
mkdir -p build && cp gen/wmem_*.mem build/ && cd build
SRC="../rtl/ns64_requant.v ../rtl/ns64_wram.v ../rtl/ns64_engine.v ../board/ns_uart.v ../board/ns64_uart_tx.v ../board/ns64_loader.v ../board/tangnano20k_ns64.v"
yowasp-yosys -q -l synth_uart.log -p "read_verilog -I../gen $SRC; synth_gowin -family gw2a -top tangnano20k_ns64 -json uart.json"
yowasp-nextpnr-himbaechel-gowin --json uart.json --write uart_pnr.json \
  --device GW2AR-LV18QN88C8/I7 --vopt family=GW2A-18C --vopt cst=../board/tangnano20k_ns64.cst --freq 27 > pnr_uart.log 2>&1
grep -E "^Info: +(LUT4|ALU|DFF|BSRAM|MULT9X9|MULTADDALU18X18|MULTALU18X18|IOB):|Max frequency" pnr_uart.log | tee resources_opensource.txt
gowin_pack -d GW2A-18C -o ns64_uart.fs uart_pnr.json
echo "Bitstream: build/ns64_uart.fs"
