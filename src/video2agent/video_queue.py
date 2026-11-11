"""The queue: a saved list of videos that get processed one after another, unattended.

It lives in data/queue.json, so it survives closing the program.
"""
import datetime
import json
import os
import time

from . import constants, helpers, pipeline
from .helpers import VideoError, format_time, log, video_length

QUEUE_FILE = os.path.join(constants.DATA_FOLDER, "queue.json")
VIDEO_EXTENSIONS = (".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".wmv", ".flv", ".ts", ".mpg", ".mpeg")


# ---------- Reading and saving ----------

def load_queue():
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as file:
            items = json.load(file)
        return items if isinstance(items, list) else []
    except (OSError, ValueError):
        return []


def save_queue(items):
    os.makedirs(os.path.dirname(QUEUE_FILE), exist_ok=True)
    # Write to a temporary file first, so a crash mid-write can't wreck the queue
    temporary = QUEUE_FILE + ".tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(items, file, ensure_ascii=False, indent=1)
    os.replace(temporary, QUEUE_FILE)


def waiting_videos(items=None):
    if items is None:
        items = load_queue()
    return [item for item in items if item["status"] == "pending"]


# ---------- Changing the queue ----------

def find_videos(paths):
    """Files are kept as they are. A folder becomes the videos directly inside it, by name."""
    videos = []
    for path in paths:
        path = os.path.abspath(path)
        if os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                full_path = os.path.join(path, name)
                if name.lower().endswith(VIDEO_EXTENSIONS) and os.path.isfile(full_path):
                    videos.append(full_path)
        else:
            videos.append(path)
    return videos


def add_videos(paths, dest=None, read_length=True):
    """Add videos to the end of the queue, to be saved in `dest` (None means data/).

    Videos already waiting are skipped. Returns how many were added.
    """
    items = load_queue()
    already_waiting = {os.path.normcase(item["video"]) for item in waiting_videos(items)}
    added = 0

    for video in find_videos(paths):
        if os.path.normcase(video) in already_waiting or not os.path.isfile(video):
            continue

        # The length is only for showing the total in the menu, so a failure here doesn't matter
        seconds = 0.0
        if read_length:
            try:
                seconds = video_length(video)
            except VideoError:
                pass

        items.append({"video": video, "status": "pending", "duration": seconds, "dest": dest,
                      "added": datetime.datetime.now().isoformat(timespec="seconds")})
        already_waiting.add(os.path.normcase(video))
        added += 1

    save_queue(items)
    return added


def remove_waiting(number):
    """Remove the Nth waiting video, counting from 1."""
    items = load_queue()
    waiting = waiting_videos(items)
    if 1 <= number <= len(waiting):
        items.remove(waiting[number - 1])
        save_queue(items)
        return True
    return False


def clear_finished():
    save_queue(waiting_videos())


# ---------- Running it ----------

def keep_awake(on):
    """Stop Windows going to sleep while videos are processing. The screen can still turn off."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))
    except Exception:
        pass


def parse_start_time(text, now=None):
    """"23:30" or "2330" as the next time the clock shows it. None if it isn't a time."""
    now = now or datetime.datetime.now()
    text = text.strip().replace(".", ":")
    if ":" not in text and text.isdigit() and len(text) in (3, 4):
        text = text[:-2] + ":" + text[-2:]

    try:
        hour, minute = [int(part) for part in text.split(":")]
        start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except ValueError:
        return None

    # Already past today, so it means tomorrow
    if start <= now:
        start += datetime.timedelta(days=1)
    return start


def wait_until(start):
    log(f"queue will start at {start.strftime('%H:%M on %a %d %b')} - leave this window open (Ctrl+C cancels)")
    while True:
        seconds_left = (start - datetime.datetime.now()).total_seconds()
        if seconds_left <= 0:
            return
        if seconds_left > 90:
            log(f"  starting in {format_time(seconds_left)}")

        # Check in every 10 minutes when it's far off, every minute when it's close
        if seconds_left > 1200:
            time.sleep(600)
        elif seconds_left > 90:
            time.sleep(60)
        else:
            time.sleep(seconds_left)


def run_queue(options=None, start_at=None):
    """Process every waiting video in order. One failing doesn't stop the rest.

    options are the transcript settings: model, language and force_whisper.
    Returns (how many done, how many failed, path of the log file).
    """
    options = options or {}
    os.makedirs(constants.LOGS_FOLDER, exist_ok=True)
    log_path = os.path.join(constants.LOGS_FOLDER, datetime.datetime.now().strftime("queue_%Y%m%d_%H%M%S.log"))
    helpers.log_file = log_path

    done = failed = 0
    queue_started = time.time()
    keep_awake(True)
    try:
        if start_at:
            wait_until(start_at)

        total = len(waiting_videos())
        log(f"queue started: {total} video(s)")
        while True:
            # Reload every time, so videos added from the menu meanwhile are picked up
            items = load_queue()
            waiting = waiting_videos(items)
            if not waiting:
                break

            item = waiting[0]
            number = done + failed + 1
            log("")
            log(f"===== {number} of {max(total, number)}: {os.path.basename(item['video'])} =====")
            video_started = time.time()
            try:
                item["out"] = pipeline.process_video(item["video"], dest=item.get("dest"), **options)
                item["status"] = "done"
                done += 1
            except KeyboardInterrupt:
                log("stopped by you - this video stays in the queue")
                break
            except VideoError as error:
                # Already logged by fail()
                item["status"], item["error"] = "failed", str(error) or "stopped with an error"
                failed += 1
            except Exception as error:
                item["status"], item["error"] = "failed", f"{type(error).__name__}: {error}"
                log(f"FAILED: {item['error']}")
                failed += 1

            item["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
            item["seconds"] = round(time.time() - video_started)
            save_queue(items)

        log("")
        log(f"queue finished: {done} done, {failed} failed, {format_time(time.time() - queue_started)} total")
        for item in load_queue():
            if item["status"] == "failed":
                log(f"  failed: {os.path.basename(item['video'])} - {item.get('error', '')}")
    except KeyboardInterrupt:
        log("cancelled before the queue started")
    finally:
        keep_awake(False)
        helpers.log_file = None

    return done, failed, log_path
