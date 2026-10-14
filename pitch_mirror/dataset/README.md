# Pitch Mirror contrastive dataset

The same text, delivered well and delivered badly, with a timestamped label for every flaw.
Two scripts, each with a public-speaker baseline, my own best take, six self-recorded flawed takes
and an automatically generated L1–L4 "bad mirror".

## Structure
```
dataset/
  plan.json              scripts (numbered sentences) + which flaw goes into which sentence, per take
  manifest.csv           one row per clip: file, script, speaker, source type, level, duration, sha256, source, licence, consent
  labels.csv             one row per flaw region (schema below)
  moon/                  script 1: JFK, Rice University, 12 Sep 1962
    script.txt
    good_moon_jfk.wav            external baseline (level 0)
    good_moon_olivia.wav         self baseline (level 0)
    bad_moon_olivia_L3_rushed.wav  … one file per flawed take, each with a .txt copy of the script
  challenger/            script 2: Ronald Reagan, Challenger address, 28 Jan 1986 (same layout)
  spectrum/              synthetic L1–L4 levels made from each baseline + labels.json (exact injected regions)
```
File names follow `good|bad_<script>_<speaker>[_L<level>_<flaw>]`, so `eval.py` picks them up with no extra config.

## Baseline sources
| clip | speaker | excerpt of the original | source | licence |
|---|---|---|---|---|
| `moon/good_moon_jfk.wav` | John F. Kennedy | 8:21.2–9:14.0 ("But why, some say, the Moon?" … "and the others, too.") | [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Jfk_rice_university_we_choose_to_go_to_the_moon.ogg), from the JFK Presidential Library | Public domain (US federal government work) |
| `challenger/good_challenger_reagan.wav` | Ronald Reagan | 1:35.1–2:22.3 ("We've grown used to wonders" … "it belongs to the brave.") | [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Ronald_Reagan_speaks_on_the_Challenger_Space_Shuttle_Disaster.ogg), from the Reagan Presidential Library | Public domain (US federal government work) |

Retrieved 14 Oct 2026. Excerpts were cut with ffmpeg and converted to 16 kHz mono WAV; nothing else was changed.
Transcripts in `script.txt` follow what is actually said in each excerpt (checked against word-level Whisper output),
with numbers written as digits ("35", "25") the way the speech recogniser outputs them.

**Why two baselines per script?** The public speaker is a strong rhetorical reference; my own best take is a
same-speaker reference that isolates delivery from voice. Comparing both tests whether the speaker normalisation
(pitch in semitones vs the speaker's median, energy vs the speaker's own loudness) makes cross-speaker comparison fair.

## Self-recorded takes
Recorded with `record_take.py` (laptop microphone, same room and position for every take, 3 s of silence at the start,
16 kHz mono WAV). Each flawed take injects its flaw only in the sentences listed in `plan.json`; every other sentence
is read normally, which keeps the regions clean to label.

| take | level | injected flaw | moon sentences | challenger sentences |
|---|---|---|---|---|
| best | 0 | none | – | – |
| rushed | 3 | pace_fast | 8–9 | 7–8 |
| monotone | 3 | monotone | 3–5 | 3–4 |
| trailing | 2 | low_energy | 9–10 | 9–11 |
| fillers | 3 | filler | 3–5 | 4–6 |
| pauses | 2 | long_pause (≈3 s) | after "highest" (3), "organize" (9) | after "States" (3), "process" (9) |
| botched | 4 | all of the above | fillers 3–4, rush 8, pause after "organize", quiet 10 | fillers 4–5, rush 7–8, pause after "process", quiet 11 |

## Synthetic bad mirror
`python make_spectrum.py <baseline>` builds levels L1 (almost perfect) to L4 (botched): tempo ×1.1/1.3/1.45/1.65,
inserted silence 0/1.5/2.5/3.5 s at 40 % of the clip, volume drop 0/0/−10/−16 dB on the last 30 %, pitch flattening
0/50/75/95 %. The regions are written by the generator into `spectrum/labels.json`, so they are exact.

## Labels (`labels.csv`)
| column | example | notes |
|---|---|---|
| clip_id | `bad_moon_olivia_L3_rushed` | file stem |
| script_id / speaker_id | `moon` / `olivia` | |
| source_type | `self_flawed`, `synthetic` | |
| level | 0–4 | 0 = baseline, 1 = almost perfect, 4 = botched |
| flaw_type | `pace_fast`, `monotone`, `low_energy`, `filler`, `long_pause` | same vocabulary as the detector |
| start_s, end_s | 26.74, 34.70 | seconds from the start of the file |
| label_method | `injected_exact`, `plan_word_aligned` | see below |
| labeler, notes | `olivia`, `sentences 8-9` | |

- **`injected_exact`** (synthetic clips): copied from `spectrum/labels.json`.
- **`plan_word_aligned`** (self-recorded clips): `make_labels.py` takes the sentences from `plan.json` and snaps the region
  to the first and last word Whisper finds there (fillers inserted at the edges included). A pause runs from the end of
  the word before the freeze to the start of the next word. Labels never use the detector's output.
  <!-- TODO(Olivia): after listening to a few regions in Audacity, add one line here saying which clips you checked. -->


## Reproduce
```bash
py -3.12 record_take.py                       # checklist / record takes
py -3.12 make_spectrum.py dataset/moon/good_moon_jfk.wav   # once per baseline
py -3.12 make_labels.py                       # → labels.csv + manifest.csv
py -3.12 stress_test.py --baseline dataset/moon/good_moon_jfk.wav
py -3.12 eval.py --plan --repeats 3 --no-ai   # good vs bad separation + rerun stability
py -3.12 eval_labels.py                       # timestamp accuracy vs labels
```

## Licence and consent
- Baseline excerpts: public domain (see sources above).
- My own recordings and everything derived from them: CC BY 4.0.
- **Consent:** to be confirmed by the speaker before the self-recorded takes are published.

## Known limitations
- Small by design (2 scripts, 3 speakers): confidence is per clip, not a population claim.
- The JFK excerpt contains crowd applause after "We choose to go to the Moon"; it is kept as recorded.
- Labels for self-recorded takes share Whisper's word timing with the detector, so timing error for word-level flaws
  (fillers) is not fully independent evidence. Pace, energy and pause regions are judged by different signals.
- Thresholds were tuned on synthetic voices before this dataset existed and were not changed afterwards.
