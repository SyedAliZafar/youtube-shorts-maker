"""
YouTube Shorts Maker
====================
Turns a local video into viral-ready Shorts using:
- OpenAI Whisper  → word-level transcription
- Claude API      → AI highlight selection  (default)
- DeepSeek API    → AI highlight selection  (optional, --provider deepseek)
- OpenCV          → face-tracking smart crop
- FFmpeg          → video processing & caption burning
"""

import os
import json
import subprocess
import tempfile
import re
import argparse
from pathlib import Path
from dataclasses import dataclass

import cv2
import whisper
import numpy as np

# ─────────────────────────────────────────────
#  Config
# ─────────────────────────────────────────────
TARGET_DURATION   = 30          # seconds per short
SHORT_W, SHORT_H  = 1080, 1920  # 9:16 vertical
NUM_SHORTS        = 3           # how many to generate
FACE_SAMPLE_RATE  = 2.0         # seconds between face-detection frames
CAPTION_COLORS    = [           # cycles per speaker / segment
    "#FF6B6B",  # coral red
    "#4ECDC4",  # teal
    "#FFE66D",  # yellow
    "#A8E6CF",  # mint
    "#FF8B94",  # pink
]

OUTPUT_DIR = Path("shorts_output")
TEMP_DIR   = Path("temp")

# AI provider: "claude" | "deepseek"  (overridden by --provider CLI flag)
AI_PROVIDER = "claude"


# ─────────────────────────────────────────────
#  Data structures
# ─────────────────────────────────────────────
@dataclass
class Word:
    text:  str
    start: float
    end:   float

@dataclass
class Segment:
    start:    float
    end:      float
    reason:   str
    title:    str


# ─────────────────────────────────────────────
#  Step 1 – Extract audio
# ─────────────────────────────────────────────
def extract_audio(video_path: str) -> str:
    audio_path = str(TEMP_DIR / "audio.wav")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        audio_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"✅ Audio extracted → {audio_path}")
    return audio_path


# ─────────────────────────────────────────────
#  Step 2 – Transcribe with Whisper
# ─────────────────────────────────────────────
def transcribe(audio_path: str) -> list[Word]:
    print("🎙️  Transcribing with Whisper (this may take a moment)…")
    model = whisper.load_model("base")
    result = model.transcribe(audio_path, word_timestamps=True)

    words: list[Word] = []
    for seg in result["segments"]:
        for w in seg.get("words", []):
            words.append(Word(
                text  = w["word"].strip(),
                start = w["start"],
                end   = w["end"],
            ))

    print(f"✅ Transcribed {len(words)} words")
    return words


def words_to_transcript(words: list[Word]) -> str:
    """Build a readable transcript with timestamps every ~30 s."""
    lines, last_mark = [], -30.0
    for w in words:
        if w.start - last_mark >= 30:
            lines.append(f"\n[{w.start:.1f}s] ")
            last_mark = w.start
        lines.append(w.text + " ")
    return "".join(lines)


# ─────────────────────────────────────────────
#  Step 3 – AI highlight selection
#  Supports: Claude (default) | DeepSeek
# ─────────────────────────────────────────────
def _build_prompt(transcript: str, video_duration: float) -> str:
    return f"""You are a viral short-form video editor.
Analyse this video transcript and pick exactly {NUM_SHORTS} segments
that would each make an outstanding ~{TARGET_DURATION}-second YouTube Short.

Rules:
- Each segment MUST be between {TARGET_DURATION - 5} and {TARGET_DURATION + 5} seconds long.
- Prefer segments with a clear hook, emotional punch, surprising fact, or satisfying payoff.
- Segments must NOT overlap.
- Video total duration: {video_duration:.1f}s

Return ONLY valid JSON (no markdown, no explanation):
{{
  "segments": [
    {{
      "start": <float seconds>,
      "end": <float seconds>,
      "title": "<catchy short title ≤ 6 words>",
      "reason": "<one sentence why this will go viral>"
    }}
  ]
}}

TRANSCRIPT:
{transcript}
"""


def _parse_segments(raw: str) -> list[Segment]:
    raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
    raw = re.sub(r"\n?```$", "", raw)
    data = json.loads(raw)
    return [
        Segment(
            start  = float(s["start"]),
            end    = float(s["end"]),
            title  = s["title"],
            reason = s["reason"],
        )
        for s in data["segments"]
    ]


def _select_via_claude(prompt: str) -> list[Segment]:
    import anthropic
    client  = anthropic.Anthropic()          # reads ANTHROPIC_API_KEY
    message = client.messages.create(
        model      = "claude-opus-4-5",
        max_tokens = 1024,
        messages   = [{"role": "user", "content": prompt}],
    )
    return _parse_segments(message.content[0].text)


def _select_via_deepseek(prompt: str) -> list[Segment]:
    """
    DeepSeek uses an OpenAI-compatible API endpoint.
    Reads DEEPSEEK_API_KEY from the environment.
    """
    from openai import OpenAI
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "DEEPSEEK_API_KEY is not set. "
            "Export it before running: export DEEPSEEK_API_KEY='your-key'"
        )
    client   = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    response = client.chat.completions.create(
        model    = "deepseek-chat",
        messages = [{"role": "user", "content": prompt}],
        max_tokens = 1024,
    )
    return _parse_segments(response.choices[0].message.content)


def select_highlights(transcript: str, video_duration: float) -> list[Segment]:
    provider = AI_PROVIDER.lower()
    label    = {"claude": "Claude", "deepseek": "DeepSeek"}.get(provider, provider)
    print(f"🤖 Asking {label} to pick the best moments…")

    prompt = _build_prompt(transcript, video_duration)

    if provider == "deepseek":
        segments = _select_via_deepseek(prompt)
    else:
        segments = _select_via_claude(prompt)   # default

    for i, seg in enumerate(segments, 1):
        print(f"  [{i}] {seg.start:.1f}s–{seg.end:.1f}s | "{seg.title}"")
        print(f"       → {seg.reason}")
    return segments


# ─────────────────────────────────────────────
#  Step 4 – Face-tracking crop region
# ─────────────────────────────────────────────
def detect_face_crop_x(video_path: str, start: float, end: float,
                        src_w: int, src_h: int) -> int:
    """
    Sample frames in the segment, find average face centre-x,
    return the best crop left-edge for a 9:16 vertical window.
    """
    crop_w = int(src_h * SHORT_W / SHORT_H)   # width of 9:16 window in source res
    crop_w = min(crop_w, src_w)

    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0

    cx_samples = []
    t = start
    while t < end:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ret, frame = cap.read()
        if not ret:
            break
        gray   = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces  = face_cascade.detectMultiScale(gray, 1.1, 4)
        if len(faces):
            # use the largest face
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            cx_samples.append(x + w // 2)
        t += FACE_SAMPLE_RATE

    cap.release()

    if cx_samples:
        avg_cx = int(np.mean(cx_samples))
    else:
        avg_cx = src_w // 2   # fallback: centre

    # clamp so the crop window fits inside the source frame
    left = avg_cx - crop_w // 2
    left = max(0, min(left, src_w - crop_w))
    return left, crop_w


# ─────────────────────────────────────────────
#  Step 5 – Extract & reframe clip
# ─────────────────────────────────────────────
def extract_clip(video_path: str, seg: Segment, index: int) -> str:
    """Cut the segment, face-crop to 9:16, scale to 1080×1920."""
    raw_path = str(TEMP_DIR / f"raw_{index}.mp4")

    # get source resolution
    probe = subprocess.run([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0", video_path
    ], capture_output=True, text=True, check=True)
    src_w, src_h = map(int, probe.stdout.strip().split(","))

    left, crop_w = detect_face_crop_x(video_path, seg.start, seg.end, src_w, src_h)

    duration = seg.end - seg.start
    vf = (
        f"crop={crop_w}:{src_h}:{left}:0,"
        f"scale={SHORT_W}:{SHORT_H}:force_original_aspect_ratio=decrease,"
        f"pad={SHORT_W}:{SHORT_H}:(ow-iw)/2:(oh-ih)/2:black"
    )

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(seg.start), "-i", video_path,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        raw_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"  ✂️  Clip {index} extracted & reframed → {raw_path}")
    return raw_path


# ─────────────────────────────────────────────
#  Step 6 – Build ASS subtitle file (coloured)
# ─────────────────────────────────────────────
def build_ass(words: list[Word], seg: Segment, color_hex: str, index: int) -> str:
    """
    Generate an ASS subtitle file with coloured word-level captions.
    Words are grouped into short lines of ≤5 words.
    """
    # ASS colour format: &H00BBGGRR  (no alpha = &H00)
    h = color_hex.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    ass_color = f"&H00{b:02X}{g:02X}{r:02X}"

    ass_path = str(TEMP_DIR / f"captions_{index}.ass")

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {SHORT_W}
PlayResY: {SHORT_H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,72,{ass_color},&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,2,2,60,60,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def ts(t: float) -> str:
        t = max(0.0, t - seg.start)
        h_  = int(t // 3600)
        m_  = int((t % 3600) // 60)
        s_  = int(t % 60)
        cs_ = int((t % 1) * 100)
        return f"{h_}:{m_:02d}:{s_:02d}.{cs_:02d}"

    # filter words in this segment
    seg_words = [w for w in words if seg.start <= w.start < seg.end]

    GROUP = 5
    events = []
    for i in range(0, len(seg_words), GROUP):
        chunk = seg_words[i : i + GROUP]
        text  = " ".join(w.text for w in chunk)
        start = ts(chunk[0].start)
        end   = ts(chunk[-1].end)
        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(events) + "\n")

    return ass_path


# ─────────────────────────────────────────────
#  Step 7 – Burn captions + overlays
# ─────────────────────────────────────────────
def burn_captions_and_overlays(clip_path: str, ass_path: str,
                                seg: Segment, index: int) -> str:
    out_path = str(OUTPUT_DIR / f"short_{index:02d}_{seg.title.replace(' ','_')}.mp4")

    duration = seg.end - seg.start

    # Build a progress-bar + title-card via drawtext / drawbox
    title_safe = seg.title.replace("'", "\\'").replace(":", "\\:")

    vf_parts = [
        # subtitles
        f"ass={ass_path}",
        # top gradient bar (decorative)
        "drawbox=x=0:y=0:w=iw:h=8:color=#FF6B6B@0.9:t=fill",
        # title card at bottom
        f"drawbox=x=0:y=ih-180:w=iw:h=180:color=black@0.55:t=fill",
        (
            f"drawtext=text='{title_safe}':"
            f"fontsize=52:fontcolor=white:fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
            f"x=(w-text_w)/2:y=h-140:shadowcolor=black:shadowx=2:shadowy=2"
        ),
        # progress bar
        (
            f"drawbox=x=0:y=ih-12:w=iw:h=12:color=#333333@0.8:t=fill,"
            f"drawbox=x=0:y=ih-12:w='iw*(t/{duration:.2f})':h=12:color=#FF6B6B@0.9:t=fill"
        ),
    ]

    vf = ",".join(vf_parts)

    cmd = [
        "ffmpeg", "-y", "-i", clip_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        out_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"  🎨 Captions & overlays burned → {out_path}")
    return out_path


# ─────────────────────────────────────────────
#  Main orchestrator
# ─────────────────────────────────────────────
def make_shorts(video_path: str):
    OUTPUT_DIR.mkdir(exist_ok=True)
    TEMP_DIR.mkdir(exist_ok=True)

    print(f"\n🎬 YouTube Shorts Maker")
    print(f"   Source: {video_path}")
    print("=" * 50)

    # get video duration
    probe = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ], capture_output=True, text=True, check=True)
    video_duration = float(probe.stdout.strip())
    print(f"   Duration: {video_duration:.1f}s\n")

    # pipeline
    audio_path  = extract_audio(video_path)
    words       = transcribe(audio_path)
    transcript  = words_to_transcript(words)
    segments    = select_highlights(transcript, video_duration)

    print("\n🔨 Processing clips…")
    results = []
    for i, seg in enumerate(segments, 1):
        color   = CAPTION_COLORS[(i - 1) % len(CAPTION_COLORS)]
        clip    = extract_clip(video_path, seg, i)
        ass     = build_ass(words, seg, color, i)
        final   = burn_captions_and_overlays(clip, ass, seg, i)
        results.append(final)

    print("\n✅ All done! Your Shorts:")
    for r in results:
        print(f"   📱 {r}")
    print()


# ─────────────────────────────────────────────
#  CLI entry point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Turn a local video into YouTube Shorts")
    parser.add_argument("video", help="Path to your source video file")
    parser.add_argument("--num",      type=int,   default=NUM_SHORTS,      help="Number of shorts to generate")
    parser.add_argument("--duration", type=int,   default=TARGET_DURATION, help="Target length in seconds")
    parser.add_argument(
        "--provider",
        choices=["claude", "deepseek"],
        default="claude",
        help="AI provider for highlight selection (default: claude)",
    )
    args = parser.parse_args()

    NUM_SHORTS      = args.num
    TARGET_DURATION = args.duration
    AI_PROVIDER     = args.provider

    make_shorts(args.video)
