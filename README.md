# Video2Agent

An AI agent cannot watch a video. It can read text and look at images, but a
two-hour recording handed over as a file is opaque to it, and a transcript alone
loses everything that was only ever shown on screen: slides, code, charts, UI.

Video2Agent turns a downloaded video into a timestamped transcript with the
matching screenshots beside each passage, so an agent can read the whole thing
end to end and report what matters, with timestamps you can check.

## What it produces

Running it on `talk.mp4` writes a `talk_agent/` folder next to the video:

| File | What |
|---|---|
| `video_digest.md` | the whole video: each block is a timestamp, the screenshot on screen, and the lines spoken while it showed |
| `parts/part_NN.md` | the digest in 15-minute chunks, for videos too long to read in one go |
| `frames/` | the screenshots (JPEG, 1024 px wide) |
| `transcript.srt`, `segments.json` | the raw transcript and frame index |
| `AGENT_PROMPT.md` | instructions for the agent: TL;DR, key points with timestamps, on-screen-only information, action items, skippable sections |

## Setup

FFmpeg must be on PATH:

    winget install Gyan.FFmpeg

Python dependencies install themselves into a project-local `.venv` the first
time `run.bat` is used.

## Use

    run.bat "C:\path\to\talk.mp4"

Then hand the folder to an agent:

    cd "C:\path\to\talk_agent"
    claude "Follow AGENT_PROMPT.md"

Other launcher commands:

    run.bat test       run the test suite (offline)
    run.bat safety     secret hygiene audit
    run.bat deps       reinstall dependencies

## Where the transcript comes from

A `.srt` or `.vtt` file next to the video with the same name (`talk.srt`,
`talk.en.vtt`) is used automatically. Otherwise speech is transcribed locally
with faster-whisper on the CPU; nothing is uploaded. The first run downloads the
model.

## How screenshots are chosen

One at every scene change, one at the middle of every spoken passage, and one
every 30 seconds while nobody is talking. Frames that look the same as the one
before are then dropped, so a slide that stays up for five minutes appears once.

## Options

| Flag | Default | |
|---|---|---|
| `--subs FILE` | | use this subtitle file |
| `--force-whisper` | | ignore subtitle files and transcribe locally |
| `--model` | `small` | `tiny`, `base`, `small`, `medium`, `large-v3` |
| `--language` | auto | e.g. `en` |
| `--scene` | `0.3` | scene-change threshold; lower gives more frames |
| `--silence-interval` | `30` | seconds between frames when nobody talks |
| `--min-gap` | `2` | minimum seconds between frames |
| `--min-segment` | `4` | merge transcript fragments shorter than this |
| `--hash-dist` | `6` | how similar two frames must be to count as duplicates; lower keeps more |
| `--width` | `1024` | screenshot width in pixels |
| `--part-minutes` | `15` | length of each part file |
| `--out DIR` | | output folder |
| `--version` | | print the version and build date |
