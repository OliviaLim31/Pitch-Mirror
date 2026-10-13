"""Audio/video helpers. Uses the ffmpeg binary bundled with imageio-ffmpeg, so no system install is needed."""
import subprocess
from pathlib import Path

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}


def ffmpeg_bin() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:  # pragma: no cover
        raise RuntimeError("Could not find ffmpeg. Run: pip install imageio-ffmpeg") from e


def is_video(path) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXT


def _run(args):
    r = subprocess.run([ffmpeg_bin(), "-y", "-loglevel", "error", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr.strip()[:500]}")


def extract_wav(src, dst, sr=16000):
    """Any audio/video file -> mono 16 kHz WAV."""
    _run(["-i", str(src), "-vn", "-ac", "1", "-ar", str(sr), "-acodec", "pcm_s16le", str(dst)])
    return dst


def cut_clip(src, dst, start, end):
    """Cut an audio clip (mp3) between start and end seconds."""
    start = max(0.0, float(start))
    dur = max(0.3, float(end) - start)
    _run(["-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-i", str(src), "-vn", "-ac", "1", "-ar", "44100", str(dst)])
    return dst


def sample_frames(src, max_frames=20, fps=1.0):
    """Return list of (t_seconds, jpeg_bytes) sampled ~1 fps, capped to max_frames evenly."""
    import cv2
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        return []
    vfps = cap.get(cv2.CAP_PROP_FPS) or 25
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    dur = n / vfps if n else 0
    if dur <= 0:
        cap.release()
        return []
    k = min(max_frames, max(1, int(dur * fps)))
    times = [dur * (i + 0.5) / k for i in range(k)]
    out = []
    for t in times:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        if w > 640:
            frame = cv2.resize(frame, (640, int(h * 640 / w)))
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            out.append((round(t, 2), buf.tobytes()))
    cap.release()
    return out
