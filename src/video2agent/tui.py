"""Interactive menu shown when the program is started without a video argument."""
import argparse
import os
import subprocess
import sys

from . import cli
from .constants import APP_VERSION, BUILD_DATE

WIDTH = 72
MODELS = ["tiny", "base", "small", "medium", "large-v3"]
MODEL_NOTES = {
    "tiny": "fastest, roughest",
    "base": "fast, rough",
    "small": "good balance (default)",
    "medium": "slower, more accurate",
    "large-v3": "slowest, most accurate",
}
VIDEO_TYPES = "*.mp4 *.mkv *.webm *.mov *.avi *.m4v *.wmv *.flv *.ts *.mpg *.mpeg"

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


def header():
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


def ask(prompt="  > "):
    try:
        return input(prompt).strip()
    except EOFError:
        return "q"


def pause(msg="  Press Enter to go back to the menu..."):
    try:
        input(msg)
    except EOFError:
        pass


# ------------------------------------------------------------- file picker

def pick_video():
    """Open the Windows file-explorer dialog. Returns a path, or None if cancelled."""
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            parent=root, title="Select a video",
            filetypes=[("Video files", VIDEO_TYPES), ("All files", "*.*")])
        root.destroy()
        return os.path.normpath(path) if path else None
    except Exception:
        pass
    if os.name == "nt":
        script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$d = New-Object System.Windows.Forms.OpenFileDialog;"
            "$d.Title = 'Select a video';"
            "$d.Filter = 'Video files|%s|All files|*.*';"
            "if ($d.ShowDialog() -eq 'OK') { [Console]::OutputEncoding = [Text.Encoding]::UTF8; $d.FileName }"
            % VIDEO_TYPES.replace(" ", ";"))
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", script],
                               stdout=subprocess.PIPE, encoding="utf-8", errors="replace")
            return r.stdout.strip() or None
        except Exception:
            pass
    print("  The file picker could not open. Type or drag the video path here:")
    path = ask().strip('"')
    return path or None


def open_folder(path):
    os.makedirs(path, exist_ok=True)
    try:
        if os.name == "nt":
            os.startfile(path)
        else:
            subprocess.run(["xdg-open", path])
    except Exception as e:
        print("  Could not open the folder: %s" % e)


def processed_videos():
    """Folders in data/ that hold a finished digest, newest first."""
    out = []
    if os.path.isdir(cli.DATA_DIR):
        for name in os.listdir(cli.DATA_DIR):
            digest = os.path.join(cli.DATA_DIR, name, "video_digest.md")
            if os.path.isfile(digest):
                out.append((os.path.getmtime(digest), name))
    return [name for _t, name in sorted(out, reverse=True)]


# ------------------------------------------------------------------ screens

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
    print("  [O] Open the folder    [Enter] Back to the menu")
    if ask().lower() == "o":
        open_folder(out_dir)


def process_screen(base, settings):
    print()
    print("  A file explorer window is opening. Pick your video...")
    video = pick_video()
    if not video:
        return
    if not os.path.isfile(video):
        print("  Not a file: %s" % video)
        return pause()

    out_dir = cli.default_out_dir(video)
    subs = None if settings["force_whisper"] else cli.find_sidecar(video)
    header()
    print()
    print("  Video      : %s" % video)
    print("  Transcript : %s" % (
        "subtitle file %s" % os.path.basename(subs) if subs
        else "transcribe locally, Whisper model '%s'" % settings["model"]))
    print("  Output     : %s" % out_dir)
    if os.path.isdir(out_dir):
        print()
        print("  This video already has a folder. Processing again replaces what is in it.")
    print()
    print("  [Enter] Start    [B] Back")
    if ask().lower() == "b":
        return

    a = argparse.Namespace(**vars(base))
    a.video, a.out = video, None
    a.model, a.force_whisper = settings["model"], settings["force_whisper"]
    print()
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
    result_screen(out_dir)


def library_screen():
    while True:
        names = processed_videos()
        header()
        print()
        if not names:
            print("  No videos processed yet.")
            print()
            return pause()
        print("  Processed videos (newest first):")
        print()
        for i, name in enumerate(names, 1):
            print("   [%d] %s" % (i, name))
        print()
        print("  Type a number to open that folder, or press Enter to go back.")
        choice = ask()
        if not choice.isdigit():
            return
        if 1 <= int(choice) <= len(names):
            open_folder(os.path.join(cli.DATA_DIR, names[int(choice) - 1]))


def run_menu(base):
    settings = {"model": base.model if base.model in MODELS else "small",
                "force_whisper": bool(base.force_whisper)}
    while True:
        header()
        print()
        print("   [1] Pick a video and process it")
        print("   [2] Processed videos (%d)" % len(processed_videos()))
        print("   [3] Open the data folder")
        print()
        print("   [4] Whisper model : %-9s %s" % (settings["model"], MODEL_NOTES[settings["model"]]))
        print("   [5] Transcript    : %s" % (
            "always transcribe, ignore subtitle files" if settings["force_whisper"]
            else "use a subtitle file if one sits beside the video"))
        print()
        print("   [Q] Quit")
        print()
        choice = ask().lower()
        if choice == "1":
            process_screen(base, settings)
        elif choice == "2":
            library_screen()
        elif choice == "3":
            open_folder(cli.DATA_DIR)
        elif choice == "4":
            settings["model"] = MODELS[(MODELS.index(settings["model"]) + 1) % len(MODELS)]
        elif choice == "5":
            settings["force_whisper"] = not settings["force_whisper"]
        elif choice in ("q", "quit", "exit"):
            return
