"""Single source of truth for what build this is.

Both values live HERE and only here — never split across pyproject.toml, __init__.py and
this file, because a build that disagrees with itself about its own version is worse than
one with no version at all. `/push` bumps both.
"""

APP_VERSION = "0.1.1"
BUILD_DATE = "2026-11-10"
