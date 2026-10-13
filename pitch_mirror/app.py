"""Pitch Mirror dashboard. Run with:  streamlit run app.py"""
import json
import tempfile
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from pitch_mirror import pipeline as P, media, gemini, tts
from pitch_mirror.config import ROOT, CACHE_DIR, gemini_mode, GEMINI_MODEL

st.set_page_config(page_title="Pitch Mirror", page_icon="🪞", layout="wide")
ACCENT = "#8B5CF6"
SEV_COL = {"high": "#F43F5E", "medium": "#F59E0B", "low": "#A78BFA"}
UPLOADS = ROOT / "uploads"
UPLOADS.mkdir(exist_ok=True)
DATA = ROOT / "data"

st.markdown(f"""
<style>
.block-container {{padding-top: 1.6rem;}}
h1, h2, h3 {{letter-spacing: -0.02em;}}
.pm-card {{background: linear-gradient(180deg,#1A1625,#141020); border:1px solid #2A2340; border-radius:16px; padding:16px 18px; margin-bottom:10px;}}
.pm-chip {{display:inline-block; padding:2px 10px; border-radius:999px; font-size:0.78rem; margin-right:6px; border:1px solid #3B2F63; color:#E9D5FF; background:#211a35;}}
.pm-muted {{color:#8A8799; font-size:0.88rem;}}
.pm-big {{font-size:3rem; font-weight:700; color:{ACCENT}; line-height:1;}}
.stButton>button {{border-radius:10px; border:1px solid #3B2F63;}}
.stButton>button:hover {{border-color:{ACCENT}; color:#E9D5FF;}}
mark.flaw {{background: rgba(244,63,94,.22); color:#FBCFE8; border-radius:4px; padding:0 2px;}}
mark.filler {{background: rgba(245,158,11,.25); color:#FDE68A; border-radius:4px; padding:0 2px;}}
</style>""", unsafe_allow_html=True)

ss = st.session_state
ss.setdefault("history", {})   # name -> analysis
ss.setdefault("current", None)
ss.setdefault("jump", 0.0)


def save_upload(f):
    if f is None:
        return None
    p = UPLOADS / f.name
    p.write_bytes(f.getbuffer())
    return p


def dataset_files():
    return sorted([p for p in DATA.glob("*") if p.suffix.lower() in media.VIDEO_EXT | {".wav", ".mp3", ".m4a", ".ogg", ".flac"}])


# ---------------- Sidebar ----------------
with st.sidebar:
    st.markdown("## 🪞 Pitch Mirror")
    mode = gemini_mode()
    st.markdown({"real": f"🟢 Gemini: **{GEMINI_MODEL}**", "mock": "🟡 Gemini: **MOCK mode** (fake AI answers)",
                 "off": "⚪ Gemini: **off** (no API key, acoustic analysis still works)"}[mode])
    st.caption("Scores come from acoustic maths and are reproducible. Gemini adds optional content/visual notes and rewrites.")
    st.divider()
    src = st.radio("Recording source", ["Upload", "From data/ folder"], horizontal=True)
    files = dataset_files()
    if src == "Upload":
        up = st.file_uploader("Speech (video or audio)", type=["mp4", "mov", "webm", "m4v", "wav", "mp3", "m4a"])
        target = save_upload(up)
    else:
        target = st.selectbox("Speech", files, format_func=lambda p: p.name) if files else None
    st.markdown("**Optional: baseline** (the SAME text, delivered well)")
    base_choice = st.selectbox("Baseline", [None] + files, format_func=lambda p: "None (use generic norms)" if p is None else p.name)
    base_up = st.file_uploader("…or upload a baseline", type=["mp4", "mov", "webm", "wav", "mp3", "m4a"], key="bup")
    base_path = save_upload(base_up) or base_choice
    tx_default = ""
    if target is not None and Path(target).with_suffix(".txt").exists():
        tx_default = Path(target).with_suffix(".txt").read_text()
    transcript = st.text_area("Optional: reference transcript / script", tx_default, height=100)
    use_ai = st.checkbox("Use Gemini notes", value=(mode != "off"), disabled=(mode == "off"))
    go_btn = st.button("✨ Analyze", type="primary", width="stretch", disabled=target is None)

if go_btn and target is not None:
    bar = st.progress(0.0, text="Starting…")
    prog = lambda m, f: bar.progress(min(1.0, f), text=m)
    try:
        base = P.analyze_core(base_path, None, False, prog) if base_path and Path(base_path) != Path(target) else None
        res = P.analyze(target, baseline=base, transcript_text=transcript or None, use_ai=use_ai, progress=prog)
        res["_path"] = str(target)
        label = Path(target).name + (f" vs {Path(base_path).name}" if base else "")
        ss.history[label] = res
        ss.current = label
        ss.jump = 0.0
        bar.empty()
    except Exception as e:
        bar.empty()
        st.error(f"Analysis failed: {e}")
        st.info("Tips: check the file plays on your computer; try a shorter clip (under 3 min); see README → Troubleshooting.")

st.markdown("# Pitch Mirror <span class='pm-muted'>· contrastive speech analytics with temporal flaw grounding</span>", unsafe_allow_html=True)
tabs = st.tabs(["📊 Results", "🔁 Re-speak", "📈 Before / After", "🧪 Evaluation", "ℹ️ How it works"])

res = ss.history.get(ss.current) if ss.current else None


def score_ring(v):
    fig = go.Figure(go.Pie(values=[v, 100 - v], hole=0.78, marker_colors=[ACCENT, "#2A2340"], textinfo="none", sort=False))
    fig.update_layout(showlegend=False, margin=dict(l=0, r=0, t=0, b=0), height=180, paper_bgcolor="rgba(0,0,0,0)",
                      annotations=[dict(text=f"<b>{v:.0f}</b><br><span style='font-size:11px'>/ 100</span>", x=0.5, y=0.5,
                                        font=dict(size=30, color="#E8E6F0"), showarrow=False)])
    return fig


def _smooth(v, k=3):
    """Rolling median over ~300 ms so the lines are readable (None = unvoiced gaps kept)."""
    arr = np.array([np.nan if x is None else x for x in v], dtype=float)
    out = arr.copy()
    for i in range(len(arr)):
        w = arr[max(0, i - k): i + k + 1]
        w = w[np.isfinite(w)]
        out[i] = np.median(w) if len(w) and np.isfinite(arr[i]) else np.nan
    return [None if not np.isfinite(x) else float(x) for x in out]


def timeline_fig(r):
    from plotly.subplots import make_subplots
    c, bo = r["contours"], r.get("baseline_overlay")
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.38, 0.32, 0.30],
                        subplot_titles=("Pitch (semitones vs speaker's own median)", "Energy (dB vs speaker's own loudness)", "Pace (words per minute)"))
    fig.add_trace(go.Scatter(x=c["t"], y=_smooth(c["pitch_st"]), name="You · pitch", line=dict(color=ACCENT, width=1.8)), 1, 1)
    fig.add_trace(go.Scatter(x=c["t"], y=_smooth(c["energy_db"]), name="You · energy", line=dict(color="#22D3EE", width=1.4)), 2, 1)
    if bo:
        fig.add_trace(go.Scatter(x=bo["t"], y=_smooth(bo["pitch_st"]), name="Baseline · pitch (time-aligned)", line=dict(color="#E9D5FF", width=1.2, dash="dot")), 1, 1)
        fig.add_trace(go.Scatter(x=bo["t"], y=_smooth(bo["energy_db"]), name="Baseline · energy", line=dict(color="#A5F3FC", width=1.1, dash="dot")), 2, 1)
    ws = r["windows"]
    fig.add_trace(go.Scatter(x=[(w["start"] + w["end"]) / 2 for w in ws], y=[w["wpm"] or None for w in ws], name="You · pace",
                             line=dict(color="#F59E0B", width=1.8, shape="spline")), 3, 1)
    fig.add_hrect(y0=100, y1=195, fillcolor="#22c55e", opacity=0.06, line_width=0, row=3, col=1)
    for f in r["flaws"]:
        fig.add_vrect(x0=f["start"], x1=max(f["end"], f["start"] + 0.25), fillcolor=SEV_COL[f["severity"]], opacity=0.13, line_width=0)
    fx = r["flaws"]
    fig.add_trace(go.Scatter(x=[f["start"] for f in fx], y=[11] * len(fx), mode="markers", name="Flaw (click to jump)",
                             marker=dict(size=12, color=[SEV_COL[f["severity"]] for f in fx], symbol="diamond", line=dict(width=1, color="#0E0B16")),
                             text=[f"#{f['id']} {f['label']} ({f['start']:.1f}-{f['end']:.1f}s)<br>{f['why'][:110]}" for f in fx],
                             hoverinfo="text", customdata=[f["start"] for f in fx]), 1, 1)
    fig.update_layout(height=560, margin=dict(l=10, r=10, t=30, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#141020",
                      font=dict(color="#B5B1C7"), legend=dict(orientation="h", y=-0.08), hovermode="closest")
    fig.update_yaxes(gridcolor="#221c33", zeroline=False)
    fig.update_yaxes(range=[-12, 13], row=1, col=1)
    fig.update_yaxes(range=[-40, 8], row=2, col=1)
    fig.update_xaxes(gridcolor="#221c33")
    fig.update_xaxes(title_text="time (s)", row=3, col=1)
    fig.update_annotations(font=dict(size=12, color="#8A8799"))
    return fig


def player(r):
    p = Path(r["_path"])
    if not p.exists():
        st.info("Original file not found on disk.")
        return
    start = int(ss.jump)
    if media.is_video(p):
        st.video(str(p), start_time=start)
    else:
        st.audio(str(p), start_time=start)
    st.caption(f"▶ Starting at {start}s. Click a flaw to jump.")


# ---------------- Results ----------------
with tabs[0]:
    if not res:
        st.markdown("<div class='pm-card'><b>Start here 👈</b><br><span class='pm-muted'>Pick a recording in the sidebar "
                    "(try <code>data/bad_1.mp4</code> with baseline <code>data/good_1.mp4</code>) and press <b>Analyze</b>.</span></div>", unsafe_allow_html=True)
    else:
        sc = res["scores"]
        c1, c2, c3 = st.columns([1.1, 2.2, 2.4])
        with c1:
            st.plotly_chart(score_ring(sc["overall"]), width="stretch", config={"displayModeBar": False})
            st.markdown(f"<div class='pm-muted' style='text-align:center'>{res['file']}<br>baseline: {res.get('baseline_file') or 'generic norms'}</div>", unsafe_allow_html=True)
        with c2:
            dims = {**sc["dimensions"], **sc["ai_dimensions"]}
            fig = go.Figure(go.Bar(x=list(dims.values()), y=list(dims.keys()), orientation="h",
                                   marker_color=[ACCENT if "AI" not in k else "#C084FC" for k in dims], text=[f"{v:.1f}" for v in dims.values()], textposition="outside"))
            fig.update_layout(height=250, margin=dict(l=0, r=30, t=0, b=0), xaxis=dict(range=[0, 11], visible=False),
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#E8E6F0"), yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        with c3:
            g = res["global"]
            m1, m2, m3 = st.columns(3)
            m1.metric("Pace (WPM)", f"{g['wpm']:.0f}")
            m2.metric("Fillers", f"{g['filler_count']}", f"{g['filler_per_min']:.1f}/min", delta_color="inverse")
            m3.metric("Pitch range", f"{g['pitch_std_st']:.1f} st")
            m4, m5, m6 = st.columns(3)
            m4.metric("Flaws", len(res["flaws"]))
            m5.metric("Clarity", f"{g['clarity_p']:.2f}")
            m6.metric("Script match", f"{res['script_match']:.0%}" if res.get("script_match") is not None else "–")
            if res.get("ai") and res["ai"].get("error"):
                st.warning(f"Gemini error (scores unaffected): {res['ai']['error'][:150]}")
            elif res.get("ai"):
                ai = res["ai"]
                st.markdown(f"<div class='pm-card'><span class='pm-chip'>AI · {ai.get('mode')}</span> <b>Hook:</b> {ai['content'].get('hook','')}<br>"
                            f"<b>Structure:</b> {ai['content'].get('structure','')}<br><b>Visual:</b> {ai.get('visual',{}).get('summary','')}</div>", unsafe_allow_html=True)

        st.markdown("### Timeline: where the delivery breaks")
        ev = st.plotly_chart(timeline_fig(res), width="stretch", on_select="rerun", selection_mode="points", key="tl")
        try:
            pts = ev.selection.points if ev and ev.selection else []
            if pts and pts[0].get("customdata") is not None:
                cd = pts[0]["customdata"]
                ss.jump = float(cd[0] if isinstance(cd, list) else cd)
        except Exception:
            pass

        left, right = st.columns([1.15, 1])
        with left:
            st.markdown("### Flaws, causes and fixes")
            types = sorted({f["label"] for f in res["flaws"]})
            pick = st.multiselect("Filter", types, default=types, label_visibility="collapsed")
            for f in [f for f in res["flaws"] if f["label"] in pick]:
                with st.container(border=True):
                    a, b = st.columns([5, 1])
                    a.markdown(f"<span class='pm-chip' style='border-color:{SEV_COL[f['severity']]}'>{f['severity'].upper()}</span>"
                               f"<b>#{f['id']} {f['label']}</b> <span class='pm-muted'>{f['start']:.1f}s → {f['end']:.1f}s · {f['source']}</span>", unsafe_allow_html=True)
                    if b.button("▶ Jump", key=f"j{f['id']}"):
                        ss.jump = max(0.0, f["start"] - 1.0)
                        st.rerun()
                    st.markdown(f"**Why (measured):** {f['why']}  \n**Fix:** {f['suggestion']}")
        with right:
            st.markdown("### Player")
            player(res)
            st.markdown("### Transcript")
            spans = [(f["start"], f["end"]) for f in res["flaws"] if f["type"] not in ("content", "visual", "filler")]
            html = []
            for w in res["words"]:
                cls = "filler" if w.get("filler") else ("flaw" if any(a - 0.05 <= w["start"] <= b + 0.05 for a, b in spans) else "")
                html.append(f"<mark class='{cls}'>{w['w']}</mark>" if cls else w["w"])
            st.markdown(f"<div class='pm-card' style='line-height:1.9'>{' '.join(html)}</div>", unsafe_allow_html=True)
            st.download_button("⬇️ Download report (JSON)", json.dumps(res, indent=2), file_name=f"{res['file']}_report.json")

# ---------------- Re-speak ----------------
with tabs[1]:
    if not res:
        st.info("Analyze a recording first.")
    else:
        opts = [f for f in res["flaws"] if f["type"] not in ("visual",)]
        if not opts:
            st.success("No flaws found. Nothing to re-speak 🎉")
        else:
            f = st.selectbox("Pick a flaw to fix", opts, format_func=lambda f: f"#{f['id']} {f['label']} · {f['start']:.1f}–{f['end']:.1f}s")
            a, b = max(0, f["start"] - 1.0), f["end"] + 1.0
            text = P.segment_text(res, a, b)
            st.markdown(f"<div class='pm-card'><span class='pm-chip'>Original</span> {text}</div>", unsafe_allow_html=True)
            if st.button("🔁 Re-speak this segment", type="primary"):
                with st.spinner("Rewriting and generating audio…"):
                    try:
                        out_dir = CACHE_DIR / "respeak"; out_dir.mkdir(exist_ok=True)
                        orig = out_dir / f"{res['hash']}_{f['id']}_orig.mp3"
                        media.cut_clip(res["_path"], orig, a, b)
                        rw = gemini.rewrite(text, f"{f['label']}: {f['why']}")
                        new = out_dir / f"{res['hash']}_{f['id']}_new.mp3"
                        engine = tts.speak(rw["rewrite"], new)
                        ss[f"rs_{res['hash']}_{f['id']}"] = {"orig": str(orig), "new": str(new), "rw": rw, "engine": engine}
                    except Exception as e:
                        st.error(f"Re-speak failed: {e}")
            r = ss.get(f"rs_{res['hash']}_{f['id']}")
            if r:
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("#### 🙁 You said")
                    st.audio(r["orig"])
                    st.markdown(f"<div class='pm-card'>{text}</div>", unsafe_allow_html=True)
                with c2:
                    st.markdown("#### 🌟 Try saying it like this")
                    st.audio(r["new"])
                    st.markdown(f"<div class='pm-card'>{r['rw']['rewrite']}</div>", unsafe_allow_html=True)
                st.caption(f"Why: {r['rw'].get('why','')} · voice by {r['engine']}")

# ---------------- Before / After ----------------
with tabs[2]:
    names = list(ss.history)
    if len(names) < 2:
        st.info("Analyze at least two recordings (e.g. your first take and your re-recorded take) to compare them.")
    else:
        c1, c2 = st.columns(2)
        A = c1.selectbox("Before", names, index=0)
        B = c2.selectbox("After", names, index=len(names) - 1)
        ra, rb = ss.history[A], ss.history[B]
        d1, d2, d3 = st.columns(3)
        d1.metric("Overall", f"{rb['scores']['overall']:.0f}", f"{rb['scores']['overall'] - ra['scores']['overall']:+.0f}")
        d2.metric("Fillers", rb["global"]["filler_count"], rb["global"]["filler_count"] - ra["global"]["filler_count"], delta_color="inverse")
        d3.metric("Flaws", len(rb["flaws"]), len(rb["flaws"]) - len(ra["flaws"]), delta_color="inverse")
        dims = list(ra["scores"]["dimensions"])
        fig = go.Figure([go.Bar(name="Before", x=dims, y=[ra["scores"]["dimensions"][k] for k in dims], marker_color="#4B3F72"),
                         go.Bar(name="After", x=dims, y=[rb["scores"]["dimensions"][k] for k in dims], marker_color=ACCENT)])
        fig.update_layout(barmode="group", height=340, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#141020", font=dict(color="#E8E6F0"), yaxis=dict(range=[0, 10.5]))
        st.plotly_chart(fig, width="stretch")

# ---------------- Evaluation ----------------
with tabs[3]:
    st.markdown("Does the score really separate **good** from **bad** speeches, and is it the same every time?  "
                "Run `python eval.py` (see README), then the results appear here.")
    ev_dir = ROOT / "eval_results"
    if (ev_dir / "summary.json").exists():
        s = json.loads((ev_dir / "summary.json").read_text())
        c = st.columns(4)
        c[0].metric("Mean gap (good − bad)", f"{s['mean_gap']:.1f} pts")
        c[1].metric("AUROC", f"{s['auroc']:.2f}")
        c[2].metric("Rerun std", f"{s['rerun_std_max']:.2f} pts")
        c[3].metric("Files", s["n_files"])
        if (ev_dir / "separation.png").exists():
            st.image(str(ev_dir / "separation.png"))
        if (ev_dir / "results.csv").exists():
            import pandas as pd
            st.dataframe(pd.read_csv(ev_dir / "results.csv"), width="stretch")
    else:
        st.info("No evaluation yet. Run:  python eval.py")

with tabs[4]:
    st.markdown((ROOT / "ARCHITECTURE.md").read_text() if (ROOT / "ARCHITECTURE.md").exists() else "See ARCHITECTURE.md")
