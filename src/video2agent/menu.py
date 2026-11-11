"""The menu you get when you start video2agent without naming a video."""
import json
import os
import subprocess
import sys

from . import constants, pipeline, video_queue
from .constants import APP_VERSION, BUILD_DATE
from .helpers import VideoError, format_time
from .transcribe import find_subtitle_file

SETTINGS_FILE = os.path.join(constants.DATA_FOLDER, "settings.json")
WIDTH = 72
INSIDE = WIDTH - 4  # room for text between "║ " and " ║"

MODELS = ["tiny", "base", "small", "medium", "large-v3"]
MODEL_NOTES = {
    "tiny": "fastest, roughest",
    "base": "fast, good for clear speech",
    "small": "good balance (default)",
    "medium": "about 3x slower, more accurate",
    "large-v3": "slowest, most accurate",
}
VIDEO_TYPES = " ".join("*" + extension for extension in video_queue.VIDEO_EXTENSIONS)

# Each text row holds two rows of pixels, using the half blocks ▀ and ▄
BANNER_ART = [
    "█   █  ▀█▀  █▀▀▄  █▀▀▀▀ ▄▀▀▀▄ ▄▀▀▀▄ ▄▀▀▀▄ ▄▀▀▀▄ █▀▀▀▀ █▄  █ ▀▀█▀▀",
    "█   █   █   █   █ █▄▄▄  █   █    ▄▀ █▄▄▄█ █ ▄▄▄ █▄▄▄  █ ▀▄█   █",
    "▀▄ ▄▀   █   █  ▄▀ █     █   █  ▄▀   █   █ █   █ █     █   █   █",
    "  ▀    ▀▀▀  ▀▀▀   ▀▀▀▀▀  ▀▀▀  ▀▀▀▀▀ ▀   ▀  ▀▀▀▀ ▀▀▀▀▀ ▀   ▀   ▀",
]
# Cyan at the top fading to blue at the bottom (256-colour terminal codes)
BANNER_COLOURS = [51, 45, 39, 33]
FILM_STRIP = ("  " + "▪   " * 17)[:INSIDE]


# ---------- Drawing ----------

def use_colour():
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def coloured(text, colour_code):
    if not use_colour():
        return text
    return f"\033[38;5;{colour_code}m{text}\033[0m"


def box_row(text="", side="║"):
    return f"{side} {text[:INSIDE].ljust(INSIDE)} {side}"


def box_edge(left, right, fill="═"):
    return left + fill * (WIDTH - 2) + right


def banner_lines(title=None, colour=False):
    """The banner as a list of lines, with an optional screen title underneath."""
    art_width = max(len(row) for row in BANNER_ART)
    indent = " " * ((INSIDE - art_width) // 2)
    tagline = "  video → transcript + screenshots for AI agents"
    version = f"v{APP_VERSION}  {BUILD_DATE}"

    lines = [box_edge("╔", "╗"), box_row(FILM_STRIP)]
    for row, colour_code in zip(BANNER_ART, BANNER_COLOURS):
        line = box_row(indent + row)
        if colour:
            # Colour only the letters, after padding, so the colour codes don't throw the width off
            line = line.replace(row, coloured(row, colour_code), 1)
        lines.append(line)
    lines += [box_row(tagline + version.rjust(INSIDE - len(tagline))), box_row(FILM_STRIP)]

    if title:
        lines += [box_edge("╠", "╣"), box_row(title), box_edge("╚", "╝")]
    else:
        lines.append(box_edge("╚", "╝"))
    return lines


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def header(title=None):
    clear_screen()
    print("\n".join(banner_lines(title, colour=True)))


def ask(prompt="  > "):
    try:
        return input(prompt).strip()
    except EOFError:
        return "q"


def pause(message="  Press Enter to go back..."):
    try:
        input(message)
    except EOFError:
        pass


# ---------- Settings ----------

def load_settings(defaults):
    """The menu's model, language and transcript choice, as saved last time."""
    settings = {
        "model": defaults.get("model") if defaults.get("model") in MODELS else "small",
        "language": defaults.get("language") or "en",
        "force_whisper": bool(defaults.get("force_whisper")),
    }
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as file:
            saved = json.load(file)
        for key in settings:
            if key in saved and isinstance(saved[key], type(settings[key])):
                settings[key] = saved[key]
    except (OSError, ValueError):
        pass

    if settings["model"] not in MODELS:
        settings["model"] = "small"
    return settings


def save_settings(settings):
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as file:
            json.dump(settings, file, indent=1)
    except OSError:
        pass


def language_label(code):
    return "auto-detect (slower, can guess wrong)" if code == "auto" else code


# ---------- File windows ----------

def file_window(kind):
    """Open a file explorer window. kind is "one", "many", "folder" or "save"."""
    import tkinter
    from tkinter import filedialog

    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)  # otherwise it can open behind the terminal
    video_types = [("Video files", VIDEO_TYPES), ("All files", "*.*")]
    try:
        if kind == "one":
            chosen = filedialog.askopenfilename(parent=root, title="Select a video", filetypes=video_types)
            return [chosen] if chosen else []
        if kind == "many":
            return list(filedialog.askopenfilenames(
                parent=root, title="Select videos (Ctrl or Shift for several)", filetypes=video_types))
        if kind == "save":
            os.makedirs(constants.DATA_FOLDER, exist_ok=True)
            chosen = filedialog.askdirectory(
                parent=root, initialdir=constants.DATA_FOLDER, mustexist=False,
                title="Save in which folder? Pick or create one (Cancel = straight into data)")
        else:
            chosen = filedialog.askdirectory(parent=root, title="Select a folder of videos")
        return [chosen] if chosen else []
    finally:
        root.destroy()


def pick(kind="one"):
    """Ask for files or a folder in a window, or by typing a path if the window can't open."""
    try:
        return [os.path.normpath(path) for path in file_window(kind)]
    except Exception:
        pass
    print("  The file picker could not open. Type or drag a path here:")
    path = ask().strip('"')
    return [path] if path else []


def pick_save_folder():
    """Ask which folder to save in, starting at data/. None means data/ itself."""
    print("  Now pick the folder to save in (the window opens at the data folder;")
    print("  you can make a new folder there). Cancel saves straight into data.")
    chosen = pick("save")
    dest = chosen[0] if chosen else None
    if dest and os.path.normcase(os.path.abspath(dest)) == os.path.normcase(constants.DATA_FOLDER):
        dest = None
    return dest


def save_folder_label(dest):
    """A save folder the way the menu shows it: data\\Physics rather than the full path."""
    folder = pipeline.save_folder(dest)
    try:
        relative = os.path.relpath(folder, constants.DATA_FOLDER)
    except ValueError:  # on another drive
        return folder
    if relative == ".":
        return "data"
    return folder if relative.startswith("..") else os.path.join("data", relative)


def open_path(path):
    try:
        if os.name == "nt":
            os.startfile(path)
        else:
            subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", path])
    except Exception as error:
        print(f"  Could not open it: {error}")


def open_folder(path):
    os.makedirs(path, exist_ok=True)
    open_path(path)


def processed_videos():
    """Every finished video folder under data/, newest first, as paths relative to data/."""
    found = []
    for folder, subfolders, files in os.walk(constants.DATA_FOLDER):
        if "video_digest.md" in files:
            finished = os.path.getmtime(os.path.join(folder, "video_digest.md"))
            found.append((finished, os.path.relpath(folder, constants.DATA_FOLDER)))
            subfolders[:] = []  # a video's own frames/ and parts/ aren't more videos
    return [name for _finished, name in sorted(found, reverse=True)]


# ---------- Screens ----------

def folder_options(folder):
    """The preview / open folder choice shown after a video finishes and in the processed list."""
    while True:
        print("  [P] Open the preview (watch the video beside its screenshots and transcript)")
        print("  [O] Open the folder    [Enter] Back")
        choice = ask().lower()
        if choice == "p":
            open_path(os.path.join(folder, "preview.html"))
        elif choice == "o":
            open_folder(folder)
        else:
            return


def finished_screen(folder):
    print()
    print(box_edge("┌", "┐", "─"))
    print(box_row("DONE. Everything for this video is in one folder:", side="│"))
    print(box_edge("└", "┘", "─"))
    print()
    print(f"  {folder}")
    print()
    print("  To have Claude analyze it, open a terminal and run:")
    print()
    print(f'    cd "{folder}"')
    print('    claude "Follow AGENT_PROMPT.md"')
    print()
    folder_options(folder)


def process_one_screen(settings):
    print()
    print("  A file explorer window is opening. Pick your video...")
    chosen = pick("one")
    if not chosen:
        return
    video = chosen[0]
    if not os.path.isfile(video):
        print(f"  Not a file: {video}")
        return pause()

    dest = pick_save_folder()
    folder = pipeline.output_folder_for(video, dest)
    subtitle_file = None if settings["force_whisper"] else find_subtitle_file(video)

    header("PROCESS ONE VIDEO")
    print()
    print(f"  Video      : {video}")
    if subtitle_file:
        print(f"  Transcript : subtitle file {os.path.basename(subtitle_file)}")
    else:
        print(f"  Transcript : transcribe locally, model '{settings['model']}', "
              f"language {language_label(settings['language'])}")
    print(f"  Output     : {folder}")
    if os.path.isdir(folder):
        print()
        print("  This video already has a folder. Processing again replaces what is in it.")
    print()
    print("  [Enter] Start    [B] Back")
    if ask().lower() == "b":
        return

    print()
    video_queue.keep_awake(True)
    try:
        folder = pipeline.process_video(video, dest=dest, **settings)
    except KeyboardInterrupt:
        print("\n  Stopped.")
        return pause()
    except VideoError:
        # The error is already on screen
        print()
        return pause()
    except Exception as error:
        print(f"\n  Something went wrong: {type(error).__name__}: {error}")
        return pause()
    finally:
        video_queue.keep_awake(False)
    finished_screen(folder)


def processed_screen():
    while True:
        names = processed_videos()
        header("PROCESSED VIDEOS")
        print()
        if not names:
            print("  No videos processed yet.")
            print()
            return pause()

        for number, name in enumerate(names, 1):
            print(f"   [{number}] {name}")
        print()
        print("  Type a number to pick one, or press Enter to go back.")
        choice = ask()
        if not choice.isdigit():
            return
        if 1 <= int(choice) <= len(names):
            name = names[int(choice) - 1]
            print()
            print(f"  {name}")
            folder_options(os.path.join(constants.DATA_FOLDER, name))


def add_to_queue(kind):
    """Pick videos (or a folder of them), then where to save them. Returns a note for the screen."""
    chosen = pick(kind)
    if not chosen:
        return ""
    dest = pick_save_folder()
    added = video_queue.add_videos(chosen, dest=dest)
    return f"Added {added} video(s), saving in {save_folder_label(dest)}."


def queue_screen(settings):
    note = ""
    while True:
        items = video_queue.load_queue()
        waiting = video_queue.waiting_videos(items)
        finished = [item for item in items if item["status"] != "pending"]

        header("OVERNIGHT QUEUE - videos run one after another, unattended")
        print()
        if not waiting:
            print("  Nothing waiting. Add videos with [A] or [F].")
        for number, item in enumerate(waiting, 1):
            length = format_time(item["duration"]) if item.get("duration") else ""
            print(f"   {number:2d}. {os.path.basename(item['video'])[:50]:<50} {length}")
            print(f"       -> {save_folder_label(item.get('dest'))}")

        if waiting:
            total = sum(item.get("duration") or 0 for item in waiting)
            print()
            print(f"  {len(waiting)} waiting, {format_time(total)} of video. Model '{settings['model']}', "
                  f"language {language_label(settings['language'])}.")

        if finished:
            print()
            print("  Last results:")
            for item in finished[-8:]:
                mark = "done  " if item["status"] == "done" else "FAILED"
                took = f" ({format_time(item['seconds'])})" if item.get("seconds") else ""
                print(f"    {mark} {os.path.basename(item['video'])[:50]}{took}")
                if item["status"] == "failed" and item.get("error"):
                    print(f"           {item['error'][:60]}")

        print()
        print("  [A] Add videos      [F] Add every video in a folder   (each asks where to save)")
        print("  [S] Start now       [T] Start at a set time (e.g. 23:30)")
        print("  [R] Remove one      [C] Clear the results list    [Enter] Back")
        if note:
            print()
            print(f"  {note}")
            note = ""

        choice = ask().lower()
        if choice == "a":
            print("  A file explorer window is opening. Hold Ctrl or Shift to pick several...")
            note = add_to_queue("many")
        elif choice == "f":
            print("  A file explorer window is opening. Pick the folder...")
            note = add_to_queue("folder")
        elif choice == "r":
            number = ask("  Remove which number? ")
            removed = number.isdigit() and video_queue.remove_waiting(int(number))
            note = "Removed." if removed else "No such number."
        elif choice == "c":
            video_queue.clear_finished()
        elif choice in ("s", "t"):
            if not waiting:
                note = "The queue is empty."
                continue

            start_at = None
            if choice == "t":
                start_at = video_queue.parse_start_time(ask("  Start at what time (24-hour, e.g. 23:30)? "))
                if not start_at:
                    note = "That is not a time. Use the form 23:30."
                    continue

            print()
            print("  The PC is kept awake until the queue finishes. Leave this window open.")
            print()
            done, failed, log_path = video_queue.run_queue(dict(settings), start_at)
            print()
            print(f"  {done} done, {failed} failed. Full log: {log_path}")
            pause()
        else:
            return


def run_menu(defaults=None):
    """The main menu. defaults are the model, language and force_whisper given on the command line."""
    if os.name == "nt":
        os.system("")  # switches on colour support in the Windows console

    settings = load_settings(defaults or {})
    while True:
        header()
        print()
        print("   [1] Pick a video and process it now")
        print(f"   [2] Overnight queue ({len(video_queue.waiting_videos())} waiting)")
        print(f"   [3] Processed videos ({len(processed_videos())})")
        print("   [4] Open the data folder")
        print()
        print(f"   [5] Whisper model : {settings['model']:<9} {MODEL_NOTES[settings['model']]}")
        print(f"   [6] Language      : {language_label(settings['language'])}")
        if settings["force_whisper"]:
            print("   [7] Transcript    : always transcribe, ignore subtitle files")
        else:
            print("   [7] Transcript    : use a subtitle file if one sits beside the video")
        print()
        print("   [Q] Quit")
        print()

        choice = ask().lower()
        if choice == "1":
            process_one_screen(settings)
        elif choice == "2":
            queue_screen(settings)
        elif choice == "3":
            processed_screen()
        elif choice == "4":
            open_folder(constants.DATA_FOLDER)
        elif choice == "5":
            # Step through the models in order, back to the first after the last
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
