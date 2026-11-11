"""Pairing transcript lines with screenshots and writing the video's output folder."""
import json
import os

from . import preview
from .constants import PART_MINUTES
from .helpers import format_time

PROMPT_TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "agent_prompt.md")


def pair_lines_with_screenshots(frames, lines):
    """Put each line under the screenshot that was on screen halfway through it.

    Returns blocks of {time, file, reason, lines}, one per screenshot.
    """
    blocks = [{"time": frame["time"], "file": frame["file"], "reason": frame["reason"], "lines": []}
              for frame in frames]
    if not blocks:
        blocks = [{"time": 0.0, "file": None, "reason": "none", "lines": []}]

    # Both lists are in time order, so walk through them together
    current = 0
    for line in lines:
        middle = (line["start"] + line["end"]) / 2.0
        while current + 1 < len(blocks) and blocks[current + 1]["time"] <= middle + 0.01:
            current += 1
        blocks[current]["lines"].append(line)
    return blocks


def blocks_to_markdown(blocks, image_folder):
    """Each block as a heading, its screenshot and the lines said while it was on screen."""
    rows = []
    for block in blocks:
        rows.append(f"## [{format_time(block['time'])}]")
        rows.append("")
        if block["file"]:
            rows.append(f"![{format_time(block['time'])}]({image_folder}{block['file']})")
            rows.append("")
        if block["lines"]:
            for line in block["lines"]:
                rows.append(f"- **{format_time(line['start'])}** {line['text']}")
        else:
            rows.append("_(no speech)_")
        rows.append("")
    return "\n".join(rows)


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as file:
        file.write(text)


def write_parts(folder, video_name, video_seconds, blocks):
    """The digest again, cut into PART_MINUTES chunks so an agent can read a long video in pieces.

    Returns how many part files were written.
    """
    part_seconds = PART_MINUTES * 60.0
    part_count = max(1, int(max(video_seconds - 0.001, 0) // part_seconds) + 1)
    written = 0

    for number in range(part_count):
        part_start, part_end = number * part_seconds, (number + 1) * part_seconds
        blocks_in_part = [block for block in blocks if part_start <= block["time"] < part_end]
        if not blocks_in_part:
            continue

        written += 1
        heading = (f"# {video_name} - part {number + 1} of {part_count} "
                   f"({format_time(part_start)} - {format_time(min(part_end, video_seconds))})\n\n")
        write_text(os.path.join(folder, "parts", f"part_{number + 1:02d}.md"),
                   heading + blocks_to_markdown(blocks_in_part, "../frames/"))
    return written


def write_srt(path, lines):
    entries = []
    for number, line in enumerate(lines, 1):
        start = format_time(line["start"], with_milliseconds=True, separator=",")
        end = format_time(line["end"], with_milliseconds=True, separator=",")
        entries.append(f"{number}\n{start} --> {end}\n{line['text']}\n\n")
    write_text(path, "".join(entries))


def write_folder(folder, video, video_seconds, frames, lines, transcript_source, transcript_note):
    """Write every file in a video's folder. The frames/ folder is already filled by then."""
    video_name = os.path.basename(video)
    blocks = pair_lines_with_screenshots(frames, lines)

    # video_digest.md - the whole video in one file
    heading = (f"# {video_name}\n\nLength {format_time(video_seconds)} - {len(frames)} screenshots - "
               f"{len(lines)} transcript segments - transcript from {transcript_source}\n\n")
    write_text(os.path.join(folder, "video_digest.md"), heading + blocks_to_markdown(blocks, "frames/"))

    part_count = write_parts(folder, video_name, video_seconds, blocks)

    # transcript.srt - a normal subtitle file that video players can show
    write_srt(os.path.join(folder, "transcript.srt"), lines)

    # segments.json - every line and screenshot with its time, for anything that wants the raw data
    with open(os.path.join(folder, "segments.json"), "w", encoding="utf-8") as file:
        json.dump({"video": video_name, "duration": video_seconds, "transcript_source": transcript_source,
                   "segments": lines, "frames": frames}, file, ensure_ascii=False, indent=1)

    # AGENT_PROMPT.md - what the agent is asked to do with all this
    with open(PROMPT_TEMPLATE, "r", encoding="utf-8") as file:
        prompt = file.read()
    write_text(os.path.join(folder, "AGENT_PROMPT.md"), prompt.format(
        video_name=video_name, video_length=format_time(video_seconds), part_minutes=f"{PART_MINUTES:g}",
        part_count=part_count, transcript_source=transcript_source, transcript_note=transcript_note))

    # preview.html - for a person to check the pairing against the video
    summary = (f"Length {format_time(video_seconds)} - {len(frames)} screenshots - "
               f"{len(lines)} transcript segments - {transcript_source.replace('`', '')}")
    write_text(os.path.join(folder, "preview.html"), preview.build_page(video, video_name, summary, blocks))
