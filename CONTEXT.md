# CONTEXT.md — YouTube Shorts Maker

## What this project does

Takes a local video file and automatically produces **YouTube Shorts** (9:16, up to 90 s) by:

1. Extracting audio with **FFmpeg**
2. Transcribing speech word-by-word with **OpenAI Whisper**
3. Sending the transcript to an **AI provider** (Claude or DeepSeek) to select the most engaging 30-second windows
4. **Face-tracking** each clip with OpenCV to smart-crop to portrait orientation
5. Burning in **coloured captions** (ASS format) and visual overlays (title card, progress bar) with FFmpeg

---

## File structure

```
youtube_shorts_maker/
├── shorts_maker.py      # main script — entire pipeline lives here
├── requirements.txt     # Python dependencies
├── README.md            # user-facing setup & usage guide
├── CONTEXT.md           # this file — project context for devs / tools
├── CLAUDE.md            # guidance for AI assistants working on this codebase
├── shorts_output/       # final .mp4 files (git-ignored)
└── temp/                # intermediate files: audio, raw clips, .ass files (git-ignored)
```

---

## Key constants (top of `shorts_maker.py`)

| Constant | Default | Purpose |
|---|---|---|
| `TARGET_DURATION` | `30` | Seconds per Short |
| `SHORT_W / SHORT_H` | `1080 / 1920` | Output resolution (9:16) |
| `NUM_SHORTS` | `3` | How many clips to produce |
| `FACE_SAMPLE_RATE` | `2.0` | Seconds between OpenCV face samples |
| `CAPTION_COLORS` | 5-colour list | Rotates per clip |
| `AI_PROVIDER` | `"claude"` | Overridden by `--provider` CLI flag |

---

## AI providers

| Provider | CLI flag | Env var needed | Model used |
|---|---|---|---|
| Claude (default) | `--provider claude` | `ANTHROPIC_API_KEY` | `claude-opus-4-5` |
| DeepSeek | `--provider deepseek` | `DEEPSEEK_API_KEY` | `deepseek-chat` |

DeepSeek is accessed via its **OpenAI-compatible endpoint** (`https://api.deepseek.com`), so the `openai` Python package is used — not a DeepSeek-specific SDK.

Both providers receive identical prompts and must return the same JSON schema:

```json
{
  "segments": [
    {
      "start": 42.0,
      "end": 72.0,
      "title": "Mind Blowing AI Fact",
      "reason": "Surprising statistic with a clear before/after payoff."
    }
  ]
}
```

---

## Pipeline step-by-step

```
extract_audio()          → temp/audio.wav            (ffmpeg, 16 kHz mono WAV)
transcribe()             → list[Word]                (Whisper base model)
words_to_transcript()    → str                       (readable text with timestamps)
select_highlights()      → list[Segment]             (Claude or DeepSeek JSON)
  ├─ _build_prompt()
  ├─ _select_via_claude()  or  _select_via_deepseek()
  └─ _parse_segments()
extract_clip()           → temp/raw_N.mp4            (ffmpeg cut + face-crop + scale)
  └─ detect_face_crop_x() → (left, crop_w)           (OpenCV Haar cascade)
build_ass()              → temp/captions_N.ass       (ASS subtitle file)
burn_captions_and_overlays() → shorts_output/short_N_Title.mp4
```

---

## Data structures

```python
@dataclass
class Word:
    text:  str
    start: float   # seconds from video start
    end:   float

@dataclass
class Segment:
    start:  float
    end:    float
    title:  str    # ≤ 6 words, AI-generated
    reason: str    # one-sentence viral rationale
```

---

## External dependencies

| Tool | Version | How used |
|---|---|---|
| `ffmpeg` / `ffprobe` | any recent | audio extract, clip cut, scale, caption burn, overlays |
| `openai-whisper` | ≥ 20231117 | local speech transcription with word timestamps |
| `opencv-python` | ≥ 4.9 | Haar cascade face detection for smart crop |
| `anthropic` | ≥ 0.25 | Claude API client |
| `openai` | ≥ 1.30 | DeepSeek API client (OpenAI-compatible) |
| `numpy` | ≥ 1.26 | averaging face centre-x samples |

---

## Environment variables

| Variable | Required for |
|---|---|
| `ANTHROPIC_API_KEY` | `--provider claude` (default) |
| `DEEPSEEK_API_KEY` | `--provider deepseek` |

---

## Known limitations & gotchas

- **Font path** in `burn_captions_and_overlays` is hardcoded to a DejaVu font path (`/usr/share/fonts/…`). On macOS or Windows, change to a valid system font path.
- **Whisper `base` model** is fast but less accurate on noisy audio. Swap to `"small"` or `"medium"` in `transcribe()` for better results.
- **Face detection** uses a Haar cascade — it works well for frontal faces but may fall back to centre-crop for profiles or cutaway shots. This is intentional and silent.
- **ASS subtitle** colours are applied per-clip (not per-word) — one colour per Short.
- All temporary files persist in `temp/` after a run and can be deleted freely.
