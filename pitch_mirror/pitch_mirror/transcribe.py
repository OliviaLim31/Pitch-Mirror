"""Speech-to-text with word timestamps (faster-whisper) = our forced alignment step."""
import re
from functools import lru_cache
from .config import WHISPER_MODEL, FILLERS, FILLER_BIGRAMS

# Whisper likes to "clean up" fillers; this prompt nudges it to keep them.
_PROMPT = "Umm, so, uh, I was like, you know, thinking... Hmm, actually, basically."


@lru_cache(maxsize=1)
def _model():
    from faster_whisper import WhisperModel
    # float32 + 1 thread + greedy decoding = bit-for-bit reproducible (int8 drifts between runs; we tested)
    return WhisperModel(WHISPER_MODEL, device="cpu", compute_type="float32", cpu_threads=1)


def norm(w: str) -> str:
    return re.sub(r"[^a-z0-9']", "", w.lower())


def transcribe(wav_path):
    # pass a numpy array (not a path) so faster-whisper never needs PyAV to decode files
    import numpy as np
    import librosa
    audio, _ = librosa.load(str(wav_path), sr=16000, mono=True)
    best = None
    # Pass 1 uses a filler-friendly prompt. Whisper sometimes derails with a prompt, so we also run
    # without it and keep whichever result has more properly timed words (sanity check).
    for prompt in (_PROMPT, None):
        words = _run(audio.astype(np.float32), prompt)
        good = sum(1 for w in words if w["end"] - w["start"] > 0.03)
        if best is None or good > best[0] * 1.15:
            best = (good, words)
        if prompt and good >= 0.9 * len(words) and len(words) > 0:
            break  # prompt run looks healthy, no need for pass 2
    words = best[1]
    mark_fillers(words)
    return words


def _run(audio, prompt):
    segs, _info = _model().transcribe(
        audio, word_timestamps=True, beam_size=1, temperature=0.0,
        initial_prompt=prompt, vad_filter=False, condition_on_previous_text=False,
    )
    words = []
    for s in segs:
        for w in s.words or []:
            t = w.word.strip()
            if not norm(t):
                continue
            words.append({"w": t, "start": round(float(w.start), 2), "end": round(float(w.end), 2),
                          "p": round(float(w.probability), 3)})
    return words


def mark_fillers(words):
    for i, w in enumerate(words):
        n = norm(w["w"])
        w["filler"] = n in FILLERS
        if n in {"like", "so", "actually", "basically"}:
            # only count as filler when it is followed by a short hesitation or repeated
            nxt = words[i + 1] if i + 1 < len(words) else None
            gap = (nxt["start"] - w["end"]) if nxt else 1
            w["filler"] = gap > 0.25 or (nxt is not None and norm(nxt["w"]) in FILLERS)
        if i > 0 and (norm(words[i - 1]["w"]), n) in FILLER_BIGRAMS:
            words[i - 1]["filler"] = True
            w["filler"] = True
    return words


def align_to_reference(words, reference_text):
    """Compare spoken words with an uploaded transcript. Returns list of skipped / inserted spans."""
    import difflib
    ref = [norm(x) for x in reference_text.split() if norm(x)]
    hyp = [norm(w["w"]) for w in words]
    sm = difflib.SequenceMatcher(a=ref, b=hyp, autojunk=False)
    issues = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        t0 = words[min(j1, len(words) - 1)]["start"] if words else 0
        t1 = words[min(max(j2 - 1, j1), len(words) - 1)]["end"] if words else 0
        issues.append({"tag": tag, "ref": " ".join(ref[i1:i2]), "said": " ".join(hyp[j1:j2]),
                       "start": t0, "end": t1})
    return {"match_ratio": round(sm.ratio(), 3), "issues": issues}
