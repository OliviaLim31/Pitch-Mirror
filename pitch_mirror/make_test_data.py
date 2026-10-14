"""Create SYNTHETIC test videos (TTS voice) so you can try the app before recording your own.
Usage: python make_test_data.py   -> writes data/good_1.mp4, data/good_2.mp4, data/bad_1.mp4, data/bad_2.mp4"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8")  # emoji-safe on Windows consoles
except Exception:
    pass

import subprocess
from pathlib import Path
from pitch_mirror.media import ffmpeg_bin

DATA = Path(__file__).parent / "data"
DATA.mkdir(exist_ok=True)
SCRIPT = ("Have you ever frozen in front of an audience? I have. Last year, my hands were shaking before my first "
          "pitch. Today I want to show you three simple habits that changed everything. First, breathe before you speak. "
          "Second, pause after every key idea. Third, look at one friendly face. Try them this week, and watch your confidence grow.")
BAD = ("Um, so, have you ever, like, frozen in front of an audience? Uh, I have. Last year, um, my hands were shaking before "
       "my first pitch. So, uh, today I want to, like, show you three simple habits that, you know, changed everything. "
       "First, um, breathe before you speak. Second, uh, pause after every key idea. Third, like, look at one friendly face. "
       "So, um, try them this week, and, uh, watch your confidence grow.")
# (name, text, gTTS accent, tempo multiplier, extra ffmpeg audio filter)
ITEMS = [("good_1", SCRIPT, "com", 1.0, None), ("good_2", SCRIPT, "co.uk", 0.95, None),
         ("bad_1", BAD, "com", 1.45, None),
         ("bad_2", BAD, "co.uk", 1.35, "volume=enable='gte(t,14)':volume=0.15")]


def make(name, text, tld, tempo, extra):
    raw = DATA / f"{name}_raw.mp3"
    mp3 = DATA / f"{name}.mp3"
    from gtts import gTTS
    gTTS(text, tld=tld).save(str(raw))
    af = f"atempo={tempo}" + (f",{extra}" if extra else "")
    subprocess.run([ffmpeg_bin(), "-y", "-loglevel", "error", "-i", str(raw), "-af", af, str(mp3)], check=True)
    raw.unlink()
    src = "testsrc2=size=640x360:rate=15" if name.startswith("good") else "color=c=0x1a1625:size=640x360:rate=15"
    subprocess.run([ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", src, "-i", str(mp3),
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(DATA / f"{name}.mp4")], check=True)
    mp3.unlink()
    (DATA / f"{name}.txt").write_text(SCRIPT)  # the reference script (same text for all = contrastive pair)
    print("wrote", DATA / f"{name}.mp4")


if __name__ == "__main__":
    for it in ITEMS:
        make(*it)
