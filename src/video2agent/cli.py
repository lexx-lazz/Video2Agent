"""The command line. With no video named it opens the menu instead.

    run.bat                               the menu
    run.bat <video>                       one video, now
    run.bat <videos or folders>           several, one after another
    run.bat --queue --at 23:30            the queue built in the menu, starting at 23:30

Every video ends up in its own folder in data/ (or the folder given with --dest):
    video_digest.md   timestamp, screenshot and what was said while it showed, for the whole video
    parts/            the same thing in 15 minute pieces
    frames/           the screenshots
    transcript.srt    the transcript as a subtitle file
    segments.json     every line and screenshot with its time
    AGENT_PROMPT.md   what to ask the AI agent to do
    preview.html      a page for checking it all against the video
"""
import argparse
import os
import sys

from . import menu, video_queue
from .constants import APP_VERSION, BUILD_DATE
from .helpers import VideoError, fail, log
from .pipeline import process_video


def build_argument_parser():
    parser = argparse.ArgumentParser(prog="video2agent",
                                     description="Video -> timestamped transcript + screenshots for AI agents")
    parser.add_argument("video", nargs="*",
                        help="video file(s) or folder(s), processed in order; leave out for the menu")
    parser.add_argument("--queue", action="store_true",
                        help="process the saved queue (built in the menu), then exit")
    parser.add_argument("--at", metavar="HH:MM", help="with --queue or several videos: wait until this time")
    parser.add_argument("--version", action="version", version=f"video2agent {APP_VERSION} ({BUILD_DATE})")
    parser.add_argument("--dest", metavar="FOLDER",
                        help="folder to save in; output goes to FOLDER/<video name>/. "
                             "A plain name such as \"Physics\" means data/Physics")
    parser.add_argument("--out", help="exact output folder, instead of <dest>/<video name>/")
    parser.add_argument("--subs", help="subtitle file to use (.srt/.vtt)")
    parser.add_argument("--force-whisper", action="store_true", help="ignore subtitle files, transcribe locally")
    parser.add_argument("--model", default="small", help="faster-whisper model (tiny/base/small/medium/large-v3)")
    parser.add_argument("--language", default="en",
                        help="spoken language code (default: en); 'auto' detects it, slower and less safe")
    return parser


def run(args):
    # The transcript settings every video gets, whichever way it's processed
    options = {"model": args.model, "language": args.language, "force_whisper": args.force_whisper}

    videos = video_queue.find_videos(args.video)
    for video in videos:
        if not os.path.isfile(video):
            log(f"skipping, not found: {video}")
    # With several videos, the missing ones are skipped. A single missing one fails below.
    if len(videos) > 1:
        videos = [video for video in videos if os.path.isfile(video)]

    start_at = None
    if args.at:
        start_at = video_queue.parse_start_time(args.at)
        if not start_at:
            fail("--at needs a time like 23:30")

    if args.queue or len(videos) > 1 or start_at:
        # Unattended: everything named goes on the saved queue, then the queue runs
        if videos:
            log(f"added {video_queue.add_videos(videos, dest=args.dest)} video(s) to the queue")
        _done, failed, log_path = video_queue.run_queue(options, start_at)
        log(f"log saved to {log_path}")
        sys.exit(1 if failed else 0)
    elif videos:
        process_video(videos[0], dest=args.dest, output_folder=args.out, subtitles=args.subs, **options)
        log('next: cd into that folder and run:  claude "Follow AGENT_PROMPT.md"')
    elif args.video:
        fail("no video files found in: " + ", ".join(args.video))
    else:
        menu.run_menu(options)


def main():
    # Video names can have any characters in them, so print as UTF-8 whatever the console says
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    args = build_argument_parser().parse_args()
    try:
        run(args)
    except VideoError:
        # The reason is already on screen
        sys.exit(1)


if __name__ == "__main__":
    main()
