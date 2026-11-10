"""The queue: a saved list of videos processed one after another, unattended."""
import argparse
import datetime
import json
import os
import time

from . import cli

QUEUE_FILE = os.path.join(cli.DATA_DIR, "queue.json")
LOG_DIR = os.path.join(cli.ROOT, "logs")
VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".wmv", ".flv", ".ts", ".mpg", ".mpeg")


def load():
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            items = json.load(f)
        return items if isinstance(items, list) else []
    except (OSError, ValueError):
        return []


def save(items):
    os.makedirs(cli.DATA_DIR, exist_ok=True)
    tmp = QUEUE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    os.replace(tmp, QUEUE_FILE)


def expand(paths):
    """Files stay as they are; a folder becomes the videos directly inside it, by name."""
    out = []
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isdir(p):
            out += [os.path.join(p, n) for n in sorted(os.listdir(p))
                    if n.lower().endswith(VIDEO_EXTS) and os.path.isfile(os.path.join(p, n))]
        else:
            out.append(p)
    return out


def add(paths, probe=True):
    """Append videos as pending. Returns how many were added (already-waiting ones are skipped)."""
    items = load()
    waiting = {os.path.normcase(i["video"]) for i in items if i["status"] == "pending"}
    added = 0
    for video in expand(paths):
        if os.path.normcase(video) in waiting or not os.path.isfile(video):
            continue
        duration = 0.0
        if probe:
            try:
                cli.FFPROBE = cli.find_tool("ffprobe")
                duration = cli.probe_duration(video)
            except SystemExit:
                pass
        items.append({"video": video, "status": "pending", "duration": duration,
                      "added": datetime.datetime.now().isoformat(timespec="seconds")})
        waiting.add(os.path.normcase(video))
        added += 1
    save(items)
    return added


def pending(items=None):
    return [i for i in (load() if items is None else items) if i["status"] == "pending"]


def clear_finished():
    save(pending())


def remove(index):
    """Remove the Nth waiting video (1-based)."""
    items = load()
    waiting = pending(items)
    if 1 <= index <= len(waiting):
        items.remove(waiting[index - 1])
        save(items)
        return True
    return False


def keep_awake(on):
    """Stop Windows going to sleep while a queue runs. The display may still turn off."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))
    except Exception:
        pass


def parse_clock(text, now=None):
    """'23:30' or '2330' -> the next datetime with that clock time."""
    now = now or datetime.datetime.now()
    digits = text.strip().replace(".", ":")
    if ":" not in digits and digits.isdigit() and len(digits) in (3, 4):
        digits = digits[:-2] + ":" + digits[-2:]
    try:
        h, m = [int(x) for x in digits.split(":")]
        when = now.replace(hour=h, minute=m, second=0, microsecond=0)
    except ValueError:
        return None
    if when <= now:
        when += datetime.timedelta(days=1)
    return when


def wait_until(when):
    cli.log("queue will start at %s - leave this window open (Ctrl+C cancels)"
            % when.strftime("%H:%M on %a %d %b"))
    while True:
        left = (when - datetime.datetime.now()).total_seconds()
        if left <= 0:
            return
        if left > 90:
            cli.log("  starting in %s" % cli.hms(left))
        time.sleep(min(left, 600 if left > 1200 else 60 if left > 90 else left))


def run_queue(base, start_at=None):
    """Process every waiting video in order. One failure does not stop the rest.

    Returns (done, failed, log_path).
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, datetime.datetime.now().strftime("queue_%Y%m%d_%H%M%S.log"))
    cli.LOG_FILE = log_path
    done = failed = 0
    t_all = time.time()
    keep_awake(True)
    try:
        if start_at:
            wait_until(start_at)
        total = len(pending())
        cli.log("queue started: %d video(s)" % total)
        while True:
            items = load()
            waiting = pending(items)
            if not waiting:
                break
            item = waiting[0]
            n = done + failed + 1
            cli.log("")
            cli.log("===== %d of %d: %s =====" % (n, max(total, n), os.path.basename(item["video"])))
            a = argparse.Namespace(**vars(base))
            a.video, a.out, a.subs = item["video"], None, None
            t0 = time.time()
            try:
                item["out"] = cli.process(a)
                item["status"] = "done"
                done += 1
            except KeyboardInterrupt:
                cli.log("stopped by you - this video stays in the queue")
                break
            except SystemExit as e:
                item["status"], item["error"] = "failed", str(e) or "stopped with an error"
                failed += 1
            except Exception as e:
                item["status"], item["error"] = "failed", "%s: %s" % (type(e).__name__, e)
                cli.log("FAILED: " + item["error"])
                failed += 1
            item["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
            item["seconds"] = round(time.time() - t0)
            save(items)
        cli.log("")
        cli.log("queue finished: %d done, %d failed, %s total"
                % (done, failed, cli.hms(time.time() - t_all)))
        for i in load():
            if i["status"] == "failed":
                cli.log("  failed: %s - %s" % (os.path.basename(i["video"]), i.get("error", "")))
    except KeyboardInterrupt:
        cli.log("cancelled before the queue started")
    finally:
        keep_awake(False)
        cli.LOG_FILE = None
    return done, failed, log_path
