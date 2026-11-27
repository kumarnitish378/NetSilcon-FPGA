"""
Chat with NetSilcon-LM-0 on the Tang Nano 20K (115200 8N1), and check every answer
against the Python int8 model (they must be identical, character for character).

  python lm_chat.py --port COM5                 interactive: type questions
  python lm_chat.py --port COM5 --test          asks the 14 test questions, PASS/FAIL
Every run writes results/logs/hw_chat_<time>.log and .csv
(question, board answer, python answer, match, seconds from Enter to the last byte).
needs: pip install pyserial numpy
"""
import argparse, csv, json, os, sys, time
import serial
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "python", "model"))
import nslm

TEST = ["hello.", "is the pump running?", "what is the pressure?", "flow rate?", "how full is the tank?",
        "motor temp?", "start the pump.", "stop the pump.", "any faults?", "next run?",
        "what can you do?", "who are you?", "run time today?", "is the pump working?"]

ap = argparse.ArgumentParser()
ap.add_argument("--port", required=True)
ap.add_argument("--test", action="store_true")
ap.add_argument("--model", default=os.path.join(ROOT, "models", "pump", "pump.json"))
a = ap.parse_args()
lm = nslm.LM.from_json(json.load(open(a.model)))
os.makedirs(os.path.join(ROOT, "results", "logs"), exist_ok=True)
stamp = time.strftime("%Y%m%d_%H%M%S")
logf = open(os.path.join(ROOT, "results", "logs", f"hw_chat_{stamp}.log"), "w")
cw = csv.writer(open(os.path.join(ROOT, "results", "logs", f"hw_chat_{stamp}.csv"), "w", newline=""))
cw.writerow(["question", "board_answer", "python_answer", "match", "seconds"])
def log(s):
    print(s); logf.write(s + "\n"); logf.flush()

ser = serial.Serial(a.port, 115200, timeout=3)
time.sleep(0.2); ser.reset_input_buffer()
log(f"NetSilcon-LM-0 chat, port {a.port}, model CRC-32 {lm.crc32():08X}")
log("NOTE: the context lives on the board. Reprogram the board before --test so it starts blank.")
ctx = [0] * nslm.CTX


def ask(q):
    global ctx
    line = "".join(c for c in q.lower() if c in nslm.ALPHABET and c != "\n")
    t0 = time.time()
    ser.write((line + "\r").encode())
    echo = ser.read_until(b"\r\n").decode(errors="replace").strip()
    ans = ser.read_until(b"\r\n").decode(errors="replace").strip()
    dt = time.time() - t0
    exp, ctx = lm.generate(line + "\n", max_chars=63, ctx=ctx)
    exp = exp.strip()
    ok = (echo == line) and (ans == exp)
    log(f"q: {line}\n   board : {ans}\n   python: {exp}   {'MATCH' if ok else 'DIFFERENT'}   {dt*1000:.0f} ms")
    cw.writerow([line, ans, exp, int(ok), f"{dt:.4f}"])
    return ok


if a.test:
    n_ok = sum(ask(q) for q in TEST)
    log(f"RESULT hardware chat: {n_ok}/{len(TEST)} answers identical to the Python int8 model")
else:
    log("type a question (empty line to quit), e.g.  q: is the pump running?")
    while True:
        q = input("> ").strip()
        if not q: break
        ask(q)
