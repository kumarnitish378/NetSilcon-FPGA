#!/bin/bash
# Mutation test: break the RTL on purpose in small ways; the engine testbench MUST fail.
# Run from anywhere (WSL Ubuntu):  bash fpga/scripts/mutation_test.sh
set -e
cd "$(dirname "$0")/.."
mkdir -p sim/mut ../results/logs
cp gen/*.mem gen/*.vh sim/mut/
cd sim/mut
LOG=../../../results/logs/mutation_$(date +%Y%m%d_%H%M%S).log
caught=0; total=0
run() {   # $1 = name, $2 = file, $3 = sed expression
    cp ../../rtl/*.v .
    sed -i "$3" "$2"
    if cmp -s "$2" "../../rtl/$2"; then echo "  [$1] sed did not change $2 (mutation not applied)"; return; fi
    total=$((total+1))
    R=$( (iverilog -g2012 -I. -o m.vvp nslm_requant.v nslm_mem.v nslm_engine.v ../../tb/tb_engine.v 2>&1 && vvp -n m.vvp +n=300) | grep RESULT || echo "RESULT compile/run error")
    if echo "$R" | grep -q PASS; then echo "  [$1] NOT caught: $R"; else caught=$((caught+1)); echo "  [$1] caught: $R"; fi
}
{
run "rounding constant removed"   nslm_requant.v 's/(25.sd1 <<< (s - 5.d1))/25'"'"'sd0/'
run "ReLU removed"                nslm_requant.v 's/(relu \&\& acc_in\[23\])/1'"'"'b0/'
run "argmax ties -> last index"   nslm_engine.v  's/\$signed(xq) > best/$signed(xq) >= best/'
run "embedding dim order swapped" nslm_engine.v  's/assign eaddr = {sym, wi\[2:0\]};/assign eaddr = {sym, ~wi[2:0]};/'
run "context order reversed"      nslm_engine.v  's/(5.d31 - p) \* 6/p * 6/'
run "layer 2 base off by one"     nslm_engine.v  's/9.d324 : 9.d390/9'"'"'d325 : 9'"'"'d390/'
run "bias high byte dropped"      nslm_engine.v  's/K_HI:    p_v\[j\*16 +: 16\] <= {rdata\[j\*8 +: 8\], 8.h00};/K_HI:    p_v[j*16 +: 16] <= 16'"'"'d0;/'
run "output layer uses ReLU"      nslm_engine.v  's/.relu(!outph)/.relu(1'"'"'b1)/'
echo "MUTATION: $caught / $total mutants caught"
} 2>&1 | tee "$LOG"
