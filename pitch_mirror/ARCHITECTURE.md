# How Pitch Mirror works (the simple version)

Think of Pitch Mirror as a **building with five rooms**. Your recording walks through the rooms in order, and each room puts what it learned into a labelled **box** that travels with it.

```
 Room 1: Mailroom        Room 2: Listening room     Room 3: Measuring room      Room 4: Comparison room       Room 5: Gallery
 (media.py)              (transcribe.py)            (acoustic.py)               (flaws.py)                    (app.py)
 video/audio  ──►  16 kHz WAV  ──►  words + exact times  ──►  pitch, energy, MFCC,  ──►  flaw regions with   ──►  dashboard: timeline,
 (ffmpeg)                (Whisper = forced          pace, pauses, fillers       start/end + WHY + fix         jump-to-second, re-speak
                          alignment)                (speaker-normalized)        + rubric scores 0-10          before/after, eval
                                                                ▲
                                                 Baseline box: the SAME text spoken well
                                                 goes through rooms 1-3 too
```

**Room 1, the Mailroom (`media.py`).** Whatever arrives (mp4, mov, mp3, wav) gets unpacked into one standard box: a mono 16 kHz WAV. We use the ffmpeg that ships inside the `imageio-ffmpeg` package, so nobody has to install ffmpeg by hand.

**Room 2, the Listening room (`transcribe.py`).** faster-whisper writes down every word together with its start and end time. That is our **forced alignment**: each word gets pinned to its exact spot in the audio. We nudge Whisper to keep "um" and "uh" instead of cleaning them up. If that nudge makes it derail, it automatically retries without the nudge and keeps the better result. Decoding is greedy, float32 and single-threaded, so the same file always gives the same words (we tested 3 reruns: identical).

**Room 3, the Measuring room (`acoustic.py`).** librosa measures the voice every 20 ms:
- **Pitch (F0)** with the YIN algorithm, converted to **semitones relative to the speaker's own median**. A deep voice and a high voice are compared fairly (*speaker-agnostic*).
- **Energy**: RMS loudness in dB relative to the speaker's own typical loudness (75th percentile).
- **MFCCs and spectral centroid** (FFT-based timbre and brightness), stored in the report.
- From the words: **pace** (articulation rate in WPM inside 6-second sliding windows), **pauses** (silent stretches found in the energy curve), **fillers**, and **clarity** (Whisper's confidence for each word).

**Room 4, the Comparison room (`flaws.py`).** This is the heart of the system. If you give a **baseline** (the same script spoken well), the room lines the two recordings up **word by word** and asks, for the *same words*: were you faster? flatter? quieter? Did you pause longer? Every deviation larger than a threshold becomes a **flaw region** with:
- `start` / `end` seconds (temporal grounding),
- `why`: the maths in plain English, e.g. *"Speech rate 200 WPM vs baseline for the same words 150 WPM: +33%, z=+1.6"* (causal explanation),
- `suggestion`: what to do instead.

Without a baseline it compares against typical norms (100–195 WPM, pauses under 1.2 s, etc.).
The rubric then turns the flaws into **six scores from 0 to 10** (Pace, Fluency, Pausing, Vocal variety, Energy, Clarity) and a weighted **overall score out of 100**. The overall score uses **only maths, no AI**, so it is reproducible.

**Optional side room: the AI desk (`gemini.py`).** If you have a Gemini key, Gemini (temperature 0, fixed rubric prompt, JSON output) reads the timed transcript and about 1 frame per second of video. It adds notes on the hook, structure and eye contact, and rewrites flawed sentences. These AI scores are shown separately and are **not** mixed into the overall score. `MOCK=1` replaces Gemini with fixed fake answers for testing.

**Room 5, the Gallery (`app.py`).** A Streamlit dashboard:
- score ring and rubric bars,
- a 3-lane time-series (pitch, energy, pace) with the **baseline overlaid** (dotted) and flaw regions shaded; click a diamond or **▶ Jump** to play that exact second,
- **Re-speak**: cuts your original clip and plays the AI-improved version beside it (text-to-speech),
- **Before / After**: compare two takes,
- **Evaluation** results.

Every analysis box is saved as JSON in `cache/`, so re-opening a file costs no time and no API calls.

## How we prove it works (the 30% + 10% criteria)
- `make_spectrum.py` builds a **graded bad mirror** (L1 almost perfect → L4 botched) from one good recording, with exact labels of where each flaw was injected.
- `stress_test.py` checks that the score **drops as the level rises** and that the injected flaw regions are **caught at the right time** (start-time error in seconds).
- `eval.py` runs all `good_*` and `bad_*` files several times and reports the **mean gap**, **AUROC** (how often good beats bad), and the **rerun standard deviation** (0.0 means perfectly reproducible).

## One-sentence pitch for judges
"Pitch Mirror lines your speech up word by word with an ideal delivery of the same text, finds the exact seconds where your pace, pitch, energy or pauses break away, explains the gap in numbers, and plays you the fixed version."
