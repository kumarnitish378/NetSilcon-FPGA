# Step 0: resource probe (not the real design)

`probe_top.v` contains the parts of NetSilcon-64x6 that might not fit:

- 64 MAC lanes, each with one 8×8 signed multiplier and a 24-bit accumulator
- 32 weight RAMs of 1K × 16, with byte-enable writes and one shared read address
- `$readmemh` initial contents (`probe_w00.mem` … `probe_w31.mem`)

The results are XOR-reduced to `uart_tx`, so synthesis cannot remove anything.
**Do not program this onto the board.** It is only for the resource reports
(`uart_tx` toggles at random).

## Open-source result (yosys + nextpnr-himbaechel, run by Claude)

| Resource | Used | Available |
|---|---|---|
| MULT9X9 | 64 | 96 (66 %) |
| BSRAM | 32 (inferred as DPX9B, 1K × 18, byte enables, init accepted) | 46 (69 %) |
| DFF | 2,810 | 15,552 (18 %) |
| LUT4 (incl. ALU) | 3,023 | 20,736 (14 %) |
| Max frequency (nextpnr estimate) | 112.7 MHz | 27 MHz needed |

nextpnr's frequency estimate is usually more optimistic than Gowin's. Only the Gowin timing report counts.

## Gowin EDA check (please run)

1. Create a new folder `C:\fpga\gowin\ns64_probe`.
2. Gowin EDA → File → New → FPGA Design Project. Name `ns64_probe`, location `C:\fpga\gowin`.
   Device **GW2AR-LV18QN88C8/I7**.
3. Add files: `probe_top.v`, `probe.cst`, `probe.sdc` from `C:\fpga\NetSilcon-64x6\probe`.
4. Copy the 32 files `probe_w00.mem` … `probe_w31.mem` into `C:\fpga\gowin\ns64_probe`
   (the project folder, next to `ns64_probe.gprj`). This is the same as for the 6x4 `.mem` files.
5. Project → Configuration → Synthesize → set Top Module to `probe_top`.
6. Run Synthesize, then Place & Route.
7. Send me (or say "check" after saving them into `C:\fpga\NetSilcon-64x6\probe\gowin_reports\`):
   - `impl\pnr\ns64_probe.rpt.txt` (resource table)
   - `impl\pnr\ns64_probe.tr.html` or the timing summary (max frequency)
   - any warnings mentioning `readmemh`, `BSRAM`, `byte` or `DSP` from the synthesis log
     `impl\gwsynthesis\ns64_probe.log`

What I'm looking for:

| Question | Pass if |
|---|---|
| 64 multipliers fit | P&R completes and DSP use is ≤ 100 % |
| Weight RAMs are block RAM | BSRAM ≈ 32 (not thousands of LUTs/registers) |
| Init files accepted | no "cannot open file" / "readmemh" error |
| Timing | max frequency ≥ 27 MHz |
