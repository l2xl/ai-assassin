# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The AI's grep tool (design/tools/grep.md): the search programs it runs -- ripgrep, GNU grep, git grep -- one of which the offered library
selects by the prompt it holds of the `grep` feature, the guard keeping a command line to the options its program's definition lists and
to the project's own files, and the run without a shell -- nothing of it changes a file."""

import os
import shlex
import subprocess
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from . import filelib, gitlib

TIMEOUT = 60
OUTPUT_LIMIT = 30000
TREE = filelib.TREE
# The options that give the pattern, so that every other word is a path, and those naming a file the program reads it from.
PATTERN_OPTIONS = ("-e", "--regexp", "-f", "--file")
FILE_OPTIONS = ("-f", "--file")


class refused(ValueError):
    """A grep command line the tool does not run."""


class search_program(NamedTuple):
    """One program the grep tool runs: its `label`, the `head` of its argv, the `fixed` options the harness sets ahead of the turn's own, and
    the options its definition lists -- the `flags` and those taking a value -- long ones in full, short ones as `-x`."""
    label: str
    head: tuple
    fixed: tuple
    flags: frozenset
    values: frozenset


def _program(label, head, fixed, flags, values):
    return search_program(label, tuple(head), tuple(fixed), frozenset(flags.split()), frozenset(values.split()))


PROGRAMS = {
    "rg": _program("ripgrep", ("rg",), ("--no-config", "--no-heading", "--with-filename", "--line-number", "--color", "never"),
                   "-i --ignore-case -S --smart-case -s --case-sensitive -w --word-regexp -x --line-regexp -F --fixed-strings -v --invert-match "
                   "-n --line-number -N --no-line-number -l --files-with-matches --files-without-match -c --count --count-matches "
                   "-o --only-matching -U --multiline --multiline-dotall -P --pcre2 --hidden --no-ignore -u --unrestricted -H --with-filename "
                   "-I --no-filename --column --vimgrep",
                   "-e --regexp -f --file -g --glob --iglob -t --type -T --type-not -A --after-context -B --before-context -C --context "
                   "-m --max-count -d --max-depth -M --max-columns -r --replace --sort"),
    "gnu": _program("GNU grep", ("grep",), ("-r", "-n", "-H", "-I", "--color=never"),
                    "-i --ignore-case --no-ignore-case -w --word-regexp -x --line-regexp -F --fixed-strings -E --extended-regexp "
                    "-G --basic-regexp -P --perl-regexp -v --invert-match -n --line-number -l --files-with-matches -L --files-without-match "
                    "-c --count -o --only-matching -h --no-filename -H --with-filename -s --no-messages -a --text -I",
                    "-e --regexp -f --file -A --after-context -B --before-context -C --context -m --max-count --include --exclude --exclude-dir"),
    "git": _program("git grep", ("git", "grep"), ("-n", "--no-color"),
                    "-i --ignore-case -w --word-regexp -v --invert-match -n --line-number -l --files-with-matches --name-only "
                    "-L --files-without-match -c --count -o --only-matching -h -H -F --fixed-strings -E --extended-regexp -G --basic-regexp "
                    "-P --perl-regexp --untracked --cached --all-match --column",
                    "-e -f -A --after-context -B --before-context -C --context -m --max-count --max-depth"),
}
# The prompts of the `grep` feature, best first, each defining the grep call for the program it names.
PROMPTS = {"grep_rg": "rg", "grep_gnu": "gnu", "grep_git": "git"}


def program(library):
    """The program of the grep prompt the `library` holds -- `rg`, `gnu` or `git` -- None while it holds none."""
    return next((PROMPTS[name] for name in PROMPTS if name in library), None)


def excludes(name, secret=()):
    """The options -- for git grep the pathspecs -- that keep a search of the program `name` out of `.git`, the tree and the `secret` files,
    appended after the turn's own so they win over its filters."""
    if name == "rg":
        return [word for glob in (".git", ".git/**", TREE, f"{TREE}/**", *secret) for word in ("--glob", f"!{glob}")]
    if name == "gnu":
        return ["--exclude-dir=.git", f"--exclude-dir={TREE}", *(f"--exclude={PurePosixPath(rel).name}" for rel in secret)]
    return [f":(exclude){rel}" for rel in (TREE, *secret)]


def guard_path(root, rel, secret=()):
    """Refuse, as `refused`, a path the program may not read: one the files tool refuses -- absolute, climbing or linking out of the project,
    in `.git`, under the tree, a `secret` file -- or one reached through a symbolic link."""
    try:
        filelib.guard(root, rel, secret)
    except filelib.refused as err:
        raise refused(str(err)) from None
    at = Path(root)
    for part in PurePosixPath(rel).parts:
        at = at / part
        if at.is_symlink():
            raise refused(f"{rel} goes through the symbolic link {at.relative_to(root).as_posix()}: name the project's files themselves")


def _no_option(option, spec):
    return refused(f"'{option}' is no option the grep tool takes for {spec.label}: only the options its definition lists, a long one in full")


def _value(words, at, option):
    if at >= len(words):
        raise refused(f"'{option}' takes a value: give it glued or as the next word")
    return words[at]


def guard(root, command, name, secret=()):
    """The argv of a grep command line of the program `name` the tool runs in the project `root`: its head and fixed options, the turn's
    options, the `excludes`, then the pattern and the paths past `--`. An option the definition does not list, a command line naming no
    pattern, and a path or `-f` file `guard_path` refuses raise `refused`."""
    spec = PROGRAMS[name]
    try:
        words = shlex.split(command)
    except ValueError as err:
        raise refused(f"the command line does not split into words: {err}") from None
    options, operands, given, files, at = [], [], False, [], 0

    def took(option, value):
        nonlocal given
        given = given or option in PATTERN_OPTIONS
        if option in FILE_OPTIONS:
            files.append(value)

    while at < len(words):
        word = words[at]
        at += 1
        if word == "--":
            operands += words[at:]
            break
        if word == "-":
            raise refused("'-' reads the stdin, and the grep tool runs without one: name the project's files")
        if word.startswith("--"):
            option, glued, value = word.partition("=")
            if option in spec.values:
                if not glued:
                    value = _value(words, at, option)
                    at += 1
                options += [word] if glued else [word, value]
                took(option, value)
            elif option in spec.flags and not glued:
                options.append(word)
            elif option in spec.flags:
                raise refused(f"'{option}' takes no value")
            else:
                raise _no_option(option, spec)
        elif word.startswith("-"):
            options.append(word)
            for index, letter in enumerate(word[1:], 1):
                option = "-" + letter
                if option in spec.values:
                    value = word[index + 1:]
                    if not value:
                        value = _value(words, at, option)
                        at += 1
                        options.append(value)
                    took(option, value)
                    break
                if option not in spec.flags:
                    raise _no_option(option, spec)
        else:
            operands.append(word)
    if not given and not operands:
        raise refused("the command line names no pattern: give it as the first word past the options, or with -e")
    pattern, paths = (None, operands) if given else (operands[0], operands[1:])
    for rel in paths:
        if name == "git" and rel.startswith(":"):
            raise refused(f"'{rel}': git grep takes literal paths here, no pathspec magic")
        guard_path(root, rel, secret)
    for rel in files:
        guard_path(root, rel, secret)
    head = [*spec.head, *spec.fixed, *options]
    if name == "git":
        return [*head, *(["-e", pattern] if pattern is not None else []), "--", *paths, *excludes(name, secret)]
    return [*head, *excludes(name, secret), "--", *([pattern] if pattern is not None else []), *paths]


def run(root, words):
    """The exit status and output of the guarded argv `words` run in `root` without a shell or stdin, cut past `OUTPUT_LIMIT` characters."""
    try:
        done = subprocess.run(words, cwd=root, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", timeout=TIMEOUT,
                              env={**os.environ, **gitlib.ENV})
    except subprocess.TimeoutExpired:
        return f"timed out after {TIMEOUT} s"
    except OSError as err:
        return f"{words[0]} could not run: {err}"
    output = done.stdout + done.stderr
    cut = f"\n… cut at {OUTPUT_LIMIT} characters: narrow the search" if len(output) > OUTPUT_LIMIT else ""
    return f"exit {done.returncode}\n{output[:OUTPUT_LIMIT]}{cut}".rstrip("\n")
