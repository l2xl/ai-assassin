# Open Trader
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Git access of AI Assassin: whether git is at hand for a project, the guard and the run of the AI's git tool, the uncommitted
files a review refuses and the review commit."""

import os
import re
import shlex
import shutil
import subprocess

READS = ("status", "diff", "log", "show", "blame", "grep", "ls-files", "shortlog", "describe", "rev-parse")
RECORDS = ("add", "commit", "mv", "rm", "restore", "branch", "tag", "switch", "merge", "cherry-pick", "revert")
# The options that discard, rewrite or delete what git holds, or reach past the repository: long names, short letters.
REFUSED = {
    "commit": ({"amend", "no-verify"}, "n"),
    "add": ({"force"}, "f"),
    "mv": ({"force"}, "f"),
    "rm": ({"force", "pathspec-from-file"}, "f"),
    "branch": ({"delete", "move", "force"}, "dDmMCf"),
    "tag": ({"delete", "force"}, "df"),
    "switch": ({"force-create", "force", "discard-changes", "merge", "orphan"}, "Cfm"),
    "merge": ({"abort"}, ""),
    "cherry-pick": ({"abort"}, ""),
    "revert": ({"abort"}, ""),
    "restore": ({"worktree"}, "W"),
}
EVERYWHERE = ({"output", "no-index", "open-files-in-pager"}, "O")
PATHS_GUARDED = ("mv", "rm")
TREE = "syngate"
MAGIC = re.compile(r"^:|[*?\[]")
REVIEW_RE = re.compile(r"^Review(ed)?\b")
ENV = {"GIT_PAGER": "cat", "GIT_EDITOR": "false", "GIT_TERMINAL_PROMPT": "0"}
TIMEOUT = 120
OUTPUT_LIMIT = 30000
SUBJECTS = 200


class refused(ValueError):
    """A git command the tool does not run."""


def git(root, *args, timeout=TIMEOUT):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, stdin=subprocess.DEVNULL, env={**os.environ, **ENV}, timeout=timeout)


def at_hand(root):
    """Whether the `git` command is found and `root` lies in a git work tree."""
    if shutil.which("git") is None:
        return False
    try:
        return git(root, "rev-parse", "--is-inside-work-tree", timeout=10).stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return False


def _option(word, longs, shorts):
    """Whether `word` is a refused option: a long one by any abbreviation git accepts, a short one anywhere in a bundle."""
    if word.startswith("--"):
        name = word[2:].partition("=")[0]
        return bool(name) and any(refused_name.startswith(name) for refused_name in longs)
    return word.startswith("-") and any(letter in shorts for letter in word[1:])


def _guard_path(word):
    if MAGIC.search(word):
        raise refused(f"'{word}': mv and rm take literal paths, no glob or pathspec magic")
    path = os.path.normpath(word)
    if path in (".", TREE) or path.startswith((TREE + os.sep, "..")) or os.path.isabs(path):
        raise refused(f"'{word}': mv and rm take no path under {TREE}/ or holding it — the items change only through the tree calls")


def guard(command):
    """(words, whether the command records) of a git command line the tool runs; a command it does not run raises `refused`."""
    try:
        words = shlex.split(command)
    except ValueError as err:
        raise refused(f"the command line does not split into words: {err}") from None
    if not words:
        raise refused("an empty command line")
    name = words[0]
    if name.startswith("-"):
        raise refused(f"'{name}': no option goes ahead of the command")
    if name not in READS + RECORDS:
        raise refused(f"'{name}' is not a command of the git tool, which only reads and records")
    longs, shorts = REFUSED.get(name, (set(), ""))
    longs, shorts, options = longs | EVERYWHERE[0], shorts + EVERYWHERE[1], True
    for word in words[1:]:
        if options and word == "--":
            options = False
        elif options and word.startswith("-") and word != "-":
            if _option(word, longs, shorts):
                raise refused(f"'{word}' would discard, rewrite or delete what git holds, or reach past the repository"
                              " (write an option's value as a word of its own)")
        elif name in PATHS_GUARDED:
            _guard_path(word)
    if name == "restore" and not {"--staged", "-S"} & set(words):
        raise refused("restore takes back the work tree; only restore --staged runs")
    return words, name in RECORDS


def run(root, words):
    """The exit status and output of `git <words>` in `root`, cut past `OUTPUT_LIMIT` characters."""
    try:
        done = git(root, *words)
    except subprocess.TimeoutExpired:
        return f"timed out after {TIMEOUT} s"
    output = done.stdout + done.stderr
    cut = f"\n… cut at {OUTPUT_LIMIT} characters" if len(output) > OUTPUT_LIMIT else ""
    return f"exit {done.returncode}\n{output[:OUTPUT_LIMIT]}{cut}".rstrip("\n")


def uncommitted(root):
    """The root-relative paths of every file with a change git has not committed: modified, staged, deleted, renamed or untracked."""
    prefix = git(root, "rev-parse", "--show-prefix").stdout.strip()
    entries = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", ".").stdout.split("\0")
    paths, renamed = set(), False
    for entry in entries:
        if renamed:
            path, renamed = entry, False
        elif len(entry) > 3:
            path, renamed = entry[3:], bool(set(entry[:2]) & {"R", "C"})
        else:
            continue
        if path.startswith(prefix):
            paths.add(path[len(prefix):])
    return paths


def state(root):
    """What tells a change of the repository: the commit at HEAD and the status of the work tree."""
    return git(root, "rev-parse", "HEAD").stdout + git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout


def since_review(root):
    """The subjects of the commits since the last review commit -- the latest whose subject opens with `Review` or `Reviewed` --
    newest first."""
    subjects = []
    for subject in git(root, "log", "--no-merges", f"-{SUBJECTS}", "--format=%s").stdout.splitlines():
        if REVIEW_RE.match(subject):
            break
        subjects.append(subject)
    return subjects


def commit(root, paths, message):
    """Commit the work tree state of `paths` alone, whatever else is staged. -> (whether it was made, git's output)."""
    done = git(root, "commit", "-m", message, "--only", "--", *paths)
    return done.returncode == 0, (done.stdout + done.stderr).strip()
