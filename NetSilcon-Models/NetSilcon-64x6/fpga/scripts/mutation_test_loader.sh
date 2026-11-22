#!/bin/bash
# Mutation test for the loader / board top: 5 deliberate bugs, tb_top must FAIL on each.
#   bash fpga/scripts/mutation_test_loader.sh      (~10 min)
cd "$(dirname "$0")/.."
python3 scripts/make_tb_load.py > /dev/null
mkdir -p sim/mut_top
cp gen/*.mem gen/tb/up_*.mem gen/tb/*_amax.mem sim/mut_top/
cd sim/mut_top
declare -A MUT FILE
MUT[ignore_crc]="s/if (~crc != rx_crc)  status <= 2'd1;/if (1'b0) status <= 2'd1;/";            FILE[ignore_crc]=loader
MUT[write_active_bank]="s/wr_addr <= {~active_bank, base + 9'd2/wr_addr <= {active_bank, base + 9'd2/"; FILE[write_active_bank]=loader
MUT[bias_bytes_swapped]="s/wr_addr <= {~active_bank, base + {8'd0, bsel}};/wr_addr <= {~active_bank, base + {8'd0, ~bsel}};/"; FILE[bias_bytes_swapped]=loader
MUT[pair_swapped]="s/wr_data <= {rx_data, pbuf\[i\]};/wr_data <= {pbuf[i], rx_data};/";  FILE[pair_swapped]=loader
MUT[keep_old_shifts]="s/            shifts    <= ld_shifts;/            shifts    <= shifts;/";          FILE[keep_old_shifts]=top
ALL=1
for m in ignore_crc write_active_bank bias_bytes_swapped pair_swapped keep_old_shifts; do
  cp ../../board/ns64_loader.v ld.v; cp ../../board/tangnano20k_ns64.v top.v
  if [ "${FILE[$m]}" = loader ]; then sed -i "${MUT[$m]}" ld.v; cmp -s ld.v ../../board/ns64_loader.v && { echo "$m NOT APPLIED"; ALL=0; continue; }
  else sed -i "${MUT[$m]}" top.v; cmp -s top.v ../../board/tangnano20k_ns64.v && { echo "$m NOT APPLIED"; ALL=0; continue; }; fi
  iverilog -g2012 -I../../gen -I../../gen/tb -o m.vvp ../../rtl/ns64_requant.v ../../rtl/ns64_wram.v \
    ../../rtl/ns64_engine.v ../../board/ns_uart.v ../../board/ns64_uart_tx.v ld.v top.v ../../tb/tb_top.v
  R=$(vvp -n m.vvp | grep -E "RESULT|checks")
  echo "mutation $m: $(echo "$R" | tr '\n' ' ')"
  echo "$R" | grep -q "RESULT: FAIL" || ALL=0
done
[ $ALL = 1 ] && echo "LOADER MUTATION TEST: PASS (every mutation detected)" || echo "LOADER MUTATION TEST: FAIL"
