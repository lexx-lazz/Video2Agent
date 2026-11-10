"""Interactive menu shown when the program is started without a video argument."""
import argparse
import json
import os
import subprocess

from . import batch, cli
from .constants import APP_VERSION, BUILD_DATE

WIDTH = 72
SETTINGS_FILE = os.path.join(cli.DATA_DIR, "settings.json")
MODELS = ["tiny", "base", "small", "medium", "large-v3"]
MODEL_NOTES = {
    "tiny": "fastest, roughest",
    "base": "fast, good for clear speech",
    "small": "good balance (default)",
    "medium": "about 3x slower, more accurate",
    "large-v3": "slowest, most accurate",
}
VIDEO_TYPES = " ".join("*" + e for e in batch.VIDEO_EXTS)

GLYPHS = {
    "V": ["#   #", "#   #", "#   #", " # # ", "  #  "],
    "I": ["###", " # ", " # ", " # ", "###"],
    "D": ["#### ", "#   #", "#   #", "#   #", "#### "],
    "E": ["#####", "#    ", "#### ", "#    ", "#####"],
    "O": [" ### ", "#   #", "#   #", "#   #", " ### "],
    "2": [" ### ", "#   #", "  ## ", " #   ", "#####"],
    "A": [" ### ", "#   #", "#####", "#   #", "#   #"],
    "G": [" ####", "#    ", "#  ##", "#   #", " ####"],
    "N": ["#   #", "##  #", "# # #", "#  ##", "#   #"],
    "T": ["#####", "  #  ", "  #  ", "  #  ", "  #  "],
}


def banner_lines(word="VIDEO2AGENT"):
    return [" ".join(GLYPHS[c][row] for c in word) for row in range(5)]


def rule(ch="="):
    return "+" + ch * (WIDTH - 2) + "+"


def boxed(text=""):
    return "| " + text[:WIDTH - 4].ljust(WIDTH - 4) + " |"


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def header(title=None):
    clear()
    print(rule())
    print(boxed())
    for line in banner_lines():
        print(boxed("  " + line))
    print(boxed())
    tag = "v%s  %s" % (APP_VERSION, BUILD_DATE)
    left = "  video -> transcript + screenshots for AI agents"
    print(boxed(left + tag.rjust(WIDTH - 4 - len(left))))
    print(rule())
    if title:
        print(boxed(title))
        print(rule("-"))


def ask(prompt="  > "):
    try:
        return input(prompt).strip()
    except EOFError:
        return "q"


def pause(msg="  Press Enter to go back..."):
    try:
        input(msg)
    except EOFError:
        pass


# ---------------------------------------------------------------- settings

def load_settings(base):
    s = {"model": base.model if base.model in MODELS else "small",
         "language": base.language or "en",
         "force_whisper": bool(base.force_whisper)}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        for k in s:
            if k in saved and isinstance(saved[k], type(s[k])):
                s[k] = saved[k]
    except (OSError, ValueError):
        pass
    if s["model"] not in MODELS:
        s["model"] = "small"
    return s


def save_settings(s):
    try:
        os.makedirs(cli.DATA_DIR, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=1)
    except OSError:
        pass


def with_settings(base, s):
    a = argparse.Namespace(**vars(base))
    a.model, a.language, a.force_whisper = s["model"], s["language"], s["force_whisper"]
    a.out = a.subs = None
    return a


def language_label(code):
    return "auto-detect (slower, can guess wrong)" if code == "auto" else code


# ------------------------------------------------------------ file pickers

def _tk_dialog(kind):
    import tkinter
    from tkinter import filedialog
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    types = [("Video files", VIDEO_TYPES), ("All files", "*.*")]
    try:
        if kind == "one":
            got = filedialog.askopenfilename(parent=root, title="Select a video", filetypes=types)
            return [got] if got else []
        if kind == "many":
            return list(filedialog.askopenfilenames(
                parent=root, title="Select videos (Ctrl or Shift for several)", filetypes=types))
        if kind == "dest":
            os.makedirs(cli.DATA_DIR, exist_ok=True)
            got = filedialog.askdirectory(
                parent=root, initialdir=cli.DATA_DIR, mustexist=False,
                title="Save in which folder? Pick or create one (Cancel = straight into data)")
        else:
            got = filedialog.askdirectory(parent=root, title="Select a folder of videos")
        return [got] if got else []
    finally:
        root.destroy()


def pick(kind="one"):
    """Open the Windows file-explorer dialog. kind: one, many, folder or dest. Returns a list of paths."""
    try:
        return [os.path.normpath(p) for p in _tk_dialog(kind)]
    except Exception:
        pass
    print("  The file picker could not open. Type or drag a path here:")
    path = ask().strip('"')
    return [path] if path else []


def dest_label(dest):
    """How a save folder is shown: relative to data/ when it is inside it."""
    folder = cli.resolve_dest(dest)
    try:
        rel = os.path.relpath(folder, cli.DATA_DIR)
    except ValueError:
        return folder
    if rel == ".":
        return "data"
    return folder if rel.startswith("..") else os.path.join("data", rel)


def pick_dest():
    """Ask which folder to save in, starting at data/. Returns None for data/ itself."""
    print("  Now pick the folder to save in (the window opens at the data folder;")
    print("  you can make a new folder there). Cancel saves straight into data.")
    got = pick("dest")
    dest = got[0] if got else None
    if dest and os.path.normcase(os.path.abspath(dest)) == os.path.normcase(cli.DATA_DIR):
        dest = None
    return dest


def open_path(path):
    try:
        if os.name == "nt":
            os.startfile(path)
        else:
            subprocess.run(["xdg-open", path])
    except Exception as e:
        print("  Could not open it: %s" % e)


def open_folder(path):
    os.makedirs(path, exist_ok=True)
    open_path(path)


def processed_videos():
    """Finished video folders anywhere under data/, as paths relative to it, newest first."""
    out = []
    for folder, subdirs, files in os.walk(cli.DATA_DIR):
        if "video_digest.md" in files:
            out.append((os.path.getmtime(os.path.join(folder, "video_digest.md")),
                        os.path.relpath(folder, cli.DATA_DIR)))
            subdirs[:] = []          # a video's own frames/ and parts/ are not categories
    return [name for _t, name in sorted(out, reverse=True)]


# ------------------------------------------------------------------ screens

def folder_actions(out_dir):
    """[P]review / [O]pen folder prompt shared by the result and library screens."""
    while True:
        print("  [P] Open the preview (watch the video beside its screenshots and transcript)")
        print("  [O] Open the folder    [Enter] Back")
        choice = ask().lower()
        if choice == "p":
            open_path(os.path.join(out_dir, "preview.html"))
        elif choice == "o":
            open_folder(out_dir)
        else:
            return


def result_screen(out_dir):
    print()
    print(rule("-"))
    print(boxed("DONE. Everything for this video is in one folder:"))
    print(rule("-"))
    print()
    print("  " + out_dir)
    print()
    print("  To have Claude analyze it, open a terminal and run:")
    print()
    print('    cd "%s"' % out_dir)
    print('    claude "Follow AGENT_PROMPT.md"')
    print()
    folder_actions(out_dir)


def process_screen(base, settings):
    print()
    print("  A file explorer window is opening. Pick your video...")
    got = pick("one")
    if not got:
        return
    video = got[0]
    if not os.path.isfile(video):
        print("  Not a file: %s" % video)
        return pause()

    dest = pick_dest()
    out_dir = cli.default_out_dir(video, dest)
    subs = None if settings["force_whisper"] else cli.find_sidecar(video)
    header("PROCESS ONE VIDEO")
    print()
    print("  Video      : %s" % video)
    print("  Transcript : %s" % (
        "subtitle file %s" % os.path.basename(subs) if subs
        else "transcribe locally, model '%s', language %s"
        % (settings["model"], language_label(settings["language"]))))
    print("  Output     : %s" % out_dir)
    if os.path.isdir(out_dir):
        print()
        print("  This video already has a folder. Processing again replaces what is in it.")
    print()
    print("  [Enter] Start    [B] Back")
    if ask().lower() == "b":
        return

    a = with_settings(base, settings)
    a.video, a.dest = video, dest
    print()
    batch.keep_awake(True)
    try:
        out_dir = cli.process(a)
    except KeyboardInterrupt:
        print("\n  Stopped.")
        return pause()
    except SystemExit:
        print()
        return pause()
    except Exception as e:
        print("\n  Something went wrong: %s: %s" % (type(e).__name__, e))
        return pause()
    finally:
        batch.keep_awake(False)
    result_screen(out_dir)


def library_screen():
    while True:
        names = processed_videos()
        header("PROCESSED VIDEOS")
        print()
        if not names:
            print("  No videos processed yet.")
            print()
            return pause()
        for i, name in enumerate(names, 1):
            print("   [%d] %s" % (i, name))
        print()
        print("  Type a number to pick one, or press Enter to go back.")
        choice = ask()
        if not choice.isdigit():
            return
        if 1 <= int(choice) <= len(names):
            print()
            print("  " + names[int(choice) - 1])
            folder_actions(os.path.join(cli.DATA_DIR, names[int(choice) - 1]))


def queue_screen(base, settings):
    note = ""
    while True:
        items = batch.load()
        waiting = batch.pending(items)
        finished = [i for i in items if i["status"] != "pending"]
        header("OVERNIGHT QUEUE - videos run one after another, unattended")
        print()
        if not waiting:
            print("  Nothing waiting. Add videos with [A] or [F].")
        for n, i in enumerate(waiting, 1):
            print("   %2d. %-50s %s" % (n, os.path.basename(i["video"])[:50],
                                       cli.hms(i["duration"]) if i.get("duration") else ""))
            print("       -> %s" % dest_label(i.get("dest")))
        total = sum(i.get("duration") or 0 for i in waiting)
        if waiting:
            print()
            print("  %d waiting, %s of video. Model '%s', language %s."
                  % (len(waiting), cli.hms(total), settings["model"], language_label(settings["language"])))
        if finished:
            print()
            print("  Last results:")
            for i in finished[-8:]:
                mark = "done  " if i["status"] == "done" else "FAILED"
                took = " (%s)" % cli.hms(i["seconds"]) if i.get("seconds") else ""
                print("    %s %s%s" % (mark, os.path.basename(i["video"])[:50], took))
                if i["status"] == "failed" and i.get("error"):
                    print("           %s" % i["error"][:60])
        print()
        print("  [A] Add videos      [F] Add every video in a folder   (each asks where to save)")
        print("  [S] Start now       [T] Start at a set time (e.g. 23:30)")
        print("  [R] Remove one      [C] Clear the results list    [Enter] Back")
        if note:
            print()
            print("  " + note)
            note = ""
        choice = ask().lower()
        if choice == "a":
            print("  A file explorer window is opening. Hold Ctrl or Shift to pick several...")
            got = pick("many")
            if got:
                dest = pick_dest()
                note = "Added %d video(s), saving in %s." % (batch.add(got, dest=dest), dest_label(dest))
        elif choice == "f":
            print("  A file explorer window is opening. Pick the folder...")
            got = pick("folder")
            if got:
                dest = pick_dest()
                note = "Added %d video(s), saving in %s." % (batch.add(got, dest=dest), dest_label(dest))
        elif choice == "r":
            n = ask("  Remove which number? ")
            note = "Removed." if n.isdigit() and batch.remove(int(n)) else "No such number."
        elif choice == "c":
            batch.clear_finished()
        elif choice in ("s", "t"):
            if not waiting:
                note = "The queue is empty."
                continue
            start_at = None
            if choice == "t":
                start_at = batch.parse_clock(ask("  Start at what time (24-hour, e.g. 23:30)? "))
                if not start_at:
                    note = "That is not a time. Use the form 23:30."
                    continue
            print()
            print("  The PC is kept awake until the queue finishes. Leave this window open.")
            print()
            done, failed, log_path = batch.run_queue(with_settings(base, settings), start_at)
            print()
            print("  %d done, %d failed. Full log: %s" % (done, failed, log_path))
            pause()
        else:
            return


def run_menu(base):
    settings = load_settings(base)
    while True:
        header()
        print()
        print("   [1] Pick a video and process it now")
        print("   [2] Overnight queue (%d waiting)" % len(batch.pending()))
        print("   [3] Processed videos (%d)" % len(processed_videos()))
        print("   [4] Open the data folder")
        print()
        print("   [5] Whisper model : %-9s %s" % (settings["model"], MODEL_NOTES[settings["model"]]))
        print("   [6] Language      : %s" % language_label(settings["language"]))
        print("   [7] Transcript    : %s" % (
            "always transcribe, ignore subtitle files" if settings["force_whisper"]
            else "use a subtitle file if one sits beside the video"))
        print()
        print("   [Q] Quit")
        print()
        choice = ask().lower()
        if choice == "1":
            process_screen(base, settings)
        elif choice == "2":
            queue_screen(base, settings)
        elif choice == "3":
            library_screen()
        elif choice == "4":
            open_folder(cli.DATA_DIR)
        elif choice == "5":
            settings["model"] = MODELS[(MODELS.index(settings["model"]) + 1) % len(MODELS)]
        elif choice == "6":
            print("  Spoken language code (en, es, de, fr, fa ...) or 'auto' to detect:")
            code = ask().lower()
            if code == "auto" or (code.isalpha() and 2 <= len(code) <= 3):
                settings["language"] = code
        elif choice == "7":
            settings["force_whisper"] = not settings["force_whisper"]
        elif choice in ("q", "quit", "exit"):
            return
        save_settings(settings)
