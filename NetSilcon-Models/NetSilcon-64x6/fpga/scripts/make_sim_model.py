"""
Prepare a Verilog simulation of ANY NetSilcon-64x6 model file (used by run_sim_model.sh).

    python3 fpga/scripts/make_sim_model.py models/<name>/<name>.json  <out_dir>

Writes into <out_dir>: the 32 block-RAM images with the model in BOTH banks, its golden vectors
(test_in/out.mem and stress_in/out.mem, so tb_engine.v runs them on bank 0 and on bank 1),
num_vectors.vh and ns64_builtin.vh with the model's shifts.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "python", "model"))
import ns64  # noqa: E402


def hexvec(v):
    return "".join(f"{int(x) & 0xFF:02x}" for x in reversed(v))     # x0 in the lowest byte


def main():
    path, out = sys.argv[1], sys.argv[2]
    d = json.load(open(path))
    net = ns64.from_json(d)                       # checks the CRC-32 stored in the file
    tv = d.get("test_vectors") or []
    if not tv:
        sys.exit("the model file has no test_vectors")
    for v in tv:                                  # the file's golden outputs must match the Python model
        if net.forward(v["x"])[0].tolist() != v["y"]:
            sys.exit("golden vectors in the file do not match the Python model")
    os.makedirs(out, exist_ok=True)
    rams = ns64.ram_images(net, net)
    for r in range(ns64.N_RAM):
        with open(os.path.join(out, f"wmem_{r:02d}.mem"), "w") as f:
            f.writelines(f"{v:04x}\n" for v in rams[r])
    sh = sum(net.S[l] << (5 * l) for l in range(ns64.NL))
    ns = min(len(tv), 200)
    for prefix, vecs in (("test", tv), ("stress", tv[:ns])):
        with open(os.path.join(out, f"{prefix}_in.mem"), "w") as f:
            f.writelines(hexvec(v["x"]) + "\n" for v in vecs)
        with open(os.path.join(out, f"{prefix}_out.mem"), "w") as f:
            f.writelines(hexvec(v["y"]) + "\n" for v in vecs)
    with open(os.path.join(out, "num_vectors.vh"), "w") as f:
        f.write(f"localparam N_VEC = {len(tv)};\nlocalparam N_STRESS = {ns};\n")
    with open(os.path.join(out, "ns64_builtin.vh"), "w") as f:
        f.write(f"localparam [34:0] BUILTIN_SHIFTS = 35'h{sh:09x};\n"
                f"localparam [31:0] BUILTIN_CRC32  = 32'h{net.crc32():08x};\n"
                f"localparam [34:0] STRESS_SHIFTS  = 35'h{sh:09x};\n")
    print(f"{d['name']}: CRC-32 {net.crc32():08X}, shifts {net.S}, {len(tv)} golden vectors "
          f"(bank 0: all, bank 1: first {ns})")


if __name__ == "__main__":
    main()
