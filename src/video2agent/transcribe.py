"""Getting a timed transcript: from a subtitle file when there is one, otherwise from Whisper."""
import glob
import os
import re
import time

from .constants import LINE_BREAK_PAUSE, LONGEST_LINE, SENTENCE_LINE, SHORTEST_LINE
from .helpers import fail, format_time, log

# A subtitle timing row, like 00:01:02,500 --> 00:01:04,000 (SRT) or 01:02.500 --> 01:04.000 (VTT)
CUE_TIMING = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s*-->\s*(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")

# <i>, <c.colour> and {\an8} style formatting inside subtitle text
FORMATTING_TAGS = re.compile(r"<[^>]+>|\{\\[^}]*\}")


# ---------- Subtitle files ----------

def find_subtitle_file(video):
    """A subtitle file next to the video with the same name: video.srt, video.en.vtt and so on."""
    name_without_extension = os.path.splitext(video)[0]
    for extension in (".srt", ".vtt"):
        if os.path.exists(name_without_extension + extension):
            return name_without_extension + extension

    # yt-dlp adds the language code, like video.en.vtt
    for extension in (".srt", ".vtt"):
        matches = sorted(glob.glob(glob.escape(name_without_extension) + ".*" + extension))
        if matches:
            return matches[0]
    return None


def to_seconds(hours, minutes, seconds, fraction):
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(fraction.ljust(3, "0")) / 1000.0


def read_subtitles(path):
    """Read an .srt or .vtt file into a list of {start, end, text} lines."""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as file:
        rows = file.read().replace("\r\n", "\n").replace("\r", "\n").split("\n")

    cues, current = [], None
    for row in rows:
        timing = CUE_TIMING.search(row)
        if timing:
            if current and current["text"]:
                cues.append(current)
            parts = timing.groups()
            current = {"start": to_seconds(*parts[0:4]), "end": to_seconds(*parts[4:8]), "text": ""}
            continue
        if current is None:
            continue

        text = FORMATTING_TAGS.sub("", row).strip()
        if not text:
            # A blank row ends the cue
            if current["text"]:
                cues.append(current)
                current = None
            continue
        current["text"] = (current["text"] + " " + text).strip()

    if current and current["text"]:
        cues.append(current)

    # YouTube's auto captions repeat the previous line at the start of every cue, so cut it off
    lines, previous = [], ""
    for cue in cues:
        text = cue["text"]
        if text == previous:
            continue
        if previous and text.startswith(previous):
            text = text[len(previous):].strip()
        previous = cue["text"]
        if text and cue["end"] > cue["start"]:
            lines.append({"start": cue["start"], "end": cue["end"], "text": text})
    return lines


# ---------- Whisper ----------

def split_into_lines(words, longest=LONGEST_LINE, pause=LINE_BREAK_PAUSE, sentence_length=SENTENCE_LINE):
    """Group (start, end, text) words into short timed lines.

    Whisper hands back chunks of about 25 seconds. That is too long to sit under one screenshot,
    so a new line starts at a pause, at the end of a sentence once the line is long enough, or
    when the line would get too long.
    """
    lines, current = [], None
    for start, end, text in words:
        if not text.strip():
            continue

        if current is not None:
            ends_sentence = current["text"].rstrip()[-1:] in ".?!"
            long_enough = current["end"] - current["start"] >= sentence_length
            if (start - current["end"] >= pause
                    or end - current["start"] > longest
                    or (ends_sentence and long_enough)):
                lines.append(current)
                current = None

        if current is None:
            current = {"start": float(start), "end": float(end), "text": text.strip()}
        else:
            current["end"] = float(end)
            current["text"] += text

    if current is not None:
        lines.append(current)

    for line in lines:
        line["text"] = " ".join(line["text"].split())
        line["end"] = max(line["end"], line["start"] + 0.1)
    return lines


def transcribe_with_whisper(video, model_name, language, video_seconds):
    try:
        from faster_whisper import WhisperModel, BatchedInferencePipeline
    except ImportError:
        fail("faster-whisper is not installed. Run: run.bat deps")

    # Half the logical cores is the sweet spot on a desktop CPU
    threads = max(1, (os.cpu_count() or 4) // 2)
    log(f"loading Whisper model '{model_name}' (CPU, int8, {threads} threads) - first run downloads it")
    model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=threads)

    # Working on 8 chunks of audio at once is several times faster than one at a time
    segments, info = BatchedInferencePipeline(model=model).transcribe(
        video, language=language, batch_size=8, word_timestamps=True)

    if language:
        log(f"language: {info.language} (set)")
    else:
        log(f"language: {info.language} (auto-detected, p={info.language_probability:.2f})")
        if info.language_probability < 0.9:
            log("  WARNING: low confidence. A wrong guess is slow and inaccurate -")
            log("  set the language in the menu or pass --language (e.g. en).")

    words, lines_without_words = [], []
    started = time.time()
    last_progress = 0.0
    for segment in segments:
        if segment.words:
            # Word times are exact. Segment times get stretched across silences.
            words += [(word.start, word.end, word.word) for word in segment.words]
        elif segment.text.strip():
            lines_without_words.append({"start": float(segment.start), "end": float(segment.end),
                                        "text": segment.text.strip()})

        # Progress every 5 seconds
        if time.time() - last_progress > 5:
            last_progress = time.time()
            percent = min(100.0, 100.0 * segment.end / video_seconds) if video_seconds else 0
            elapsed = time.time() - started
            time_left = elapsed * (100.0 - percent) / percent if percent > 1 else 0
            log(f"  transcribed {format_time(segment.end)} / {format_time(video_seconds)} "
                f"({percent:.0f}%, {format_time(elapsed)} elapsed, about {format_time(time_left)} left)")

    lines = sorted(lines_without_words + split_into_lines(words), key=lambda line: line["start"])
    log(f"transcription done in {format_time(time.time() - started)}, {len(lines)} segments")
    return lines


# ---------- Tidying ----------

def merge_short_lines(lines, shortest=SHORTEST_LINE, max_gap=1.5, longest=30.0):
    """Join lines shorter than `shortest` onto the next one, unless there's a real pause between."""
    def length(line):
        return line["end"] - line["start"]

    def can_join(first, second):
        return second["start"] - first["end"] <= max_gap and second["end"] - first["start"] <= longest

    def join(first, second):
        first["end"] = max(first["end"], second["end"])
        first["text"] = (first["text"] + " " + second["text"]).strip()

    merged = []
    for line in lines:
        # A line that is still too short takes in the one after it
        if merged and length(merged[-1]) < shortest and can_join(merged[-1], line):
            join(merged[-1], line)
        else:
            merged.append(dict(line))

    # The last line has nothing after it, so a short one joins the line before instead
    if len(merged) > 1 and length(merged[-1]) < shortest and can_join(merged[-2], merged[-1]):
        join(merged[-2], merged.pop())
    return merged
