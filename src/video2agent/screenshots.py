"""Picking moments to screenshot, taking the screenshots and throwing away the repeats."""
import os
import re

from .constants import (MIN_SECONDS_BETWEEN_SCREENSHOTS, NEW_WRITING_PERCENT, SAME_PICTURE_DISTANCE,
                        SCENE_CHANGE_THRESHOLD, SCREENSHOT_WIDTH, SILENCE_SCREENSHOT_EVERY)
from .helpers import find_program, log, run_command


def find_scene_changes(video, threshold=SCENE_CHANGE_THRESHOLD):
    """Times (seconds) where the picture changes sharply, like a new slide."""
    result = run_command([find_program("ffmpeg"), "-hide_banner", "-nostats", "-i", video, "-an", "-sn",
                          "-vf", f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"])
    return [float(seconds) for seconds in re.findall(r"pts_time:\s*([0-9.]+)", result.stderr)]


def pick_screenshot_times(lines, scene_changes, video_seconds,
                          silence_every=SILENCE_SCREENSHOT_EVERY, min_gap=MIN_SECONDS_BETWEEN_SCREENSHOTS):
    """List of (time, reason) to take screenshots at, in order.

    Every scene change, the middle of every spoken line, and every so often while nobody talks.
    When two are too close together the scene change wins, then speech, then silence.
    """
    last_moment = max(0.0, video_seconds - 0.05)

    # Each candidate is (priority, time, reason). The lowest priority number wins a clash.
    candidates = [(0, min(moment + 0.15, last_moment), "scene") for moment in scene_changes]
    candidates += [(1, (line["start"] + line["end"]) / 2.0, "speech") for line in lines]

    # The gaps between lines, as start/end pairs: [0, first start], [first end, second start] ...
    edges = [0.0]
    for line in lines:
        edges += [line["start"], line["end"]]
    edges.append(video_seconds)

    for index in range(0, len(edges), 2):
        gap_start, gap_end = edges[index], edges[index + 1]
        if gap_end - gap_start >= silence_every:
            moment = gap_start + (1.0 if index == 0 else silence_every)
            while moment < gap_end - 1.0:
                candidates.append((2, moment, "silence"))
                moment += silence_every

    # A silent video with no scene changes still gets one screenshot
    if not candidates:
        candidates.append((2, min(1.0, video_seconds / 2.0), "silence"))

    chosen = []
    for _priority, moment, reason in sorted(candidates):
        moment = min(max(moment, 0.0), last_moment)
        if all(abs(moment - taken) >= min_gap for taken, _reason in chosen):
            chosen.append((moment, reason))
    return sorted(chosen)


def take_screenshots(video, times, frames_folder, width=SCREENSHOT_WIDTH):
    """Save one JPEG per time, named after the second it was taken at (f_000092.jpg)."""
    frames = []
    for index, (moment, reason) in enumerate(times):
        file_name = f"f_{int(moment):06d}.jpg"
        if frames and frames[-1]["file"] == file_name:
            file_name = f"f_{int(moment):06d}_{index}.jpg"
        path = os.path.join(frames_folder, file_name)

        result = run_command([find_program("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                              "-ss", f"{moment:.3f}", "-i", video, "-frames:v", "1",
                              "-vf", f"scale={width}:-2", "-q:v", "3", path])
        if result.returncode == 0 and os.path.exists(path) and os.path.getsize(path) > 0:
            frames.append({"time": moment, "file": file_name, "reason": reason})

        if (index + 1) % 50 == 0:
            log(f"  extracted {index + 1} / {len(times)} frames")
    return frames


def percent_changed(first, second):
    """Percent of pixels that clearly differ between two small grayscale thumbnails."""
    from PIL import ImageChops
    histogram = ImageChops.difference(first, second).histogram()
    # Brightness differences under 48 (out of 255) are just video compression noise
    return 100.0 * sum(histogram[48:]) / float(first.size[0] * first.size[1])


def remove_repeats(frames, frames_folder, max_distance=SAME_PICTURE_DISTANCE, min_change=NEW_WRITING_PERCENT):
    """Delete screenshots that look the same as the last one kept.

    A fingerprint (perceptual hash) spots the same slide twice. It can't see one new line of
    handwriting, so a look-alike is still kept when enough of its pixels changed.
    """
    try:
        from PIL import Image
        import imagehash
    except ImportError:
        log("pillow/imagehash missing - skipping duplicate removal")
        return frames

    kept = []
    last_fingerprint, last_thumbnail = None, None
    for frame in frames:
        path = os.path.join(frames_folder, frame["file"])
        with Image.open(path) as picture:
            fingerprint = imagehash.phash(picture)
            thumbnail = picture.convert("L").resize((160, 90))

        # Always compare with the last one KEPT, so slow writing adds up until it counts
        if last_fingerprint is not None and fingerprint - last_fingerprint <= max_distance:
            frame["change"] = round(percent_changed(thumbnail, last_thumbnail), 2)
            if frame["change"] < min_change:
                os.remove(path)
                continue

        kept.append(frame)
        last_fingerprint, last_thumbnail = fingerprint, thumbnail
    return kept
