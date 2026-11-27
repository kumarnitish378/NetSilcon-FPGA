#!/usr/bin/env bash
# NetSilcon-6x4-LGNs : sim + synth + P&R check for one model (run in WSL Ubuntu)
# usage: ./run_fpga_checks.sh exp01_w360
# needs: iverilog, yosys (or yowasp-yosys), nextpnr-himbaechel (or yowasp-nextpnr-himbaechel)
set -euo pipefail
NAME=$1
HERE="$(cd "$(dirname "$0")" && pwd)"
D="$HERE/$NAME"; LOGS="$HERE/../results/logs"; mkdir -p "$LOGS"
STAMP=$(date +%Y%m%d_%H%M%S); LOG="$LOGS/fpga_${NAME}_${STAMP}.log"
MOD="netsilcon_6x4_lgn_${NAME}"
YOSYS=$(command -v yosys || command -v yowasp-yosys)
PNR=$(command -v nextpnr-himbaechel || command -v yowasp-nextpnr-himbaechel-gowin)
cd "$D"
{
echo "== $NAME  $(date)"
echo "== 1) Icarus bit-exact test vs Python golden vectors"
iverilog -g2012 -o tb.vvp "tb_${MOD}.v" "${MOD}.v"
vvp -n tb.vvp | grep RESULT

echo "== 2) yosys synth_gowin of the CORE alone (no wrapper)"
"$YOSYS" -q -p "read_verilog ${MOD}.v; synth_gowin -top ${MOD} -json core.json; tee -o core_stat.txt stat"
grep -E "Number of cells|LUT|MUX2|ALU|DFF|BSRAM|SP|DPB|MULT|IBUF|OBUF" core_stat.txt || true

echo "== 3) place & route the timing wrapper on GW2AR-LV18QN88C8/I7 (Tang Nano 20K) @27 MHz"
"$YOSYS" -q -p "read_verilog ${MOD}.v timing_wrapper.v; synth_gowin -top timing_wrapper -json wrap.json"
"$PNR" --json wrap.json --write pnr.json --device GW2AR-LV18QN88C8/I7 \
       --vopt family=GW2A-18C --vopt cst=tangnano20k.cst --freq 27 2> pnr.log || true
grep -A24 "Device utilisation" pnr.log | grep -E "LUT4|MUX2|ALU|DFF|BSRAM|RAM16|MULT18|IOB" || true
grep "Max frequency" pnr.log | tail -1 || true
} 2>&1 | tee "$LOG"
echo "log: $LOG"
