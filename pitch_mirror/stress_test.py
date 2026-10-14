"""Stress test on the graded bad-mirror spectrum made by make_spectrum.py.
Checks (1) the score drops as the flaw level rises, (2) injected flaw regions are caught (temporal hit rate).
Usage: python stress_test.py --baseline data/good_1.mp4"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8")  # emoji-safe on Windows consoles
except Exception:
    pass

import argparse
import json
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pitch_mirror import pipeline as P

ap = argparse.ArgumentParser()
ap.add_argument("--baseline", required=True)
ap.add_argument("--spectrum", default="dataset/spectrum")
a = ap.parse_args()
labels = json.loads((Path(a.spectrum) / "labels.json").read_text())
base = P.analyze_core(a.baseline, use_ai=False)
rows, hits = [], []
for name, lab in sorted(labels.items(), key=lambda kv: kv[1]["level"]):
    if lab["source"] != Path(a.baseline).name:
        continue
    r = P.analyze(Path(a.spectrum) / name, baseline=base, use_ai=False)
    rows.append({"file": name, "level": lab["level"], "overall": r["scores"]["overall"], "n_flaws": len(r["flaws"])})
    for g in lab["flaws"]:
        found = [f for f in r["flaws"] if f["type"] == g["type"] and f["start"] < g["end"] + 0.5 and f["end"] > g["start"] - 0.5]
        err = min((abs(f["start"] - g["start"]) for f in found), default=None)
        hits.append({"file": name, "level": lab["level"], "type": g["type"], "label_start": g["start"], "label_end": g["end"],
                     "detected": bool(found), "start_error_s": None if err is None else round(err, 2)})
    print(f"L{lab['level']} {name}: overall={r['scores']['overall']:.1f}, flaws={len(r['flaws'])}")
out = Path("eval_results"); out.mkdir(exist_ok=True)
tag = Path(a.baseline).stem  # one set of files per baseline, so running several baselines never overwrites
df, dh = pd.DataFrame(rows), pd.DataFrame(hits)
df.to_csv(out / f"stress_scores_{tag}.csv", index=False); dh.to_csv(out / f"stress_hits_{tag}.csv", index=False)
print(dh.to_string(index=False))
if len(dh):
    print("\nDetection rate by type:\n", dh.groupby("type")["detected"].mean().round(2).to_string())
plt.style.use("dark_background")
fig, ax = plt.subplots(figsize=(7, 3.6), facecolor="#0E0B16"); ax.set_facecolor("#141020")
base_score = P.analyze(a.baseline, use_ai=False)["scores"]["overall"]
ax.plot([0] + df["level"].tolist(), [base_score] + df["overall"].tolist(), "-o", color="#8B5CF6")
ax.set_xlabel("flaw level (0 = original good)"); ax.set_ylabel("overall score"); ax.set_ylim(0, 100)
ax.set_title("Score falls as injected flaws get worse", color="#E8E6F0"); fig.tight_layout(); fig.savefig(out / f"stress_gradient_{tag}.png", dpi=150)
