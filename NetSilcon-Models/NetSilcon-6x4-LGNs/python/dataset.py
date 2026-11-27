"""
NetSilcon-6x4-LGNs  |  Exp-01 dataset: rover obstacle avoidance
4 corner distance sensors (8-bit, 0..255 cm): FL, FR, RL, RR
2 outputs:
  speed : 0=stop 1=slow 2=medium 3=fast            (4 classes, 2 bits)
  steer : 0=hard-left 1=left 2=straight 3=right 4=hard-right  (5 classes, 3 bits)

The "teacher" is a hand-written rule set (synthetic, documented here) so the
network has a ground truth to learn. Replace teacher() with real logged data later.
"""
import numpy as np

N_SPEED, N_STEER = 4, 5
SPEED_NAMES = ["stop", "slow", "medium", "fast"]
STEER_NAMES = ["hard-left", "left", "straight", "right", "hard-right"]


def teacher(s):
    """s: (N,4) int array [FL, FR, RL, RR] -> speed (N,), steer (N,)"""
    s = s.astype(np.int32)
    fl, fr, rl, rr = s[:, 0], s[:, 1], s[:, 2], s[:, 3]
    front = np.minimum(fl, fr)
    rear = np.minimum(rl, rr)

    speed = np.select([front < 30, front < 70, front < 130], [0, 1, 2], 3)
    # something very close behind and the way ahead is not blocked -> keep moving
    speed = np.where((rear < 20) & (front >= 30) & (speed < 2), 2, speed)

    d = fl - fr                      # >0 : more room on the left
    steer = np.select([d > 60, d > 20, d < -60, d < -20], [0, 1, 4, 3], 2)
    steer = np.where(front >= 150, 2, steer)          # open road -> straight
    return speed.astype(np.int64), steer.astype(np.int64)


def make(n, seed):
    rng = np.random.default_rng(seed)
    # mix of uniform and "close obstacle" heavy samples so every class appears
    a = rng.integers(0, 256, size=(n, 4))
    b = rng.integers(0, 160, size=(n, 4))
    pick = rng.random((n, 1)) < 0.5
    s = np.where(pick, a, b).astype(np.uint8)
    sp, st = teacher(s)
    return s, sp, st


# Thermometer encoding: bit k of sensor i = (s_i > T[k]). In hardware this is a
# constant comparator -> pure combinational logic, no storage.
THRESH = np.arange(8, 256, 8)          # 31 thresholds per sensor -> 124 input bits


def encode(s):
    s = s.astype(np.int32)
    bits = (s[:, :, None] > THRESH[None, None, :])     # (N,4,31)
    return bits.reshape(len(s), -1).astype(np.float32)  # order: sensor-major


if __name__ == "__main__":
    s, sp, st = make(20000, 1)
    print("speed class counts", np.bincount(sp, minlength=4))
    print("steer class counts", np.bincount(st, minlength=5))
