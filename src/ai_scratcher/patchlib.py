# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The AI's patch tool: the paths a unified diff names, the guard refusing a diff that reaches the tree or leaves the project, and its
application with `git apply` -- all of the diff or none of it -- reporting the paths changed."""

import re
import shutil
import subprocess
from pathlib import PurePosixPath

TREE = "syngate"
DEV_NULL = "/dev/null"
# The lines that name a file: `--- a/x` and `+++ b/x` of a section, `diff --git a/x b/x`, and the `rename`/`copy` from and to lines.
NAME_RE = re.compile(r"^(?:---|\+\+\+) (\S+)(?:\t.*)?$|^diff --git (\S+) (\S+)$|^(?:rename|copy) (?:from|to) (\S.*)$", re.M)
SYMLINK_RE = re.compile(r"^(?:new|old)(?: file)? mode 120000$", re.M)


class refused(Exception):
    pass


def paths(diff):
    """The project paths of a git-style unified diff, in order and each once: the `a/` or `b/` prefix off, `/dev/null` left out."""
    names = [name for match in NAME_RE.finditer(diff) for name in match.groups() if name and name != DEV_NULL]
    return list(dict.fromkeys(name[2:] if name[:2] in ("a/", "b/") else name for name in names))


def guard(diff):
    """The project paths of a diff the AI may apply -> them; a diff with no section, a file name without its `a/` or `b/` prefix, a
    path absolute, climbing out of the project, naming `.git` or the tree, or a symbolic link raises `refused`."""
    if not re.search(r"^\+\+\+ ", diff, re.M):
        raise refused("the patch is not a unified diff: name each file's section with `--- a/` and `+++ b/` lines")
    if SYMLINK_RE.search(diff):
        raise refused("the patch makes a symbolic link: a patch writes no symbolic link")
    if any(not line[4:].startswith(("a/", "b/")) for line in diff.splitlines() if line[:4] in ("--- ", "+++ ") and line[4:] != DEV_NULL):
        raise refused("every file of the patch is named with the `a/` or `b/` prefix of a relative path")
    found = paths(diff)
    for rel in found:
        parts = PurePosixPath(rel).parts
        if PurePosixPath(rel).is_absolute() or ".." in parts or parts[0] in (TREE, ".git"):
            raise refused(f"the patch may not change {rel}: the tree changes only through the tree calls, and nothing outside the project or in .git")
    return found


def apply(root, diff):
    """The paths the diff changed, applied to the project in `root` with `git apply` as a whole, or raises `refused` -- with git's
    message naming the section that failed -- leaving every file as it was."""
    changed = guard(diff)
    if shutil.which("git") is None:
        raise refused("git is not at hand to apply the patch")
    for check in (["--check"], []):
        done = subprocess.run(["git", "apply", *check, "-p1", "-"], cwd=root, input=diff, capture_output=True, text=True)
        if done.returncode:
            raise refused((done.stderr or done.stdout).strip() or "git apply refused the patch")
    return changed
