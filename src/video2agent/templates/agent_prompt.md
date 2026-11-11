# Task: analyze this video

This folder is a text + image rendering of the video **{video_name}** (length {video_length}).

## What is here
- `video_digest.md` - the whole video. Each block is a timestamp, the screenshot
  that was on screen, and the transcript lines spoken while it showed.
- `parts/part_NN.md` - the same digest split into {part_minutes}-minute chunks ({part_count} part(s)).
  Read these one at a time if the full digest is too large.
- `frames/` - the screenshots. **Open the images**, do not rely on the transcript alone:
  slides, code, charts and UI often carry information nobody says out loud.
- `transcript.srt`, `segments.json` - the raw transcript and frame index.
- `preview.html` - a page for a person to check the output against the video. Ignore it.

Transcript source: {transcript_source}. {transcript_note}

## How to work
1. Read every part in order. Look at the screenshot of each block before its text.
2. Keep running notes per part, then merge them.
3. Cite a timestamp `[HH:MM:SS]` for every claim so it can be checked in the video.

## Report (write it to `REPORT.md` in this folder)
1. **TL;DR** - 3 to 5 sentences.
2. **Key points** - in order, each with its timestamp and why it matters.
3. **On-screen only** - anything visible in the screenshots that was not spoken
   (text on slides, numbers, code, URLs, names, diagrams).
4. **Action items / takeaways** - concrete things a viewer should do or remember.
5. **Skippable sections** - time ranges that are intros, filler, sponsor reads or repetition.

If something is unreadable in a frame or the transcript looks wrong, say so
instead of guessing.
