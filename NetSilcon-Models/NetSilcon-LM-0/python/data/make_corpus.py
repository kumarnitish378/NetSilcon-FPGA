"""
NetSilcon-LM-0 corpus v2: short dialogues with one device (a water pump controller).

    q: can you tell me the pressure?
    a: the pressure is 3 bar.

SYNTHETIC: every line comes from the templates below with random values. LM-0 has no sensor
inputs, so the numbers in the answers are random; sensor inputs are the LM-2 step.

v2 (more data, many more ways to ask):
  * every topic has many question cores, combined with openers ("hey, ", "pump, ",
    "can you tell me ...") and endings ("?", " now?", " please?")
  * HELD-OUT wordings: about 20 % of every topic's question cores (never a v1 wording) never
    appear in training.
    pump_unseen.txt asks only those, to measure if the model understands new wordings.
usage: python make_corpus.py -> pump_train.txt, pump_test.txt (seen wordings), pump_unseen.txt,
       wordings.json (which cores are seen / held out)
"""
import json, os, random

ALPHABET = "\n :,.?abcdefghijklmnopqrstuvwxyz0123456789"   # 42 symbols, index 0 = newline

# topic -> (question cores, answer function(rng, state)).  {x} marks nothing: cores are complete.
Q = {
 "status": ["is the pump running", "is the pump on", "pump status", "are you running", "what is your status",
            "is the motor on", "is the pump working", "are you on", "is the pump off", "are you working",
            "is the motor running", "status of the pump", "what is the pump doing", "is water pumping",
            "are you pumping", "is it running"],
 "pressure": ["what is the pressure", "pressure", "how much pressure", "tell me the pressure",
              "what is the water pressure", "line pressure", "current pressure", "pressure level",
              "how high is the pressure", "give me the pressure", "what pressure do you see", "pressure reading"],
 "flow": ["what is the flow", "flow rate", "how much water is flowing", "what is the flow rate", "water flow",
          "how fast is the water", "flow now", "how much water per minute", "current flow", "flow reading"],
 "tank": ["how full is the tank", "tank level", "what is the tank level", "is the tank full", "water level",
          "how much water is in the tank", "is the tank empty", "tank status", "level of the tank", "how full is it"],
 "temp": ["what is the motor temperature", "motor temp", "is the motor hot", "how hot is the motor",
          "temperature", "motor heat", "is the motor too hot", "what is the temperature", "motor temperature now",
          "how warm is the motor"],
 "start": ["start the pump", "turn on the pump", "start", "switch on the motor", "start pumping", "pump on",
           "turn it on", "switch on", "begin pumping", "run the pump", "start the motor", "power on"],
 "stop": ["stop the pump", "turn off the pump", "stop", "switch off the motor", "stop pumping", "pump off",
          "turn it off", "switch off", "halt the pump", "shut down the pump", "stop the motor", "power off"],
 "fault": ["any faults", "is there a problem", "why did you stop", "are you ok", "any errors", "is something wrong",
           "any alarm", "what is wrong", "any issue", "fault status", "are there any problems", "error check"],
 "schedule": ["when do you run next", "next run", "what is the schedule", "when is the next run", "schedule",
              "when will you start", "what time do you run", "next start time", "run schedule", "when do you pump"],
 "hello": ["hello", "hi", "good morning", "hello pump", "hi pump", "hey", "good evening", "namaste",
           "hey pump", "hello there", "good afternoon", "hi there"],
 "help": ["what can you do", "help", "what can i ask", "how can you help", "what do you know", "options",
          "what are your commands", "show help", "what can i say", "commands"],
 "name": ["who are you", "what is your name", "your name", "what are you", "tell me about you",
          "who am i talking to", "introduce yourself", "name please"],
 "time": ["how long did you run today", "run time today", "how many hours today", "running hours",
          "how long have you run", "today run time", "total run time today", "hours run today"],
}
COMMANDS = {"start", "stop", "hello", "help", "name"}
OPEN_Q = ["", "", "", "hey, ", "pump, ", "please tell me ", "can you tell me ", "tell me ", "ok, ", "so "]
OPEN_C = ["", "", "", "please ", "pump, ", "hey, ", "can you ", "now "]
END_Q = ["?", "?", "?", " now?", " please?", " today?", "."]
END_C = [".", ".", " now.", " please.", ""]


def ans(topic, r, on):
    n = lambda lo, hi: str(r.randint(lo, hi))
    st = "running" if on else "stopped"
    A = {
     "status": ["yes, the pump is running." if on else "no, the pump is stopped.", f"the pump is {st}.", f"status: {st}."],
     "pressure": [f"the pressure is {n(1,6)} bar.", f"pressure: {n(1,6)} bar.", f"it is {n(1,6)} bar now."],
     "flow": [f"the flow is {n(5,60)} litres per minute.", f"flow: {n(5,60)} litres per minute."],
     "tank": [f"the tank is {n(0,100)} percent full.", f"tank level: {n(0,100)} percent."],
     "temp": [f"the motor is at {n(20,75)} degrees.", f"motor temperature: {n(20,75)} degrees."],
     "start": ["ok, starting the pump.", "the pump is already running." if on else "ok, the pump is on now."],
     "stop": ["ok, stopping the pump.", "the pump is already stopped." if not on else "ok, the pump is off now."],
     "fault": ["no faults. all is ok.", "dry run detected. please check the water.", "high temperature. the motor needs rest.",
               "low voltage. please check the supply.", "all is ok."],
     "schedule": [f"next run at {n(5,9)}:{r.choice(['00','15','30','45'])} for {n(10,60)} minutes.",
                  f"i run at {n(5,9)}:{r.choice(['00','15','30','45'])} every day."],
     "hello": ["hello. how can i help?", "hi. ask me about the pump.", f"hello. the pump is {st}."],
     "help": ["ask me about pressure, flow, tank and faults.", "i can start, stop and report the pump."],
     "name": ["i am the pump controller.", "i am netsilcon, the pump brain."],
     "time": [f"i ran for {n(1,12)} hours today."],
    }
    return r.choice(A[topic])


# grader: which answers are correct for which topic (used by train_lm.py)
ANSWER_PATTERNS = {
 "status": r"^a: (yes, the pump is running\.|no, the pump is stopped\.|the pump is (running|stopped)\.|status: (running|stopped)\.)$",
 "pressure": r"^a: (the pressure is \d bar\.|pressure: \d bar\.|it is \d bar now\.)$",
 "flow": r"^a: (the flow is \d+ litres per minute\.|flow: \d+ litres per minute\.)$",
 "tank": r"^a: (the tank is \d+ percent full\.|tank level: \d+ percent\.)$",
 "temp": r"^a: (the motor is at \d+ degrees\.|motor temperature: \d+ degrees\.)$",
 "start": r"^a: (ok, starting the pump\.|the pump is already running\.|ok, the pump is on now\.)$",
 "stop": r"^a: (ok, stopping the pump\.|the pump is already stopped\.|ok, the pump is off now\.)$",
 "fault": r"^a: (no faults\. all is ok\.|dry run detected\. please check the water\.|high temperature\. the motor needs rest\.|low voltage\. please check the supply\.|all is ok\.)$",
 "schedule": r"^a: (next run at \d:\d\d for \d+ minutes\.|i run at \d:\d\d every day\.)$",
 "hello": r"^a: (hello\. how can i help\?|hi\. ask me about the pump\.|hello\. the pump is (running|stopped)\.)$",
 "help": r"^a: (ask me about pressure, flow, tank and faults\.|i can start, stop and report the pump\.)$",
 "name": r"^a: (i am the pump controller\.|i am netsilcon, the pump brain\.)$",
 "time": r"^a: i ran for \d+ hours today\.$",
}


# the first V1N[t] cores of every topic are the v1 corpus wordings: always trained on
V1N = {"status": 6, "pressure": 4, "flow": 3, "tank": 4, "temp": 3, "start": 4, "stop": 4, "fault": 4,
       "schedule": 3, "hello": 4, "help": 3, "name": 2, "time": 2}


def split_cores(seed=123):
    """hold out about 20 % of each topic's cores, chosen only from the new (non-v1) wordings"""
    r = random.Random(seed); seen, held = {}, {}
    for t, cores in Q.items():
        base, extra = cores[:V1N[t]], cores[V1N[t]:]
        c = extra[:]; r.shuffle(c); k = max(1, round(0.2 * len(cores)))
        held[t], seen[t] = sorted(c[:k]), sorted(base + c[k:])
    return seen, held


def question(r, topic, cores):
    core = r.choice(cores)
    if topic in COMMANDS:
        return r.choice(OPEN_C) + core + r.choice(END_C)
    return r.choice(OPEN_Q) + core + r.choice(END_Q)


def make(n, seed, cores):
    r = random.Random(seed); out = []
    topics = list(Q)
    for _ in range(n):
        t = r.choice(topics); on = r.random() < 0.5
        out.append(f"q: {question(r, t, cores[t])}\na: {ans(t, r, on)}\n")
    return "".join(out)


def graded_questions(cores, n, seed):
    """list of (topic, question) for the grader"""
    r = random.Random(seed); topics = list(Q)
    return [(t, question(r, t, cores[t])) for t in (topics[i % len(topics)] for i in range(n))]


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    seen, held = split_cores()
    for name, n, seed, cores in (("pump_train.txt", 50000, 1, seen), ("pump_test.txt", 3000, 2, seen),
                                 ("pump_unseen.txt", 3000, 3, held)):
        txt = make(n, seed, cores)
        assert set(txt) <= set(ALPHABET), set(txt) - set(ALPHABET)
        open(os.path.join(here, name), "w").write(txt)
        print(name, len(txt), "chars")
    json.dump({"seen": seen, "held_out": held}, open(os.path.join(here, "wordings.json"), "w"), indent=1)
    print("held-out question cores:", sum(len(v) for v in held.values()), "of", sum(len(v) for v in Q.values()))
