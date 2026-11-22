# Setup prompt for AI coding agents

Clone the repository, open your AI coding agent in its root folder, and paste the prompt below.

```bash
git clone --recurse-submodules https://github.com/kumarnitish378/NetSilcon-FPGA.git
cd NetSilcon-FPGA
```

---

```text
You are working in NetSilcon-FPGA: open-source neural-network engines on FPGA with a fixed
network shape in Verilog and loadable int8 weights, prototyped on a Sipeed Tang Nano 20K
(Gowin GW2AR-18).

1. Read, in this order: Agent/PROJECT_SUMMARY.md, Agent/WORKING_RULES.md, Agent/MODEL_INDEX.md,
   then the README.md of the model folder I want to work on
   (NetSilcon-Models/NetSilcon-6x4 or NetSilcon-Models/NetSilcon-64x6).

2. Check my environment and tell me what is missing (do not install anything without asking):
   - Python 3.9+ with numpy (pyserial only for the board)
   - Icarus Verilog (iverilog, vvp) for simulation
   - optional: Node.js 20+ for the website/ submodule, yowasp-yosys + nextpnr for open-source builds
   - which OS I use; on Windows, whether I have WSL for the bash scripts

3. Prove the setup works, without a board, and show me the RESULT lines:
   - cd NetSilcon-Models/NetSilcon-6x4 && bash fpga/scripts/run_all_tests.sh
   - cd NetSilcon-Models/NetSilcon-64x6 && python3 python/model/make_synthetic.py
     (must report self-check PASS and leave fpga/gen/ unchanged in git)
     && bash fpga/scripts/run_sim_engine.sh
   Every test must end with "RESULT: PASS". If one fails, stop and show me the output.

4. Summarise in 5 lines what the project is and what you can help with, then ask me what I
   want to do. Follow Agent/WORKING_RULES.md for every change: bit-exact Python model first,
   then Verilog, then simulation, then hardware; never claim a number that no log shows.
```

---

## What the agent should be able to do afterwards

- Explain any part of the design (engine, requantizer, loader, UART protocol, host tool)
- Train a new model for an existing shape and produce its `models/<app>/` folder
- Add a new network shape as a new folder `NetSilcon-Models/NetSilcon-<shape>/` with the same layout
- Run the simulations and mutation tests, and read the hardware logs in `results/logs/`
- Update the website through `tools/sync_website.py` and the `website/` submodule
