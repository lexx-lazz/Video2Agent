# Video2Agent

An AI agent cannot watch a video. It can read text and look at images, but a
two-hour recording handed over as a file is opaque to it, and a transcript alone
loses everything that was only ever shown on screen: slides, code, charts, UI.

Video2Agent turns a downloaded video into a timestamped transcript with the
matching screenshots beside each passage, so an agent can read the whole thing
end to end and report what matters, with timestamps you can check.

## What it produces

Every video gets one folder named after it, inside the project's `data` folder.
Processing `talk.mp4` writes `data/talk/`, and that folder is everything an agent
needs. You can group videos: each time you pick a video, a second window asks
which folder to save in, so a course can live in `data/Physics/talk/`.

| File | What |
|---|---|
| `video_digest.md` | the whole video: each block is a timestamp, the screenshot on screen, and the lines spoken while it showed |
| `parts/part_NN.md` | the digest in 15-minute chunks, for videos too long to read in one go |
| `frames/` | the screenshots (JPEG, 1024 px wide) |
| `transcript.srt`, `segments.json` | the raw transcript and frame index |
| `preview.html` | for you, not the agent: the video beside every screenshot and its lines, to check the pairing |
| `AGENT_PROMPT.md` | instructions for the agent: TL;DR, key points with timestamps, on-screen-only information, action items, skippable sections |

## Setup

FFmpeg must be on PATH:

    winget install Gyan.FFmpeg

You also need Python 3.9 or newer (tested on 3.9 and 3.12). The Python packages
install themselves into a `.venv` folder inside the project the first time
`run.bat` is used.

## Use

Double-click `run.bat`, or run it with no arguments, for the menu:

    [1] Pick a video and process it now  opens a file explorer window
    [2] Overnight queue                  line up videos, run them one after another
    [3] Processed videos                 open a finished folder or its preview
    [4] Open the data folder
    [5] Whisper model                    tiny / base / small / medium / large-v3
    [6] Language                         spoken language, English by default
    [7] Transcript                       use subtitles if found, or always transcribe

When a video finishes, the menu shows its folder and the two lines that hand it
to an agent:

    cd "data\talk"
    claude "Follow AGENT_PROMPT.md"

To skip the menu, pass the video directly:

    run.bat "C:\path\to\talk.mp4"

Other launcher commands:

    run.bat test       run the test suite (offline)
    run.bat safety     secret hygiene audit
    run.bat deps       reinstall dependencies

## Checking the result

Every folder has a `preview.html`. Open it (option `P` after a video finishes, or
from Processed videos) and the video plays on the left with every screenshot
and its transcript lines on the right. The block for the moment now playing is
highlighted, and clicking any timestamp or screenshot jumps the video there. If
what is highlighted matches what you see and hear, the pairing is right.

## Running a batch overnight

In the menu, option 2 is the queue. Add videos one by one or a whole folder,
then start it now or at a set time such as 23:30. Videos run in order, one
failure does not stop the rest, the PC is kept awake until the last one is
done, and a log of the run is written to `logs/`.

The same thing without the menu, for a scheduled task or a headless machine:

    run.bat "C:\lectures"                    every video in a folder, in order
    run.bat a.mp4 b.mp4 c.mp4                several videos, in order
    run.bat --queue --at 23:30               the queue built in the menu, at 23:30

A one-hour lecture takes roughly 10 to 15 minutes on a six-core desktop CPU with
the default model.

## Where the transcript comes from

A `.srt` or `.vtt` file next to the video with the same name (`talk.srt`,
`talk.en.vtt`) is used automatically. Otherwise speech is transcribed locally
with faster-whisper on the CPU; nothing is uploaded. The first run downloads the
model. The spoken language is assumed to be English unless you change it:
letting the model guess is slower, and a wrong guess ruins the transcript.

## How screenshots are chosen

One at every scene change, one at the middle of every spoken passage, and one
every 30 seconds while nobody is talking. Frames that look the same as the one
before are then dropped, so a slide that stays up for five minutes appears once,
while a board that is being written on is captured again as it fills in.

## Options

| Flag | Default | |
|---|---|---|
| `--subs FILE` | | use this subtitle file |
| `--force-whisper` | | ignore subtitle files and transcribe locally |
| `--model` | `small` | `tiny`, `base`, `small`, `medium`, `large-v3` |
| `--language` | `en` | spoken language code, or `auto` to detect it |
| `--queue` | | process the saved queue, then exit |
| `--at HH:MM` | | wait until this time before starting a queue or batch |
| `--dest FOLDER` | `data` | folder to save in; output goes to `FOLDER/<video name>/`. A plain name means a folder inside `data` |
| `--out DIR` | | exact output folder, instead of `<dest>/<video name>/` |
| `--version` | | print the version and build date |

The numbers that decide how a video is cut up (how often to take a screenshot,
how different two screenshots must be to keep both, how long a transcript line
can be, how long each part is) are all in `src/video2agent/constants.py`, each
with a comment saying what it does.

## How the code is laid out

| File | Job |
|---|---|
| `cli.py` | the command line; with no video named it opens the menu |
| `menu.py` | the menu and the file explorer windows |
| `pipeline.py` | one video from start to finish, in order |
| `transcribe.py` | subtitle files, Whisper, and cutting speech into timed lines |
| `screenshots.py` | when to take screenshots, taking them, dropping repeats |
| `digest.py` | pairing lines with screenshots and writing the output folder |
| `preview.py` | the preview page |
| `video_queue.py` | the overnight queue |
| `templates/` | the preview page and the agent instructions, as plain files |

## Licence

Video2Agent is free to use, change and share for anything that isn't commercial:
personal projects, study, research, schools, charities and the like. Selling it,
or using it to make money, is not allowed without asking first.

The full terms are the [PolyForm Noncommercial License 1.0.0](LICENSE).

Required Notice: Copyright (c) 2026 lexx-lazz (https://github.com/lexx-lazz/Video2Agent)
