"""The version, where things get saved, and the numbers that decide how a video is cut up.

Change a number here and every video processed after that uses it.
"""
import os

APP_VERSION = "0.2.1"
BUILD_DATE = "2026-11-11"

# Results go in data/ and queue logs in logs/, both inside the project folder
PROJECT_FOLDER = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_FOLDER = os.path.join(PROJECT_FOLDER, "data")
LOGS_FOLDER = os.path.join(PROJECT_FOLDER, "logs")


# ---------- Transcript lines ----------

# Start a new line when the speaker pauses this long (seconds)
LINE_BREAK_PAUSE = 0.7

# A line never runs longer than this (seconds)
LONGEST_LINE = 9.0

# A line that ends a sentence is closed once it is at least this long (seconds)
SENTENCE_LINE = 4.0

# Lines shorter than this get joined to the next one (seconds)
SHORTEST_LINE = 4.0


# ---------- Screenshots ----------

# How different two frames have to be (0 to 1) for FFmpeg to call it a scene change
SCENE_CHANGE_THRESHOLD = 0.3

# While nobody is talking, take a screenshot this often (seconds)
SILENCE_SCREENSHOT_EVERY = 30.0

# Never take two screenshots closer together than this (seconds)
MIN_SECONDS_BETWEEN_SCREENSHOTS = 2.0

# Screenshots are saved this many pixels wide
SCREENSHOT_WIDTH = 1024

# Two screenshots whose fingerprints differ by this many bits or fewer look the same
SAME_PICTURE_DISTANCE = 6

# A look-alike screenshot is still kept when this percent of it changed, like a new line of
# handwriting on a board
NEW_WRITING_PERCENT = 0.5


# ---------- Output ----------

# Besides the full digest, the video is split into parts this many minutes long
PART_MINUTES = 15.0
