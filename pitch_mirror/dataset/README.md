# Pitch Mirror contrastive dataset

Fill this in as you build the dataset. Judges weight data engineering at 30%, so document it carefully.

## Structure
```
dataset/
  good/        ideal baseline recordings (e.g. ted_1.wav) + transcript (ted_1.txt)
  bad/         your self-recorded flawed versions of the SAME transcripts (ted_1_bad_rushed.wav, ...)
  spectrum/    auto-generated graded flaws (made by make_spectrum.py) + labels.json
  labels.csv   one row per flaw region: file,type,start_s,end_s,level,notes
```

## Sources (baseline)
| file | speaker | source URL | licence | clip (start-end) |
|---|---|---|---|---|
| ted_1.wav | … | … | … | … |

## How the "bad spectrum" was built
1. **Synthetic gradient**: `python make_spectrum.py dataset/good/ted_1.wav` → levels L1 (almost perfect) to L4 (botched): tempo ×1.1/1.3/1.45/1.65, inserted silence 0/1.5/2.5/3.5 s, volume drop 0/0/−10/−16 dB on the last 30%, pitch flattening 0/50/75/95%. Flaw regions are written to `labels.json` automatically, so they are exact.
2. **Human flaws**: Olivia re-recorded the same transcript with injected fillers, rushing, mumbling and trailing off. Label each flaw's start/end in `labels.csv` (listen in VLC/Audacity and note the seconds).

## Alignment
Word timestamps come from faster-whisper (word-level timestamps = forced alignment to the audio). Saved in each analysis JSON (`words`).
