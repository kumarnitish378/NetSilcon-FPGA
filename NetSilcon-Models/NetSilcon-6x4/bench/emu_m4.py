"""Run the Cortex-M4 build in the Unicorn emulator: check the 576 vectors, count instructions for one inference."""
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
f = ELFFile(open("m4.elf", "rb"))
mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
lo = min(s["p_vaddr"] for s in f.iter_segments() if s["p_type"] == "PT_LOAD") & ~0xFFF
hi = max(s["p_vaddr"] + s["p_memsz"] for s in f.iter_segments() if s["p_type"] == "PT_LOAD")
size = ((hi - lo) + 0xFFFFF) & ~0xFFFFF
mu.mem_map(lo, size)
for s in f.iter_segments():
    if s["p_type"] == "PT_LOAD":
        mu.mem_write(s["p_vaddr"], s.data())
mu.mem_map(0x20000000, 0x100000)                     # RAM for the stack
sym = {x.name: x["st_value"] for x in f.get_section_by_name(".symtab").iter_symbols()}
count = {"n": 0}
mu.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: count.__setitem__("n", count["n"] + 1))
def call(name, limit):
    count["n"] = 0
    mu.reg_write(UC_ARM_REG_SP, 0x200F0000)
    mu.reg_write(UC_ARM_REG_LR, 0x0FFFFFF1)             # return address outside the code -> stop
    mu.emu_start(sym[name] | 1, 0x0FFFFFF0, count=limit)
    return count["n"]
n_start = call("start", 3_000_000)                     # runs the 576 checks, then spins in for(;;)
bad = int.from_bytes(mu.mem_read(sym["result_bad"], 4), "little", signed=True)
print("Cortex-M4 build: 576-vector check ->", "PASS" if bad == 0 else f"{bad} mismatches")
n = call("one", 100000)
print("instructions for ONE inference (incl. call/return):", n)
