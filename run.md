# Quick Start

## Setup
```bash
uv sync
```

Ensure FFmpeg, ffprobe, and ffmpeg are installed and in PATH.

## Basic Usage
```bash
python shorts_maker.py <video.mp4>
```

This generates YouTube Shorts in `shorts_output/` using defaults:
- **Provider:** Claude (requires `ANTHROPIC_API_KEY`)
- **Number of shorts:** 3
- **Target duration per short:** 60 seconds

## Key Flags

| Flag | Example | Purpose |
|------|---------|---------|
| `--num` | `--num 5` | Generate N shorts (default: 3) |
| `--target-duration` | `--target-duration 45` | Short duration in seconds (default: 60) |
| `--provider` | `--provider deepseek` | AI provider: `claude` or `deepseek` (default: claude) |
| `--output-dir` | `--output-dir ./my_shorts` | Output directory (default: shorts_output) |

## Examples

```bash
# 5 shorts, 45 seconds each, using DeepSeek
python shorts_maker.py video.mp4 --num 5 --target-duration 45 --provider deepseek

# Custom output directory
python shorts_maker.py video.mp4 --output-dir ./youtube_ready
```

## Environment Variables

- `ANTHROPIC_API_KEY` – Claude API key (required for Claude provider)
- `DEEPSEEK_API_KEY` – DeepSeek API key (required for DeepSeek provider)

## Pipeline

Video → Extract Audio → Transcribe (Whisper) → Select Segments (AI) → Face Crop → Burn Captions + Overlays → Output

## Debugging

- Check `temp/` for intermediate files (transcripts, ASS caption files)
- Inspect `temp/captions_N.ass` to verify subtitle timing
- Use `--provider deepseek` if you lack Anthropic credits
