#!/usr/bin/env python3
"""video2agent - turn a video into a timestamped transcript + screenshots digest
that an AI agent can read end to end.

    run.bat <video> [options]        (or: python -m video2agent <video> [options])

Writes <video>_agent/ next to the video:
    video_digest.md   timestamp + screenshot + what was said while it showed
    parts/part_NN.md  the digest in 15-minute chunks
    frames/           screenshots (JPEG)
    transcript.srt    plain transcript
    segments.json     machine-readable segments and frames
    AGENT_PROMPT.md   instructions for the agent
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

from .constants import APP_VERSION, BUILD_DATE

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


# ----------------------------------------------------------------- helpers

def log(msg):
    print("[video2agent] " + msg, flush=True)


def die(msg):
    print("[video2agent] ERROR: " + msg, file=sys.stderr)
    sys.exit(1)


def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          encoding="utf-8", errors="replace")


def find_tool(name):
    path = shutil.which(name)
    if path:
        return path
    # winget puts shims here; a shell opened before the install won't have it on PATH
    local = os.environ.get("LOCALAPPDATA")
    if local:
        cand = os.path.join(local, "Microsoft", "WinGet", "Links", name + ".exe")
        if os.path.exists(cand):
            return cand
    die("%s not found on PATH. Install FFmpeg (Windows: winget install Gyan.FFmpeg)." % name)


def hms(t, ms=False, sep="."):
    t = max(0.0, float(t))
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    if ms:
        whole = int(s)
        milli = int(round((s - whole) * 1000))
        if milli == 1000:
            whole, milli = whole + 1, 0
        return "%02d:%02d:%02d%s%03d" % (h, m, whole, sep, milli)
    return "%02d:%02d:%02d" % (h, m, int(s))


def probe_duration(video):
    r = run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", video])
    try:
        return float(r.stdout.strip())
    except ValueError:
        die("ffprobe could not read the duration of %s\n%s" % (video, r.stderr.strip()))


def has_audio(video):
    r = run([FFPROBE, "-v", "error", "-select_streams", "a", "-show_entries",
             "stream=index", "-of", "csv=p=0", video])
    return bool(r.stdout.strip())


# -------------------------------------------------------------- transcript

TS_RE = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s*-->\s*(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
TAG_RE = re.compile(r"<[^>]+>|\{\\[^}]*\}")


def _ts(h, m, s, frac):
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(frac.ljust(3, "0")) / 1000.0


def parse_subs(path):
    """Parse .srt or .vtt into [{start, end, text}]."""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        lines = f.read().replace("\r\n", "\n").replace("\r", "\n").split("\n")
    segs, cur = [], None
    for line in lines:
        m = TS_RE.search(line)
        if m:
            if cur and cur["text"]:
                segs.append(cur)
            g = m.groups()
            cur = {"start": _ts(*g[0:4]), "end": _ts(*g[4:8]), "text": ""}
            continue
        if cur is None:
            continue
        s = TAG_RE.sub("", line).strip()
        if not s:
            if cur["text"]:
                segs.append(cur)
                cur = None
            continue
        cur["text"] = (cur["text"] + " " + s).strip()
    if cur and cur["text"]:
        segs.append(cur)

    # YouTube auto-captions repeat the previous line in each cue: strip the overlap
    cleaned, prev = [], ""
    for s in segs:
        text = s["text"]
        if text == prev:
            continue
        if prev and text.startswith(prev):
            text = text[len(prev):].strip()
        prev = s["text"]
        if text and s["end"] > s["start"]:
            cleaned.append({"start": s["start"], "end": s["end"], "text": text})
    return cleaned


def find_sidecar(video):
    """Subtitle next to the video with the same name (video.srt, video.en.vtt ...)."""
    stem = os.path.splitext(video)[0]
    for ext in (".srt", ".vtt"):
        if os.path.exists(stem + ext):
            return stem + ext
    for ext in (".srt", ".vtt"):
        hits = sorted(glob.glob(glob.escape(stem) + ".*" + ext))
        if hits:
            return hits[0]
    return None


def whisper_transcribe(video, model_name, language, duration):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        die("faster-whisper is not installed. Run: pip install -r requirements.txt")
    log("loading Whisper model '%s' (CPU, int8) - first run downloads it" % model_name)
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, info = model.transcribe(video, language=language, vad_filter=True,
                                      beam_size=5, word_timestamps=True)
    log("language: %s (p=%.2f)" % (info.language, info.language_probability))
    out, t0, last = [], time.time(), 0.0
    for s in segments:
        text = s.text.strip()
        if text:
            # segment-level times get stretched across silences; word times do not
            start, end = float(s.start), float(s.end)
            if s.words:
                start, end = float(s.words[0].start), float(s.words[-1].end)
            out.append({"start": start, "end": max(end, start + 0.1), "text": text})
        if time.time() - last > 5:
            last = time.time()
            pct = 100.0 * s.end / duration if duration else 0
            log("  transcribed %s / %s (%.0f%%, %.0fs elapsed)"
                % (hms(s.end), hms(duration), pct, time.time() - t0))
    log("transcription done in %.0fs, %d segments" % (time.time() - t0, len(out)))
    return out


def merge_short(segs, min_len, max_gap=1.5, max_len=30.0):
    """Merge fragments shorter than min_len into their neighbour."""
    def join(p, s):
        p["end"] = max(p["end"], s["end"])
        p["text"] = (p["text"] + " " + s["text"]).strip()

    def fits(p, s):
        return s["start"] - p["end"] <= max_gap and s["end"] - p["start"] <= max_len

    out = []
    for s in segs:
        # a fragment that is still too short absorbs whatever comes next
        if out and (out[-1]["end"] - out[-1]["start"]) < min_len and fits(out[-1], s):
            join(out[-1], s)
        else:
            out.append(dict(s))
    # a short tail has nothing after it: fold it back
    if len(out) > 1 and (out[-1]["end"] - out[-1]["start"]) < min_len and fits(out[-2], out[-1]):
        join(out[-2], out.pop())
    return out


# ------------------------------------------------------------------ frames

def detect_scenes(video, threshold):
    r = run([FFMPEG, "-hide_banner", "-nostats", "-i", video, "-an", "-sn",
             "-vf", "select='gt(scene,%s)',showinfo" % threshold, "-f", "null", "-"])
    return [float(x) for x in re.findall(r"pts_time:\s*([0-9.]+)", r.stderr)]


def candidate_times(segs, scenes, duration, silence_every, min_gap):
    """(time, reason) list. Scene changes win over speech midpoints win over fillers."""
    cands = [(0, min(t + 0.15, max(0.0, duration - 0.05)), "scene") for t in scenes]
    cands += [(1, (s["start"] + s["end"]) / 2.0, "speech") for s in segs]

    # every N seconds wherever nobody is talking
    edges = [0.0]
    for s in segs:
        edges += [s["start"], s["end"]]
    edges.append(duration)
    for i in range(0, len(edges), 2):
        a, b = edges[i], edges[i + 1]
        if b - a >= silence_every:
            t = a + (1.0 if i == 0 else silence_every)
            while t < b - 1.0:
                cands.append((2, t, "silence"))
                t += silence_every
    if not cands:
        cands.append((2, min(1.0, duration / 2.0), "silence"))

    kept = []
    for _prio, t, why in sorted(cands):
        t = min(max(t, 0.0), max(0.0, duration - 0.05))
        if all(abs(t - k[0]) >= min_gap for k in kept):
            kept.append((t, why))
    return sorted(kept)


def extract_frames(video, times, frames_dir, width):
    out = []
    for i, (t, why) in enumerate(times):
        name = "f_%06d.jpg" % int(t)
        if out and out[-1]["file"] == name:
            name = "f_%06d_%d.jpg" % (int(t), i)
        path = os.path.join(frames_dir, name)
        r = run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-ss", "%.3f" % t,
                 "-i", video, "-frames:v", "1", "-vf", "scale=%d:-2" % width,
                 "-q:v", "3", path])
        if r.returncode == 0 and os.path.exists(path) and os.path.getsize(path) > 0:
            out.append({"time": t, "file": name, "reason": why})
        if (i + 1) % 50 == 0:
            log("  extracted %d / %d frames" % (i + 1, len(times)))
    return out


def dedupe_frames(frames, frames_dir, max_dist):
    """Drop a frame when it looks the same as the last one kept."""
    try:
        from PIL import Image
        import imagehash
    except ImportError:
        log("pillow/imagehash missing - skipping duplicate removal")
        return frames
    kept, last = [], None
    for f in frames:
        path = os.path.join(frames_dir, f["file"])
        with Image.open(path) as im:
            h = imagehash.phash(im)
        if last is not None and (h - last) <= max_dist:
            os.remove(path)
            continue
        kept.append(f)
        last = h
    return kept


# ------------------------------------------------------------------ output

def build_blocks(frames, segs):
    """Attach each transcript segment to the frame on screen at its midpoint."""
    blocks = [{"time": f["time"], "file": f["file"], "reason": f["reason"], "lines": []}
              for f in frames]
    if not blocks:
        blocks = [{"time": 0.0, "file": None, "reason": "none", "lines": []}]
    j = 0
    for s in segs:
        mid = (s["start"] + s["end"]) / 2.0
        while j + 1 < len(blocks) and blocks[j + 1]["time"] <= mid + 0.01:
            j += 1
        blocks[j]["lines"].append(s)
    return blocks


def render_blocks(blocks, img_prefix):
    out = []
    for b in blocks:
        out.append("## [%s]" % hms(b["time"]))
        out.append("")
        if b["file"]:
            out.append("![%s](%s%s)" % (hms(b["time"]), img_prefix, b["file"]))
            out.append("")
        if b["lines"]:
            for s in b["lines"]:
                out.append("- **%s** %s" % (hms(s["start"]), s["text"]))
        else:
            out.append("_(no speech)_")
        out.append("")
    return "\n".join(out)


AGENT_PROMPT = """# Task: analyze this video

This folder is a text + image rendering of the video **{name}** (length {dur}).

## What is here
- `video_digest.md` - the whole video. Each block is a timestamp, the screenshot
  that was on screen, and the transcript lines spoken while it showed.
- `parts/part_NN.md` - the same digest split into {part_min}-minute chunks ({nparts} part(s)).
  Read these one at a time if the full digest is too large.
- `frames/` - the screenshots. **Open the images**, do not rely on the transcript alone:
  slides, code, charts and UI often carry information nobody says out loud.
- `transcript.srt`, `segments.json` - the raw transcript and frame index.

Transcript source: {source}. {source_note}

## How to work
1. Read every part in order. Look at the screenshot of each block before its text.
2. Keep running notes per part, then merge them.
3. Cite a timestamp `[HH:MM:SS]` for every claim so it can be checked in the video.

## Report (write it to `REPORT.md` in this folder)
1. **TL;DR** - 3 to 5 sentences.
2. **Key points** - in order, each with its timestamp and why it matters.
3. **On-screen only** - anything visible in the screenshots that was not spoken
   (text on slides, numbers, code, URLs, names, diagrams).
4. **Action items / takeaways** - concrete things a viewer should do or remember.
5. **Skippable sections** - time ranges that are intros, filler, sponsor reads or repetition.

If something is unreadable in a frame or the transcript looks wrong, say so
instead of guessing.
"""


def main():
    global FFMPEG, FFPROBE
    ap = argparse.ArgumentParser(description="Video -> timestamped transcript + screenshots for AI agents")
    ap.add_argument("video")
    ap.add_argument("--version", action="version",
                    version="video2agent %s (%s)" % (APP_VERSION, BUILD_DATE))
    ap.add_argument("--out", help="output folder (default: <video>_agent next to the video)")
    ap.add_argument("--subs", help="subtitle file to use (.srt/.vtt)")
    ap.add_argument("--force-whisper", action="store_true", help="ignore subtitle files, transcribe locally")
    ap.add_argument("--model", default="small", help="faster-whisper model (tiny/base/small/medium/large-v3)")
    ap.add_argument("--language", default=None, help="language code, e.g. en (default: auto-detect)")
    ap.add_argument("--scene", type=float, default=0.3, help="scene-change threshold 0-1")
    ap.add_argument("--silence-interval", type=float, default=30.0, help="seconds between frames during silence")
    ap.add_argument("--min-gap", type=float, default=2.0, help="minimum seconds between frames")
    ap.add_argument("--min-segment", type=float, default=4.0, help="merge transcript fragments shorter than this")
    ap.add_argument("--width", type=int, default=1024, help="screenshot width in px")
    ap.add_argument("--hash-dist", type=int, default=6, help="perceptual-hash distance treated as duplicate")
    ap.add_argument("--part-minutes", type=float, default=15.0, help="length of each part file")
    a = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    video = os.path.abspath(a.video)
    if not os.path.isfile(video):
        die("video not found: " + video)
    FFMPEG, FFPROBE = find_tool("ffmpeg"), find_tool("ffprobe")

    out_dir = os.path.abspath(a.out) if a.out else os.path.splitext(video)[0] + "_agent"
    frames_dir = os.path.join(out_dir, "frames")
    parts_dir = os.path.join(out_dir, "parts")
    for d in (frames_dir, parts_dir):
        if os.path.isdir(d):
            shutil.rmtree(d)
        os.makedirs(d)

    duration = probe_duration(video)
    log("video: %s (%s)" % (os.path.basename(video), hms(duration)))

    # --- transcript
    subs = a.subs or (None if a.force_whisper else find_sidecar(video))
    if a.subs and not os.path.isfile(a.subs):
        die("subtitle file not found: " + a.subs)
    if subs:
        log("using subtitles: " + os.path.basename(subs))
        segs = parse_subs(subs)
        source, note = "subtitle file `%s`" % os.path.basename(subs), ""
    elif not has_audio(video):
        log("no audio track - screenshots only")
        segs, source, note = [], "none (video has no audio track)", ""
    else:
        segs = whisper_transcribe(video, a.model, a.language, duration)
        source = "local speech recognition (faster-whisper `%s`)" % a.model
        note = "Names, jargon and numbers may be misheard - cross-check against the screenshots."
    segs = [s for s in segs if s["start"] < duration + 1]
    segs = merge_short(sorted(segs, key=lambda s: s["start"]), a.min_segment)
    log("%d transcript segments" % len(segs))

    # --- frames
    log("detecting scene changes (threshold %.2f)" % a.scene)
    scenes = detect_scenes(video, a.scene)
    times = candidate_times(segs, scenes, duration, a.silence_interval, a.min_gap)
    log("%d scene changes, %d candidate frames" % (len(scenes), len(times)))
    frames = extract_frames(video, times, frames_dir, a.width)
    before = len(frames)
    frames = dedupe_frames(frames, frames_dir, a.hash_dist)
    log("kept %d frames (%d near-duplicates dropped)" % (len(frames), before - len(frames)))

    # --- output
    blocks = build_blocks(frames, segs)
    name = os.path.basename(video)
    head = "# %s\n\nLength %s - %d screenshots - %d transcript segments - transcript from %s\n\n" % (
        name, hms(duration), len(frames), len(segs), source)

    def write(path, text):
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    write(os.path.join(out_dir, "video_digest.md"), head + render_blocks(blocks, "frames/"))

    part_len = a.part_minutes * 60.0
    nparts = max(1, int((max(duration - 0.001, 0)) // part_len) + 1)
    written = 0
    for p in range(nparts):
        lo, hi = p * part_len, (p + 1) * part_len
        chunk = [b for b in blocks if lo <= b["time"] < hi]
        if not chunk:
            continue
        written += 1
        write(os.path.join(parts_dir, "part_%02d.md" % (p + 1)),
              "# %s - part %d of %d (%s - %s)\n\n" % (name, p + 1, nparts, hms(lo), hms(min(hi, duration)))
              + render_blocks(chunk, "../frames/"))

    write(os.path.join(out_dir, "transcript.srt"), "".join(
        "%d\n%s --> %s\n%s\n\n" % (i + 1, hms(s["start"], True, ","), hms(s["end"], True, ","), s["text"])
        for i, s in enumerate(segs)))

    with open(os.path.join(out_dir, "segments.json"), "w", encoding="utf-8") as f:
        json.dump({"video": name, "duration": duration, "transcript_source": source,
                   "segments": segs, "frames": frames}, f, ensure_ascii=False, indent=1)

    write(os.path.join(out_dir, "AGENT_PROMPT.md"), AGENT_PROMPT.format(
        name=name, dur=hms(duration), part_min=("%g" % a.part_minutes), nparts=written,
        source=source, source_note=note))

    log("done -> " + out_dir)
    log('next: cd into that folder and run:  claude "Follow AGENT_PROMPT.md"')


if __name__ == "__main__":
    main()
