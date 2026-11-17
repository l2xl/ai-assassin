# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The AI's log tool over the record of every item's chat, the filed conversations included: the turns of the chats a UID or glob names
one line each, the parts of a turn -- its user messages, its steps, its reply -- one line each or one in full, and the search of the parts
holding every word asked within a time range, with the text the user folded out and the results a security finding dropped taken out of
everything it returns or finds -- nothing of it changes a chat."""

import fnmatch
import json
import re
import time
from datetime import datetime, timedelta

from . import filelib

LINE_LIMIT = 120  # characters of the line one step is told in
LIST_LIMIT = 400  # turns or steps one listing returns
READ_LIMIT = 20000  # characters one reading of a part returns
SEARCH_LIMIT = 60  # matches one search returns
SNIPPET = 60  # characters a match line tells on each side of the first word found
FOLDED = "[folded out by the user]"
DROPPED = "[dropped for a security finding]"
# What a step whose result a security finding dropped keeps -- what it was and the AI's own call -- and nothing it was answered with.
KEPT = ("kind", "name", "tool", "tools", "uid", "input", "inputs")
HIDDEN = ("at",)  # fields of a step the full text leaves out: where the page places it
PARTS = ("user", "reply")  # the parts of a turn named in place of a step number
TIME_FORMAT = "%Y-%m-%d %H:%M"
SPAN_RE = re.compile(r"(\d+)\s*([dhm])")
SPAN_SECONDS = {"d": 86400, "h": 3600, "m": 60}
WORD_RE = re.compile(r'"([^"]+)"|(\S+)')


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


def plural(count, noun, many=None):
    return f"{count} {noun if count == 1 else many or noun + 's'}"


def first_line(text):
    """The first line of `text` that holds anything, cut at `LINE_LIMIT` characters."""
    line = next((line.strip() for line in str(text or "").splitlines() if line.strip()), "")
    return line if len(line) <= LINE_LIMIT else line[:LINE_LIMIT - 1] + "…"


def step_head(step):
    """What a step is, as the head of its line: its kind and the name of its tool, agent or calls."""
    kind = step.get("kind") or "step"
    if kind == "tool":
        return f"tool {step.get('name')}"
    if kind == "agent":
        return "agent" + (f" @{step['uid']}" if step.get("uid") else f" {step['name']}" if step.get("name") else "")
    if kind == "calls":
        return f"calls {', '.join(step.get('tools') or ())}".strip()
    return kind


def step_line(step):
    """One step as one line: its kind and what names it -- the call of a tool, the first line of a text, the files of a diff."""
    kind = step.get("kind") or "step"
    if kind in ("tool", "workflow"):
        tail = compact(step.get("input") or {})
    elif kind == "agent":
        tail = step.get("prompt")
    elif kind == "calls":
        tail = f"{len(step.get('lines') or ())} lines"
    elif kind == "diff":
        tail = ", ".join(f"{file.get('status')} {file.get('path')}" for file in step.get("files") or ())
    elif kind == "usage":
        tail = ", ".join(f"{step[key]}{unit}" for key, unit in (("seconds", " s"), ("cost_usd", " $"), ("input_tokens", " in"), ("output_tokens", " out"))
                         if step.get(key) is not None)
    else:
        tail = step.get("text")
    told = first_line(tail)
    line = f"{step_head(step)}: {told}" if told else step_head(step)
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


def when(seconds):
    """The local date and time of epoch `seconds` as the tool tells it, "" for a turn recorded without one."""
    return datetime.fromtimestamp(seconds).strftime(TIME_FORMAT) if isinstance(seconds, (int, float)) else ""


def moment(value, name, end=False, now=None):
    """The epoch seconds a `since` or `until` field names -- an ISO date or date-time in local time, a bare date standing for its first
    moment or, with `end`, its last; or a span back from `now` such as `3d`, `12h`, `30m` -- None without the field; anything else raises `refused`."""
    if value is None:
        return None
    text = value.strip() if isinstance(value, str) else ""
    if span := SPAN_RE.fullmatch(text):
        return (time.time() if now is None else now) - int(span[1]) * SPAN_SECONDS[span[2]]
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise refused(f"{name} must be a date (2026-11-17), a date-time (2026-11-17 14:30) or a span back from now (3d, 12h, 30m)") from None
    if end and len(text) <= 10:
        parsed += timedelta(days=1, microseconds=-1)
    return parsed.timestamp()


def address(entry, part=None):
    return f"@{entry['uid']} turn {entry['turn']}" + (f" {part}" if part else "")


def chosen(chats, uid, own, every):
    """The UIDs of the chats a call's `uid` names -- an item's UID, `@` for the asking chat `own` or a glob of UIDs -- in order; without one,
    every chat for `every`, else the asking one."""
    if uid is None:
        return sorted(chats) if every else [own]
    named = uid.strip().removeprefix("@") if isinstance(uid, str) else ""
    if not named and uid != "@":
        raise refused("uid must be an item's UID, @ for this chat or a glob of UIDs such as AREA-*")
    return [own] if not named else sorted(key for key in chats if fnmatch.fnmatchcase(key, named))


def within(entries, since, until):
    """The entries recorded within the bounds, newest first; a bound given leaves out a turn recorded without a time."""
    kept = [entry for entry in entries if (since is None and until is None) or isinstance(entry.get("time"), (int, float))
            and (since is None or entry["time"] >= since) and (until is None or entry["time"] <= until)]
    return sorted(kept, key=lambda entry: (isinstance(entry.get("time"), (int, float)), entry.get("time") or 0, entry["turn"]), reverse=True)


def head(entry, *more):
    return " · ".join(part for part in (address(entry), when(entry.get("time")), *more) if part)


def turns(entries):
    """The turns as their count over one line each: address, time, steps, the first lines of the user's message and of the reply."""
    lines = [head(entry, plural(len(entry["steps"]), "step"), *(f"{part}: {told}" for part, text in (("user", "\n".join(entry["user"])), ("reply", entry["reply"]))
                                                               if (told := first_line(text)))) for entry in entries[:LIST_LIMIT]]
    cut = f"\n… cut at {LIST_LIMIT} turns: narrow it with uid, since or until" if len(entries) > LIST_LIMIT else ""
    return plural(len(entries), "turn") + ("\n" if lines else "") + "\n".join(lines) + cut


def listing(entry):
    """One turn as its head over a line each for its user messages, its steps under their numbers and its reply, past `LIST_LIMIT` steps cut."""
    steps = entry["steps"]
    lines = [f"user\t{first_line(text)}" for text in entry["user"] if text.strip()]
    lines += [f"{index}\t{step_line(step)}" for index, step in enumerate(steps[:LIST_LIMIT], 1)]
    lines += [f"… cut at {LIST_LIMIT} steps: read a later one with step"] if len(steps) > LIST_LIMIT else []
    lines += [f"reply\t{first_line(entry['reply'])}"] if entry["reply"].strip() else []
    return "\n".join([head(entry, plural(len(steps), "step")), *lines])


def part_text(entry, step):
    """(name, text) of the part of a turn `step` names: a step by its number in full, `user` its user messages, `reply` its reply; a part
    the turn lacks raises `refused`."""
    if step in PARTS:
        text = "\n\n".join(text for text in entry["user"] if text.strip()) if step == "user" else entry["reply"]
        if not text.strip():
            raise refused(f"turn {entry['turn']} of @{entry['uid']} holds no {'user message' if step == 'user' else 'reply'}")
        return step, text
    index, steps = whole(step, "step", 1), entry["steps"]
    if not 1 <= index <= len(steps):
        raise refused(f"turn {entry['turn']} has {plural(len(steps), 'step')}: step {index} is outside it")
    return f"step {index} of {len(steps)}", "\n".join(render(steps[index - 1]))


def full(entry, step, offset):
    """The part `step` names of the turn in full from character `offset` on, a text past `READ_LIMIT` characters cut and telling the offset to
    go on from; an offset past the text raises `refused`."""
    name, text = part_text(entry, step)
    start = offset or 0
    if start and start >= len(text):
        raise refused(f"{address(entry, name.split(' of ')[0])} has {len(text)} characters: offset {start} is past its end")
    chunk = text[start:start + READ_LIMIT]
    end = start + len(chunk)
    more = f"\n… cut at {READ_LIMIT} characters: go on with offset {end}" if end < len(text) else ""
    return f"{address(entry, name)}, characters {start + 1}-{end} of {len(text)}\n{chunk}{more}"


def words_of(search):
    """The words of a search, lowercase: each run of non-space characters, a quoted phrase as one; none raises `refused`."""
    words = [(phrase or word).lower() for phrase, word in WORD_RE.findall(search if isinstance(search, str) else "")]
    if not words:
        raise refused("search must hold a word to find")
    return words


def snippet(text, words):
    """The text around the first place a word of the search is found in it, on one line, cut ends marked."""
    low = text.lower()
    at, size = min((low.find(word), len(word)) for word in words if word in low)
    start, end = max(0, at - SNIPPET), min(len(text), at + size + SNIPPET)
    return ("…" if start else "") + " ".join(text[start:end].split()) + ("…" if end < len(text) else "")


def search(entries, words):
    """The parts of the turns holding every word, newest turn first and in their order within it, one line each: address, time, what the
    part is and the text around the first word found, past `SEARCH_LIMIT` matches cut."""
    found = []
    for entry in entries:
        parts = [*(("user", "user", text) for text in entry["user"]),
                 *((f"step {index}", step_head(step), "\n".join(render(step))) for index, step in enumerate(entry["steps"], 1)),
                 ("reply", "reply", entry["reply"])]
        found += [(entry, " · ".join(bit for bit in (address(entry, name), when(entry.get("time")), "" if what == name else what, snippet(text, words)) if bit))
                  for name, what, text in parts if all(word in text.lower() for word in words)]
    cut = f"\n… cut at {SEARCH_LIMIT} matches: narrow the search with uid, since, until or one more word" if len(found) > SEARCH_LIMIT else ""
    count = f"{plural(len(found), 'match', 'matches')} in {plural(len({id(entry) for entry, _ in found}), 'turn')}"
    return count + ("\n" if found else "") + "\n".join(line for _, line in found[:SEARCH_LIMIT]) + cut


def scrubbed(entry, pattern):
    return {**entry, "user": scrub(list(entry["user"]), pattern), "steps": scrub(list(entry["steps"]), pattern), "reply": scrub(entry["reply"], pattern)}


def read(chats, folded, call, own, now=None):
    """The text a log call asks for out of the record of the `chats` -- UID -> its turns, each {uid, turn, time, user, steps, reply} -- the
    `folded` texts being the user's cuts and `own` the asking chat: with `search` the parts holding every word in the chats `uid` names, every
    one without it; with `turn` one turn of one chat, the asking one without `uid`, its parts listed or the one `step` names in full; else the
    turns of the chats `uid` names, the asking one without it -- each within `since` and `until`. A turn or part that is missing, a glob in
    place of the one chat a turn is read in and anything malformed raise `refused`."""
    since, until = moment(call.get("since"), "since", now=now), moment(call.get("until"), "until", end=True, now=now)
    number, pattern = whole(call.get("turn"), "turn", 1), fold_pattern(folded)
    named = chosen(chats, call.get("uid"), own, "search" in call)
    if "search" in call:
        words = words_of(call["search"])
        entries = [entry for uid in named for entry in chats.get(uid, ()) if number is None or entry["turn"] == number]
        return search([scrubbed(entry, pattern) for entry in within(entries, since, until)], words)
    if number is None:
        if call.get("step") is not None:
            raise refused("name the turn of the step with turn")
        return turns([scrubbed(entry, pattern) for entry in within([entry for uid in named for entry in chats.get(uid, ())], since, until)])
    if len(named) != 1:
        raise refused(f"a turn is read in one chat: name one item's UID in uid, the glob names {plural(len(named), 'chat')}")
    entry = next((entry for entry in chats.get(named[0], ()) if entry["turn"] == number), None)
    if entry is None:
        known = ", ".join(str(entry["turn"]) for entry in chats.get(named[0], ())) or "none"
        raise refused(f"no turn {number} of @{named[0]} is recorded; its turns: {known}")
    entry = scrubbed(entry, pattern)
    if call.get("step") is None:
        return listing(entry)
    return full(entry, call["step"], whole(call.get("offset"), "offset", 0))


def label(call):
    """The call as its result and its refusal name it: `log`, then the fields it gives in the order they narrow."""
    told = [f"{key} {json.dumps(call[key], ensure_ascii=False) if key == 'search' else call[key]}" for key in ("search", "since", "until") if call.get(key) is not None]
    where = [str(call["uid"])] if call.get("uid") is not None else []
    return " ".join(["log", *where, *(f"{key} {call[key]}" for key in ("turn", "step") if call.get(key) is not None), *told])
