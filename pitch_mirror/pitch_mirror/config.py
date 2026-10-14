import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

CACHE_DIR = ROOT / "cache"
CACHE_DIR.mkdir(exist_ok=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base.en").strip()
MOCK = os.getenv("MOCK", "0").strip() == "1"
MAX_FRAMES = int(os.getenv("MAX_FRAMES", "20"))

FILLERS = {"um", "uh", "umm", "uhm", "erm", "er", "ah", "hmm", "like", "so", "actually", "basically"}
FILLER_BIGRAMS = {("you", "know"), ("i", "mean"), ("kind", "of"), ("sort", "of")}

# Generic norms used when no baseline recording is supplied.
# wpm here = articulation rate (words / spoken span inside a 6 s window; long pauses are judged separately)
NORMS = {"wpm": 150.0, "wpm_lo": 100.0, "wpm_hi": 195.0, "pause_s": 1.2, "pitch_st_std": 2.0}


def gemini_mode() -> str:
    """'mock', 'real' or 'off'."""
    if MOCK:
        return "mock"
    return "real" if GEMINI_API_KEY else "off"
