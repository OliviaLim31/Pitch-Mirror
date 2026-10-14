"""Smoke test: python tests/smoke_test.py   (runs in MOCK mode, no API key needed; needs data/ from make_test_data.py)"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8")  # emoji-safe on Windows consoles
except Exception:
    pass

import os, sys, json, tempfile
from pathlib import Path
os.environ["MOCK"] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)

from pitch_mirror import pipeline as P, media, gemini, tts, flaws as F

ok = lambda m: print("  ✅", m)
assert (ROOT / "data/good_1.mp4").exists(), "run python make_test_data.py first"
print("1) ffmpeg:", media.ffmpeg_bin()); ok("ffmpeg found")
g = P.analyze_core("data/good_1.mp4", use_ai=True)
b = P.analyze("data/bad_1.mp4", baseline=g, transcript_text=(ROOT / "data/bad_1.txt").read_text())
for k in ["words", "windows", "pauses", "global", "contours", "flaws", "scores", "baseline_overlay"]:
    assert k in b, k
assert all({"start", "end", "type", "severity", "why", "suggestion"} <= set(f) for f in b["flaws"])
ok(f"pipeline: {len(b['words'])} words, {len(b['flaws'])} flaws, overall={b['scores']['overall']}")
gg = P.analyze("data/good_1.mp4")
assert gg["scores"]["overall"] > b["scores"]["overall"], "good should beat bad"
ok(f"good ({gg['scores']['overall']}) > bad ({b['scores']['overall']})")
assert b["global"]["filler_count"] >= 3; ok(f"fillers detected: {b['global']['filler_count']}")
assert b["ai"]["mode"] == "mock"; ok("Gemini mock mode works")
frames = media.sample_frames("data/good_1.mp4", 5); assert len(frames) == 5; ok("frame sampling")
with tempfile.TemporaryDirectory() as td:
    clip = media.cut_clip("data/bad_1.mp4", Path(td) / "c.mp3", 1, 4); assert clip.stat().st_size > 1000; ok("clip cut")
    rw = gemini.rewrite("um so like we built an app", "fillers"); assert "um" not in rw["rewrite"].split(); ok("rewrite (mock)")
    try:
        eng = tts.speak(rw["rewrite"], Path(td) / "t.mp3"); ok(f"TTS via {eng}")
    except Exception as e:
        print("  ⚠️ TTS needs internet:", e)
r2 = P.analyze("data/bad_1.mp4", baseline=g, transcript_text=(ROOT / "data/bad_1.txt").read_text())
assert r2["scores"] == b["scores"]; ok("reproducible (cached rerun identical)")

print("2) Streamlit AppTest")
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=240)
at.run(); assert not at.exception, at.exception; ok("app loads")
at.sidebar.radio[0].set_value("From data/ folder").run()
at.sidebar.selectbox[0].set_value(ROOT / "data/bad_1.mp4").run()
at.sidebar.selectbox[1].set_value(ROOT / "data/good_1.mp4").run()
at.sidebar.button[0].click().run(); assert not at.exception, at.exception
assert at.session_state["current"], "no analysis stored"; ok(f"analysis via UI: {at.session_state['current']}")
jump = [b_ for b_ in at.button if b_.label == "▶ Jump"]; assert jump
jump[0].click().run(); assert not at.exception; ok(f"jump button -> start {at.session_state['jump']}s")
print("\nALL SMOKE TESTS PASSED")

print("3) Re-speak + Before/After tabs")
rs = [b_ for b_ in at.button if "Re-speak" in b_.label]; assert rs
rs[0].click().run(); assert not at.exception, at.exception
assert len(at.get("audio")) >= 2, "re-speak audio missing"; ok("re-speak generated original + rewrite audio")
at.sidebar.selectbox[0].set_value(ROOT / "data/good_2.mp4").run(); at.sidebar.button[0].click().run()
assert not at.exception and len(at.session_state["history"]) == 2; ok("before/after has 2 analyses")
print("ALL TABS OK")
