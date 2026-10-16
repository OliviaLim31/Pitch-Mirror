"""Pitch Mirror web server (the "switchboard" between the web page and the analysis engine).

Run from the pitch_mirror/ folder:
    py -3.12 -m uvicorn server:app --reload
Then open http://localhost:8000
"""
import json
import re
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pitch_mirror import pipeline as P, media, gemini, tts, flaws as F
from pitch_mirror.config import ROOT, CACHE_DIR, FILLERS, gemini_mode, GEMINI_MODEL

WEB = ROOT / "web"
UPLOADS = ROOT / "uploads"
SESSIONS = ROOT / "sessions"
RESPEAK = CACHE_DIR / "respeak"
DATA = ROOT / "data"
for d in (UPLOADS, SESSIONS, RESPEAK):
    d.mkdir(exist_ok=True)

AUDIO_EXT = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm"}
DEFAULT_RUBRICS = [
    {"id": "hackathon", "name": "Hackathon pitch", "minutes": 3, "focus": ["hook", "problem", "demo", "ask"]},
    {"id": "investor", "name": "Investor demo", "minutes": 5, "focus": ["problem", "market", "traction", "ask"]},
    {"id": "class", "name": "Class presentation", "minutes": 10, "focus": ["intro", "body", "summary"]},
    {"id": "event", "name": "Event hosting", "minutes": 5, "focus": ["welcome", "agenda", "energy"]},
]

app = FastAPI(title="Pitch Mirror")
JOBS = {}  # job_id -> live progress dict (kept in memory only)


# ───────────────────────── helpers ─────────────────────────
def _session_path(sid):
    if not re.fullmatch(r"[a-f0-9]{10}", sid):
        raise HTTPException(404, "Unknown session")
    return SESSIONS / f"{sid}.json"


def load_session(sid):
    p = _session_path(sid)
    if not p.exists():
        raise HTTPException(404, "Session not found")
    return json.loads(p.read_text())


def save_session(s):
    _session_path(s["id"]).write_text(json.dumps(s))


def load_rubrics():
    f = ROOT / "rubrics.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"[rubrics.json] invalid JSON, using defaults: {e}")
    return DEFAULT_RUBRICS


def is_filler(word):
    return re.sub(r"[^a-z]", "", word.lower()) in FILLERS


def group_flaws(flaws):
    """Bundle bursts of single filler words into one card ("Filler 'um' x6"), keep other flaws as they are."""
    out, burst = [], []

    def flush():
        if not burst:
            return
        words = [b["why"].split("'")[1] if "'" in b["why"] else "um" for b in burst]
        top = max(set(words), key=words.count).strip()
        sev = "high" if len(burst) >= 4 else "medium" if len(burst) >= 2 else "low"
        out.append({"type": "filler", "label": f"Filler \u201c{top}\u201d \u00d7{len(burst)}" if len(burst) > 1 else f"Filler \u201c{top}\u201d",
                    "start": burst[0]["start"], "end": burst[-1]["end"], "severity": sev, "count": len(burst),
                    "why": f"{len(burst)} filler word(s) in {burst[-1]['end'] - burst[0]['start']:.0f} seconds. " + burst[0]["why"],
                    "suggestion": burst[0]["suggestion"], "source": "acoustic"})
        burst.clear()

    for f in sorted(flaws, key=lambda x: x["start"]):
        if f["type"] == "filler":
            if burst and f["start"] - burst[-1]["end"] > 8:
                flush()
            burst.append(f)
        else:
            out.append(dict(f))
    flush()
    out.sort(key=lambda x: x["start"])
    for i, f in enumerate(out):
        f["idx"] = i
        if f["type"] in ("pace_fast",):
            m = re.search(r"(\d+) WPM", f["why"])
            if m:
                f["label"] = f"Too fast \u00b7 {m.group(1)} wpm"
    return out


def attention_curve(r, n=160):
    """ESTIMATED audience attention 0..1 from energy, pace and flaws. Honest heuristic, labelled as such in the UI."""
    dur = max(r["global"]["duration"], 1)
    ws = r["windows"]
    c = r["contours"]
    out = []
    for k in range(n):
        t = dur * k / (n - 1)
        a = 0.72
        w = min(ws, key=lambda w: abs((w["start"] + w["end"]) / 2 - t)) if ws else None
        if w:
            if w["energy_db"] is not None:
                a += max(-0.25, min(0.1, w["energy_db"] / 40))
            if w["wpm"]:
                a -= min(0.2, abs(w["wpm"] - 150) / 400)
            if w["pitch_std_st"] is not None:
                a += max(-0.1, min(0.08, (w["pitch_std_st"] - 2) / 20))
        for f in r["flaws"]:
            if f["start"] - 0.5 <= t <= f["end"] + 1.5:
                a -= {"high": 0.22, "medium": 0.12, "low": 0.06}[f["severity"]]
        if t < 10:  # first seconds: audience is still curious
            a += 0.05
        out.append(round(max(0.05, min(1.0, a)), 3))
    # gentle smoothing
    sm = [sum(out[max(0, i - 2): i + 3]) / len(out[max(0, i - 2): i + 3]) for i in range(n)]
    return [round(x, 3) for x in sm]


def headline(scores, ai):
    dims = scores["dimensions"]
    delivery = (dims["Pace"] + dims["Fluency (fillers)"] + dims["Pausing"] + dims["Energy / projection"]) / 4
    content = ai["content"]["score"] if ai and ai.get("content", {}).get("score") is not None else None
    if content is not None and content - delivery >= 1.5:
        return "Solid content, delivery drags it down"
    if content is not None and delivery - content >= 1.5:
        return "Confident delivery, content needs a sharper story"
    if scores["overall"] >= 80:
        return "Strong, confident delivery"
    if scores["overall"] >= 60:
        return "Good base, a few moments lose the room"
    return "Several moments lose the room"


def session_exists(sid):
    return bool(sid) and re.fullmatch(r"[a-f0-9]{10}", sid) is not None and (SESSIONS / f"{sid}.json").exists()


def public_session(s, full=True):
    r = s["result"]
    ai = r.get("ai") if r.get("ai") and not r["ai"].get("error") else None
    prev = s.get("previous")
    summary = {
        "id": s["id"], "name": s["name"], "speaker": s.get("speaker", "Olivia"), "rubric": s["rubric"],
        "created": s["created"], "file": r["file"], "duration": r["global"]["duration"],
        "overall": r["scores"]["overall"], "n_flaws": len(s["display_flaws"]), "is_video": r["is_video"],
        "previous": prev if session_exists(prev) else None,  # the take this one re-recorded (gone if it was deleted)
    }
    if not full:
        return summary
    return {**summary,
            "scores": r["scores"], "global": r["global"], "flaws": s["display_flaws"], "fixed": s.get("fixed", []),
            "headline": headline(r["scores"], ai), "attention": attention_curve(r),
            "words": [{"w": w["w"], "s": w["start"], "e": w["end"], "f": bool(w.get("filler"))} for w in r["words"]],
            "windows": [{"t": (w["start"] + w["end"]) / 2, "wpm": w["wpm"], "db": w["energy_db"]} for w in r["windows"]],
            "ai": ai, "ai_error": (r.get("ai") or {}).get("error"), "media_url": f"/api/media/{s['id']}",
            "transcript": r["transcript"], "version": r.get("version")}


# ───────────────────────── 🎓 Checkpoint 2: your first API endpoint ─────────────────────────
# 🎓 TODO (Olivia): write a GET endpoint at "/api/health" that returns
#    {"ok": True, "gemini": gemini_mode(), "model": GEMINI_MODEL}
#    Hint: look at how @app.get("/api/rubrics") is written just below, and copy its shape.
#    The green dot next to the workspace name in the top bar lights up once this works.


# ───────────────────────── API ─────────────────────────
@app.get("/api/rubrics")
def get_rubrics():
    return load_rubrics()


@app.get("/api/samples")
def samples():
    exts = media.VIDEO_EXT | AUDIO_EXT
    return [p.name for p in sorted(DATA.glob("*")) if p.suffix.lower() in exts]


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    suffix = Path(file.filename or "rec.webm").suffix.lower() or ".webm"
    if suffix not in media.VIDEO_EXT | AUDIO_EXT:
        raise HTTPException(400, f"Unsupported file type {suffix}")
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(file.filename or "recording").stem)[:60]
    dst = UPLOADS / f"{safe}_{uuid.uuid4().hex[:6]}{suffix}"
    with open(dst, "wb") as out:
        while chunk := await file.read(1 << 20):
            out.write(chunk)
    return {"upload": dst.name, "name": file.filename}


class AnalyzeReq(BaseModel):
    upload: str | None = None
    sample: str | None = None
    rubric: str = "hackathon"
    speaker: str = "Olivia"
    name: str | None = None  # the name you gave the file: shown in Sessions/Results, never used as a path
    previous: str | None = None  # id of the session this take re-records (from the Re-record button)


def _run_job(job_id, path, rubric, speaker, display_name, previous=None):
    job = JOBS[job_id]

    def prog(msg, frac):
        job["stage"], job["progress"] = msg, round(frac, 3)

    try:
        res = P.analyze(path, baseline=None, transcript_text=None, use_ai=gemini_mode() != "off", progress=prog)
        sid = uuid.uuid4().hex[:10]
        s = {"id": sid, "name": display_name, "speaker": speaker, "rubric": rubric, "created": time.time(),
             "path": str(path), "result": res, "display_flaws": group_flaws(res["flaws"]), "fixed": [],
             "previous": previous}
        save_session(s)
        job.update(status="done", progress=1.0, session=sid, stage="Done")
    except Exception as e:  # pragma: no cover
        job.update(status="error", error=str(e)[:400])


@app.post("/api/analyze")
def analyze(req: AnalyzeReq):
    if req.upload:
        path = UPLOADS / Path(req.upload).name
    elif req.sample:
        path = DATA / Path(req.sample).name
    else:
        raise HTTPException(400, "Give an upload or a sample")
    if not path.exists():
        raise HTTPException(404, "File not found")
    rub = next((r for r in load_rubrics() if r["id"] == req.rubric), load_rubrics()[0])
    # display name: your own name if you gave one (control characters removed, max 80), else the file on disk
    display = re.sub(r"[\x00-\x1f]", "", req.name or "").strip()[:80] or path.name
    previous = req.previous if session_exists(req.previous) else None  # ignore ids that don't exist
    job_id = uuid.uuid4().hex[:10]
    JOBS[job_id] = {"status": "running", "progress": 0.0, "stage": "Queued", "file": path.name, "name": display,
                    "rubric": rub, "started": time.time(), "is_video": media.is_video(path),
                    "gemini": gemini_mode(), "speaker": req.speaker}
    threading.Thread(target=_run_job, args=(job_id, path, rub, req.speaker, display, previous), daemon=True).start()
    return {"job": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "Unknown job")
    j = dict(JOBS[job_id])
    j["elapsed"] = round(time.time() - j["started"], 1)
    return j


@app.get("/api/jobs/{job_id}/media")
def job_media(job_id: str):
    j = JOBS.get(job_id)
    if not j:
        raise HTTPException(404)
    p = UPLOADS / j["file"] if (UPLOADS / j["file"]).exists() else DATA / j["file"]
    return FileResponse(p)


@app.get("/api/sessions")
def sessions():
    out = []
    for p in SESSIONS.glob("*.json"):
        try:
            out.append(public_session(json.loads(p.read_text()), full=False))
        except Exception:
            pass
    return sorted(out, key=lambda s: s["created"], reverse=True)


@app.get("/api/sessions/{sid}")
def session(sid: str):
    return public_session(load_session(sid))


@app.delete("/api/sessions/{sid}")
def delete_session(sid: str):
    _session_path(sid).unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/media/{sid}")
def session_media(sid: str):
    p = Path(load_session(sid)["path"])
    if not p.exists():
        raise HTTPException(404, "Original file missing")
    return FileResponse(p)


@app.post("/api/sessions/{sid}/flaws/{idx}/fixed")
def toggle_fixed(sid: str, idx: int):
    s = load_session(sid)
    fixed = set(s.get("fixed", []))
    fixed.symmetric_difference_update({idx})
    s["fixed"] = sorted(fixed)
    save_session(s)
    return {"fixed": s["fixed"]}


class RespeakReq(BaseModel):
    regenerate: bool = False
    tone: str = "confident"


@app.post("/api/sessions/{sid}/flaws/{idx}/respeak")
def respeak(sid: str, idx: int, req: RespeakReq):
    s = load_session(sid)
    flaws = s["display_flaws"]
    if not 0 <= idx < len(flaws):
        raise HTTPException(404, "Unknown flaw")
    f = flaws[idx]
    r = s["result"]
    a, b = max(0.0, f["start"] - 1.0), min(r["global"]["duration"], f["end"] + 1.0)
    text = P.segment_text(r, a, b)
    key = f"{sid}_{idx}"
    orig = RESPEAK / f"{key}_orig.mp3"
    new = RESPEAK / f"{key}_new.mp3"
    meta_p = RESPEAK / f"{key}.json"
    if meta_p.exists() and not req.regenerate:
        return json.loads(meta_p.read_text())
    if not orig.exists():
        media.cut_clip(s["path"], orig, a, b)
    problem = f"{f['label']}: {f['why']}"
    if req.regenerate:
        problem += f" Make it sound {req.tone}; try a different phrasing than before."
    rw = gemini.rewrite(text, problem)
    engine = tts.speak(rw["rewrite"], new)
    meta = {"original_text": text, "rewrite": rw["rewrite"], "why": rw.get("why", ""), "engine": engine,
            "original_url": f"/api/respeak/{orig.name}", "rewrite_url": f"/api/respeak/{new.name}?v={int(time.time())}",
            "original_fillers": sum(1 for w in text.split() if is_filler(w)),
            "rewrite_fillers": sum(1 for w in rw["rewrite"].split() if is_filler(w)),
            "span": [a, b], "tone": req.tone, "gemini": gemini_mode()}
    meta_p.write_text(json.dumps(meta))
    return meta


@app.get("/api/respeak/{name}")
def respeak_file(name: str):
    p = RESPEAK / Path(name).name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="audio/mpeg")


@app.post("/api/sessions/{sid}/flaws/{idx}/practice")
async def practice(sid: str, idx: int, file: UploadFile = File(...)):
    """Analyze a short practice take of one segment (acoustic only, no AI) and compare with the original segment."""
    s = load_session(sid)
    f = s["display_flaws"][idx]
    dst = UPLOADS / f"practice_{sid}_{idx}_{uuid.uuid4().hex[:4]}.webm"
    dst.write_bytes(await file.read())
    try:
        res = P.analyze_core(dst, None, False)
    except Exception as e:
        raise HTTPException(400, f"Could not analyze the take: {str(e)[:200]}")
    r = s["result"]
    seg = [w for w in r["words"] if w["end"] >= f["start"] - 1 and w["start"] <= f["end"] + 1]
    seg_dur = (seg[-1]["end"] - seg[0]["start"]) if len(seg) > 1 else 1
    return {"transcript": res["transcript"],
            "before": {"fillers": sum(1 for w in seg if w.get("filler")), "wpm": round(len(seg) / max(seg_dur, 0.5) * 60)},
            "after": {"fillers": res["global"]["filler_count"], "wpm": round(res["global"]["wpm"])}}


@app.get("/api/compare")
def compare(a: str, b: str):
    A, B = load_session(a), load_session(b)
    ra, rb = A["result"], B["result"]

    def ai_score(r, key):
        ai = r.get("ai") if r.get("ai") and not r["ai"].get("error") else None
        return ai.get(key, {}).get("score") if ai else None

    rows = [
        {"name": "Filler words", "a": ra["global"]["filler_count"], "b": rb["global"]["filler_count"], "better": "lower"},
        {"name": "Hook / content (AI)", "a": ai_score(ra, "content"), "b": ai_score(rb, "content"), "better": "higher"},
        {"name": "Pace (wpm)", "a": round(ra["global"]["wpm"]), "b": round(rb["global"]["wpm"]), "better": "closer150"},
        {"name": "Vocal variety", "a": ra["scores"]["dimensions"]["Vocal variety (pitch)"], "b": rb["scores"]["dimensions"]["Vocal variety (pitch)"], "better": "higher"},
        {"name": "Eye contact (AI)", "a": ai_score(ra, "visual"), "b": ai_score(rb, "visual"), "better": "higher"},
        {"name": "Overall", "a": round(ra["scores"]["overall"]), "b": round(rb["scores"]["overall"]), "better": "higher"},
    ]
    rows = [r for r in rows if r["a"] is not None and r["b"] is not None]
    # Reproducibility evidence = eval.py's cache-cleared reruns of the whole pipeline (re-scoring one cached
    # result would always give sigma 0 and prove nothing). Not run yet -> the badge says so.
    summ = ROOT / "eval_results" / "summary.json"
    ev = json.loads(summ.read_text()) if summ.exists() else None
    repro = {"available": bool(ev), "runs": ev["repeats"] if ev else 0, "files": ev["n_files"] if ev else 0,
             "sigma": round(ev["rerun_std_max"], 2) if ev else None, "version": rb.get("version"), "temperature": 0}
    fa, fb = ra["global"]["filler_count"], rb["global"]["filler_count"]
    if fa > 0 and fb < fa:
        head = {"text": "You cut fillers by", "value": f"{round((fa - fb) / fa * 100)}%"}
    else:
        d = round(rb["scores"]["overall"] - ra["scores"]["overall"])
        head = {"text": "Your overall score moved", "value": f"{d:+d} pts"}
    return {"a": public_session(A, full=False), "b": public_session(B, full=False), "rows": rows, "headline": head,
            "repro": repro,
            "timeline_a": [{"t": (w["start"] + w["end"]) / 2, "wpm": w["wpm"]} for w in ra["windows"]],
            "timeline_b": [{"t": (w["start"] + w["end"]) / 2, "wpm": w["wpm"]} for w in rb["windows"]],
            "flaws_a": [{"s": f["start"], "sev": f["severity"]} for f in A["display_flaws"]],
            "flaws_b": [{"s": f["start"], "sev": f["severity"]} for f in B["display_flaws"]]}


@app.get("/api/evaluation")
def evaluation():
    d = ROOT / "eval_results"
    if not (d / "summary.json").exists():
        return {"available": False}
    out = {"available": True, "summary": json.loads((d / "summary.json").read_text())}
    if (d / "results.csv").exists():
        lines = (d / "results.csv").read_text().strip().splitlines()
        hdr = lines[0].split(",")
        out["rows"] = [dict(zip(hdr, l.split(","))) for l in lines[1:]]
    out["has_plot"] = (d / "separation.png").exists()
    return out


@app.get("/api/evaluation/plot")
def evaluation_plot():
    p = ROOT / "eval_results" / "separation.png"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


@app.exception_handler(Exception)
async def all_errors(_, exc):  # pragma: no cover
    return JSONResponse({"detail": str(exc)[:300]}, status_code=500)


# The web page itself (must be mounted LAST so /api routes win)
app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
