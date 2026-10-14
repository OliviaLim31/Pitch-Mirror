# Track C notes — Contrastive Speech Analytics & Temporal Flaw Grounding

Source: the official Track C problem statement PDF (Drive id 1ewVNqeGBcg76GUUvoj0buPWueQrgDf_6), linked from the hackathon overview PDF. Fetched 13 Oct 2026.

## What the track really asks for (it is mostly about AUDIO)
1. **Contrastive dataset**
   - "Good" baseline: real recordings of strong speakers (TED, politicians, debaters), transcribed.
   - "Bad" spectrum: the SAME transcript re-delivered with injected flaws (self-recorded, synthesized or edited), as a gradient from "botched" to "almost perfect".
   - Labels: paired good/bad files with start/end timestamps of each flaw.
2. **Forced alignment and feature extraction**: map words to timestamps; FFT, MFCCs, pitch/F0 contours, speech rate, pauses, vocal clarity.
3. **Temporal grounding and causal explanation**: exact start/end of each flaw region that deviates from the baseline, plus a human-readable explanation of the maths ("why").
4. **Dashboard**: upload audio + transcript; time-series overlay of baseline vs participant features, flaw regions highlighted with explanations.

Tech considerations: quality over quantity; **speaker-agnostic** (normalize pitch and energy per speaker); good temporal precision; **reproducible** across runs.

## Deliverables
- Public GitHub repo with code + docs (README with setup, dependencies, how to run).
- The dataset (paired audio, transcripts, alignment labels) in GitHub or a public Drive link in the README.
- Working dashboard prototype.
- Technical documentation of max 6 pages (dataset construction, rubric, architecture, scoring).
- 3–10 minute YouTube video (unlisted is OK, English audio or subtitles): dataset collection, stress tests across speech qualities, dashboard catching flaws.
- Devpost: description, repo link, video, all team members with real names.

## Judging weights → what Pitch Mirror does for each
| Criterion | Weight | Pitch Mirror feature |
|---|---|---|
| Causal explainability & temporal grounding | 25% | Every flaw has start/end seconds, a measured number vs the baseline (e.g. "182 WPM vs baseline 141, +29%, z=+2.4") and a plain-English cause + fix |
| Data engineering & stress testing | **30%** | `dataset/` structure + `make_spectrum.py`, which builds a graded bad-mirror (levels 1–4) from one good recording by speeding up, flattening pitch, lowering volume and inserting pauses, with auto-written labels. Plus Olivia's own self-recorded pairs |
| Feature extraction | 20% | librosa: RMS energy (dB), F0 via YIN (semitones vs speaker median), MFCC, spectral centroid/FFT, WPM, pauses, fillers, Whisper word confidence |
| Visualization & dashboard | 15% | Streamlit dark dashboard: pitch/energy/pace overlay vs baseline, shaded flaw regions, click-to-jump, re-speak A/B |
| Reproducibility & code quality | 10% | Deterministic acoustic core (no AI needed for scores), Gemini at temperature 0 and cached, `eval.py` reports rerun std and AUROC |

## Important adjustments vs the original "video pitch" idea
- The core must work on **audio + transcript**. Video/visual (eye contact, gestures) is a bonus layer, not the main thing.
- The baseline must be **the same text** delivered well. Upload a baseline file and the app compares against it word by word. Without one, it falls back to generic norms.
- Scores come from deterministic acoustic maths. Gemini is used only for the optional content/visual notes and the rewrite, so the scores are reproducible.
