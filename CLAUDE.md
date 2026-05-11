# CLAUDE.md — AI Assistant Guide for YouTube Shorts Maker

This file tells AI coding assistants (Claude, Cursor, Copilot, etc.) how to work effectively on this codebase.

---

## Project summary

A single-file Python CLI tool (`shorts_maker.py`) that converts local video files into YouTube Shorts. The pipeline is: FFmpeg audio extraction → Whisper transcription → AI segment selection → OpenCV face crop → FFmpeg clip + caption burn.

Read `CONTEXT.md` for the full architecture before making changes.

---

## Code conventions

- **One file, linear pipeline.** All logic lives in `shorts_maker.py`. Do not split into multiple modules unless specifically asked.
- **Functions are steps.** Each function corresponds to one labelled pipeline step. Keep that 1:1 relationship.
- **Global constants at the top.** `TARGET_DURATION`, `NUM_SHORTS`, `AI_PROVIDER`, etc. are overridden by `argparse` at runtime — do not turn them into function parameters or class attributes without good reason.
- **No classes** (except the two `@dataclass`s). Keep it procedural.
- **`subprocess` over Python bindings for FFmpeg.** Do not introduce `moviepy` or `ffmpeg-python`; the raw subprocess calls are intentional for transparency and control.
- **Type hints on all function signatures.**

---

## Adding a new AI provider

1. Create a `_select_via_<name>(prompt: str) -> list[Segment]` function following the pattern of `_select_via_claude` and `_select_via_deepseek`.
2. Call `_parse_segments(raw_text)` on the model's text output — do not duplicate that logic.
3. Add the new name to the `choices` list in the `--provider` argparse argument.
4. Add a row to the provider table in both `CONTEXT.md` and `README.md`.
5. Add the required env var and any new pip package to `requirements.txt`.

The shared prompt is built by `_build_prompt()`. Do not create provider-specific prompts — the schema must stay identical across all providers.

---

## Modifying caption style

Captions are written as **ASS (Advanced SubStation Alpha)** files in `build_ass()`.

- Font, size, and colour are set in the `[V4+ Styles]` section of the header string.
- ASS colour format is `&H00BBGGRR` (BGR, not RGB — this is a common mistake).
- Word grouping (currently 5 words per line) is controlled by the `GROUP` constant inside `build_ass`.
- Do not switch to SRT — ASS is required for the colour and positioning features used here.

---

## Modifying overlays

Overlays are pure FFmpeg `drawbox` / `drawtext` filter chains in `burn_captions_and_overlays()`.

- The `vf_parts` list is joined with `,` into a single `-vf` argument.
- The progress bar uses FFmpeg's `t` (current time) expression — keep the `duration` variable in scope when editing this.
- If adding a new overlay element, append to `vf_parts` before the join.
- **Font path** (`fontfile=`) is OS-specific. When suggesting changes, remind the user to verify the path on their system.

---

## FFmpeg patterns used in this project

| Task | Pattern |
|---|---|
| Get video duration | `ffprobe … -show_entries format=duration` |
| Get resolution | `ffprobe … -show_entries stream=width,height` |
| Seek before input | `-ss <start> -i video` (fast seek, may be slightly imprecise) |
| Face-crop + scale | `crop=W:H:X:0,scale=1080:1920:force_original_aspect_ratio=decrease,pad=…` |
| Burn ASS subs | `-vf ass=path/to/file.ass` |
| Animated drawbox | `drawbox=…:w='iw*(t/DURATION)'` |

---

## Testing guidance

There is no test suite. When making changes:

1. Use a short test video (< 2 min) to keep Whisper fast.
2. Check `temp/` after a run — inspect `captions_N.ass` to verify subtitle timing.
3. Play back a finished `shorts_output/*.mp4` in VLC or QuickTime to verify overlays.
4. If the AI provider call fails, add `print(raw)` before `_parse_segments(raw)` to inspect the raw response.

---

## What NOT to do

- **Do not add a GUI or web server** unless explicitly requested.
- **Do not auto-upload to YouTube** — the tool stops at local file output by design.
- **Do not cache or store transcripts** to disk between runs — keep the pipeline stateless.
- **Do not change the JSON schema** returned by the AI providers — `_parse_segments` depends on `segments[].start`, `.end`, `.title`, `.reason`.
- **Do not remove the `--provider` flag** or hard-code a single provider.
- **Do not import `anthropic` at the top level** — it is imported lazily inside `_select_via_claude` so the script works without it installed when using DeepSeek.

---

## Common tasks

**"Add a new provider X"** → see *Adding a new AI provider* above.

**"Make captions bigger / different colour"** → edit `build_ass()`, specifically the `Style:` line in the ASS header. Remember BGR colour order.

**"Use a better Whisper model"** → change `"base"` to `"small"`, `"medium"`, or `"large"` in `transcribe()`. Warn the user this increases RAM usage and run time.

**"Generate more or fewer shorts"** → `--num N` CLI flag, or change `NUM_SHORTS` default.

**"Support YouTube URL input"** → add `yt-dlp` as a dependency, detect if `video_path` is a URL (`http` prefix), download to `temp/` first, then pass the local path through the existing pipeline unchanged.

**"Add background music"** → after `extract_clip()`, mix in a music track with `ffmpeg -i clip.mp4 -i music.mp3 -filter_complex amix=inputs=2:duration=first` before caption burning.
