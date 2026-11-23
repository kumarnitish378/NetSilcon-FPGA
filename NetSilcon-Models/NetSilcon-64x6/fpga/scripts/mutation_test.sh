#!/bin/bash
# Mutation test: break the engine on purpose in 6 different ways; the testbench must
# FAIL every time. Proves the golden-vector test really checks each part of the math.
#   bash fpga/scripts/mutation_test.sh
cd "$(dirname "$0")/.."
mkdir -p sim/mutation
cp gen/*.mem sim/mutation/; cp gen/tb/wmem_*.mem sim/mutation/
cd sim/mutation
declare -A MUT
MUT[rounding]="s/(25'sd1 <<< (s - 5'd1))/25'sd0/"
MUT[relu]="s/(relu \&\& acc_in\[23\])/(1'b0)/"
MUT[bias_hi]="s/K_HI:    p_v\[j\*16 +: 16\] <= {rdata\[j\*8 +: 8\], 8'h00};/K_HI: p_v[j*16 +: 16] <= 16'd0;/"
MUT[layer_shift]="s/(layer == 3'd0) ? 3'd0 : layer - 3'd1;/(layer == 3'd0) ? 3'd0 : layer;/"
MUT[out_clamp]="s/(v < -25'sd128) ? 8'h80 : v\[7:0\]/v[7:0]/"
MUT[last_weight]="s/(t < n_in + 7'd2) ? K_W : K_NONE/(t < n_in + 7'd1) ? K_W : K_NONE/"
ALL=1
for m in rounding relu bias_hi layer_shift out_clamp last_weight; do
  sed "${MUT[$m]}" ../../rtl/ns64_requant.v > rq.v
  sed "${MUT[$m]}" ../../rtl/ns64_engine.v  > en.v
  if cmp -s rq.v ../../rtl/ns64_requant.v && cmp -s en.v ../../rtl/ns64_engine.v; then
    echo "mutation $m: NOT APPLIED (script error)"; ALL=0; continue; fi
  iverilog -g2012 -I../../gen -o m.vvp rq.v ../../rtl/ns64_wram.v en.v ../../tb/tb_engine.v
  R=$(vvp -n m.vvp +n=60 | grep -E "RESULT|stress model")
  echo "mutation $m: $(echo "$R" | tr '\n' ' ')"
  echo "$R" | grep -q "RESULT: FAIL" || ALL=0
done
[ $ALL = 1 ] && echo "MUTATION TEST: PASS (every mutation detected)" || echo "MUTATION TEST: FAIL"
