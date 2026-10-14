"""Acoustic feature extraction with librosa. Everything is speaker-normalized:
pitch in semitones relative to the speaker's own median, energy in dB relative to the speaker's median."""
import numpy as np
import librosa

SR = 16000
HOP = 320  # 20 ms


def load(wav):
    y, _ = librosa.load(str(wav), sr=SR, mono=True)
    return y


def frame_features(y):
    """Per-20ms contours: time, energy_db_rel, pitch_st_rel (nan when unvoiced), centroid, mfcc."""
    rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=HOP)[0]
    db = librosa.amplitude_to_db(rms + 1e-9, ref=1.0)
    voiced_mask = db > (np.max(db) - 45)
    # reference loudness = 75th percentile of voiced frames (robust to a quiet stretch)
    med_db = float(np.percentile(db[voiced_mask], 75)) if voiced_mask.any() else float(np.median(db))
    f0 = librosa.yin(y, fmin=65, fmax=420, sr=SR, frame_length=1024, hop_length=HOP)
    n = min(len(f0), len(db))
    f0, db, voiced_mask = f0[:n], db[:n], voiced_mask[:n]
    f0 = np.where(voiced_mask & (f0 > 66) & (f0 < 415), f0, np.nan)
    med_f0 = float(np.nanmedian(f0)) if np.isfinite(f0).any() else 150.0
    st = 12 * np.log2(f0 / med_f0)
    cent = librosa.feature.spectral_centroid(y=y, sr=SR, n_fft=1024, hop_length=HOP)[0][:n]
    mfcc = librosa.feature.mfcc(y=y, sr=SR, n_mfcc=13, n_fft=1024, hop_length=HOP)[:, :n]
    t = librosa.frames_to_time(np.arange(n), sr=SR, hop_length=HOP)
    return {"t": t, "db_rel": db - med_db, "st": st, "centroid": cent, "mfcc": mfcc,
            "voiced": voiced_mask, "median_f0_hz": med_f0, "median_db": med_db}


def _slice(ff, a, b):
    i0, i1 = np.searchsorted(ff["t"], a), np.searchsorted(ff["t"], b)
    return slice(i0, max(i1, i0 + 1))


def window_stats(ff, words, duration, win=6.0, step=1.0):
    """Sliding windows of acoustic + lexical stats."""
    rows = []
    t = 0.0
    while t < max(duration - 0.5, 0.01):
        a, b = t, min(t + win, duration)
        s = _slice(ff, a, b)
        ws = [w for w in words if a <= (w["start"] + w["end"]) / 2 < b]
        speech = sum(w["end"] - w["start"] for w in ws)
        # articulation rate: words per minute over the span actually spoken (pauses are judged separately)
        span = (ws[-1]["end"] - ws[0]["start"]) if len(ws) >= 2 else 0
        st = ff["st"][s]
        st = st[np.isfinite(st)]
        rows.append({
            "start": round(a, 2), "end": round(b, 2),
            "wpm": round(len(ws) / span * 60, 1) if span > 0.5 else 0.0,
            "n_words": len(ws), "fillers": sum(1 for w in ws if w.get("filler")),
            "speech_ratio": round(speech / (b - a), 3) if b > a else 0,
            "pitch_std_st": round(float(np.std(st)), 2) if len(st) > 5 else None,
            "pitch_mean_st": round(float(np.mean(st)), 2) if len(st) > 5 else None,
            "energy_db": round(float(np.percentile(ff["db_rel"][s][ff["voiced"][s]], 75)), 2) if ff["voiced"][s].sum() > 10 else None,
            "clarity_p": _clarity(ws),
        })
        t += step
    return rows


def _clarity(ws):
    ps = [w["p"] for w in ws if w.get("p")]
    return round(float(np.mean(ps)), 3) if ps else None


def pauses(words, ff=None, min_gap=0.6, silence_db=-30.0):
    """Silent stretches between the first and last word. Uses the ENERGY contour (frames > 30 dB below the
    speaker's loudness) when available, because Whisper word ends often swallow silence."""
    if not words:
        return []
    out = []
    if ff is not None:
        t, db = ff["t"], ff["db_rel"]
        silent = (db < silence_db) & (t > words[0]["start"]) & (t < words[-1]["end"])
        i, n = 0, len(t)
        while i < n:
            if silent[i]:
                j = i
                while j < n and silent[j]:
                    j += 1
                a, b = float(t[i]), float(t[j - 1])
                if b - a >= min_gap:
                    before = [w for w in words if w["start"] <= a + 0.1]
                    after = [w for w in words if w["end"] >= b - 0.1]
                    out.append({"start": round(a, 2), "end": round(b, 2), "dur": round(b - a, 2),
                                "after": before[-1]["w"] if before else "", "before": after[0]["w"] if after else ""})
                i = j
            else:
                i += 1
        return out
    for a, b in zip(words, words[1:]):
        g = b["start"] - a["end"]
        if g >= min_gap:
            out.append({"start": round(a["end"], 2), "end": round(b["start"], 2), "dur": round(g, 2),
                        "after": a["w"], "before": b["w"]})
    return out


def global_stats(ff, words, duration):
    st = ff["st"][np.isfinite(ff["st"])]
    speaking = (words[-1]["end"] - words[0]["start"]) if words else 0
    voiced_db = ff["db_rel"][ff["voiced"]]
    return {
        "duration": round(duration, 2),
        "n_words": len(words),
        "wpm": round(len(words) / speaking * 60, 1) if speaking > 0 else 0.0,
        "filler_count": sum(1 for w in words if w.get("filler")),
        "filler_per_min": round(sum(1 for w in words if w.get("filler")) / max(speaking, 1) * 60, 2),
        "pitch_std_st": round(float(np.std(st)), 2) if len(st) else 0.0,
        "energy_std_db": round(float(np.std(voiced_db)), 2) if len(voiced_db) else 0.0,
        "median_f0_hz": round(ff["median_f0_hz"], 1),
        "clarity_p": _clarity(words) or 0.9,
        "mfcc_mean": [round(float(x), 2) for x in np.mean(ff["mfcc"], axis=1)],
        "centroid_mean_hz": round(float(np.mean(ff["centroid"][ff["voiced"]])), 1) if ff["voiced"].any() else 0.0,
    }


def downsample_contours(ff, step=5):
    """Keep every 5th frame (100 ms) for plotting / JSON."""
    st = ff["st"][::step]
    return {"t": [round(float(x), 2) for x in ff["t"][::step]],
            "energy_db": [round(float(x), 2) for x in ff["db_rel"][::step]],
            "pitch_st": [None if not np.isfinite(x) else round(float(x), 2) for x in st]}
