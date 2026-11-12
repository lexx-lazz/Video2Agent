"""Processing one video from start to finish. Every other part of the program comes through here."""
import os
import shutil
import time

from . import constants
from .digest import write_folder
from .helpers import fail, find_ffmpeg, format_time, has_audio, log, video_length
from .screenshots import find_scene_changes, pick_screenshot_times, remove_repeats, take_screenshots
from .transcribe import find_subtitle_file, merge_short_lines, read_subtitles, transcribe_with_whisper


def save_folder(dest):
    """The folder a video's results go in. A plain name like "Physics" means a folder in data/."""
    if not dest:
        return constants.DATA_FOLDER
    return os.path.normpath(dest if os.path.isabs(dest) else os.path.join(constants.DATA_FOLDER, dest))


def output_folder_for(video, dest=None):
    """Each video gets its own folder, named after the video file."""
    return os.path.join(save_folder(dest), os.path.splitext(os.path.basename(video))[0])


def process_video(video, dest=None, output_folder=None, subtitles=None,
                  force_whisper=False, model="small", language="en"):
    """Turn one video into its folder of transcript, screenshots and digest. Returns the folder."""
    started = time.time()
    video = os.path.abspath(video)
    if not os.path.isfile(video):
        fail(f"video not found: {video}")

    # Stop now with a clear message if FFmpeg can't be found
    find_ffmpeg()

    folder = os.path.abspath(output_folder) if output_folder else output_folder_for(video, dest)
    frames_folder = os.path.join(folder, "frames")
    parts_folder = os.path.join(folder, "parts")
    # Start these two clean, so a re-run never mixes old screenshots with new ones
    for subfolder in (frames_folder, parts_folder):
        if os.path.isdir(subfolder):
            shutil.rmtree(subfolder)
        os.makedirs(subfolder)

    video_seconds = video_length(video)
    log(f"video: {os.path.basename(video)} ({format_time(video_seconds)})")

    # ---------- Transcript ----------
    subtitle_file = subtitles or (None if force_whisper else find_subtitle_file(video))
    if subtitles and not os.path.isfile(subtitles):
        fail(f"subtitle file not found: {subtitles}")

    if subtitle_file:
        log(f"using subtitles: {os.path.basename(subtitle_file)}")
        lines = read_subtitles(subtitle_file)
        transcript_source = f"subtitle file `{os.path.basename(subtitle_file)}`"
        transcript_note = ""
    elif not has_audio(video):
        log("no audio track - screenshots only")
        lines = []
        transcript_source = "none (video has no audio track)"
        transcript_note = ""
    else:
        whisper_language = None if language in (None, "", "auto") else language
        lines = transcribe_with_whisper(video, model, whisper_language, video_seconds)
        transcript_source = f"local speech recognition (faster-whisper `{model}`)"
        transcript_note = "Names, jargon and numbers may be misheard - cross-check against the screenshots."

    lines = [line for line in lines if line["start"] < video_seconds + 1]
    lines = merge_short_lines(sorted(lines, key=lambda line: line["start"]))
    log(f"{len(lines)} transcript segments")

    # ---------- Screenshots ----------
    log(f"detecting scene changes (threshold {constants.SCENE_CHANGE_THRESHOLD:.2f})")
    scene_changes = find_scene_changes(video)
    times = pick_screenshot_times(lines, scene_changes, video_seconds)
    log(f"{len(scene_changes)} scene changes, {len(times)} candidate frames")

    frames = take_screenshots(video, times, frames_folder)
    if times and not frames:
        fail(f"no screenshots could be read from the video (0 of {len(times)}). Was the file moved or "
             f"renamed while it was being processed? {video}")

    taken = len(frames)
    frames = remove_repeats(frames, frames_folder)
    log(f"kept {len(frames)} frames ({taken - len(frames)} near-duplicates dropped)")

    # ---------- Output ----------
    write_folder(folder, video, video_seconds, frames, lines, transcript_source, transcript_note)

    log(f"done in {format_time(time.time() - started)} -> {folder}")
    log(f"{len(frames)} screenshots, {len(lines)} transcript segments")
    return folder
