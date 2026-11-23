#!/bin/bash
# Icarus Verilog: run the NetSilcon-64x6 engine with ANY model file and compare every golden
# vector with the Python int8 model, bit for bit. No board needed.
#   bash fpga/scripts/run_sim_model.sh models/pump_health/pump_health.json
set -e
[ -n "$1" ] || { echo "usage: bash fpga/scripts/run_sim_model.sh models/<name>/<name>.json"; exit 2; }
MODEL="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
cd "$(dirname "$0")/.."
NAME="$(basename "$MODEL" .json)"
OUT="sim/model_$NAME"
python3 scripts/make_sim_model.py "$MODEL" "$OUT"
cd "$OUT"
iverilog -g2012 -I. -o engine.vvp \
  ../../rtl/ns64_requant.v ../../rtl/ns64_wram.v ../../rtl/ns64_engine.v ../../tb/tb_engine.v
vvp -n engine.vvp | sed -e "s/synthetic model:/$NAME (bank 0):/" -e "s/stress model   :/$NAME (bank 1):/" | tee engine.log
grep -q "RESULT: PASS" engine.log
