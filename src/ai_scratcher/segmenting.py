# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Large texts in segments (ORCHESTRATOR-TIER-LARGE, ORCHESTRATOR-SECURITY-LARGE): a text cut along its own structure into segments bounded in
characters, each carrying the last whole units of the one before, and the ends of a long row of segments. Nothing here calls a model."""

import re

SEGMENT_CHARS = 2000  # a segment of a message: far under the 8192 tokens of the models' window even at one character to a token
OVERLAP_CHARS = 300  # what a segment takes over of the one before, in whole units
LEVELS = (r"\n[ \t]*\n\s*", r"\n", r"(?<=[.!?])\s+", r"\s+")  # blank lines, lines, sentences, words: the boundaries, coarse to fine


def parts(text, level):
    """The pieces of `text` cut after every boundary of the `level`, the boundary staying with the piece before it, so that they join into `text`."""
    cuts, start = [], 0
    for found in re.finditer(LEVELS[level], text):
        if found.end() > start and found.end() < len(text):
            cuts.append(text[start:found.end()])
            start = found.end()
    return [*cuts, text[start:]]


def units(text, size, level=0):
    """The units of `text` in order, each at most `size` characters: a piece that fits stays whole, one that does not is cut at the next finer
    boundary, and one without any boundary left at the fixed length. They join into `text`."""
    if len(text) <= size:
        return [text]
    if level == len(LEVELS):
        return [text[at:at + size] for at in range(0, len(text), size)]
    pieces = parts(text, level)
    return units(text, size, level + 1) if len(pieces) == 1 else [unit for piece in pieces for unit in units(piece, size, level + 1)]


def segments(text, size=SEGMENT_CHARS, overlap=OVERLAP_CHARS):
    """The segments of `text`, each at most `size` characters, cut between units -- never inside one that a coarser boundary lets stand -- and
    each opening with the last whole units of the one before it, up to `overlap` characters of them: a run of whole units no longer than the
    overlap thus stands unsplit in at least one segment. A text that fits `size` is its only segment, unchanged."""
    if overlap * 2 > size:
        raise ValueError("the overlap of segments may be half of their size at most")
    if len(text) <= size:
        return [text]
    pieces, found, start = units(text, size), [], 0
    while True:
        end, length = start, 0
        while end < len(pieces) and length + len(pieces[end]) <= size:
            length += len(pieces[end])
            end += 1
        found.append("".join(pieces[start:end]))
        if end == len(pieces):
            return found
        back, carried = end, 0
        while back - 1 > start and carried + len(pieces[back - 1]) <= overlap:
            back -= 1
            carried += len(pieces[back])
        start = back


def ends(row, cap):
    """`row` when it holds at most `cap` items, else its first and its last ones, the tail keeping the odd one: where the ask of a message stands."""
    if len(row) <= cap:
        return list(row)
    head = cap // 2
    return [*row[:head], *row[len(row) - (cap - head):]]
