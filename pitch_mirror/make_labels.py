"""Build dataset/labels.csv (one row per flaw region) and dataset/manifest.csv (one row per clip).

Self-recorded takes: the injection plan (dataset/plan.json) says WHICH sentences carry each flaw.
Whisper word timestamps say WHEN those sentences start and end in the take, so every region is
snapped to word boundaries (label_method = plan_word_aligned; spot-check a few in Audacity).
Synthetic takes: copied from dataset/spectrum/labels.json (label_method = injected_exact).
Labels never use the detector's output, only the plan and the word timings.

Usage:  py -3.12 make_labels.py"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8")  # emoji-safe on Windows consoles
except Exception:
    pass

import csv
import difflib
import hashlib
import json
from pathlib import Path

import soundfile as sf

from pitch_mirror import pipeline as P
from pitch_mirror.transcribe import norm

ROOT = Path(__file__).parent
DATASET = ROOT / "dataset"
PLAN = json.loads((DATASET / "plan.json").read_text(encoding="utf-8"))
SOURCES = {
    "good_moon_jfk": {"speaker": "jfk", "excerpt": "8:21.2-9:14.0", "licence": "Public domain (US federal government work)",
                      "url": "https://commons.wikimedia.org/wiki/File:Jfk_rice_university_we_choose_to_go_to_the_moon.ogg"},
    "good_challenger_reagan": {"speaker": "reagan", "excerpt": "1:35.1-2:22.3", "licence": "Public domain (US federal government work)",
                               "url": "https://commons.wikimedia.org/wiki/File:Ronald_Reagan_speaks_on_the_Challenger_Space_Shuttle_Disaster.ogg"},
}
RETRIEVED = "2026-10-14"
LABEL_COLS = ["clip_id", "script_id", "speaker_id", "source_type", "level", "flaw_type", "start_s", "end_s",
              "label_method", "labeler", "notes"]
MANIFEST_COLS = ["clip_id", "file", "script_id", "speaker_id", "source_type", "level", "duration_s", "sha256",
                 "source_url", "excerpt", "retrieved", "licence", "consent"]


def sentence_ranges(script):
    """Index range of each sentence inside the normalised script word list, e.g. sentence 3 -> (14, 23)."""
    out, i = {}, 0
    for n, s in enumerate(PLAN["scripts"][script]["sentences"], 1):
        k = len([w for w in s.split() if norm(w)])
        out[n] = (i, i + k)
        i += k
    return out


def match_words(words, script):
    """Map each script word index to the position of the same word in the take (difflib alignment)."""
    ref = [norm(w) for w in " ".join(PLAN["scripts"][script]["sentences"]).split() if norm(w)]
    hyp = [norm(w["w"]) for w in words]
    m = {}
    for a, b, size in difflib.SequenceMatcher(a=ref, b=hyp, autojunk=False).get_matching_blocks():
        for k in range(size):
            m[a + k] = b + k
    return ref, m


def take_regions(path, script, take):
    words = P.analyze_core(path, use_ai=False)["words"]
    ref, m = match_words(words, script)
    rng = sentence_ranges(script)
    rows = []
    for flaw in PLAN["takes"][take]["flaws"]:
        for n1, n2 in _sentence_spans(flaw.get("sentences", {}).get(script, [])):
            # region = every spoken word between the previous sentence's last matched word and the next
            # sentence's first matched word, so fillers inserted at the edges are included
            before = [m[i] for i in range(0, rng[n1][0]) if i in m]
            after = [m[i] for i in range(rng[n2][1], len(ref)) if i in m]
            j0 = before[-1] + 1 if before else 0
            j1 = after[0] - 1 if after else len(words) - 1
            if j0 > j1:
                continue
            rows.append((flaw["type"], words[j0]["start"], words[j1]["end"], f"sentences {n1}-{n2}" if n2 > n1 else f"sentence {n1}"))
        for n, word in flaw.get("after", {}).get(script, []):
            i0, i1 = rng[n]
            idx = next(i for i in range(i0, i1) if ref[i] == norm(word))
            if idx in m and m[idx] + 1 < len(words):
                # the pause = silence between that word and whatever was said right after it
                a, b = words[m[idx]]["end"], words[m[idx] + 1]["start"]
                note = f"after '{word}' in sentence {n}" + ("" if b - a >= 1.0 else f" (only {b - a:.1f}s, shorter than planned)")
                rows.append((flaw["type"], a, b, note))
    return rows


def _sentence_spans(ns):
    """[3, 4, 5, 9] -> [(3, 5), (9, 9)]: consecutive sentences become one region."""
    spans = []
    for n in sorted(ns):
        if spans and n == spans[-1][1] + 1:
            spans[-1] = (spans[-1][0], n)
        else:
            spans.append((n, n))
    return spans


def manifest_row(path, script, speaker, source_type, level, url="", excerpt="", licence="", consent=""):
    return {"clip_id": path.stem, "file": path.relative_to(DATASET).as_posix(), "script_id": script, "speaker_id": speaker,
            "source_type": source_type, "level": level, "duration_s": round(sf.info(path).duration, 2),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "source_url": url, "excerpt": excerpt,
            "retrieved": RETRIEVED if url else "", "licence": licence, "consent": consent}


def main():
    labels, manifest = [], []
    me = PLAN["speaker"]
    for script, info in PLAN["scripts"].items():
        base = DATASET / script / info["baseline"]
        src = SOURCES[base.stem]
        manifest.append(manifest_row(base, script, src["speaker"], "external_baseline", 0, src["url"], src["excerpt"],
                                     src["licence"], "n/a (public-domain recording)"))
        for take, t in PLAN["takes"].items():
            name = f"good_{script}_{me}" if t["level"] == 0 else f"bad_{script}_{me}_L{t['level']}_{take}"
            path = DATASET / script / f"{name}.wav"
            if not path.exists():
                print(f"⬜ missing {path.relative_to(ROOT)} (record it with: py -3.12 record_take.py {script} {take})")
                continue
            manifest.append(manifest_row(path, script, me, "self_baseline" if t["level"] == 0 else "self_flawed",
                                         t["level"], licence="CC BY 4.0", consent="yes (see dataset/README.md)"))
            for ftype, a, b, note in take_regions(path, script, take):
                labels.append({"clip_id": name, "script_id": script, "speaker_id": me, "source_type": "self_flawed",
                               "level": t["level"], "flaw_type": ftype, "start_s": f"{a:.2f}", "end_s": f"{b:.2f}",
                               "label_method": "plan_word_aligned", "labeler": me, "notes": note})
            print(f"✅ {name}")

    spec = DATASET / "spectrum"
    synth = json.loads((spec / "labels.json").read_text()) if (spec / "labels.json").exists() else {}
    for fname, info in synth.items():
        path = spec / fname
        stem = Path(info["source"]).stem  # e.g. good_moon_jfk
        script, speaker = stem.split("_")[1], stem.split("_")[2]
        src = SOURCES.get(stem, {})
        manifest.append(manifest_row(path, script, speaker, "synthetic", info["level"], licence=src.get("licence", "CC BY 4.0"),
                                     consent="n/a (derived)" if src else "yes (see dataset/README.md)"))
        for f in info["flaws"]:
            labels.append({"clip_id": path.stem, "script_id": script, "speaker_id": speaker, "source_type": "synthetic",
                           "level": info["level"], "flaw_type": f["type"], "start_s": f"{f['start']:.2f}", "end_s": f"{f['end']:.2f}",
                           "label_method": "injected_exact", "labeler": "make_spectrum.py", "notes": f.get("detail", "")})

    for name, cols, rows in (("labels.csv", LABEL_COLS, labels), ("manifest.csv", MANIFEST_COLS, manifest)):
        with open(DATASET / name, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        print(f"wrote dataset/{name} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
