"""Build a graded 'bad mirror' spectrum from ONE good recording (Track C requirement 1b + 1c).
Usage: python make_spectrum.py dataset/good/ted_1.wav
Writes dataset/spectrum/<name>_L1..L4.wav plus labels.json with the injected flaw regions (start/end seconds)."""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8")  # emoji-safe on Windows consoles
except Exception:
    pass

import json
import subprocess
import sys
from pathlib import Path
import soundfile as sf
import numpy as np
from pitch_mirror.media import ffmpeg_bin, extract_wav

# level: (tempo, pause seconds inserted at 40%, volume drop dB on last 30%, monotone strength 0..1)
LEVELS = {1: (1.1, 0.0, 0, 0.0), 2: (1.3, 1.5, 0, 0.5), 3: (1.45, 2.5, -10, 0.75), 4: (1.65, 3.5, -16, 0.95)}


def monotone(y, sr, strength):
    """Flatten pitch movement by compressing it towards the median (approximation via pitch-shift blending)."""
    if strength <= 0:
        return y
    import librosa
    f0 = librosa.yin(y, fmin=65, fmax=420, sr=sr)
    med = np.nanmedian(f0)
    hop = 512
    out = np.copy(y)
    seg = sr // 4  # 0.25 s blocks
    for s in range(0, len(y), seg):
        blk = y[s:s + seg]
        fi = f0[s // hop:(s + seg) // hop]
        if len(blk) < 2048 or len(fi) == 0:
            continue
        st = 12 * np.log2(np.nanmedian(fi) / med) if np.nanmedian(fi) > 0 else 0
        out[s:s + len(blk)] = librosa.effects.pitch_shift(blk, sr=sr, n_steps=-st * strength)[:len(blk)]
    return out


def build(src):
    src = Path(src)
    outdir = Path("dataset/spectrum"); outdir.mkdir(parents=True, exist_ok=True)
    tmp = outdir / f"{src.stem}_src.wav"
    extract_wav(src, tmp)
    labels = json.loads((outdir / "labels.json").read_text()) if (outdir / "labels.json").exists() else {}
    for lvl, (tempo, pause, vol, mono) in LEVELS.items():
        sped = outdir / f"_tmp.wav"
        subprocess.run([ffmpeg_bin(), "-y", "-loglevel", "error", "-i", str(tmp), "-filter:a", f"atempo={tempo}", str(sped)], check=True)
        y, sr = sf.read(sped)
        y = monotone(y.astype(np.float32), sr, mono)
        regions = [{"type": "pace_fast", "start": 0.0, "end": round(len(y) / sr, 2), "detail": f"tempo x{tempo}"}] if tempo >= 1.25 else []
        if mono:
            regions.append({"type": "monotone", "start": 0.0, "end": round(len(y) / sr, 2), "detail": f"pitch flattened {mono:.0%}"})
        if pause:
            cut = int(len(y) * 0.4)
            y = np.concatenate([y[:cut], np.zeros(int(pause * sr), dtype=y.dtype), y[cut:]])
            regions.append({"type": "long_pause", "start": round(cut / sr, 2), "end": round(cut / sr + pause, 2), "detail": f"{pause}s silence"})
        if vol:
            s = int(len(y) * 0.7)
            y[s:] *= 10 ** (vol / 20)
            regions.append({"type": "low_energy", "start": round(s / sr, 2), "end": round(len(y) / sr, 2), "detail": f"{vol} dB"})
        name = f"{src.stem}_L{lvl}.wav"
        sf.write(outdir / name, y, sr)
        labels[name] = {"source": src.name, "level": lvl, "flaws": regions}
        print("wrote", outdir / name)
    sped.unlink(); tmp.unlink()
    (outdir / "labels.json").write_text(json.dumps(labels, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python make_spectrum.py path/to/good_recording.(wav|mp3|mp4)")
    build(sys.argv[1])
