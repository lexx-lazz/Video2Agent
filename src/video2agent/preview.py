"""preview.html, the page a person opens to check a video's screenshots and transcript.

The video plays on the left. On the right is every screenshot with the lines paired to it. The
block for the moment that's playing lights up, and clicking any timestamp jumps the video there.
The page itself lives in templates/preview.html.
"""
import html
import os
import pathlib

from .helpers import format_time

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "preview.html")


def block_start(block):
    """When a block starts to apply: its first line, or its screenshot if that came first."""
    if block["lines"]:
        return min(block["time"], block["lines"][0]["start"])
    return block["time"]


def block_html(block):
    parts = [f'<div class="block" data-t="{block_start(block):.2f}">',
             f'<p class="cap"><button class="t" data-seek="{block["time"]:.2f}">{format_time(block["time"])}'
             f'</button>screenshot taken at {format_time(block["time"])}</p>']

    if block["file"]:
        parts.append(f'<img loading="lazy" src="frames/{html.escape(block["file"])}" '
                     f'alt="{format_time(block["time"])}" data-seek="{block["time"]:.2f}">')

    if block["lines"]:
        for line in block["lines"]:
            parts.append(f'<div class="line" data-t="{line["start"]:.2f}" data-e="{line["end"]:.2f}">'
                         f'<button class="t" data-seek="{line["start"]:.2f}">{format_time(line["start"])}</button>'
                         f'<span>{html.escape(line["text"])}</span></div>')
    else:
        parts.append('<div class="none">(no speech)</div>')

    parts.append("</div>")
    return "\n".join(parts)


def build_page(video_path, title, summary, blocks):
    with open(TEMPLATE, "r", encoding="utf-8") as file:
        page = file.read()

    # The page links to the original video rather than copying it
    try:
        video_url = pathlib.Path(video_path).as_uri()
    except ValueError:
        video_url = ""

    page = page.replace("{{TITLE}}", html.escape(title))
    page = page.replace("{{SUMMARY}}", html.escape(summary))
    page = page.replace("{{VIDEO_PATH}}", html.escape(video_path))
    page = page.replace("{{VIDEO_URL}}", html.escape(video_url, quote=True))
    # Blocks go in last, so nothing a speaker says can be mistaken for a placeholder
    page = page.replace("{{BLOCKS}}", "\n".join(block_html(block) for block in blocks))
    return page
