"""
A/B link test with the NetSilcon-6x4 bitstream (its 5-byte replies), to find out whether
the UART errors seen with NetSilcon-64x6 come from the 64x6 design or from the board / USB
bridge / PC. Same method as  ns64_host.py --linktest : the same request N times, no retries,
every reply must be identical.

    1. Program C:\\fpga\\gowin\\netsilcon\\impl\\pnr\\netsilcon.fs  (6x4, top tangnano20k_uart)
    2. python linktest_6x4.py COM7 2000

Writes logs/<date_time>_linktest6x4.log and .csv (in the NetSilcon-64x6 folder).
"""
import csv
import datetime
import os
import platform
import sys
import time

import serial

HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(HERE, "..", "logs")


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM7"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
    os.makedirs(LOGS, exist_ok=True)
    base = os.path.join(LOGS, datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + "_linktest6x4")
    lf = open(base + ".log", "w", encoding="utf-8")
    cf = open(base + ".csv", "w", newline="", encoding="utf-8")
    w = csv.writer(cf)
    w.writerow(["kind", "index", "bytes", "reply_hex", "ok"])

    def log(s):
        print(s)
        lf.write(s + "\n")
        lf.flush()

    log(f"NetSilcon-6x4 link test  {datetime.datetime.now().isoformat(timespec='seconds')}  port {port}  "
        f"Python {platform.python_version()}  pyserial {serial.VERSION}  {platform.platform()}")
    s = serial.Serial(port, 115200, timeout=0.2)
    time.sleep(0.05)
    s.reset_input_buffer()
    total = 0
    for kind, req in (("info", b"\xC5"), ("inference", bytes([0xA5, 64, 64, 64, 64]))):
        ref, bad, short, t0 = None, 0, 0, time.perf_counter()
        for k in range(n):
            s.write(req)
            r = s.read(5)
            if ref is None and len(r) == 5:
                ref = r
            ok = r == ref
            if not ok:
                bad += 1
                short += len(r) < 5
                if bad <= 10:
                    log(f"  {kind} #{k}: {len(r)} bytes {r.hex(' ')}   expected {ref.hex(' ') if ref else '?'}")
                time.sleep(0.05)
                s.reset_input_buffer()
            w.writerow([kind, k, len(r), r.hex(), int(ok)])
        total += bad
        log(f"{kind}: {n} replies of 5 bytes, {bad} damaged ({short} short) = {bad / n * 100:.2f} %, "
            f"{bad / (n * 5) * 1e6:.0f} per million bytes; reference {ref.hex(' ') if ref else '?'}; "
            f"{time.perf_counter() - t0:.1f} s")
    log(f"RESULT: {'PASS (no damaged replies)' if total == 0 else 'LINK ERRORS SEEN'}")
    log(f"log files: {base}.log and .csv")
    lf.close()
    cf.close()


if __name__ == "__main__":
    main()
