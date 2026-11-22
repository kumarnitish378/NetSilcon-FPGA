# Benchmarks

The same bit-exact int8 network in plain C (`net.h`, weights in `model.h` from
`models/motor_fault/motor_fault.json`). Results and sources: [`docs/benchmarks.md`](../docs/benchmarks.md).

```bash
# Desktop / laptop CPU, one inference at a time
gcc -O2 -march=native -o bench_cpu bench_cpu.c && ./bench_cpu

# Cortex-M4 (STM32F4 class): build for the real core, count instructions in an emulator
pip install ziglang unicorn pyelftools
python -m ziglang cc -target thumb-freestanding-eabihf -mcpu=cortex_m4 -O2 -nostdlib \
    -ffreestanding -fno-builtin -Wl,-e,start -Wl,--image-base=0x08000000 -o m4.elf m4.c
python emu_m4.py
```
