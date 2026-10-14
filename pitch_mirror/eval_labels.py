"""Timestamp accuracy against the labels (PRD FR-E3).

For every labelled flaw region in dataset/labels.csv, take the detections of the SAME type that overlap it
(±0.5 s tolerance), merge them into one span, and measure start error, end error and IoU.
Self-recorded takes are compared against their script's external baseline; synthetic takes against
the recording they were generated from.

Usage:  py -3.12 eval_labels.py
Writes eval_results/label_timing.csv (one row per label) and label_timing_summary.csv (per type)."""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8")  # emoji-safe on Windows consoles
except Exception:
    pass

import csv
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

from pitch_mirror import pipeline as P

ROOT = Path(__file__).parent
DATASET = ROOT / "dataset"
OUT = ROOT / "eval_results"
PLAN = json.loads((DATASET / "plan.json").read_text(encoding="utf-8"))
TOL = 0.5


def main():
    labels = list(csv.DictReader(open(DATASET / "labels.csv", encoding="utf-8")))
    files = {r["clip_id"]: DATASET / r["file"] for r in csv.DictReader(open(DATASET / "manifest.csv", encoding="utf-8"))}
    synth = json.loads((DATASET / "spectrum" / "labels.json").read_text())
    by_clip = defaultdict(list)
    for lab in labels:
        by_clip[lab["clip_id"]].append(lab)

    bases, rows = {}, []
    for clip, labs in by_clip.items():
        path, script = files[clip], labs[0]["script_id"]
        if labs[0]["source_type"] == "synthetic":
            base_path, txt = DATASET / script / synth[path.name]["source"], None
        else:
            base_path, txt = DATASET / script / PLAN["scripts"][script]["baseline"], (DATASET / script / "script.txt").read_text(encoding="utf-8")
        if base_path not in bases:
            bases[base_path] = P.analyze_core(base_path, use_ai=False)
        flaws = P.analyze(path, baseline=bases[base_path], transcript_text=txt, use_ai=False)["flaws"]
        for lab in labs:
            a, b = float(lab["start_s"]), float(lab["end_s"])
            hit = [f for f in flaws if f["type"] == lab["flaw_type"] and f["start"] < b + TOL and f["end"] > a - TOL]
            row = {"clip_id": clip, "source_type": lab["source_type"], "level": lab["level"], "flaw_type": lab["flaw_type"],
                   "label_start": a, "label_end": b, "detected": bool(hit)}
            if hit:
                ds, de = min(f["start"] for f in hit), max(f["end"] for f in hit)
                inter = max(0.0, min(b, de) - max(a, ds))
                union = max(b, de) - min(a, ds)
                row.update(det_start=round(ds, 2), det_end=round(de, 2), start_error_s=round(abs(ds - a), 2),
                           end_error_s=round(abs(de - b), 2), iou=round(inter / union, 3) if union > 0 else 1.0)
            rows.append(row)
        print(f"{clip}: {sum(r['detected'] for r in rows if r['clip_id'] == clip)}/{len(labs)} labelled flaws detected")

    OUT.mkdir(exist_ok=True)
    df = pd.DataFrame(rows).reindex(columns=["clip_id", "source_type", "level", "flaw_type", "label_start", "label_end", "detected",
                                             "det_start", "det_end", "start_error_s", "end_error_s", "iou"])
    df.to_csv(OUT / "label_timing.csv", index=False)
    summary = df.groupby(["source_type", "flaw_type"]).agg(
        n=("detected", "size"), detection_rate=("detected", "mean"), median_start_error_s=("start_error_s", "median"),
        median_end_error_s=("end_error_s", "median"), median_iou=("iou", "median")).round(2).reset_index()
    summary.to_csv(OUT / "label_timing_summary.csv", index=False)
    print("\n" + summary.to_string(index=False))


if __name__ == "__main__":
    main()
