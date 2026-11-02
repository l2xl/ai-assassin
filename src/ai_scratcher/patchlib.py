# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The AI's patch tool: the paths a unified diff names, the guard refusing a diff that reaches the tree or leaves the project, and its
application with `git apply` -- all of the diff or none of it -- reporting the paths changed; and the exact replacement of one text in
one file under the same guard."""

import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath

TREE = "syngate"
DEV_NULL = "/dev/null"
# The lines that name a file: `--- a/x` and `+++ b/x` of a section, `diff --git a/x b/x`, and the `rename`/`copy` from and to lines.
NAME_RE = re.compile(r"^(?:---|\+\+\+) (\S+)(?:\t.*)?$|^diff --git (\S+) (\S+)$|^(?:rename|copy) (?:from|to) (\S.*)$", re.M)
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$")
SYMLINK_RE = re.compile(r"^(?:new|old)(?: file)? mode 120000$", re.M)


class refused(Exception):
    pass


def paths(diff):
    """The project paths of a git-style unified diff, in order and each once: the `a/` or `b/` prefix off, `/dev/null` left out."""
    names = [name for match in NAME_RE.finditer(diff) for name in match.groups() if name and name != DEV_NULL]
    return list(dict.fromkeys(name[2:] if name[:2] in ("a/", "b/") else name for name in names))


def guard_path(rel):
    """Refuse, as `refused`, a project path absolute, climbing out of the project or naming `.git` or the tree."""
    parts = PurePosixPath(rel).parts
    if not parts or PurePosixPath(rel).is_absolute() or ".." in parts or parts[0] in (TREE, ".git"):
        raise refused(f"the patch may not change {rel}: the tree changes only through the tree calls, and nothing outside the project or in .git")


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
        guard_path(rel)
    return found


def recount(diff):
    """The diff with the line counts of every hunk header set to the lines its hunk carries -- a model miscounts them far more often than
    it misquotes the context. A hunk ends at the next hunk header, `diff --git` line or `--- ` line followed by a `+++ ` one, its trailing
    empty lines left out; git's own `--recount` would read such a `--- ` line as a removed one."""
    lines, out, at = diff.split("\n"), [], 0
    while at < len(lines):
        header = HUNK_RE.match(lines[at])
        if not header:
            out.append(lines[at])
            at += 1
            continue
        end = at + 1
        while end < len(lines) and not (lines[end].startswith(("@@ ", "diff --git ")) or (lines[end].startswith("--- ") and end + 1 < len(lines)
                                                                                     and lines[end + 1].startswith("+++ "))):
            end += 1
        body = lines[at + 1:end]
        while body and body[-1] == "":
            body.pop()
        old = sum(1 for line in body if line[:1] in (" ", "-", ""))
        new = sum(1 for line in body if line[:1] in (" ", "+", ""))
        start_old, start_new = int(header.group(1)), int(header.group(2))
        out.append(f"@@ -{start_old},{old} +{start_new},{new} @@{header.group(3)}")
        out += lines[at + 1:end]
        at = end
    return "\n".join(out)


def apply(root, diff):
    """The paths the diff changed, applied to the project in `root` with `git apply` as a whole, or raises `refused` -- with git's
    message naming the section that failed -- leaving every file as it was."""
    changed = guard(diff)
    if shutil.which("git") is None:
        raise refused("git is not at hand to apply the patch")
    for check in (["--check"], []):
        done = subprocess.run(["git", "apply", *check, "-p1", "-"], cwd=root, input=recount(diff), capture_output=True, text=True)
        if done.returncode:
            raise refused((done.stderr or done.stdout).strip() or "git apply refused the patch")
    return changed


def replace(root, rel, old, new=""):
    """[rel] after changing the one occurrence of the exact text `old` in the project file `rel` to `new`, line endings kept, or raises
    `refused` -- for a path the guard refuses, a file that is no regular file of the project, or a text absent or repeated there."""
    guard_path(rel)
    base = Path(root).resolve()
    path = base / rel
    if path.is_symlink() or not path.is_file() or base not in path.resolve().parents:
        raise refused(f"{rel} is no file of the project: a replace changes an existing regular file, a patch creates one")
    with open(path, encoding="utf-8", newline="") as file:
        text = file.read()
    count = text.count(old) if old else 0
    if count == 0:
        raise refused(f"the text to replace is not in {rel}: copy it exactly from the file as it is now")
    if count > 1:
        raise refused(f"the text to replace occurs {count} times in {rel}: widen it with the words around it until it occurs once")
    with open(path, "w", encoding="utf-8", newline="") as file:
        file.write(text.replace(old, new, 1))
    return [rel]
