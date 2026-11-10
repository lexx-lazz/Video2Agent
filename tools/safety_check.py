"""Pre-flight secret hygiene audit.

Run this BEFORE putting a real credential in .env, and again before any push.

Language-agnostic: it only shells out to git, so it works the same in a Python
project and a C++ one. Exits non-zero if anything fails, so `run.bat safety` can
be used as a gate in a script or a scheduled task.

    run.bat safety
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Files that hold credentials and must never be tracked.
SECRET_FILES = [".env", ".env.local", ".env.production"]

# Extensions worth scanning. Anything else is treated as binary/noise.
TEXT_SUFFIXES = {
    ".py", ".pyi", ".c", ".h", ".cpp", ".hpp", ".cc", ".cs", ".java", ".go", ".rs",
    ".js", ".ts", ".jsx", ".tsx", ".json", ".toml", ".yaml", ".yml", ".ini", ".cfg",
    ".md", ".txt", ".bat", ".sh", ".ps1", ".sql", ".html", ".css", ".xml", "",
}

# Vendor key prefixes are near-zero false positive. The generic assignment rule
# below catches the rest.
KEY_PATTERNS = [
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}"), "an OpenAI-style secret key"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"), "a GitHub token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}"), "a GitHub fine-grained token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "an AWS access key id"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}"), "a Google API key"),
    (re.compile(r"\bxox[baprs]-[0-9A-Za-z\-]{10,}"), "a Slack token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "a private key block"),
]

# KEY = "long-opaque-value". Placeholders and obvious examples are excluded.
ASSIGNMENT = re.compile(
    r"""(?ix)
    \b(?P<name>[A-Z0-9_]*(?:SECRET|PASSWORD|PASSWD|TOKEN|API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY)[A-Z0-9_]*)
    \s*[:=]\s*
    ['\"]?(?P<value>[A-Za-z0-9+/=_\-]{16,})['\"]?
    """
)
PLACEHOLDER = re.compile(
    r"(?i)^(your|my|the)?[_\-]?(x{3,}|\.{3,}|placeholder|example|changeme|redacted|"
    r"dummy|sample|test|fake|none|null|todo|insert|replace|abc123|secret|password|"
    r"token|key|value)"
)


def git(*args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout.strip()


def main() -> int:
    failures: list[str] = []
    warnings: list[str] = []

    code, _ = git("rev-parse", "--git-dir")
    if code != 0:
        print("[ERROR] Not a git repository. Nothing to audit.")
        return 1

    # 1. Secret files must be ignored, and must not be tracked.
    for name in SECRET_FILES:
        path = ROOT / name
        ignored, _ = git("check-ignore", "-q", name)
        _, tracked = git("ls-files", "--error-unmatch", name)
        is_tracked = bool(tracked)

        if is_tracked:
            failures.append(
                f"{name} is TRACKED by git. The value is in the repository and in its "
                f"history — treat the credential as compromised and rotate it. Adding it "
                f"to .gitignore now does not remove it."
            )
        elif path.exists() and ignored != 0:
            failures.append(f"{name} exists but is NOT git-ignored. Add it to .gitignore.")
        elif ignored == 0:
            print(f"  ok    {name} is git-ignored")

    # 2. Nothing secret staged right now.
    _, staged = git("diff", "--cached", "--name-only")
    for line in staged.splitlines():
        if Path(line).name in SECRET_FILES:
            failures.append(f"{line} is STAGED for commit. Unstage it: git restore --staged {line}")

    # 3. Scan tracked text files for credential-shaped strings.
    _, tracked_out = git("ls-files")
    scanned = 0
    for rel in tracked_out.splitlines():
        path = ROOT / rel
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            if path.stat().st_size > 1_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1

        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern, label in KEY_PATTERNS:
                if pattern.search(line):
                    failures.append(f"{rel}:{lineno} looks like {label}.")
            match = ASSIGNMENT.search(line)
            if match and not PLACEHOLDER.match(match.group("value")):
                warnings.append(
                    f"{rel}:{lineno} assigns {match.group('name')} a long literal value. "
                    f"Confirm it is not a real credential."
                )
    print(f"  ok    scanned {scanned} tracked text files")

    # 4. .env.example should exist and should not carry values.
    example = ROOT / ".env.example"
    if not example.exists():
        warnings.append(".env.example is missing. It documents the key names with empty values.")
    else:
        for lineno, line in enumerate(example.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            _, _, value = line.partition("=")
            if value.strip().strip("\"'"):
                warnings.append(f".env.example:{lineno} has a value filled in. Leave them empty.")

    print()
    for w in warnings:
        print(f"  WARN  {w}")
    for f in failures:
        print(f"  FAIL  {f}")

    print()
    if failures:
        print(f"SAFETY AUDIT FAILED — {len(failures)} problem(s), {len(warnings)} warning(s).")
        return 1
    print(f"Safety audit passed. {len(warnings)} warning(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
