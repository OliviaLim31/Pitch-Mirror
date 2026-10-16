# 🪞 Pitch Mirror

## ▶️ Quick start
```powershell
git clone https://github.com/OliviaLim31/Pitch-Mirror.git
cd Pitch-Mirror\pitch_mirror
py -3.12 -m pip install -r requirements.txt   # first time only
py -3.12 -m uvicorn server:app --reload
```
Wait for `Application startup complete.`, then open **http://localhost:8000**.
The older Streamlit dashboard still works too: `py -3.12 -m streamlit run app.py` → http://localhost:8501.

**Contrastive speech analytics with temporal flaw grounding.** Built for Multimodal AI Hackathon 2026, Track C.

Upload a speech (video or audio) and, optionally, an "ideal" recording of the same text. Pitch Mirror finds the **exact seconds** where your delivery goes wrong (too fast, monotone, long pauses, fillers, trailing off), **explains why with numbers**, scores you with a reproducible rubric, and plays you a **fixed version** of the sentence.

> New to all of this? Follow the steps exactly in order. Every command goes into a **terminal**: **Terminal** on Mac (press Cmd+Space and type "Terminal") or **PowerShell** on Windows (Start menu → type "PowerShell").

---

## 1. Install (one time, about 10 minutes)

### Step 1: Install Python 3.12
- **Windows:** download Python 3.12 from https://www.python.org/downloads/ . On the first installer screen, **tick "Add python.exe to PATH"**, then click Install Now.
- **Mac:** download Python 3.12 from https://www.python.org/downloads/macos/ and run the installer.

Check that it worked:
- Windows: `py -3.12 --version`
- Mac: `python3.12 --version`

It should print `Python 3.12.x`.

**Supported Python versions: 3.11, 3.12, 3.13 and 3.14** (64-bit). If you already have one of the others,
use it and replace `3.12` in every command with your version, e.g. `py -3.14 -m pip install -r requirements.txt`.
On 3.11, pip automatically installs slightly older numpy / scipy / librosa (see `requirements.txt`); the
smoke test and the web app give identical scores on all four versions.
Not supported: **3.10 or older** (numpy, scipy and librosa no longer support them) and **3.15** (ctranslate2,
the engine Whisper runs on, has no build for it yet).

### Step 2: Get the project
Clone it (or unzip a copy), for example onto your Desktop, then move the terminal into the folder that contains `server.py`:
- Windows: `cd $HOME\Desktop` → `git clone https://github.com/OliviaLim31/Pitch-Mirror.git` → `cd Pitch-Mirror\pitch_mirror`
- Mac: `cd ~/Desktop` → `git clone https://github.com/OliviaLim31/Pitch-Mirror.git` → `cd Pitch-Mirror/pitch_mirror`

### Step 3: Create a virtual environment (a private box for this project's libraries)
**Windows (PowerShell):**
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```
If you get "running scripts is disabled", run this once, then try the activate line again:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

**Mac:**
```bash
python3.12 -m venv .venv
source .venv/bin/activate
```
You should now see `(.venv)` at the start of the terminal line. **Every time you open a new terminal, run the activate line again.**

### Step 4: Install the libraries
```bash
pip install --upgrade pip
pip install -r requirements.txt
```
This takes 3–8 minutes. You do not need to install ffmpeg; it comes bundled.

### Step 5: Get your free Gemini API key (optional but recommended)
1. Go to https://aistudio.google.com/apikey and sign in with Google.
2. Click **Create API key** and copy it.
3. In the project folder, copy `.env.example` to a new file named `.env`:
   - Windows: `copy .env.example .env`
   - Mac: `cp .env.example .env`
4. Open `.env` in Notepad or TextEdit and paste the key after the `=`: `GEMINI_API_KEY=AIza...your key...`

⚠️ Never share the `.env` file or put it on GitHub (it is already in `.gitignore`).
Your Gemini Pro *app subscription* is not the same thing as an API key; you need the key from AI Studio.
Without a key the app still works: all acoustic scores and flaws still run, and only the AI notes and AI rewrites are switched off.

---

## 2. Try it in 2 minutes with the test files
```bash
python make_test_data.py      # makes 4 robot-voice test videos in data/ (needs internet)
python -m uvicorn server:app --reload
```
Open http://localhost:8000:
1. Under the upload box, click a sample such as `bad_1.mp4` (or **Browse files** / **Record now**).
2. Click **Analyze your pitch →** next to the file. The first run downloads the Whisper speech model (about 150 MB, one time only).

Want to compare against a baseline recording of the same text? The Streamlit dashboard does that: `streamlit run app.py` → http://localhost:8501, then **Recording source → From data/ folder**, **Speech:** `bad_1.mp4`, **Baseline:** `good_1.mp4`, **✨ Analyze**.

Stop the app with **Ctrl+C** in the terminal.

---

## 3. Record your own dataset (the most important part: 30% of the score!)

Track C wants **the same text** delivered well and badly.

1. **Pick 2–3 good baselines**: short (30–90 s) clips of great speakers, e.g. a TED talk opening. Download the audio and write the exact transcript in a `.txt` file with the same name. Note the source URL in `dataset/README.md`.
2. **Record yourself saying the SAME text**, a few times with injected flaws:
   - rushed (too fast), monotone (flat voice), trailing off (getting quiet at sentence ends),
   - fillers ("um", "like", "you know"), long awkward pauses,
   - one "almost perfect" take.
   A phone voice memo or video is fine. Quiet room, phone 30 cm from your mouth.
3. Put files in `data/` named like this so the evaluation can find them:
   ```
   data/good_1.mp4   data/good_1.txt      (baseline + its transcript)
   data/bad_1.mp4    data/bad_1.txt       (your flawed version, same transcript)
   ```
4. **Make an automatic graded "bad mirror"** from each good file:
   ```bash
   python make_spectrum.py data/good_1.mp4
   python stress_test.py --baseline data/good_1.mp4
   ```
   This creates levels L1 (almost perfect) to L4 (botched) with exact flaw labels, and shows the score falling level by level (`eval_results/stress_gradient.png`).

---

## 4. Run the evaluation (proof that it works)
```bash
python eval.py --repeats 3 --baseline data/good_1.mp4
```
Results are saved in `eval_results/` (and shown in the app's 🧪 Evaluation tab):
- **mean gap**: how many points good speeches beat bad ones by,
- **AUROC**: 1.0 means every good file beat every bad file,
- **rerun std**: 0.0 means the same file gets the same score every time,
- `separation.png`: put this chart in your demo video!

Add `--no-ai` to save Gemini calls (the scores do not use AI anyway).

---

## 5. Use the dashboard
- **📊 Results**: score ring, rubric bars, pitch/energy/pace timeline with the baseline overlaid. Shaded regions are flaws. Click a ◆ diamond or **▶ Jump** to hear that second. The transcript highlights fillers (yellow) and flaw words (red). Download the report as JSON.
- **🔁 Re-speak**: choose a flaw, click **Re-speak**, and hear *your* clip next to the improved version.
- **📈 Before / After**: analyze your first take and your improved take, then compare.
- **🧪 Evaluation**: the results of `eval.py`.

---

## 6. Troubleshooting
| Problem | Fix |
|---|---|
| `py` / `python3.12` not found | Reinstall Python and tick "Add to PATH" (Windows). Close and reopen the terminal. |
| `No module named ...` | You forgot to activate: run the activate line from Step 3, then `pip install -r requirements.txt`. |
| First analysis is slow | It is downloading the Whisper model the first time. Later runs are fast, and repeated files are instant (cached). |
| Analysis is slow on long videos | Keep clips under 3 minutes. Optionally set `WHISPER_MODEL=tiny.en` in `.env`. |
| "Gemini error" banner | Check the key in `.env` (no quotes or spaces) and restart the app. Scores still work without it. Quota hit? Wait a minute, or use `MOCK=1`. |
| Re-speak has no audio | Text-to-speech needs internet (edge-tts, falling back to gTTS). |
| Video won't play in the browser | Convert it to mp4 (H.264) or upload the audio instead. `.mov` from iPhone sometimes won't preview, but it still analyzes. |
| Want to re-run from scratch | Delete the `cache/` folder. |
| Port already in use | `python -m uvicorn server:app --reload --port 8001` (Streamlit: `streamlit run app.py --server.port 8502`) |
| Browser says `ERR_CONNECTION_REFUSED` | The server is not running. Start it again and wait for `Application startup complete.` |

Test everything without a key: `MOCK=1 python tests/smoke_test.py` (on Windows PowerShell: `$env:MOCK=1; python tests/smoke_test.py`).

---

## Project map
```
server.py            web app server (FastAPI) → http://localhost:8000
web/                 web app pages: index.html, styles.css, app.js
app.py               Streamlit dashboard (older UI) → http://localhost:8501
eval.py              good vs bad separation + reproducibility
make_test_data.py    synthetic test videos (robot voice)
make_spectrum.py     graded bad-mirror generator with labels
stress_test.py       checks score gradient + flaw detection timing
pitch_mirror/        the engine: media, transcribe, acoustic, flaws, gemini, tts, pipeline
dataset/README.md    dataset documentation template
ARCHITECTURE.md      how it works, explained simply
TRACK_C_NOTES.md     official Track C requirements mapped to features
```

## Submission checklist (deadline Thu 15 Oct, 2:45 PM MYT)
- [ ] Public GitHub repo with this code and README (do **not** upload `.env`)
- [ ] Dataset in the repo or a public Google Drive link in this README
- [ ] Technical documentation of max 6 pages (start from ARCHITECTURE.md + dataset/README.md + eval charts)
- [ ] 3–10 minute YouTube video (unlisted is OK, English): dataset collection → stress test → dashboard catching flaws
- [ ] Devpost description + all team members added
