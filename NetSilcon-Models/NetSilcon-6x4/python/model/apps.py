"""Applications for the NetSilcon-6x4 chip.

Every app uses the SAME network shape (4 inputs -> 6 -> 6 -> 6 -> 6 -> 2 outputs).
Only the numbers (weights, biases, shifts) change. Each app defines:
  inputs   : name, unit, range  (the chip sees q = round(value / range * 127), 0..127)
  outputs  : labels for y0 and y1.  Decision = outputs[1] if y1 > y0 else outputs[0]
  make(n, seed) -> (X real units, label 0/1)
  demo     : scenarios shown by  netsilcon_host.py --demo

To add your own job: copy IRRIGATION, change the inputs, the rules in make()
and the demo, then run  python make_model.py <name>.
"""
import os

import numpy as np
import data as motor_data

# --------------------------------------------------------------------------- 1. motor fault
MOTOR = dict(
    name="motor_fault",
    title="BLDC motor fault detector",
    inputs=[dict(name="current", unit="A", range=20.0), dict(name="voltage", unit="V", range=30.0),
            dict(name="speed", unit="rpm", range=6000.0), dict(name="temp", unit="C", range=120.0)],
    outputs=["HEALTHY", "FAULT"],
    make=motor_data.make,
    demo=[
        dict(title="Cooling failure: 10 A, 24 V, 3500 rpm, temperature rising",
             rows=[[10, 24, 3500, t] for t in range(50, 121, 10)]),
        dict(title="Supply sag: 8 A at 65 C, voltage dropping",
             rows=[[8, v, round(3800 * v / 24, 2), 65] for v in (24, 22, 20, 18, 16, 14)]),
        dict(title="Mechanical bind: 10 A, 24 V, 65 C, speed collapsing",
             rows=[[10, 24, r, 65] for r in (3500, 3000, 2500, 2000, 1500)]),
    ],
)


# --------------------------------------------------------------------------- 2. smart irrigation
def irrigation_make(n, seed=0):
    """Water the field or not?

    Inputs: soil moisture [%], air temperature [C], air humidity [%], sunlight [%]
    WATER when the soil is drier than what the weather needs:
        threshold = 35 + 0.6*(temp-25) - 0.15*(humidity-50) + 0.08*(sun-50)   [% moisture]
    but WAIT (skip) even if dry, unless the soil is critically dry (< 15 %):
        - harsh midday sun (sun > 75 % and temp > 30 C): water evaporates, water in the evening
        - humidity > 90 %: rain is falling or about to
    """
    rng = np.random.default_rng(seed)
    soil = rng.uniform(0, 100, n)
    temp = rng.uniform(5, 48, n)
    hum = rng.uniform(10, 100, n)
    sun = rng.uniform(0, 100, n)
    # 20 % of samples: dry soil in the tricky "wait" weather, so the network learns those edges
    k = rng.random(n) < 0.2
    soil[k] = rng.uniform(0, 45, k.sum())
    noon = k & (rng.random(n) < 0.6)
    sun[noon] = rng.uniform(65, 100, noon.sum()); temp[noon] = rng.uniform(25, 48, noon.sum())
    rain = k & ~noon
    hum[rain] = rng.uniform(80, 100, rain.sum())
    thr = 35 + 0.6 * (temp - 25) - 0.15 * (hum - 50) + 0.08 * (sun - 50)
    water = soil < thr
    wait = ((sun > 75) & (temp > 30)) | (hum > 90)
    water = np.where(wait & (soil >= 15), False, water)
    X = np.stack([soil, temp, hum, sun], axis=1)
    return X, water.astype(int)


IRRIGATION = dict(
    name="irrigation",
    title="Smart irrigation controller",
    inputs=[dict(name="soil", unit="%", range=100.0), dict(name="air_temp", unit="C", range=50.0),
            dict(name="humidity", unit="%", range=100.0), dict(name="sunlight", unit="%", range=100.0)],
    outputs=["SKIP", "WATER"],
    make=irrigation_make,
    demo=[
        dict(title="Evening, 28 C, 50 % humidity, 10 % sun: soil drying out",
             rows=[[m, 28, 50, 10] for m in (70, 60, 50, 40, 35, 30, 20, 10)]),
        dict(title="Dry soil (25 %) through the day: sunlight rising, 35 C",
             rows=[[25, 35, 40, s] for s in (0, 20, 40, 60, 80, 100)]),
        dict(title="Dry soil (25 %), 26 C, 30 % sun: humidity rising (rain coming)",
             rows=[[25, 26, h, 30] for h in (40, 60, 80, 88, 92, 98)]),
        dict(title="Critically dry soil (8 %) at harsh noon, 40 C, 95 % sun",
             rows=[[8, 40, 30, 95]]),
    ],
)

# --------------------------------------------------------------------------- 3. rover driver
# 4 single-point LiDARs (TFmini-S / TF-Luna), mounted at the corners:
#   FL, FR look FORWARD (one at each edge of the body), RL, RR look BACKWARD.
# Outputs are continuous (regression), -1..+1 -> chip value = round(v * 127):
#   y0 speed    : -1 full reverse ... 0 stop ... +1 full forward
#   y1 steering : -1 full left    ... 0 straight ... +1 full right
ROVER_CLEAR = 4.0       # m, readings >= this mean "nothing in range"
ROVER_BLOCK = 0.6       # m, front closer than this -> do not drive forward
ROVER_SLOW = 2.0        # m, front distance at which full speed is allowed


def rover_targets(X):
    """The driving rules, version 2 (what the network must learn). X: (n, 4) metres FL, FR, RL, RR.
    All rules are smooth ramps (no sudden jumps): a small network can learn them and
    the robot drives smoothly instead of jerking between modes.

    1. SPEED follows the usable space ahead. If one front side is clearly more open, that
       side counts too, because the robot is about to turn into it:
         front = min(FL, FR) + 0.5 x (|FL - FR| - 0.2), the extra part limited to 0..0.5 m
         front >= 2.0 m : +1.0 (full forward)      front 0.6 m : +0.15 (creep)
         front 0.45 m   :  0   (stop)              front <= 0.3 m : -0.4 (reverse)
       Reversing is scaled by the room behind, rear = min(RL, RR):
         rear >= 0.6 m : full reverse ... rear <= 0.25 m : 0 (boxed in -> STOP)
    2. SIDE to go to: +1 right ... -1 left, from FR - FL. Small bias to the right,
       so a wall straight ahead (FL = FR) is passed on the right ("keep right").
    3. STEERING = side x strength x direction of travel
         strength: 0 when the closest front reading is >= 2.5 m ... 1.0 (full lock) at <= 0.6 m
         direction: +1 forward, -1 reverse (Ackermann 3-point turn: backing with the
         wheels left swings the nose right), 0 when stopped
    Fixed logic outside the network: predictive safety stop and the 3-point-turn supervisor.
    """
    FL, FR, RL, RR = X[:, 0], X[:, 1], X[:, 2], X[:, 3]
    close = np.minimum(FL, FR)
    front = close + 0.5 * np.clip(np.abs(FL - FR) - 0.2, 0, 1.0)
    rear = np.minimum(RL, RR)
    speed = np.interp(front, [0.3, 0.45, ROVER_BLOCK, ROVER_SLOW], [-0.4, 0.0, 0.15, 1.0])
    rear_room = np.clip((rear - 0.25) / 0.35, 0, 1)
    speed = np.where(speed < 0, speed * rear_room, speed)
    side = np.clip((FR - FL + 0.1) / 0.3, -1, 1)
    strength = np.clip((2.5 - close) / (2.5 - ROVER_BLOCK), 0, 1)
    direction = np.clip(speed / 0.15, -1, 1)
    steer = side * strength * direction
    return np.stack([speed, steer], axis=1)


ROVER_STATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rover_sim", "visited_states.npy")


def rover_make(n, seed=0):
    rng = np.random.default_rng(seed)
    # distances: half spread over the whole range, half concentrated near the robot
    X = np.where(rng.random((n, 4)) < 0.5, rng.uniform(0, ROVER_CLEAR, (n, 4)),
                 rng.uniform(0, 1.5, (n, 4)))
    # 15 %: open space on that sensor (no target -> reads "clear")
    X = np.where(rng.random((n, 4)) < 0.15, ROVER_CLEAR, X)
    # 15 %: wall straight ahead (FL and FR almost equal)
    w = rng.random(n) < 0.15
    X[w, 1] = np.clip(X[w, 0] + rng.normal(0, 0.05, w.sum()), 0, ROVER_CLEAR)
    # 40 %: real situations the robot met in the simulator (rover_sim.py --collect), if available
    if os.path.exists(ROVER_STATES) and seed != 2:          # seed 2 = test set stays synthetic
        V = np.load(ROVER_STATES)
        k = int(0.4 * n)
        X[:k] = V[rng.integers(0, len(V), k)]
    X = np.clip(X, 0, ROVER_CLEAR)
    return X, rover_targets(X)


ROVER = dict(
    name="rover",
    title="Rover driver v2 (speed + steering)",
    kind="regression",
    inputs=[dict(name="FL", unit="m", range=ROVER_CLEAR), dict(name="FR", unit="m", range=ROVER_CLEAR),
            dict(name="RL", unit="m", range=ROVER_CLEAR), dict(name="RR", unit="m", range=ROVER_CLEAR)],
    outputs=["speed", "steering"],
    make=rover_make,
    targets=rover_targets,
    demo=[
        dict(title="Open space, then a wall slowly getting closer (straight ahead)",
             rows=[[d, d, 4, 4] for d in (4, 3, 2, 1.5, 1.0, 0.8, 0.6, 0.5, 0.4)]),
        dict(title="Obstacle on the LEFT half of the path, getting closer (right side open)",
             rows=[[d, 4, 4, 4] for d in (3, 2, 1.5, 1.0, 0.7)]),
        dict(title="Obstacle on the RIGHT half of the path, getting closer (left side open)",
             rows=[[4, d, 4, 4] for d in (3, 2, 1.5, 1.0, 0.7)]),
        dict(title="Dead end: front blocked, rear clear -> back out (3-point turn)",
             rows=[[0.4, 0.5, 2, 2], [0.5, 0.3, 2, 2], [0.4, 0.4, 1.0, 1.0]]),
        dict(title="Boxed in: front and rear blocked -> stop",
             rows=[[0.4, 0.4, 0.4, 0.4], [0.3, 0.5, 0.5, 0.3]]),
    ],
)

APPS = {a["name"]: a for a in (MOTOR, IRRIGATION, ROVER)}
