"""Evaluation: do good speeches score higher than bad ones, and are scores stable across reruns?
Usage:  python eval.py               (uses data/good_*.* and data/bad_*.*, 2 repeats)
        python eval.py --repeats 3 --baseline data/good_1.mp4
Outputs eval_results/results.csv, summary.json, separation.png"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8")  # emoji-safe on Windows consoles
except Exception:
    pass

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pitch_mirror import pipeline as P
from pitch_mirror.config import CACHE_DIR

ROOT = Path(__file__).parent
EXT = {".mp4", ".mov", ".webm", ".m4v", ".wav", ".mp3", ".m4a"}


def auroc(pos, neg):
    """Probability that a random good file scores higher than a random bad file (ties = 0.5)."""
    if not pos or not neg:
        return float("nan")
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--baseline", default=None, help="optional good recording of the same text")
    ap.add_argument("--no-ai", action="store_true", help="skip Gemini (saves API calls; scores do not use AI anyway)")
    a = ap.parse_args()
    d = Path(a.data)
    files = sorted(p for p in d.glob("*") if p.suffix.lower() in EXT and p.stem.split("_")[0] in ("good", "bad"))
    if not files:
        raise SystemExit(f"No good_*/bad_* files found in {d}. See README → Record your dataset.")
    base = P.analyze_core(a.baseline, use_ai=False) if a.baseline else None
    rows = []
    for rep in range(a.repeats):
        if rep > 0:  # clear cache so every repeat really re-runs the whole pipeline
            for p in CACHE_DIR.glob("core_*.json"):
                p.unlink()
            if base:
                base = P.analyze_core(a.baseline, use_ai=False)
        for f in files:
            if base and Path(a.baseline).resolve() == f.resolve():
                bl = None
            else:
                bl = base
            txt = f.with_suffix(".txt").read_text() if f.with_suffix(".txt").exists() else None
            r = P.analyze(f, baseline=bl, transcript_text=txt, use_ai=not a.no_ai)
            rows.append({"file": f.name, "label": f.stem.split("_")[0], "repeat": rep, "overall": r["scores"]["overall"],
                         "n_flaws": len(r["flaws"]), "wpm": r["global"]["wpm"], "fillers": r["global"]["filler_count"],
                         **{k: v for k, v in r["scores"]["dimensions"].items()}})
            print(f"[repeat {rep}] {f.name:20s} overall={r['scores']['overall']:.1f} flaws={len(r['flaws'])}")
    df = pd.DataFrame(rows)
    out = ROOT / "eval_results"; out.mkdir(exist_ok=True)
    df.to_csv(out / "results.csv", index=False)
    per_file = df.groupby(["file", "label"])["overall"].agg(["mean", "std"]).reset_index().fillna(0)
    good = per_file[per_file.label == "good"]["mean"].tolist()
    bad = per_file[per_file.label == "bad"]["mean"].tolist()
    s = {"n_files": len(files), "repeats": a.repeats,
         "good_mean": float(np.mean(good)) if good else None, "bad_mean": float(np.mean(bad)) if bad else None,
         "mean_gap": float(np.mean(good) - np.mean(bad)) if good and bad else float("nan"),
         "auroc": auroc(good, bad), "rerun_std_max": float(per_file["std"].max())}
    (out / "summary.json").write_text(json.dumps(s, indent=2))
    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(8, 4.2), facecolor="#0E0B16")
    ax.set_facecolor("#141020")
    for i, (lab, col) in enumerate([("good", "#8B5CF6"), ("bad", "#F43F5E")]):
        sub = df[df.label == lab]
        ax.scatter(sub["overall"], np.full(len(sub), i) + np.random.default_rng(0).uniform(-0.12, 0.12, len(sub)), s=70, color=col, alpha=0.85, label=lab)
    ax.set_yticks([0, 1]); ax.set_yticklabels(["ideal", "flawed"]); ax.set_xlim(0, 100); ax.set_xlabel("Overall score (0-100)")
    ax.set_title(f"Separation: gap {s['mean_gap']:.1f} pts · AUROC {s['auroc']:.2f} · rerun std ≤ {s['rerun_std_max']:.2f}", color="#E8E6F0")
    ax.legend(loc="lower right"); fig.tight_layout(); fig.savefig(out / "separation.png", dpi=150)
    print(json.dumps(s, indent=2))


if __name__ == "__main__":
    main()
