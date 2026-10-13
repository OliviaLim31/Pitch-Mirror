"""One function to analyze a recording: analyze(path, baseline=..., transcript=...). Results are cached as JSON."""
import hashlib
import json
import tempfile
from pathlib import Path

from . import acoustic, media, transcribe, flaws as F, gemini
from .config import CACHE_DIR, MAX_FRAMES, WHISPER_MODEL, gemini_mode

VERSION = "1.3"


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _cache_path(key):
    return CACHE_DIR / f"{key}.json"


def analyze_core(path, transcript_text=None, use_ai=True, progress=lambda msg, frac: None):
    """Everything that does NOT depend on a baseline. Cached by file content."""
    path = Path(path)
    key = f"core_{file_hash(path)}_{hashlib.md5(((transcript_text or '') + WHISPER_MODEL + gemini_mode() + str(use_ai) + VERSION).encode()).hexdigest()[:8]}"
    cp = _cache_path(key)
    if cp.exists():
        return json.loads(cp.read_text())
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "audio.wav"
        progress("Extracting audio", 0.05)
        media.extract_wav(path, wav)
        y = acoustic.load(wav)
        dur = len(y) / acoustic.SR
        progress("Transcribing + aligning words (Whisper)", 0.15)
        words = transcribe.transcribe(wav)
        progress("Extracting acoustic features (pitch, energy, MFCC)", 0.55)
        ff = acoustic.frame_features(y)
    res = {
        "file": path.name, "hash": file_hash(path), "version": VERSION,
        "words": words,
        "windows": acoustic.window_stats(ff, words, dur),
        "pauses": acoustic.pauses(words, ff),
        "global": acoustic.global_stats(ff, words, dur),
        "contours": acoustic.downsample_contours(ff),
        "is_video": media.is_video(path),
        "transcript": " ".join(w["w"] for w in words),
    }
    if transcript_text:
        al = transcribe.align_to_reference(words, transcript_text)
        res["script_match"] = al["match_ratio"]
        res["script_issues"] = al["issues"]
    res["ai"] = None
    if use_ai and gemini_mode() != "off":
        progress(f"Gemini content/visual judgement ({gemini_mode()})", 0.75)
        frames = media.sample_frames(path, MAX_FRAMES) if res["is_video"] else []
        try:
            res["ai"] = gemini.judge(words, frames)
        except Exception as e:
            res["ai"] = {"error": str(e)[:300]}
    if not (res["ai"] and res["ai"].get("error")):  # don't cache failed AI calls, so a fixed key works next time
        cp.write_text(json.dumps(res))
    progress("Done", 1.0)
    return res


def analyze(path, baseline=None, transcript_text=None, use_ai=True, progress=lambda m, f: None):
    """Full analysis. `baseline` = a core/analysis dict of the SAME text delivered well (optional)."""
    core = analyze_core(path, transcript_text, use_ai, progress)
    res = dict(core)
    fl = F.detect(res, baseline)
    ai = res.get("ai") if res.get("ai") and not res["ai"].get("error") else None
    if ai:
        for n in ai.get("notes", []):
            try:
                fl.append({"type": n.get("type", "content"), "label": F.LABEL.get(n.get("type"), "AI note"),
                           "start": float(n["start"]), "end": float(n["end"]), "severity": "medium",
                           "severity_score": 1.0, "why": n.get("issue", ""), "suggestion": n.get("suggestion", ""),
                           "source": f"gemini-{ai.get('mode', 'real')}"})
            except (KeyError, TypeError, ValueError):
                pass
        fl.sort(key=lambda f: f["start"])
        for k, f in enumerate(fl):
            f["id"] = k + 1
    res["flaws"] = fl
    res["scores"] = F.score(res, fl, ai)
    res["baseline_file"] = baseline["file"] if baseline else None
    res["baseline_overlay"] = F.warp_baseline_contours(res, baseline) if baseline else None
    return res


def segment_text(analysis, start, end, pad=0.3):
    return " ".join(w["w"] for w in analysis["words"] if w["end"] >= start - pad and w["start"] <= end + pad)
