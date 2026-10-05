"""
The running release, worked out rather than written down.

A hand-typed version number is only ever right on the day it is typed: the
next edit makes it a lie, and nobody remembers to bump a constant before
restarting a development server. Since the office runs this from a git
checkout, the checkout already knows the answer - the date of the commit it is
sitting on, and which commit that is - so the footer asks git instead of
trusting a number.

The format is CalVer plus build metadata:

    2026.09.17+efa765f          the commit's own date, and its short hash
    2026.09.17+efa765f-dev      the same, with uncommitted changes on top

The date reads as a date to anyone in the Division; the hash pins exactly one
commit for whoever has to reproduce a report of "it still does the old thing".
`-dev` is the honest part: while the working tree is modified, what is running
is not any commit, so the stamp says so rather than naming one.

Nothing here can fail loudly. Git may be absent, the checkout may have been
copied without its history, and the version stamp is not worth a 500 on every
page - each step falls back to the next, and `FALLBACK` is the last word.
"""

import subprocess
from pathlib import Path

# Named when the history cannot be read at all - a copied folder, an archive,
# a machine without git. Raise it by hand when a numbered release is cut.
FALLBACK = "1.0.0"

_GIT_TIMEOUT = 5


def _git(base_dir: Path, *args: str) -> str:
    """One git command, or "" if git cannot answer."""
    try:
        finished = subprocess.run(
            ["git", "-C", str(base_dir), *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
            # Windows: keep a console window from flashing up under a service
            # or a double-clicked launcher.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return ""                               # no git binary, or it hung
    if finished.returncode != 0:
        return ""                               # not a checkout, or no commits yet
    return finished.stdout.strip()


def system_version(base_dir: Path, *, mark_uncommitted: bool = False) -> str:
    """
    The stamp for the footer: CalVer + commit, or `FALLBACK`.

    `mark_uncommitted` costs a second git call that walks the working tree, so
    it is asked for only in development - a deployed checkout is not edited in
    place, and there the extra call would buy nothing on every start-up.
    """
    stamp = _git(base_dir, "log", "-1", "--date=format:%Y.%m.%d", "--format=%cd+%h")
    if not stamp:
        return FALLBACK

    if mark_uncommitted and _git(base_dir, "status", "--porcelain"):
        stamp += "-dev"
    return stamp
