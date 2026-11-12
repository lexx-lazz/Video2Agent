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
def find_ffmpeg():
    """Full path to the ffmpeg program.

    The copy that comes with the imageio-ffmpeg package is used first, so every PC runs the same
    FFmpeg and nobody has to install it. One installed on the system is the fallback.
    """
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass

    path = shutil.which("ffmpeg")
    if path:
        return path

    # winget installs FFmpeg here, and a terminal opened before the install won't see it on PATH
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        winget_path = os.path.join(local_appdata, "Microsoft", "WinGet", "Links", "ffmpeg.exe")
        if os.path.exists(winget_path):
            return winget_path

    fail("ffmpeg not found. Run: run.bat deps")


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


def open_video(video):
    """Open a video with PyAV, FFmpeg's own libraries, which Whisper already needs."""
    import av
    try:
        return av.open(video)
    except Exception as error:
        fail(f"could not read {video}\n{error}")


def video_length(video):
    """How long the video is in seconds, read from the file's own metadata."""
    with open_video(video) as container:
        if container.duration is not None:
            return container.duration / 1_000_000  # PyAV counts in microseconds

        # Some files only store a length per stream, so take the longest
        lengths = [float(stream.duration * stream.time_base) for stream in container.streams
                   if stream.duration is not None and stream.time_base is not None]
    if not lengths:
        fail(f"could not read the duration of {video}")
    return max(lengths)


def has_audio(video):
    with open_video(video) as container:
        return any(stream.type == "audio" for stream in container.streams)
