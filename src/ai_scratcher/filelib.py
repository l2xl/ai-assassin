# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The AI's files tool: the guard keeping a read inside the project and off the tree, `.git` and the files named as secret, the listing
of a folder and the reading of a text file by a range of its lines -- nothing of it changes a file."""

from pathlib import Path, PurePosixPath

TREE = "syngate"
SKIPPED = (".git", "__pycache__", "node_modules")  # folders a listing leaves out
READ_LIMIT = 20000  # characters one read returns
LIST_LIMIT = 400  # entries one listing returns
LIST_DEPTH = 5  # folder levels a listing may descend


class refused(Exception):
    pass


def guard(root, rel, secret=()):
    """The path of the project file or folder `rel` under `root`; a path absolute, climbing or linking out of the project, naming `.git`
    or the tree, or one of the `secret` project paths raises `refused`."""
    pure = PurePosixPath(rel or ".")
    parts = pure.parts
    if pure.is_absolute() or ".." in parts:
        raise refused(f"{rel} is outside the project: name a path relative to the project root")
    if parts and parts[0] == TREE:
        raise refused(f"{rel} is in the tree: the items are read only through the tree calls")
    if ".git" in parts or str(pure) in secret:
        raise refused(f"{rel} is not readable")
    base = Path(root).resolve()
    path = (base / pure).resolve()
    if path != base and base not in path.parents:
        raise refused(f"{rel} is outside the project: name a path relative to the project root")
    return path


def whole(value, name, least, default):
    """The whole number an optional field of a call carries, `default` without it; anything else, or one under `least`, raises `refused`."""
    if value is None:
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = None
    if number is None or isinstance(value, bool) or number < least:
        raise refused(f"{name} must be a whole number of at least {least}")
    return number


def listing(root, rel=".", depth=None, secret=()):
    """The entries of the project folder `rel`, `depth` levels deep (1 by default, `LIST_DEPTH` at most), one per line: a folder as its
    path with a trailing slash, a file as its path with its size in bytes; the tree is named and not entered, the skipped folders and the
    secret files are left out, and a listing past `LIST_LIMIT` entries is cut."""
    base, folder = Path(root).resolve(), guard(root, rel, secret)
    if not folder.is_dir():
        raise refused(f"{rel} is no folder of the project")
    depth = min(whole(depth, "depth", 1, 1), LIST_DEPTH)
    lines, cut = [], False

    def walk(at, left):
        nonlocal cut
        for entry in sorted(at.iterdir(), key=lambda entry: (not entry.is_dir(), entry.name)):
            name = entry.relative_to(base).as_posix()
            if entry.name in SKIPPED or name in secret:
                continue
            if len(lines) >= LIST_LIMIT:
                cut = True
                return
            if entry.is_dir():
                lines.append(name + "/")
                if left > 1 and name != TREE and not entry.is_symlink():
                    walk(entry, left - 1)
            elif entry.is_file():
                lines.append(f"{name}  {entry.stat().st_size}")

    walk(folder, depth)
    return "\n".join(lines or ["(empty)"]) + (f"\n… cut at {LIST_LIMIT} entries: list a folder below" if cut else "")


def read(root, rel, start=None, count=None, secret=()):
    """The lines of the project text file `rel` from line `start` (1 by default), `count` of them or all: a first line telling the range
    returned and the lines of the file, then every line under its number. A read past `READ_LIMIT` characters is cut at a whole line and
    tells the line to go on from; a folder, a missing file and a file that is no UTF-8 text raise `refused`."""
    path = guard(root, rel, secret)
    if not path.is_file():
        raise refused(f"{rel} is no file of the project" + (": list it instead" if path.is_dir() else ""))
    start, count = whole(start, "from", 1, 1), whole(count, "lines", 1, None)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        raise refused(f"{rel} is not a text file") from None
    if start > max(len(lines), 1):
        raise refused(f"{rel} has {len(lines)} lines: from {start} is past its end")
    wanted, out, size = lines[start - 1:start - 1 + count if count else None], [], 0
    for number, line in enumerate(wanted, start):
        numbered = f"{number}\t{line}"
        if out and size + len(numbered) > READ_LIMIT:
            break
        out.append(numbered)
        size += len(numbered) + 1
    last = start + len(out) - 1
    more = f"\n… cut at {READ_LIMIT} characters: go on with from {last + 1}" if len(out) < len(wanted) else ""
    return f"{rel} lines {start}-{last} of {len(lines)}\n" + "\n".join(out) + more
