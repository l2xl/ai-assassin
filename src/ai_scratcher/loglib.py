# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The AI's log tool: the steps of a turn of the chat as its record keeps them, one line each or one in full, with the text the user folded
out and the results a security finding dropped taken out of everything it returns -- nothing of it changes the chat."""

import json
import re

from . import filelib

LINE_LIMIT = 120  # characters of the line one step is told in
LIST_LIMIT = 400  # steps one listing returns
READ_LIMIT = 20000  # characters one reading of a step returns
FOLDED = "[folded out by the user]"
DROPPED = "[dropped for a security finding]"
# What a step whose result a security finding dropped keeps -- what it was and the AI's own call -- and nothing it was answered with.
KEPT = ("kind", "name", "tool", "tools", "uid", "input", "inputs")
HIDDEN = ("at",)  # fields of a step the full text leaves out: where the page places it


class refused(Exception):
    pass


def fold_pattern(folded):
    """The pattern matching any of the folded `texts` -- the longest first -- or None where nothing is folded."""
    texts = sorted({text for text in folded if text.strip()}, key=len, reverse=True)
    return re.compile("|".join(re.escape(text) for text in texts)) if texts else None


def scrub(value, pattern):
    """A copy of `value` -- a step or what it holds -- with every place of the folded text (`pattern`) a `FOLDED` mark, and every step
    carrying a `dropped` mark cut down to what `KEPT` names and the `DROPPED` mark."""
    if isinstance(value, str):
        return pattern.sub(FOLDED, value) if pattern else value
    if isinstance(value, list):
        return [scrub(each, pattern) for each in value]
    if isinstance(value, dict):
        if "kind" in value and value.get("dropped"):
            value = {**{key: value[key] for key in KEPT if key in value}, "dropped": DROPPED}
        return {key: scrub(each, pattern) for key, each in value.items()}
    return value


def compact(value):
    return json.dumps(value, ensure_ascii=False)


def first_line(text):
    """The first line of `text` that holds anything, cut at `LINE_LIMIT` characters."""
    line = next((line.strip() for line in str(text or "").splitlines() if line.strip()), "")
    return line if len(line) <= LINE_LIMIT else line[:LINE_LIMIT - 1] + "…"


def step_line(step):
    """One step as one line: its kind and what names it -- the call of a tool, the first line of a text, the files of a diff."""
    kind = step.get("kind") or "step"
    if kind == "tool":
        head, tail = f"tool {step.get('name')}", compact(step.get("input") or {})
    elif kind == "agent":
        head, tail = "agent" + (f" @{step['uid']}" if step.get("uid") else ""), step.get("prompt")
    elif kind == "workflow":
        head, tail = "workflow", compact(step.get("input") or {})
    elif kind == "calls":
        head, tail = f"calls {', '.join(step.get('tools') or ())}".strip(), f"{len(step.get('lines') or ())} lines"
    elif kind == "diff":
        head, tail = "diff", ", ".join(f"{file.get('status')} {file.get('path')}" for file in step.get("files") or ())
    elif kind == "usage":
        head, tail = "usage", ", ".join(f"{step[key]}{unit}" for key, unit in (("seconds", " s"), ("cost_usd", " $"), ("input_tokens", " in"), ("output_tokens", " out"))
                                       if step.get(key) is not None)
    else:
        head, tail = kind, step.get("text")
    told = first_line(tail)
    line = f"{head}: {told}" if told else head
    return f"{line} — {step['dropped']}" if step.get("dropped") else line


def render(step, pad=""):
    """The lines of a step in full: every field under its name, a text under it indented, the steps nested in it under their numbers."""
    lines = []
    for key, value in step.items():
        if value is None or key in HIDDEN:
            continue
        if key == "steps":
            lines.append(f"{pad}steps:")
            for number, nested in enumerate(value, 1):
                lines += [f"{pad}  {number}.", *render(nested, pad + "    ")]
        elif isinstance(value, str):
            lines += [f"{pad}{key}:", *(f"{pad}  {line}" for line in value.split("\n"))] if "\n" in value else [f"{pad}{key}: {value}"]
        elif isinstance(value, list) and value and all(isinstance(each, str) for each in value):
            lines.append(f"{pad}{key}:")
            for each in value:
                first, *rest = each.split("\n")
                lines += [f"{pad}  - {first}", *(f"{pad}    {line}" for line in rest)]
        else:
            lines.append(f"{pad}{key}: {compact(value)}")
    return lines


def whole(value, name, least):
    """The whole number an optional field of a call carries, None without it; anything else, or one under `least`, raises `refused`."""
    try:
        return filelib.whole(value, name, least, None)
    except filelib.refused as err:
        raise refused(str(err)) from None


def listing(steps, number, pattern):
    """The steps of turn `number` as their count over one line each under its number, a listing past `LIST_LIMIT` steps cut."""
    count = f"{len(steps)} step{'s' * (len(steps) != 1)}"
    lines = [f"{index}\t{step_line(step)}" for index, step in enumerate(scrub(steps[:LIST_LIMIT], pattern), 1)]
    cut = f"\n… cut at {LIST_LIMIT} steps: read a later one with step" if len(steps) > LIST_LIMIT else ""
    return f"turn {number}: {count}" + ("\n" if lines else "") + "\n".join(lines) + cut


def full(steps, number, index, offset, pattern):
    """Step `index` of turn `number` in full from character `offset` on, a text past `READ_LIMIT` characters cut and telling the offset to
    go on from; a step outside the turn or an offset past the text raises `refused`."""
    if not 1 <= index <= len(steps):
        raise refused(f"turn {number} has {len(steps)} steps: step {index} is outside it")
    text = "\n".join(render(scrub(steps[index - 1], pattern)))
    start = offset or 0
    if start and start >= len(text):
        raise refused(f"step {index} of turn {number} has {len(text)} characters: offset {start} is past its end")
    chunk = text[start:start + READ_LIMIT]
    end = start + len(chunk)
    more = f"\n… cut at {READ_LIMIT} characters: go on with offset {end}" if end < len(text) else ""
    return f"turn {number} step {index} of {len(steps)}, characters {start + 1}-{end} of {len(text)}\n{chunk}{more}"


def read(record, folded, call):
    """The text a log call asks for out of the `record` of a chat -- its steps by turn number, the `folded` texts of its messages being
    the user's cuts: the steps of the turn the call names one line each, or the step it names in full. A turn that is missing or has no
    steps recorded, a step outside it and anything that is no whole number raise `refused`, telling the turns of the record."""
    number = whole(call.get("turn"), "turn", 1)
    known = ", ".join(str(turn) for turn in sorted(record)) or "none"
    if number is None:
        raise refused(f"name the turn to read with turn; turns of this chat with steps: {known}")
    if number not in record:
        raise refused(f"no steps of turn {number} are recorded; turns of this chat with steps: {known}")
    index, offset = whole(call.get("step"), "step", 1), whole(call.get("offset"), "offset", 0)
    pattern = fold_pattern(folded)
    return listing(record[number], number, pattern) if index is None else full(record[number], number, index, offset, pattern)
