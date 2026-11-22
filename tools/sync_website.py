"""Keep the website (git submodule website/) in step with the models in this repository.

    python tools/sync_website.py          show what would change
    python tools/sync_website.py --apply  copy the model files into the website

What it does
  1. Copies every NetSilcon-6x4 model file (models/<app>/*.json) into
     website/src/data/models/. The website's playground runs these files bit-exact,
     and `npm run check` in website/ verifies them.
  2. Prints the key facts of every model (CRC, test vectors, accuracy) and the
     NetSilcon-64x6 result summaries, so you can compare them with the numbers in
     website/src/data/facts.ts. Numbers on the site are written by hand on purpose:
     each carries a basis label (M measured, E estimated, T target).

After --apply:
  cd website && npm run check && git add -A && git commit -m "Sync models" && git push
  cd .. && git add website && git commit -m "Update website submodule"
"""
import argparse
import filecmp
import glob
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "NetSilcon-Models")
SITE = os.path.join(ROOT, "website")
SITE_MODELS = os.path.join(SITE, "src", "data", "models")


def model_facts(path):
    d = json.load(open(path, encoding="utf-8"))
    crc = d.get("crc32") or d.get("crc16") or "?"
    n = len(d.get("test_vectors") or d.get("tests") or [])
    acc = d.get("accuracy_int8")
    acc = f"{acc * 100:.1f} %" if isinstance(acc, (int, float)) and acc <= 1 else (acc or "-")
    return crc, n, acc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="copy the files (default: only show)")
    a = ap.parse_args()
    if not os.path.isdir(SITE_MODELS):
        raise SystemExit("website/ is empty. Run:  git submodule update --init")

    print("1. NetSilcon-6x4 model files -> website/src/data/models/")
    changes = 0
    for src in sorted(glob.glob(os.path.join(MODELS, "NetSilcon-6x4", "models", "**", "*.json"), recursive=True)):
        dst = os.path.join(SITE_MODELS, os.path.basename(src))
        state = "same" if os.path.exists(dst) and filecmp.cmp(src, dst, shallow=False) else ("new" if not os.path.exists(dst) else "CHANGED")
        if state != "same":
            changes += 1
            if a.apply:
                shutil.copy2(src, dst)
        print(f"   {os.path.basename(src):20s} {state}{' (copied)' if state != 'same' and a.apply else ''}")

    print("\n2. Model facts (compare with website/src/data/facts.ts)")
    for model_dir in sorted(glob.glob(os.path.join(MODELS, "NetSilcon-*"))):
        for p in sorted(glob.glob(os.path.join(model_dir, "models", "**", "*.json"), recursive=True)):
            crc, n, acc = model_facts(p)
            print(f"   {os.path.basename(model_dir):15s} {os.path.relpath(p, model_dir):38s} CRC {crc}  vectors {n:5d}  int8 accuracy {acc}")

    print("\n3. Result summaries")
    for p in sorted(glob.glob(os.path.join(MODELS, "*", "results", "*.txt"))):
        print(f"   {os.path.relpath(p, ROOT)}")

    if changes and not a.apply:
        print(f"\n{changes} model file(s) differ. Run again with --apply to copy them.")
    elif changes:
        print("\nCopied. Next: cd website && npm run check, commit and push, then commit the submodule pointer here.")
    else:
        print("\nModel files are in sync.")


if __name__ == "__main__":
    main()
