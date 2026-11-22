"""Write the .mem files tb_load.v needs, from models/*.json (run from sim/)."""
import json, sys
sys.path.insert(0, "../model")
from make_model import crc16, image
for name in ("motor_fault", "irrigation", "rover"):
    m = json.load(open(f"../models/{name}.json"))
    img = image(m["weights"], m["biases"], m["shifts"])
    c = crc16(img)
    assert f"{c:04X}" == m["crc16"]
    full = img + bytes([c >> 8, c & 0xFF])
    open(f"{name}_image.mem", "w").write("\n".join(f"{b:02x}" for b in full) + "\n")
    open(f"{name}_tin.mem", "w").write("\n".join("%02x%02x%02x%02x" % (t[3], t[2], t[1], t[0]) for t in m["tests"]) + "\n")
    open(f"{name}_tout.mem", "w").write("\n".join("%02x%02x" % (t[5] & 255, t[4] & 255) for t in m["tests"]) + "\n")
    print(name, "CRC", m["crc16"])
