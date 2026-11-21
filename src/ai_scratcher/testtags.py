# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The comment tag of the test setup (design/syngate/test_setup.md): finds the routines bound by a comment line ending in
`syngate` and a UID, with an optional binding, in any text file the `files` globs of a setup match."""

import re
from pathlib import Path

from .syngatelib import BINDING_NAME_RE, UID_RE, Location

OPENER = r"(?:/{2,}|/\*+|\*+|<!--|--+|#+|;+|%+|\{-)"
UID_PATTERN = r"[A-Z](?:[A-Z0-9_-]*[A-Z0-9])?"
TAG_RE = re.compile(rf"^\s*{OPENER}\s*(?:\S*[:\s])?syngate(?::\s*|\s+)({UID_PATTERN})(?:[ \t]+([a-z0-9_]+))?[ \t]*(?:\*/|-->|-\}}|)[ \t]*$")
COMMENT_STARTS = ("//", "/*", "*", "<!--", "--", "#", ";", "%", "{-")
CLOSER_RE = re.compile(r"^(?:[\])}]|end\W*$)")
STRING_RE = re.compile(r"""\(\s*(["'`])((?:\\.|(?!\1).)*)\1""")


def _is_comment(line):
    """Whether a stripped line is a comment line, as the head search passes it over."""
    return line.startswith(COMMENT_STARTS)


def _indent(line):
    """Width of the line's leading whitespace, tabs expanded."""
    expanded = line.expandtabs(4)
    return len(expanded) - len(expanded.lstrip())


def _head_name(head):
    """The routine's name from its head line: its first argument when that is a string literal, else the identifier in front of its first `(`; None when neither."""
    paren = head.find("(")
    if paren < 0:
        return None
    literal = STRING_RE.match(head, paren)
    if literal and literal.group(2).strip():
        return literal.group(2)
    ident = re.search(r"([A-Za-z_$][\w$]*)\s*$", head[:paren])
    return ident.group(1) if ident else None


def _routine_end(lines, head):
    """Index of the last line of the routine whose head is lines[head]: the last line indented deeper than the head, closing brackets or `end` at the head's indent included."""
    base, last = _indent(lines[head]), head
    for i in range(head + 1, len(lines)):
        text = lines[i].strip()
        if not text:
            continue
        if _indent(lines[i]) > base or (_indent(lines[i]) == base and CLOSER_RE.match(text)):
            last = i
        else:
            break
    return last


def _files(root, globs):
    """The text files under `root` the root-relative globs match, sorted, each once."""
    root, found = Path(root).resolve(), {}
    for pattern in globs:
        for path in root.glob(pattern):
            resolved = path.resolve()
            if path.is_file() and resolved.is_relative_to(root):
                found[resolved.relative_to(root).as_posix()] = path
    return [(rel, found[rel]) for rel in sorted(found)]


def comment_locations(root, globs):
    """({(uid, binding|None): [Location]}, [(uid, message)]) -- the comment-tagged routines of the files the globs match, and the
    problems of tags with no routine or a head giving no name. Several tags over one head bind it several times."""
    found, problems = {}, []
    for rel, path in _files(root, globs):
        try:
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(lines):
            tag = TAG_RE.match(line.rstrip("\r\n"))
            if not tag or not UID_RE.match(tag.group(1)) or (tag.group(2) and not BINDING_NAME_RE.match(tag.group(2))):
                continue
            uid, binding = tag.group(1), tag.group(2)
            head = next((i for i in range(n + 1, len(lines))
                         if lines[i].strip() and not _is_comment(lines[i].strip())), None)
            if head is None:
                problems.append((uid, f"{uid}: {rel}:{n + 1}: the syngate tag has no routine below it"))
                continue
            routine = _head_name(lines[head].strip())
            if routine is None:
                problems.append((uid, f"{uid}: {rel}:{head + 1}: the head of the routine tagged at line {n + 1} gives no name: {lines[head].strip()}"))
                continue
            span = "".join(lines[n:_routine_end(lines, head) + 1])
            found.setdefault((uid, binding), []).append(Location(rel, n + 1, f"{rel}::{routine}", span, routine))
    return found, problems
