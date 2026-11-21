#!/bin/bash
# Open-source build for the Tang Nano 20K: Yosys -> nextpnr-himbaechel -> gowin_pack (Apicula)
#   pip install yowasp-yosys yowasp-nextpnr-himbaechel-gowin apycula
# Usage:  bash scripts/build_opensource.sh uart       live inference + model update (default)
#         bash scripts/build_opensource.sh selftest   on-board self-test (LEDs + UART message)
set -e
cd "$(dirname "$0")/.."
TARGET=${1:-uart}
mkdir -p build && cp gen/*.mem build/ && cd build
if [ "$TARGET" = "selftest" ]; then
  TOP=tangnano20k_selftest; SRC="../board/tangnano20k_selftest.v"; CST=../board/tangnano20k.cst
else
  TOP=tangnano20k_uart; SRC="../board/ns_uart.v ../board/ns_loader.v ../board/tangnano20k_uart.v"; CST=../board/tangnano20k_uart.cst
fi
yowasp-yosys -q -l synth_$TARGET.log -p "read_verilog -I../gen ../rtl/nn_layer.v ../rtl/netsilcon_top.v $SRC; synth_gowin -family gw2a -top $TOP -json $TARGET.json"
yowasp-nextpnr-himbaechel-gowin --json $TARGET.json --write ${TARGET}_pnr.json \
  --device GW2AR-LV18QN88C8/I7 --vopt family=GW2A-18C --vopt cst=$CST --freq 27 > pnr_$TARGET.log 2>&1
grep -E "MULT9X9|LUT4:|DFF:|BSRAM:|Max frequency" pnr_$TARGET.log
gowin_pack -d GW2A-18C -o netsilcon_$TARGET.fs ${TARGET}_pnr.json
echo "Bitstream: build/netsilcon_$TARGET.fs"
