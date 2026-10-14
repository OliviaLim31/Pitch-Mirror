"""Temporal flaw grounding + causal explanations + rubric scoring.

If a baseline analysis (same text, delivered well) is given, each window is compared with the SAME words in the
baseline (word alignment via difflib). Otherwise generic norms are used."""
import difflib
import numpy as np
from .config import NORMS
from .transcribe import norm

SUGGEST = {
    "pace_fast": "Slow down here: breathe at each comma and aim for about {target:.0f} WPM.",
    "pace_slow": "Pick the pace up a little; it is dragging. Aim for about {target:.0f} WPM.",
    "long_pause": "Shorten this silence or make it deliberate (pause after a key point, not mid-sentence).",
    "filler": "Replace the filler with a silent pause. Silence sounds confident; 'um' sounds unsure.",
    "monotone": "Vary your pitch: lift on the key word, drop at the end of the sentence.",
    "low_energy": "Project here: keep volume up through the end of the sentence instead of trailing off.",
    "clarity": "Articulate more clearly: open the mouth and finish word endings.",
    "skipped_text": "You left out or changed part of the script here.",
}
LABEL = {"pace_fast": "Too fast", "pace_slow": "Too slow", "long_pause": "Long pause", "filler": "Filler words",
         "monotone": "Monotone", "low_energy": "Low energy", "clarity": "Unclear words", "skipped_text": "Script deviation",
         "visual": "Visual delivery", "content": "Content"}


def _sev(x):
    return "high" if x >= 2.0 else "medium" if x >= 1.0 else "low"


def word_map(words, base_words):
    """Pairs (i_participant, j_baseline) of matching words."""
    a = [norm(w["w"]) for w in words]
    b = [norm(w["w"]) for w in base_words]
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    pairs = []
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            pairs.append((blk.a + k, blk.b + k))
    return pairs


def warp_baseline_contours(analysis, baseline):
    """Map baseline contours onto participant time using matched word starts (for the overlay chart)."""
    pairs = word_map(analysis["words"], baseline["words"])
    if len(pairs) < 2:
        return None
    pt = np.array([analysis["words"][i]["start"] for i, _ in pairs])
    bt = np.array([baseline["words"][j]["start"] for _, j in pairs])
    order = np.argsort(bt)
    bt, pt = bt[order], pt[order]
    c = baseline["contours"]
    t = np.interp(np.array(c["t"]), bt, pt)
    return {"t": [round(float(x), 2) for x in t], "energy_db": c["energy_db"], "pitch_st": c["pitch_st"],
            "match_ratio": round(len(pairs) / max(1, len(analysis["words"])), 3)}


def _baseline_local(words_idx, pairs_d, base_words, base_contours, words):
    """Compare the SAME matched words in participant vs baseline (fillers/extra words are ignored here)."""
    m = [i for i in words_idx if i in pairs_d]
    if len(m) < 4:
        return None
    js = [pairs_d[i] for i in m]
    if (max(js) - min(js)) > 2 * len(js):
        return None
    a, b = base_words[min(js)]["start"], base_words[max(js)]["end"]
    pa, pb = words[m[0]]["start"], words[m[-1]]["end"]
    if b - a <= 0.3 or pb - pa <= 0.3:
        return None
    t = np.array(base_contours["t"])
    inside = (t >= a) & (t <= b)
    st = np.array([x for x, k in zip(base_contours["pitch_st"], inside) if k and x is not None], dtype=float)
    return {"wpm": len(m) / (b - a) * 60, "p_wpm": len(m) / (pb - pa) * 60, "pitch_std": float(np.std(st)) if len(st) > 5 else None, "span": (a, b)}


def detect(analysis, baseline=None):
    words, wins = analysis["words"], analysis["windows"]
    raw = []
    pairs_d = {}
    if baseline:
        pairs_d = dict(word_map(words, baseline["words"]))
        bw = baseline["windows"]
        base_wpm_sd = float(np.std([w["wpm"] for w in bw if w["n_words"] >= 3]) or 20) or 20
    for w in wins:
        idx = [i for i, x in enumerate(words) if w["start"] <= (x["start"] + x["end"]) / 2 < w["end"]]
        loc = _baseline_local(idx, pairs_d, baseline["words"], baseline["contours"], words) if baseline else None
        if loc:
            w = dict(w, wpm=round(loc["p_wpm"], 1))
        ref_wpm = loc["wpm"] if loc else NORMS["wpm"]
        src = f"baseline for the same words ({ref_wpm:.0f} WPM)" if loc else f"typical range {NORMS['wpm_lo']:.0f}-{NORMS['wpm_hi']:.0f} WPM"
        hi = ref_wpm * 1.25 if loc else NORMS["wpm_hi"]
        lo = ref_wpm * 0.72 if loc else NORMS["wpm_lo"]
        if w["n_words"] >= 4 and w["wpm"] > hi:
            d = (w["wpm"] - ref_wpm) / ref_wpm
            z = (w["wpm"] - ref_wpm) / (base_wpm_sd if baseline else 20)
            raw.append(("pace_fast", w, z / 1.5, ref_wpm,
                        f"Speech rate {w['wpm']:.0f} WPM vs {src}: {d:+.0%}, z={z:+.1f}. Words are packed {w['n_words']} into {w['end']-w['start']:.0f}s, leaving no breathing pauses."))
        elif w["n_words"] >= 4 and 0 < w["wpm"] < lo:
            d = (w["wpm"] - ref_wpm) / ref_wpm
            raw.append(("pace_slow", w, abs(d) * 3, ref_wpm,
                        f"Speech rate {w['wpm']:.0f} WPM vs {src}: {d:+.0%}. Words are stretched out, so the listener waits."))
        ps = w["pitch_std_st"]
        ref_ps = loc["pitch_std"] if (loc and loc.get("pitch_std")) else NORMS["pitch_st_std"]
        if ps is not None and w["n_words"] >= 3 and ps < max(0.8, 0.55 * ref_ps):
            raw.append(("monotone", w, (ref_ps - ps) / max(ref_ps, 0.1) * 2.5, None,
                        f"Pitch variation {ps:.1f} semitones (std of F0, speaker-normalized) vs {ref_ps:.1f} in the "
                        f"{'baseline' if loc else 'typical range'}: {ps/ref_ps-1:+.0%}. The F0 contour is nearly flat."))
        if w["energy_db"] is not None and w["energy_db"] < -8 and w["n_words"] >= 2:
            raw.append(("low_energy", w, abs(w["energy_db"]) / 8, None,
                        f"Mean energy {w['energy_db']:.1f} dB below this speaker's own median loudness (RMS). Volume drops off here."))
        if w["clarity_p"] is not None and w["clarity_p"] < 0.55 and w["n_words"] >= 3:
            raw.append(("clarity", w, (0.55 - w["clarity_p"]) * 6 + 0.5, None,
                        f"Average word recognition confidence {w['clarity_p']:.2f} (clear speech is usually >0.8). Words are hard to decode."))
    flaws = _merge(raw, words)
    # pauses
    for p in analysis["pauses"]:
        ref_gap = None
        if baseline:
            prev = [i for i, x in enumerate(words) if x["start"] <= p["start"] + 0.1]
            if prev and prev[-1] in pairs_d:
                bj = pairs_d[prev[-1]]
                bt = baseline["words"][bj]["start"]
                nb = baseline["words"][bj + 1]["start"] if bj + 1 < len(baseline["words"]) else bt + 1
                ref_gap = max([bp["dur"] for bp in baseline["pauses"] if bt - 0.1 <= bp["start"] <= nb + 0.1] or [0.0])
        thr = (ref_gap + 0.8) if ref_gap is not None else NORMS["pause_s"]
        if p["dur"] > thr:
            ref_txt = f"baseline pause here is {ref_gap:.2f}s" if ref_gap is not None else f"norm is <{NORMS['pause_s']}s mid-speech"
            flaws.append(_flaw("long_pause", p["start"], p["end"], (p["dur"] - thr) / 0.8 + 0.5,
                               f"Silence of {p['dur']:.2f}s between '{p['after']}' and '{p['before']}' ({ref_txt}); energy stays below the voice threshold for the whole gap."))
    # fillers
    fl = [w for w in words if w.get("filler")]
    for w in fl:
        near = sum(1 for x in fl if abs(x["start"] - w["start"]) < 5)
        flaws.append(_flaw("filler", w["start"], w["end"], 0.5 * near,
                           f"Filler '{w['w'].strip()}' detected ({near} filler(s) within ±5 s). Fillers lower perceived confidence."))
    # script deviations
    for iss in analysis.get("script_issues", []):
        if iss["tag"] in ("delete", "replace") and len(iss["ref"].split()) >= 2:
            flaws.append(_flaw("skipped_text", iss["start"], iss["end"], 1.0,
                               f"Script says '{iss['ref']}' but speaker said '{iss['said'] or '(nothing)'}'."))
    flaws.sort(key=lambda f: f["start"])
    for k, f in enumerate(flaws):
        f["id"] = k + 1
    return flaws


def _flaw(typ, a, b, sev, why, target=None):
    sug = SUGGEST.get(typ, "").format(target=target or NORMS["wpm"])
    return {"type": typ, "label": LABEL.get(typ, typ), "start": round(float(a), 2), "end": round(float(b), 2),
            "severity": _sev(sev), "severity_score": round(float(sev), 2), "why": why, "suggestion": sug,
            "source": "acoustic"}


def _merge(raw, words):
    """Merge overlapping flagged windows of the same type into one region, trimmed to the spoken words."""
    out = []
    for typ in sorted({r[0] for r in raw}):
        rs = sorted([r for r in raw if r[0] == typ], key=lambda r: r[1]["start"])
        cur = None
        for r in rs:
            if cur and r[1]["start"] <= cur["end"]:
                cur["end"] = max(cur["end"], r[1]["end"])
                if r[2] > cur["sev"]:
                    cur.update(sev=r[2], why=r[4], tgt=r[3])
            else:
                if cur:
                    out.append(cur)
                cur = {"typ": typ, "start": r[1]["start"], "end": r[1]["end"], "sev": r[2], "why": r[4], "tgt": r[3]}
        if cur:
            out.append(cur)
    res = []
    for c in out:
        inside = [w for w in words if w["start"] >= c["start"] and w["end"] <= c["end"]]
        a = inside[0]["start"] if inside else c["start"]
        b = inside[-1]["end"] if inside else c["end"]
        res.append(_flaw(c["typ"], a, b, c["sev"], c["why"], c["tgt"]))
    return res


def _cover(flaws, types, dur):
    tot = sum(f["end"] - f["start"] for f in flaws if f["type"] in types)
    return min(1.0, tot / max(dur, 1))


def score(analysis, flaws, ai=None):
    g, dur = analysis["global"], analysis["global"]["duration"]
    clip = lambda x: round(float(max(0.0, min(10.0, x))), 1)
    pace = 10 - 10 * _cover(flaws, {"pace_fast", "pace_slow"}, dur) - max(0, abs(g["wpm"] - NORMS["wpm"]) - 25) / 8
    fluency = 10 - 1.0 * g["filler_per_min"]
    long_p = [f for f in flaws if f["type"] == "long_pause"]
    pauses = 10 - 1.0 * len(long_p) * 60 / max(dur, 20)
    variety = 2 + (g["pitch_std_st"] - 0.5) * 3.2 - 8 * _cover(flaws, {"monotone"}, dur)
    energy = 10 - 12 * _cover(flaws, {"low_energy"}, dur)
    clarity = (g["clarity_p"] - 0.45) / 0.45 * 10
    dims = {"Pace": clip(pace), "Fluency (fillers)": clip(fluency), "Pausing": clip(pauses),
            "Vocal variety (pitch)": clip(variety), "Energy / projection": clip(energy), "Clarity": clip(clarity)}
    weights = {"Pace": .2, "Fluency (fillers)": .2, "Pausing": .15, "Vocal variety (pitch)": .2,
               "Energy / projection": .1, "Clarity": .15}
    acoustic_overall = round(sum(dims[k] * w for k, w in weights.items()) * 10, 1)
    ai_dims = {}
    if ai:
        if ai.get("content", {}).get("score") is not None:
            ai_dims["Content (AI)"] = clip(ai["content"]["score"])
        if ai.get("visual", {}).get("score") is not None:
            ai_dims["Visual (AI)"] = clip(ai["visual"]["score"])
    return {"dimensions": dims, "ai_dimensions": ai_dims, "overall": acoustic_overall,
            "overall_note": "Overall = weighted acoustic rubric (deterministic). AI dimensions are shown separately and not included, so the score is reproducible."}
