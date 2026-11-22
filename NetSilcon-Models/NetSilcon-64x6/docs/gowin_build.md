# Build NetSilcon-64x6 in Gowin EDA (V1.9.11.03 Education)

A new Gowin project of its own. The 6x4 project in `C:\fpga\gowin\netsilcon` is not touched.

## 1. Create the project

1. Make the folder `C:\fpga\gowin\ns64`.
2. Gowin EDA → **File → New → FPGA Design Project**.
   Name `ns64`, Create in `C:\fpga\gowin`. (Gowin makes `C:\fpga\gowin\ns64\ns64.gprj`.)
3. Device: **GW2AR-LV18QN88C8/I7** (Series GW2AR, Package QFN88, Speed C8/I7, Device GW2AR-18C).

## 2. Add the files

**Project → Add Files**, from the `fpga\` folder of NetSilcon-64x6 (on the build laptop:
`C:\fpga\NetSilcon-6x4-github\NetSilcon-Models\NetSilcon-64x6\fpga`):

| Folder | Files |
|---|---|
| `rtl\` | `ns64_requant.v`, `ns64_wram.v`, `ns64_engine.v` |
| `board\` | `ns_uart.v`, `ns64_uart_tx.v`, `ns64_loader.v`, `tangnano20k_ns64.v` |
| `board\` | `tangnano20k_ns64.cst` (the **only** `.cst` in this project) |
| `board\` | `tangnano20k.sdc` (27 MHz, keep it **enabled**) |

Do **not** add anything from `fpga\tb\`, `fpga\probe\` or `fpga\sim\`.

**Important:** Gowin **copies** added files into `C:\fpga\gowin\ns64\src\` and compiles those
copies. When a file changes in `fpga\`, copy it again before synthesizing
(PowerShell):

```powershell
$S = "C:\fpga\NetSilcon-6x4-github\NetSilcon-Models\NetSilcon-64x6\fpga"; $D = "C:\fpga\gowin\ns64\src"
copy $S\rtl\ns64_*.v, $S\board\ns_uart.v, $S\board\ns64_uart_tx.v, $S\board\ns64_loader.v, $S\board\tangnano20k_ns64.v, $S\board\tangnano20k_ns64.cst, $S\board\tangnano20k.sdc $D
dir $D
```

## 3. Initial RAM contents

Copy the 32 files `fpga\gen\wmem_00.mem` … `fpga\gen\wmem_31.mem` into `C:\fpga\gowin\ns64\`
(next to `ns64.gprj`, same as the `.mem` files of the 6x4 project).
They hold the built-in synthetic model (CRC-32 6F4225BF) in bank 0.

## 4. Settings

**Project → Configuration**:

- Synthesize → General → **Top Module/Entity**: `tangnano20k_ns64`
- Synthesize → General → **Include Path**: `C:\fpga\NetSilcon-6x4-github\NetSilcon-Models\NetSilcon-64x6\fpga\gen` (for `ns64_builtin.vh`)
- Everything else stays at the defaults (the 6x4 project also uses the defaults: SSPI/MSPI not
  set as regular IO).

## 5. Run

1. **Synthesize**. In the log, look for warnings with `readmemh`, `cannot open`, `BSRAM`, `DSP`.
2. **Place & Route**.
3. Save these into `docs\gowin_reports\` of NetSilcon-64x6 and say "check":
   - `C:\fpga\gowin\ns64\impl\pnr\ns64.rpt.txt` (resources)
   - `C:\fpga\gowin\ns64\impl\pnr\ns64.tr.html` (timing; or copy the Fmax line)
   - `C:\fpga\gowin\ns64\impl\gwsynthesis\ns64.log` (synthesis log)

## 6. Program (SRAM, lost at power-off)

**Tools → Programmer**:

- Cable: **USB Debugger A**, frequency **0.9 MHz**
- Device: **GW2AR-18C**, Operation **SRAM Program**
- File: `C:\fpga\gowin\ns64\impl\pnr\ns64.fs`
- Program/Configure. LED0 starts blinking (heartbeat).

LED5 may light right after programming if the USB bridge sends a stray byte (seen on the 6x4 too).
It is harmless.

## 7. First hardware tests (Windows PowerShell or cmd)

```
cd C:\fpga\NetSilcon-6x4-github\NetSilcon-Models\NetSilcon-64x6\python\host
python ns64_host.py COM7 --info                                   expect: synthetic 6F4225BF built-in
python ns64_host.py COM7 --test                                   1000 golden vectors, expect 0 mismatches
python ns64_host.py COM7 --load ..\..\models\stress\stress.json --corrupt   expect: REFUSED - CRC error
python ns64_host.py COM7 --test --count 100                       old model still exact
python ns64_host.py COM7 --load ..\..\models\stress\stress.json             expect: LOADED 732C18C9 (~2 s)
python ns64_host.py COM7 --test                                   200 stress vectors
python ns64_host.py COM7 --load ..\..\models\synthetic\synthetic.json          back to the synthetic model
python ns64_host.py COM7 --random 500                             random inputs vs Python
```

Every run writes `results\logs\<date_time>_<mode>.log` and `.csv`. Say "check" and I'll read them.
