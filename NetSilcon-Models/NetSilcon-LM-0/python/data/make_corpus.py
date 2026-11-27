"""
NetSilcon-LM-0 corpus: short dialogues with one device (a water pump controller).

    q: is the pump running?
    a: yes, the pump is running.

SYNTHETIC: every line comes from the templates below with random values. The model
learns the language of the device (questions, answers, numbers, units). LM-0 has no
sensor inputs, so the numbers it says are made up; sensor inputs are the LM-2 step.

usage: python make_corpus.py   -> data/pump_train.txt, data/pump_test.txt
"""
import os, random

ALPHABET = "\n :,.?abcdefghijklmnopqrstuvwxyz0123456789"   # 42 symbols, index 0 = newline


def num(r, lo, hi):
    return str(r.randint(lo, hi))


def dialogue(r):
    on = r.random() < 0.5
    st = "running" if on else "stopped"
    topic = r.choice(["status", "status", "pressure", "flow", "tank", "temp", "start", "stop",
                      "fault", "schedule", "hello", "help", "name", "time"])
    if topic == "status":
        q = r.choice(["is the pump running?", "is the pump on?", "pump status?", "are you running?",
                      "what is your status?", "is the motor on?"])
        a = r.choice([f"yes, the pump is running." if on else "no, the pump is stopped.",
                      f"the pump is {st}.", f"status: {st}."])
    elif topic == "pressure":
        p = num(r, 1, 6)
        q = r.choice(["what is the pressure?", "pressure?", "how much pressure?", "tell me the pressure."])
        a = r.choice([f"the pressure is {p} bar.", f"pressure: {p} bar.", f"it is {p} bar now."])
    elif topic == "flow":
        f = num(r, 5, 60)
        q = r.choice(["what is the flow?", "flow rate?", "how much water is flowing?"])
        a = r.choice([f"the flow is {f} litres per minute.", f"flow: {f} litres per minute."])
    elif topic == "tank":
        t = num(r, 0, 100)
        q = r.choice(["how full is the tank?", "tank level?", "what is the tank level?", "is the tank full?"])
        a = r.choice([f"the tank is {t} percent full.", f"tank level: {t} percent."])
    elif topic == "temp":
        c = num(r, 20, 75)
        q = r.choice(["what is the motor temperature?", "motor temp?", "is the motor hot?"])
        a = r.choice([f"the motor is at {c} degrees.", f"motor temperature: {c} degrees."])
    elif topic == "start":
        q = r.choice(["start the pump.", "turn on the pump.", "please start.", "switch on the motor."])
        a = r.choice(["ok, starting the pump.", "the pump is already running." if on else "ok, the pump is on now."])
    elif topic == "stop":
        q = r.choice(["stop the pump.", "turn off the pump.", "please stop.", "switch off the motor."])
        a = r.choice(["ok, stopping the pump.", "the pump is already stopped." if not on else "ok, the pump is off now."])
    elif topic == "fault":
        q = r.choice(["any faults?", "is there a problem?", "why did you stop?", "are you ok?"])
        a = r.choice(["no faults. all is ok.", "dry run detected. please check the water.",
                      "high temperature. the motor needs rest.", "low voltage. please check the supply.",
                      "all is ok."])
    elif topic == "schedule":
        h = num(r, 5, 9); m = r.choice(["00", "15", "30", "45"]); d = num(r, 10, 60)
        q = r.choice(["when do you run next?", "next run?", "what is the schedule?"])
        a = r.choice([f"next run at {h}:{m} for {d} minutes.", f"i run at {h}:{m} every day."])
    elif topic == "hello":
        q = r.choice(["hello.", "hi.", "good morning.", "hello pump."])
        a = r.choice(["hello. how can i help?", "hi. ask me about the pump.", "good morning. the pump is " + st + "."])
    elif topic == "help":
        q = r.choice(["what can you do?", "help.", "what can i ask?"])
        a = r.choice(["ask me about pressure, flow, tank and faults.", "i can start, stop and report the pump."])
    elif topic == "name":
        q = r.choice(["who are you?", "what is your name?"])
        a = r.choice(["i am the pump controller.", "i am netsilcon, the pump brain."])
    else:
        h = num(r, 1, 12)
        q = r.choice(["how long did you run today?", "run time today?"])
        a = f"i ran for {h} hours today."
    return f"q: {q}\na: {a}\n"


def make(n, seed):
    r = random.Random(seed)
    return "".join(dialogue(r) for _ in range(n))


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    for name, n, seed in (("pump_train.txt", 12000, 1), ("pump_test.txt", 1500, 2)):
        txt = make(n, seed)
        assert set(txt) <= set(ALPHABET), set(txt) - set(ALPHABET)
        open(os.path.join(here, name), "w").write(txt)
        print(name, len(txt), "chars")
