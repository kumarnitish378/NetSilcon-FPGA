"""Write bench/net.h (weights, biases, shifts, golden vectors of models/synthetic.json) for bench.c.
    cd bench && python3 make_net_h.py && gcc -O3 -march=native -o bench bench.c && ./bench"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "model"))
import ns64
d = json.load(open(os.path.join(HERE, "..", "models", "synthetic.json")))
net = ns64.from_json(d)
with open(os.path.join(HERE, "net.h"), "w") as f:
    for l in range(ns64.NL):
        f.write(f"static const signed char W{l}[{ns64.SIZES[l+1]*ns64.SIZES[l]}]={{" + ",".join(str(int(v)) for v in net.W[l].reshape(-1)) + "};\n")
        f.write(f"static const short B{l}[{ns64.SIZES[l+1]}]={{" + ",".join(str(int(v)) for v in net.B[l]) + "};\n")
    f.write("static const signed char *WS[7]={W0,W1,W2,W3,W4,W5,W6};\nstatic const short *BS[7]={B0,B1,B2,B3,B4,B5,B6};\n")
    f.write("static const int SH[7]={" + ",".join(map(str, net.S)) + "};\nstatic const int SZ[8]={16,64,64,64,64,64,64,16};\n")
    tv = d["test_vectors"]
    f.write(f"#define NV {len(tv)}\nstatic const signed char TX[NV][16]={{" + ",".join("{" + ",".join(map(str, v['x'])) + "}" for v in tv) + "};\n")
    f.write("static const signed char TY[NV][16]={" + ",".join("{" + ",".join(map(str, v['y'])) + "}" for v in tv) + "};\n")
print("wrote net.h")
