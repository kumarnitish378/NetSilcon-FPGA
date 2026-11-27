#!/usr/bin/env bash
# Mutation test: flip gates in the last logic layer on purpose; the Icarus testbench MUST fail.
# Proves the testbench really checks the circuit (a PASS on a broken circuit = useless test).
# usage: ./mutation_test.sh exp01_w180
set -euo pipefail
NAME=$1
HERE="$(cd "$(dirname "$0")" && pwd)"
D="$HERE/$NAME"; LOGS="$HERE/../results/logs"; mkdir -p "$LOGS"
MOD="netsilcon_6x4_lgn_${NAME}"
LOG="$LOGS/mutation_${NAME}_$(date +%Y%m%d_%H%M%S).log"
TMP=$(mktemp -d)
cd "$D"
DEPTH=$(grep -o "wire l[0-9]*_0 " "${MOD}.v" | wc -l)
LAST=$((DEPTH - 1))
fails=0; total=0
{
for J in 0 1 2 3 4; do
  # invert one gate output of the last layer
  sed -E "s/^(    wire l${LAST}_${J} = )(.*);$/\1~(\2);/" "${MOD}.v" > "$TMP/mut.v"
  if cmp -s "${MOD}.v" "$TMP/mut.v"; then echo "gate l${LAST}_${J}: not found"; continue; fi
  iverilog -g2012 -o "$TMP/m.vvp" "tb_${MOD}.v" "$TMP/mut.v"
  R=$(cd "$D" && vvp -n "$TMP/m.vvp" | grep RESULT)
  total=$((total + 1))
  echo "mutant l${LAST}_${J} inverted: $R"
  if echo "$R" | grep -q FAIL; then fails=$((fails + 1)); fi
done
echo "MUTATION $NAME: $fails/$total mutants caught"
} | tee "$LOG"
rm -rf "$TMP"
