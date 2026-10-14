"""Optional Gemini layer: content + visual judgement and rewriting. Never needed for the core scores.
Modes: real (GEMINI_API_KEY set), mock (MOCK=1, deterministic fake answers), off (no key)."""
import json
import re
from .config import GEMINI_API_KEY, GEMINI_MODEL, gemini_mode

RUBRIC_PROMPT = """You are a strict, consistent public-speaking judge. Use ONLY this rubric.
CONTENT (from the transcript): hook in first 10 s, clear structure (intro/body/close), clarity of message. Score 0-10.
VISUAL (from the frames, if any; each frame is labelled with its timestamp): eye contact with camera, open gestures, facial expression. Score 0-10, or null if there are no frames.
Return JSON only:
{"content": {"score": number, "hook": string, "structure": string, "clarity": string},
 "visual": {"score": number|null, "summary": string},
 "notes": [{"start": seconds, "end": seconds, "type": "content"|"visual", "issue": string, "suggestion": string}]}
Give at most 6 notes. Timestamps must come from the transcript word times or frame labels.
TRANSCRIPT WITH TIMES:
"""

REWRITE_PROMPT = """Rewrite this spoken segment so it is clear and confident to say aloud.
Remove filler words, keep the same meaning and roughly the same length, keep it in the first person.
Problem detected: {problem}
Segment: "{text}"
Return JSON only: {{"rewrite": string, "why": string}}"""


_CLIENT = None


def _client():
    # keep one client alive (a temporary client gets closed before the request finishes)
    global _CLIENT
    if _CLIENT is None:
        from google import genai
        _CLIENT = genai.Client(api_key=GEMINI_API_KEY)
    return _CLIENT


def _json(text):
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


def _call(parts):
    from google.genai import types
    resp = _client().models.generate_content(
        model=GEMINI_MODEL, contents=parts,
        config=types.GenerateContentConfig(temperature=0, seed=7, response_mime_type="application/json"))
    return _json(resp.text)


def timed_transcript(words):
    lines, cur, t0 = [], [], None
    for w in words:
        if t0 is None:
            t0 = w["start"]
        cur.append(w["w"])
        if w["end"] - t0 > 5:
            lines.append(f"[{t0:.1f}s] " + " ".join(cur))
            cur, t0 = [], None
    if cur:
        lines.append(f"[{t0:.1f}s] " + " ".join(cur))
    return "\n".join(lines)


def judge(words, frames):
    mode = gemini_mode()
    if mode == "off":
        return None
    if mode == "mock":
        dur = words[-1]["end"] if words else 10
        return {"content": {"score": 6.5, "hook": "[MOCK] Opens with a statement, not a question or story.",
                            "structure": "[MOCK] Intro and body present; closing is weak.", "clarity": "[MOCK] Main message is understandable."},
                "visual": {"score": 7.0 if frames else None, "summary": "[MOCK] Mostly looking at camera." if frames else "No video frames."},
                "notes": [{"start": 0.0, "end": min(5.0, dur), "type": "content", "issue": "[MOCK] Weak hook",
                           "suggestion": "Start with a question or a surprising fact."}],
                "mode": "mock"}
    from google.genai import types
    parts = [RUBRIC_PROMPT + timed_transcript(words)]
    for t, jpg in frames:
        parts.append(f"Frame at {t:.1f}s:")
        parts.append(types.Part.from_bytes(data=jpg, mime_type="image/jpeg"))
    out = _call(parts)
    out["mode"] = "real"
    return out


def rewrite(text, problem):
    mode = gemini_mode()
    if mode == "mock" or mode == "off":
        from .config import FILLERS
        clean = " ".join(w for w in text.split() if re.sub(r"[^a-z]", "", w.lower()) not in FILLERS)
        tag = "[MOCK]" if mode == "mock" else "[NO API KEY - simple filler removal]"
        return {"rewrite": clean or text, "why": f"{tag} Removed fillers; deliver slower with one deliberate pause."}
    return _call([REWRITE_PROMPT.format(text=text, problem=problem)])
