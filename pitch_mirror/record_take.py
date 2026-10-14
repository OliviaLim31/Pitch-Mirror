"""Record one dataset take straight into the right file: dataset/<script>/<name>.wav (16 kHz mono).

Usage (from the pitch_mirror folder):
    py -3.12 record_take.py                  # checklist: which takes are done, which are left
    py -3.12 record_take.py moon best        # your best take of the "moon" script
    py -3.12 record_take.py moon rushed      # a flawed take; where to put the flaw comes from dataset/plan.json
Press Enter to start, stay silent during the 3-second count-in, read the script, then press Enter to stop.
Recording the same take again replaces the old file."""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8")  # emoji-safe on Windows consoles
except Exception:
    pass

import json
import math
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from scipy.signal import resample_poly

ROOT = Path(__file__).parent
DATASET = ROOT / "dataset"
PLAN = json.loads((DATASET / "plan.json").read_text(encoding="utf-8"))
SR_OUT = 16000
LEAD_IN = 3  # seconds of silence at the start (recording protocol, PRD §6.3)
TAG = {"pace_fast": "RUSH", "monotone": "FLAT", "low_energy": "QUIET", "filler": "UM"}


def take_name(script, take):
    level = PLAN["takes"][take]["level"]
    if level == 0:
        return f"good_{script}_{PLAN['speaker']}"
    return f"bad_{script}_{PLAN['speaker']}_L{level}_{take}"


def take_path(script, take):
    return DATASET / script / f"{take_name(script, take)}.wav"


def show_script(script, take):
    """Print the script with the sentences to flaw marked, e.g. '>> [RUSH]' and a ⏸ where to freeze."""
    tags, pauses = {}, set()
    for f in PLAN["takes"][take]["flaws"]:
        for n in f.get("sentences", {}).get(script, []):
            tags.setdefault(n, []).append(TAG[f["type"]])
        for n, word in f.get("after", {}).get(script, []):
            pauses.add((n, word))
    print(f"\n{'═' * 70}\n  {script.upper()} · {take} (level {PLAN['takes'][take]['level']})\n  {PLAN['takes'][take]['how']}\n{'═' * 70}")
    for n, sentence in enumerate(PLAN["scripts"][script]["sentences"], 1):
        words = []
        for w in sentence.split():
            words.append(w)
            if (n, w.strip(",.;?")) in pauses:
                words.append("⏸ (freeze 3 s)")
        mark = f">> [{'+'.join(tags[n])}] " if n in tags else "   "
        print(f"{n:>2} {mark}{' '.join(words)}")
    print("═" * 70)


def record(script, take):
    show_script(script, take)
    dev = sd.query_devices(kind="input")
    sr_in = int(dev["default_samplerate"])
    input(f"\nMic: {dev['name']}\nPress Enter to start recording…")
    chunks = []
    stream = sd.InputStream(samplerate=sr_in, channels=1, dtype="float32", callback=lambda d, *_: chunks.append(d.copy()))
    with stream:
        for s in range(LEAD_IN, 0, -1):
            print(f"  stay silent… {s}", flush=True)
            time.sleep(1)
        print("🔴 GO! Read now. Press Enter when you finish.")
        input()
    audio = np.concatenate(chunks)[:, 0] if chunks else np.zeros(1, dtype="float32")
    g = math.gcd(SR_OUT, sr_in)
    audio = resample_poly(audio, SR_OUT // g, sr_in // g).astype("float32")
    dst = take_path(script, take)
    sf.write(dst, audio, SR_OUT, subtype="PCM_16")
    shutil.copy(DATASET / script / "script.txt", dst.with_suffix(".txt"))
    peak = 20 * math.log10(max(float(np.max(np.abs(audio))), 1e-9))
    print(f"\n✅ Saved {dst.relative_to(ROOT)}  ({len(audio) / SR_OUT:.1f} s, peak {peak:.0f} dB)")
    if peak < -30:
        print("⚠️  Very quiet. Move closer to the mic (about 30 cm) and record this take again.")
    elif peak > -0.5:
        print("⚠️  Clipping (too loud). Move back a little and record this take again.")


def checklist():
    left = []
    for script in PLAN["scripts"]:
        print(f"\n{script}:")
        for take in PLAN["takes"]:
            done = take_path(script, take).exists()
            print(f"  {'✅' if done else '⬜'} {take:<9} → {take_path(script, take).name}")
            if not done:
                left.append(f"py -3.12 record_take.py {script} {take}")
    print(f"\nNext: {left[0]}" if left else "\nAll takes recorded 🎉")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        checklist()
    elif len(sys.argv) == 3 and sys.argv[1] in PLAN["scripts"] and sys.argv[2] in PLAN["takes"]:
        record(sys.argv[1], sys.argv[2])
        checklist()
    else:
        print(__doc__)
        print("Scripts:", ", ".join(PLAN["scripts"]), "\nTakes:  ", ", ".join(PLAN["takes"]))
