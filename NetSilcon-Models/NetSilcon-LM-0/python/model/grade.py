"""
Answer grader for LM-0: does the model give a correct answer for the question's topic?

For each graded question the int8 model starts from a blank context (as a freshly programmed
board), generates greedily, and the answer must match the topic's answer pattern exactly
(e.g. "a: the pressure is 3 bar." for a pressure question). Numbers can be any value.

  seen   : questions built from the wordings used in training (new random combinations)
  unseen : questions built only from HELD-OUT wordings the model never saw

usage: python grade.py [model.json]   -> prints scores per topic
"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "python", "data"))
import nslm
import make_corpus as C


def grade(lm, n=260, seed=50):
    w = json.load(open(os.path.join(ROOT, "python", "data", "wordings.json")))
    res = {}
    for kind, cores in (("seen", w["seen"]), ("unseen", w["held_out"])):
        qs = C.graded_questions(cores, n, seed)
        per, fails = {}, []
        for topic, q in qs:
            a, _ = lm.generate(f"q: {q}\n", max_chars=63)
            ok = re.match(C.ANSWER_PATTERNS[topic], a.rstrip("\n")) is not None
            per.setdefault(topic, [0, 0]); per[topic][0] += ok; per[topic][1] += 1
            if not ok: fails.append((topic, q, a.rstrip("\n")))
        tot = sum(v[0] for v in per.values())
        res[kind] = dict(correct=tot, total=len(qs), per_topic=per, fails=fails)
    return res


def report(res, log=print):
    for kind in ("seen", "unseen"):
        r = res[kind]
        log(f"  {kind:6s} wordings: {r['correct']}/{r['total']} answers correct ({100*r['correct']/r['total']:.1f} %)  "
            + "  ".join(f"{t} {c}/{n}" for t, (c, n) in r["per_topic"].items()))


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "models", "pump", "pump.json")
    lm = nslm.LM.from_json(json.load(open(path)))
    res = grade(lm); report(res)
    for f in res["unseen"]["fails"][:8]: print("   unseen fail:", f)
