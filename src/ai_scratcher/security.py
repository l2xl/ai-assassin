# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The rules of the security scan, each without a model: what is external text and what alters, the mark of a session's unscanned text,
the invisible and bidirectional characters, the check of a scan answer, the findings the user accepted and how settling them ends a held
call -- the findings being {span, category, reason}, as a context review highlights them."""

import hashlib
import json
import re
import shlex
import unicodedata
from datetime import date
from pathlib import Path

from . import gitlib, segmenting

# The controls that turn the reading order of the text: the Arabic mark, the logical runs, the overrides and the isolates.
BIDIRECTIONAL_RE = re.compile("[\u061c\u200e\u200f\u202a-\u202e\u2066-\u206f]")
# The characters the reader sees not at all: the joiners and separators, the soft hyphen, the Hangul fillers, the BOM and the interlinear marks, the tag block.
INVISIBLE_RE = re.compile("[\u00ad\u034f\u3164\uffa0\u115f-\u1160\u17b4-\u17b5\u180e\u200b-\u200d\u2060-\u2064\ufeff\ufff9-\ufffb\U000e0001-\U000e007f]")
# A run of one kind of hidden characters, the bidirectional kind tried first so that a run never mixes the two.
HIDDEN_RE = re.compile(f"(?:{BIDIRECTIONAL_RE.pattern}+|{INVISIBLE_RE.pattern}+)")


def hidden_findings(text):
    """The findings of the text's hidden characters: one {span, category, reason} per run of one kind of them in the order they stand in the
    text, the span the run as it stands there, the category `bidirectional` or `invisible` and the reason the Unicode names of the run's characters."""
    return [{"span": match.group(), "category": "bidirectional" if BIDIRECTIONAL_RE.search(match.group()) else "invisible",
             "reason": ", ".join(unicodedata.name(char, f"U+{ord(char):04X}") for char in match.group())}
            for match in HIDDEN_RE.finditer(text)]


SCAN_WINDOW = 120_000  # the characters of external text the scan agent judges in one call: a larger text goes in windows
SCAN_OVERLAP = SCAN_WINDOW // 4  # what a window takes over of the one before, in whole units
MALFORMED = "malformed"
FINDING_FIELDS = ("span", "category", "reason")


def malformed_finding(reason):
    """The finding a malformed scan answer counts as: no span to highlight, the category `malformed` and the `reason`."""
    return {"span": "", "category": MALFORMED, "reason": reason}


def check_scan_answer(text, answer):
    """The findings a scan agent's `answer` stands for over the scanned `text`: its own findings that are well formed and whose span stands in
    the text, as they are; every other part -- an answer that is no {findings: [...]} object, an entry that is no {span, category, reason}
    of strings, a span that is empty or absent from the text -- a `malformed` finding of its own, so a bad answer never reads as nothing found."""
    if not isinstance(answer, dict) or set(answer) != {"findings"} or not isinstance(answer["findings"], list):
        return [malformed_finding("the scan answer is not an object of the schema: {findings: [{span, category, reason}]}")]
    checked = []
    for number, entry in enumerate(answer["findings"], 1):
        if not isinstance(entry, dict) or set(entry) != set(FINDING_FIELDS) or not all(isinstance(entry[field], str) for field in FINDING_FIELDS):
            checked.append(malformed_finding(f"finding {number} of the scan answer is not {{span, category, reason}} of strings"))
        elif not entry["span"] or entry["span"] not in text:
            checked.append(malformed_finding(f"finding {number} names a span absent from the text: {entry['span']!r} ({entry['category']}: {entry['reason']})"))
        else:
            checked.append(dict(entry))
    return checked


NOTHING_FOUND = "nothing found"
ALERT = "⚠ {count} concern{plural} in the context"
# The tools whose result is external text: a connector's own web fetch and search, and the WebSurf call of any action.
EXTERNAL_TOOLS = ("WebFetch", "WebSearch", "websurf")
TREE_EDITS = ("add", "edit", "remove", "move", "rename")
PATCH_CALLS = ("patch", "replace")
# The WebSurf actions that act in the user's browser as the user, `websurf.INTERACTIVE`.
SURF_ALTERING = ("fill", "mouse")
ACCEPTED_FILE = Path(".ai-assassin") / "accepted_findings.json"
SETTLED = ("accept", "drop")
DROP_REFUSAL = "refused: the user dropped from the session the external text it may rest on, after the security scan found {spans}"


def scan_line(findings):
    """The line a scan leaves: `nothing found` without findings -- never `safe`, the scan being a tripwire -- else the alert counting them."""
    return ALERT.format(count=len(findings), plural="" if len(findings) == 1 else "s") if findings else NOTHING_FOUND


def is_external(tool, marked=False):
    """Whether the result of a call of `tool` is external text: a web fetch or search, a WebSurf call of any action, and the report of a
    subagent -- `agent` -- whose session was `marked` by such text; every other result, the project's and the user's, is trusted."""
    return tool in EXTERNAL_TOOLS or (tool == "agent" and bool(marked))


def is_altering(call):
    """Whether the harness call changes the tree, a project file, the history -- a recording git command -- or a page in the user's browser,
    or runs the shell; a git command that does not split is taken for altering."""
    tool = call.get("tool")
    if tool == "git":
        try:
            words = shlex.split(str(call.get("command") or ""))
        except ValueError:
            return True
        return bool(words) and words[0] in gitlib.RECORDS
    if tool == "websurf":
        return call.get("action") in SURF_ALTERING
    return tool in TREE_EDITS or tool in PATCH_CALLS or tool == "shell"


class scan_mark:
    """The scan mark of one session: the external results it took and has not had scanned, marked while there is any; kept as JSON with
    the chat log."""

    def __init__(self, pending=()):
        self.pending = [str(text) for text in pending]

    @property
    def marked(self):
        return bool(self.pending)

    def take(self, text):
        """Mark the session with one more external result."""
        self.pending.append(str(text))

    def scanned(self):
        """Clear the mark once what came in has been scanned."""
        self.pending = []

    def child(self):
        """The mark a subagent started from this session starts with: this session's unscanned text, so the child of a marked session starts marked."""
        return scan_mark(self.pending)

    def to_json(self):
        return {"pending": list(self.pending)}

    @classmethod
    def from_json(cls, data):
        return cls(data.get("pending") or () if isinstance(data, dict) else ())


def gate(mark, call=None, recommendation=None):
    """The texts to scan before `call` is applied or `recommendation` applied or asked: what came in since the last scan when the call alters
    or a recommendation stands, else none -- a session without a new external result scanning nothing, whatever it calls."""
    return list(mark.pending) if recommendation is not None or (call is not None and is_altering(call)) else []


def text_key(text):
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def windowed(text, judge):
    """The checked findings of `judge` over `text`: one call for a text that fits `SCAN_WINDOW`, else one for each of its overlapping windows,
    the findings of all joined once each, a span checked against the window it was found in."""
    found = []
    for window in segmenting.segments(text, SCAN_WINDOW, SCAN_OVERLAP):
        found += [finding for finding in check_scan_answer(window, judge(window)) if finding not in found]
    return found


def scan(texts, judge=None, accepted=(), verdicts=None):
    """The unsettled findings over `texts`, each with the `index` of its text: the hidden characters of the text and, with a `judge` -- the scan
    agent as text -> its answer -- the checked findings of its answer, a judge that fails standing for a malformed one; a finding whose exact
    wording is `accepted` left out. The verdicts are kept in `verdicts` by the hash of the text, so no text is judged twice; no texts call no
    judge."""
    verdicts = {} if verdicts is None else verdicts
    found = []
    for index, text in enumerate(texts):
        key = text_key(text)
        if key not in verdicts:
            judged = []
            if judge is not None:
                try:
                    judged = windowed(text, judge)
                except Exception as err:
                    judged = [malformed_finding(f"the scan agent gave no answer: {err}")]
            verdicts[key] = hidden_findings(text) + judged
        found += [{**finding, "index": index} for finding in verdicts[key] if not is_accepted(accepted, finding)]
    return found


def review(texts, findings):
    """The context review of a held call: every scanned text holding a finding, in order, with its findings as {number, span, category, reason},
    `number` the finding's place among `findings` -- the order the user's answers follow."""
    return [{"text": text, "findings": [{"number": number, **{field: finding[field] for field in FINDING_FIELDS}}
                                       for number, finding in enumerate(findings) if finding["index"] == index]}
            for index, text in enumerate(texts) if any(finding["index"] == index for finding in findings)]


def accepted_path(home=None):
    """Where the user's accepted findings are kept: `.ai-assassin/accepted_findings.json` of the user's home."""
    return Path(home or Path.home()) / ACCEPTED_FILE


def load_accepted(home=None):
    """The user's accepted findings, {span, category, day} each; none when the file is missing or unreadable."""
    try:
        data = json.loads(accepted_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [entry for entry in data if isinstance(entry, dict) and isinstance(entry.get("span"), str) and entry["span"]] if isinstance(data, list) else []


def is_accepted(accepted, finding):
    """Whether the finding's exact wording was accepted; a finding without a span -- a malformed answer -- never is."""
    span = finding.get("span")
    return bool(span) and any(entry.get("span") == span for entry in accepted)


def accept(finding, home=None, day=None):
    """Save the finding's exact wording for the user, with its category and the day it was accepted, once. -> the accepted findings."""
    accepted = load_accepted(home)
    if finding.get("span") and not is_accepted(accepted, finding):
        accepted.append({"span": finding["span"], "category": str(finding.get("category") or ""), "day": day or date.today().isoformat()})
        path = accepted_path(home)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(accepted, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return accepted


def settle(findings, answers):
    """(verdict, refusal) of a held call once the user answered its `findings` -- `answers` giving `accept` or `drop` for each in order:
    (None, None) while one is unsettled, (`apply`, None) when every one was accepted, else (`refuse`, the line the model reads, naming the
    dropped spans)."""
    answers = list(answers)
    if len(answers) < len(findings) or any(answer not in SETTLED for answer in answers[:len(findings)]):
        return None, None
    dropped = [finding for finding, answer in zip(findings, answers) if answer == "drop"]
    if not dropped:
        return "apply", None
    return "refuse", DROP_REFUSAL.format(spans="; ".join(f"{finding.get('category')} {finding.get('span')!r}" for finding in dropped))
