"""Small things every part of video2agent uses: logging, errors, FFmpeg and time formatting."""
import functools
import os
import shutil
import subprocess
import time

# While the queue runs, every log line is also written to this file
log_file = None


class VideoError(Exception):
    """Something went wrong with one video. The message says what in plain words."""


def log(message):
    line = f"[video2agent] {message}"
    print(line, flush=True)
    if log_file:
        try:
            with open(log_file, "a", encoding="utf-8") as file:
                file.write(time.strftime("%H:%M:%S ") + line + "\n")
        except OSError:
            pass


def fail(message):
    """Log the problem and stop working on this video."""
    log(f"ERROR: {message}")
    raise VideoError(message)


def run_command(command):
    """Run a program and give back what it printed, without opening a window."""
    return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          encoding="utf-8", errors="replace")


@functools.lru_cache(maxsize=None)
def find_program(name):
    """Full path to ffmpeg or ffprobe."""
    path = shutil.which(name)
    if path:
        return path

    # winget installs FFmpeg here, and a terminal opened before the install won't see it on PATH
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        winget_path = os.path.join(local_appdata, "Microsoft", "WinGet", "Links", name + ".exe")
        if os.path.exists(winget_path):
            return winget_path

    fail(f"{name} not found on PATH. Install FFmpeg (Windows: winget install Gyan.FFmpeg).")


def format_time(seconds, with_milliseconds=False, separator="."):
    """Seconds as 01:02:05, or as 01:02:05.250 for subtitle files (SRT wants a comma there)."""
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int(seconds % 3600 // 60)
    rest = seconds % 60

    if not with_milliseconds:
        return f"{hours:02d}:{minutes:02d}:{int(rest):02d}"

    whole = int(rest)
    milliseconds = int(round((rest - whole) * 1000))
    if milliseconds == 1000:  # 4.9996 rounds up to the next second
        whole, milliseconds = whole + 1, 0
    return f"{hours:02d}:{minutes:02d}:{whole:02d}{separator}{milliseconds:03d}"


def video_length(video):
    """How long the video is in seconds, read from the file's own metadata."""
    result = run_command([find_program("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", video])
    try:
        return float(result.stdout.strip())
    except ValueError:
        fail(f"ffprobe could not read the duration of {video}\n{result.stderr.strip()}")


def has_audio(video):
    result = run_command([find_program("ffprobe"), "-v", "error", "-select_streams", "a",
                          "-show_entries", "stream=index", "-of", "csv=p=0", video])
    return bool(result.stdout.strip())
