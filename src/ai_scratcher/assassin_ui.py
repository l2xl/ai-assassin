# Open Trader
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""AI Assassin: the loopback web UI joining the syngate DAG of a project and the Synthetic AI harness.

`assassin` (or `python -m ai_scratcher.assassin_ui`) serves a single-page editor for the
tree under `syngate/`: the DAG with live status rollup, per-field item edits
(autosave) and drag-and-drop placement through the canonical writer, the AI chat
anchored at every item, and test / review / clear runs driven through `syngate.py`
subprocesses with output streamed to the browser over SSE. Stamping stays in the
syngate CLI code path, so the browser button and the terminal command are the same
user action. A change of the engine's own Python sources re-executes the server in
place once no turn or run is live, keeping its port, token and chats; a changed page
reloads itself in the browser.

The server binds 127.0.0.1 only. Every request must carry the per-session
token from the URL printed at startup (`X-Assassin-Token` header or `?token=`),
and the Host header must be a loopback name -- the jupyter-style defense
against CSRF and DNS rebinding for localhost tools that run subprocesses.
"""

import argparse
import collections
import copy
import functools
import hashlib
import hmac
import http.client
import http.server
import itertools
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import api_connection
from . import cc_transcript
from . import assassin_setup
from . import filelib
from . import loglib
from . import gitlib
from . import greplib
from . import matching
from . import patchlib
from . import pruning
from . import recommend
from . import security
from . import services
from . import syngatelib
from . import synthetic
from . import tiering
from . import tiling
from . import websurf

DEFAULT_PORT = 8712
# A project's own port lies among the PORT_SPAN ports above DEFAULT_PORT, chosen by a hash of its root.
PORT_SPAN = 200
DEFAULT_BUILD_DIR = "cmake-build-debug-clang"
# UIDs and the glob patterns syngate.py accepts for batch review/clear, a `UID:binding` narrowing a test run to one binding.
RUN_UID_RE = re.compile(r"^[A-Za-z0-9_\-?*\[\]!:]+$")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
# Coverage files picked up automatically when none are given explicitly.
DEFAULT_COVERAGE = ("pytest-coverage.jsonl", "syngate_coverage.jsonl", "build-ci/syngate_coverage.jsonl")
# Test / review runs started from the page fold their records in here, so a run recolors the statuses.
RUN_COVERAGE = "syngate_coverage.jsonl"
TURN_ROUTE = r"/api/turn/([A-Za-z0-9_\-]+:\d+)"
# Project files opened from a link: git-tracked files are readable, only markdown is written.
FILE_LIMIT = 1 << 20
# The project files the mention hint offers: at most this many, the walk without git skipping hidden folders and these.
FILES_LIMIT = 5000
WALK_SKIPPED = {"node_modules", "__pycache__", "venv", "env", "dist", "build", "target", "site-packages"}
# The chats of the items, kept next to the tree across server runs; a settled change is written this many seconds after the first.
CHATS_FILE = "assassin_chats.json"
LEGACY_CHATS_FILE = "syngate_chats.json"
# The record of the server serving the root -- its pid, port and token -- found by a second `assassin` on the same root, which opens
# that server instead of starting one; a probe of it that gets no answer within this many seconds finds it dead.
SERVER_FILE = "assassin_server.json"
PROBE_TIMEOUT = 2.0
WRITE_DELAY = 0.5
# The harness's own permission, first among every connector's modes: whether a reply's add, edit, move, rename and remove calls
# are applied; its reads -- query, context, skill -- always are.
TREE_MODE = {"id": "tree", "label": "Tree edit", "hint": "add, edit, move and remove items; reading the tree stays on", "default": True, "advanced": False}
TREE_OFF = "The tree is read-only for this chat: add, edit, move, rename and remove are refused — answer in text and say what you would change."
TREE_REFUSAL = "tree edits are off for this chat — switch Tree edit on"
# The harness's Edit files permission, listed after the tree mode: whether a reply's `patch` call -- a unified diff of project files -- is
# applied; the tree files are never in reach of it. Neither it nor the tree mode ever reaches a connector.
PATCH_MODE = {"id": "patch", "label": "Edit files", "hint": "apply the diffs of the reply to project files; syngate items are not in reach",
              "default": True, "advanced": False}
PATCH_REFUSAL = "project file edits are off for this chat — switch Edit files on"
# A reply's `shell` call runs with `sh -c` in the project root only while the chat's Raw command mode (`bash`) is on, without stdin, within
# SHELL_TIMEOUT seconds, its output cut past SHELL_LIMIT characters; a command naming the tree is refused in every mode.
SHELL_MODE = "bash"
# The permission each tool an off-context agent lists needs on in the chat that starts it; a tool absent here needs none.
AGENT_TOOL_MODES = {"syngate_api": "tree", "patch": "patch", "shell": SHELL_MODE, "websurf": "websurf"}
SHELL_REFUSAL = "raw commands are off for this chat — switch Raw command on"
SHELL_TREE = "a command naming syngate is refused: the items are read and changed only through the tree calls"
SHELL_TREE_RE = re.compile(r"(?<![\w.-])syngate(?![\w.-])")
SHELL_TIMEOUT = 300
SHELL_LIMIT = 20000
GIT_ABSENT = "git is not at hand for this project"
# A grep call while the offered library holds no grep prompt: none of its programs is at hand.
GREP_ABSENT = ("no grep tool is offered: neither ripgrep nor GNU grep is found and git is not at hand for this project — "
               "list and read the files with the files tool")
# The git commands outside the git tool's reads and records that erase nothing: their refusal points to the shell, which runs them while
# the chat's Raw command permission is on.
GIT_SHELL_COMMANDS = ("submodule", "remote", "fetch", "ls-remote", "clone")
GIT_SHELL_HINT = "run it with the shell tool, `git …` as its command, which the chat's Raw command permission allows"
# The longest prompt an agent call may carry: the delegated item's statement and seed context are the briefing, a prompt adds only what
# the tree lacks; a longer one restates the task and is refused.
DELEGATION_PROMPT_LIMIT = 300
DELEGATION_RESTATED = (f"the prompt restates the task — the item's statement and seed context are its briefing: put what the statement "
                       f"lacks into it with `edit`, then delegate with no prompt or one of at most {DELEGATION_PROMPT_LIMIT} characters")
# The server settings, kept next to the tree, one section per feature: `websurf` holds the WebSurf host lists `allow` and `block`,
# `connections` the setup of the OpenAI-compatible API connections.
SETTINGS_FILE = "assassin_settings.json"
# The section whose absence has the server run the first setup by itself, and how the chats show its step.
SETUP_SECTION = "orchestrator"
SETUP_PROGRESS = "setting up the model services…"
# The project files the files tool never lists or reads: the server settings hold keys, the stored chats what a chat was told to forget.
UNREADABLE = (SETTINGS_FILE, CHATS_FILE, LEGACY_CHATS_FILE)
# The harness's Interactive WebSurf permission, listed after every connector's modes while a browser is attached: whether a reply's
# websurf `fill` and `mouse` act on the surf tab; the passive actions are always on. Neither it nor the tree mode ever reaches a connector.
SURF_MODE = {"id": "websurf", "label": "Interactive WebSurf", "hint": "type and click in the surf tab of your browser — WebSurf fill and mouse; opening, "
             "reading and looking at pages stay on", "default": False, "advanced": False}
HARNESS_MODES = ("tree", "patch", "websurf")
# The `chat` section of the server settings: the setup -- connector, model, effort and the main permission switches -- of every new chat,
# kept as the last choice made in a new chat. A chat with messages keeps its own setup, in the chats file; advanced permissions are never kept here.
CHAT_SECTION = "chat"
# The note a chat is headed by when a stored permission list failed its check and was reset to the defaults; it is shown to the user and goes to the AI.
MODES_RESET = "The permission switches of this chat were invalid ({why}) and have been reset to the defaults: {modes}."
# What the user reads when a turn ends on an error that is the harness's own bug, not a refusal or a failure of the connection.
INTERRUPTED = "The chat was interrupted by an unexpected error in the harness — this is a bug, not something to retry blindly: {error}"
SURF_OFF = ("Interactive WebSurf is off for this chat: fill and mouse are refused, open, close, status, query, screenshot and wait stay on — "
            "switch Interactive WebSurf on to act")
# The request of the review commit's message, sent to the reviewed item's chat when no single commit names the review.
# The message heading a turn whose anchored item's statement changed since the conversation's previous turn, or sent from the editor.
STATEMENT_NOTE = "The statement of @{uid} now reads:\n\n{statement}"
# How the messages the user queued while a turn ran reach the model at the turn's next round, after the results it asked for.
# The context step of a turn whose message brings a change of the pruning into a session the harness writes, in place.
REWRITTEN = "pruning brought in from turn {turn}: the messages of the session since are rewritten under the pruning now settled"
# The context steps of a turn whose message brings a change of its Claude Code session's pruning in: replayed into a new transcript, or rolled back.
REPLAYED = "pruning replayed from turn {turn}: the session goes on in a new transcript, the turns since rebuilt under the pruning now settled"
FORKED = "pruning rolled back to before turn {turn}: the session is resumed forked there and the turns since go with this message as replayed history"
QUEUED_NOTE = "\n\nThe user wrote while you were working:\n\n{text}"
# The engine's own files: the page, read for every request, and the Python sources, watched so a change re-executes the server in place
# once nothing runs; the restarted process takes the session token and the listening socket over from these variables.
PAGE_FILE = Path(__file__).resolve().parent / "assassin_ui.html"
# The markdown renderer, inlined into the page in its slot as the page is served, and the diagram frame it draws in: a page of its own served
# at MARKDOWN_FRAME_PATH without the token, loading the drawing library -- MERMAID_URL unless `markdown.mermaid` of the server settings names a copy.
MARKDOWN_FILE = Path(__file__).resolve().parent / "markdown.js"
MARKDOWN_SLOT = b'<script src="markdown.js"></script>'
MARKDOWN_FRAME_FILE = Path(__file__).resolve().parent / "markdown_frame.html"
MARKDOWN_FRAME_PATH = "/markdown-frame"
MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.esm.min.mjs"
ENGINE_DIR = Path(__file__).resolve().parent
ENGINE_POLL = 1.0
TOKEN_ENV = "ASSASSIN_TOKEN"
LISTEN_ENV = "ASSASSIN_LISTEN_FD"
RESTARTING = "the engine is restarting — send again in a moment"
# Seconds a restart gives the held turns it stops to end, so they are written out as stopped.
HELD_GRACE = 5.0
# Run in a fresh interpreter before a restart: every engine source compiles and the server imports.
PREFLIGHT = "import sys\nfor path in sys.argv[1:]:\n    compile(open(path, encoding='utf-8').read(), path, 'exec')\nimport ai_scratcher.assassin_ui\n"
REVIEW_MESSAGE = ("Formulate the commit message of the review that stamped {stamped}: answer in text with one line `Review: …` condensing what "
                  "these commits since the last review commit changed, newest first:\n{subjects}")


class ApiError(Exception):
    def __init__(self, status, message, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


def git_label(call):
    """How a git call reads in the log: `git <command>`, or `git -C <path> <command>` where it names a folder to run in."""
    return f"git -C {call['path']} {call['command']}" if call.get("path") is not None else f"git {call['command']}"


def _number(value, name, cast=float):
    try:
        return cast(value)
    except (TypeError, ValueError):
        raise ApiError(400, f"'{name}' must be a number") from None


def _call(run):
    """Run a core tree call, mapping its refusal onto the HTTP answer: an
    unknown item is 404, a lost compare-and-swap 409, anything else a 400."""
    try:
        return run()
    except syngatelib.stale_edit as err:
        raise ApiError(409, str(err), current=err.current) from None
    except syngatelib.unknown_uid as err:
        raise ApiError(404, str(err)) from None
    except syngatelib.tree_error as err:
        raise ApiError(400, str(err)) from None


class Job:
    """One run of the runner; `then`, given the job once its process exited, yields the lines of what closes the run -- a review
    commit -- and the run stays live until it is done, the chat `turn` it awaits meanwhile stopped with the run."""

    def __init__(self, job_id, argv, then=None):
        self.id = job_id
        self.argv = argv
        self.then = then
        self.turn = None
        self.lines = []
        self.returncode = None
        self.proc = None
        self.cond = threading.Condition()

    def say(self, line):
        with self.cond:
            self.lines.append(line)
            self.cond.notify_all()

    def snapshot(self):
        with self.cond:
            return {"id": self.id, "argv": list(self.argv), "running": self.returncode is None,
                    "returncode": self.returncode, "lines": list(self.lines)}

    def stream(self):
        """Yield output lines as they arrive; return the exit code when done."""
        index = 0
        while True:
            with self.cond:
                while index >= len(self.lines) and self.returncode is None:
                    self.cond.wait(0.2)
                fresh = self.lines[index:]
                index += len(fresh)
                done = self.returncode if index >= len(self.lines) else None
            yield from fresh
            if done is not None:
                return done


def shifted(step, shift):
    """A copy of the step, its `at` and those of the steps nested in it moved by `shift` seconds."""
    moved = copy.deepcopy(step)
    pending = [moved]
    while pending:
        each = pending.pop()
        each["at"] = round(each.get("at", 0) + shift, 2)
        pending += each.get("steps") or []
    return moved


def agent_steps(steps, skip=()):
    """Every agent step among `steps`, the ones nested in agent steps included, but those of the items in `skip` and under them."""
    for step in steps:
        if step.get("kind") == "agent" and step.get("uid") not in skip:
            yield step
            yield from agent_steps(step.get("steps") or (), skip)


def tallied(lines):
    """The applied lines of a turn with every repeated one said once, at its first place, its count closing it: `(×3)`."""
    counts = collections.Counter(lines)
    return [f"{line} (×{counts[line]})" if counts[line] > 1 else line for line in dict.fromkeys(lines)]


def told(outcome):
    """A turn's outcome as a model reads it where it never saw the turn's log -- the history of a new session, an off-context agent's report:
    the lines of what the turn applied, then its reply or error. The chat shows the reply alone, the applied calls being blocks of the log."""
    return "\n".join([*outcome.get("applied", ()), outcome.get("reply", outcome.get("error")) or ""]).strip("\n")


class Change:
    """The cumulative change of a turn: every item and project file it changed, each named once, as it stands when the change is read."""

    def __init__(self, root):
        self.root, self.items, self.files = Path(root), {}, {}  # uid -> (state, its UID before the turn); path -> whether it was there before

    def item(self, call, uid):
        """Note the applied tree call of the item `uid`: an item added and removed in the turn leaves nothing, a renamed one goes by its new UID."""
        tool = call["tool"]
        if tool == "add":
            self.items[uid] = ("changed", uid) if uid in self.items else ("added", uid)
        elif tool == "rename":
            self.items[call["new_uid"]] = self.items.pop(uid, ("changed", uid))
        elif tool == "remove":
            state, was = self.items.pop(uid, ("changed", uid))
            if state != "added":
                self.items[was] = ("removed", was)
        else:
            self.items.setdefault(uid, ("changed", uid))

    def paths(self, call):
        """The project files a patch or replace call names, each with whether it is there now -- read before the call is applied."""
        removed = re.findall(r"^--- a/(\S+)", str(call.get("diff") or ""), re.M) if call.get("tool") == "patch" else []
        return {path: (self.root / path).is_file() for path in dict.fromkeys([*tiering.patched_paths(call), *(os.path.normpath(path) for path in removed)])}

    def note(self, touched):
        """Note the files of an applied patch, `touched` being what `paths` read before it."""
        for path, there in touched.items():
            self.files.setdefault(path, there)

    def merge(self, view):
        """Take in the change of a turn this one delegated and awaited, as its `view`."""
        for uid, state, was in (view or {}).get("items", ()):
            if state == "removed":
                self.item({"tool": "remove"}, uid)
            elif was != uid:
                self.items[uid] = self.items.pop(was, (state, was))
            else:
                self.items.setdefault(uid, (state, was))
        for path, state in (view or {}).get("files", ()):
            self.files.setdefault(path, state != "added")

    def view(self):
        """{items: [[uid, added|changed|removed, its UID before the turn]], files: [[path, added|changed|removed]]}, an empty part left out."""
        files = [[path, "changed" if was and there else "added" if there else "removed"] for path, was in self.files.items()
                 if (there := (self.root / path).is_file()) or was]
        items = [[uid, state, was] for uid, (state, was) in self.items.items()]
        return {**({"items": items} if items else {}), **({"files": files} if files else {})}


def changed_lines(view):
    """The cumulative change of a turn as the lines a delegating turn reads: its items in one, its project files in another."""
    items = ", ".join(f"{uid} {state}" + (f" (was {was})" if was != uid and state != "added" else "") for uid, state, was in (view or {}).get("items", ()))
    files = ", ".join(f"{path} {state}" for path, state in (view or {}).get("files", ()))
    return [*([f"Changed items: {items}"] if items else []), *([f"Changed files: {files}"] if files else [])]


def delegation_report(outcome):
    """All a starting session receives of a DAG-bound subagent: its closing text -- or error -- and its cumulative change, none of its calls,
    results or intermediate texts."""
    return "\n".join([outcome.get("reply", outcome.get("error")) or "", *changed_lines(outcome.get("changed"))]).strip("\n")


class Turn:
    """One chat exchange run on its own thread: the page awaits its outcome by polling, re-attaching after a reload, and may stop it.
    Its steps are recorded as they happen, every change announced through `changed`; `parent` is the turn that delegated it."""

    def __init__(self, turn_id, connector, changed=lambda: None, parent=None):
        self.id = turn_id
        self.connector = connector
        self.changed = changed
        self.parent = parent
        self.thread = None
        self.outcome = None
        self.stopped = False
        self.started = time.monotonic()
        self.steps, self.origins = [], []
        self.children, self.job, self.procs = [], None, []  # the turns it delegated, the test run it awaits, the shell processes it runs
        self.rounds, self.pruning = 0, None  # the rounds the turn sent to its connection, the thread of its prune agent
        self.held, self.offer, self.answer = None, None, None  # what the turn asks while it is held, the recommendation it offers, the user's answer
        self.batch = None  # the calls step of the batch in flight, which a recommendation asked meanwhile holds
        self.cond = threading.Condition()

    def elapsed(self):
        return round(time.monotonic() - self.started, 2)

    def add_step(self, step, shift=0.0):
        """Record a copy of the step, `shift` seconds later; a step announced again, as the same object, replaces its record."""
        stored = shifted(step, shift)
        with self.cond:
            index = next((index for index, origin in enumerate(self.origins) if origin is step), None)
            if index is None:
                self.origins.append(step)
                self.steps.append(stored)
            else:
                self.steps[index] = stored
        self.changed()

    def finish(self, outcome):
        with self.cond:
            self.outcome = outcome
            self.cond.notify_all()

    def snapshot(self, wait=0):
        with self.cond:
            self.cond.wait_for(lambda: self.outcome is not None, timeout=wait)
            return {"turn": self.id, "running": self.outcome is None, **({"steps": list(self.steps)} if self.steps else {}), **(self.outcome or {})}


SETUP_KEYS = ("connector", "model", "effort", "modes", recommend.BEHAVIOUR_KEY)
# The state of a chat is exactly one of these, the first that holds. The server tells every one but `unread` -- a reply this tab has not shown --
# which is the tab's own and takes the place of `waiting` alone.
CHAT_STATES = ("blocked", "working", "agents", "failed", "stopped", "unread", "waiting")


def cut_ranges(text, cuts):
    """The cuts of a message -- `[from, to]` spans of its text folded out of the exchange -- sorted, merged where they touch and clipped to
    the text; anything malformed is left out."""
    spans = sorted((max(0, cut[0]), min(len(text), cut[1])) for cut in (cuts if isinstance(cuts, list) else ())
                   if isinstance(cut, (list, tuple)) and len(cut) == 2 and all(type(edge) is int for edge in cut))
    merged = []
    for start, end in spans:
        if start >= end:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def kept_text(text, cuts):
    """The text with its cuts taken out."""
    at, parts = 0, []
    for start, end in cut_ranges(text, cuts):
        parts.append(text[at:start])
        at = end
    return "".join(parts) + text[at:]


class Chat:
    """The one chat of an item, shared by every page showing the item: its live conversation -- exchange log, setup, connector session
    and the turn in flight -- and the conversations filed behind it, each with its log, session and setup, in start order.
    Turns are numbered per item and addressed as `<UID>:<n>`."""

    def __init__(self, uid):
        self.uid = uid
        self.turns = 0
        self.archive = []
        self.background = []
        self.asked = None  # what the user is asked while a held turn or a blocking alert of the model services stands over the chat; set by whoever holds it
        self.erase()

    def erase(self):
        self.log = []
        self.reports = []
        self.session = None
        self.session_connector = None  # the connector whose session `session` is: a session is meaningful to the connector that opened it alone
        self.setup = {}
        self.turn = None
        self.started = None
        self.statement = None
        self.queue = []
        self.denied = []  # the keys of the recommendations denied in the live conversation, never shown again in it
        self.scan = security.scan_mark()  # the external text the conversation took and has not had scanned; ends with the conversation
        self.prune = pruning.new_state()  # the prune verdicts and the switches set by hand of the live conversation; ends with it
        self.keep = {}  # what the session keeps of its start: the composed system prompt, the statements and the files measured; ends with the session

    def conversation(self):
        """The live conversation as it is kept with the chat log: its log, session and setup and, where they hold anything, its kept session start,
        scan mark, denied recommendations and pruning state."""
        return {"started": self.started, "log": [dict(m) for m in self.log], "session": self.session, "setup": dict(self.setup), "statement": self.statement,
                **({"session_connector": self.session_connector, **({"keep": self.keep} if self.keep else {})} if self.session else {}),
                **({"scan": self.scan.to_json()} if self.scan.marked else {}), **({"denied": list(self.denied)} if self.denied else {}),
                **({"prune": copy.deepcopy(self.prune)} if {**self.prune, "sent": 0} != pruning.new_state() else {})}  # a turn sent alone is no state: turns end with the run

    def file(self):
        """Begin a new conversation: the live one joins the filed ones when it holds messages, the setup staying with the live one but for the
        recommendation behaviour, which ends with the conversation as its scan mark, denied recommendations and pruning state do."""
        if self.log:
            self.archive.append(self.conversation())
            self.archive.sort(key=lambda stored: stored["started"] or 0)
        self.log, self.reports, self.session, self.started, self.statement = [], [], None, None, None
        self.session_connector = None
        self.denied = []
        self.scan, self.prune = security.scan_mark(), pruning.new_state()
        self.setup.pop(recommend.BEHAVIOUR_KEY, None)
        self.keep = {}

    def resume(self, index):
        """The filed conversation `index` becomes the live one, with its setup, the live one filed in its place."""
        if not isinstance(index, int) or not 0 <= index < len(self.archive):
            raise ApiError(404, f"no conversation {index} of {self.uid}")
        stored = self.archive.pop(index)
        self.file()
        self.log, self.session, self.started, self.statement = stored["log"], stored["session"], stored["started"], stored.get("statement")
        self.session_connector = stored.get("session_connector")
        self.keep = stored.get("keep") or {}
        self.restore_state(stored)
        self.setup = dict(stored["setup"]) or self.setup

    @staticmethod
    def summary(stored):
        """A filed conversation as the page lists it: its start, first line of text and message count."""
        first = next((m["text"] for m in stored["log"] if m.get("text")), "")
        return {"started": stored["started"], "title": first.strip().split("\n", 1)[0][:120], "messages": len(stored["log"])}

    @property
    def running(self):
        return self.turn is not None and self.turn.outcome is None

    def next_turn(self, connector, changed, parent=None):
        self.turns += 1
        self.turn = Turn(f"{self.uid}:{self.turns}", connector, changed, parent)
        return self.turn

    def kept(self, upto=None):
        """The exchange as it travels: every message -- of the log ahead of index `upto`, where given -- but a failed or stopped turn's, its
        cuts taken out, one left empty left out."""
        kept = []
        for m in self.log[:upto]:
            kept += [{"role": "user", "text": step["text"]} for step in m.get("steps") or () if step.get("kind") == "user" and str(step.get("text") or "").strip()]
            said = "" if pruning.reply_pruned(m, self.prune) else kept_text(m["text"], m.get("cuts"))  # a pruned reply leaves its stub with the next message
            text = "\n".join([*m.get("applied", ()), said]).strip("\n")  # the lines the log shows as blocks
            if m["role"] not in ("error", "stopped") and text.strip():
                kept.append({"role": m["role"], "text": text})
        return kept

    def head(self, upto=None):
        """The exchange as a new session's head holds it -- of the log ahead of index `upto`, where given: every answered turn as the pruning
        holds it -- its AI texts, the results of its steps no verdict cut, the stubs of the cut ones and its reply -- the user's messages, and
        a message logged without steps as it travels; a failed or stopped turn's is left out."""
        said = []
        for m in self.log[:upto]:
            reply = kept_text(m["text"], m.get("cuts")) if m.get("text") else ""
            if m["role"] == "ai" and isinstance(m.get("turn"), int) and isinstance(m.get("steps"), list):
                said += pruning.head(m["turn"], m["steps"], reply, self.prune["applied"])
            elif m["role"] not in ("error", "stopped") and (text := "\n".join([*m.get("applied", ()), reply]).strip("\n")).strip():
                said.append({"role": m["role"], "text": text})
        return said

    @staticmethod
    def _entry(log, at, uid=None):
        """{uid, turn, time, user, steps, reply} of the turn answered by `log[at]`: the user's messages ahead of it, its steps and its reply."""
        start = at
        while start > 0 and log[start - 1]["role"] == "user":
            start -= 1
        m = log[at]
        return {"uid": uid, "turn": m["turn"], "time": m.get("time"), "user": [str(u.get("text") or "") for u in log[start:at]],
                "steps": list(m.get("steps") or ()), "reply": str(m.get("text") or "")}

    def turn_record(self, number):
        """{turn, user, steps, reply} of the answered turn `number` as the log keeps it: the user's messages ahead of its answer, its steps and
        its reply; None for a turn the log holds no answer of."""
        at = next((index for index, m in enumerate(self.log) if m.get("turn") == number and m["role"] == "ai"), None)
        if at is None:
            return None
        entry = self._entry(self.log, at)
        return {key: entry[key] for key in ("turn", "user", "steps", "reply")}

    def turn_entries(self):
        """The turns kept of the chat -- of the live conversation and the filed ones, the turn in flight with its steps so far, the batch still running left out --
        as {uid, turn, time, user, steps, reply}, by turn number, the later record of a number replacing the earlier; what the log tool reads."""
        found = {}
        for log in [*(stored["log"] for stored in self.archive), self.log]:
            for at, m in enumerate(log):
                if isinstance(m.get("turn"), int) and isinstance(m.get("steps"), list):
                    found[m["turn"]] = self._entry(log, at, self.uid)
        if self.running and (steps := [step for step in self.turn.steps if "pending" not in step]):  # a finished turn is read from its logged answer, with its time and reply
            number = int(self.turn.id.rpartition(":")[2])
            ahead = []
            for m in reversed(self.log):
                if m["role"] != "user":
                    break
                ahead.insert(0, str(m.get("text") or ""))
            found[number] = {"uid": self.uid, "turn": number, "time": None, "user": ahead, "steps": steps, "reply": ""}
        return [found[number] for number in sorted(found)]

    def folded_texts(self):
        """The spans of text the user folded out of the messages of the chat, the live conversation's and the filed ones'."""
        return [text[start:end] for log in [self.log, *(stored["log"] for stored in self.archive)] for m in log for text in [m.get("text") or ""]
                for start, end in cut_ranges(text, m.get("cuts"))]

    def snapshot(self):
        return {"uid": self.uid, "log": [pruning.log_view(m, self.prune) for m in self.log], "session": self.session, "started": self.started, **self.setup,
                "archive": [self.summary(stored) for stored in self.archive], "turn": self.turn.id if self.running else None,
                **({"steps": list(self.turn.steps)} if self.running else {}), **({"agents": agents} if (agents := self.agents()) else {}),
                **({"queue": [dict(m) for m in self.queue]} if self.queue else {}),
                **({"held": {"turn": self.turn.id, "asked": self.turn.held, **(({"review": self.turn.offer["review"]} if "review" in self.turn.offer else {"recommendation": self.turn.offer}) if self.turn.offer else {})}}
                   if self.running and self.turn.held is not None else {})}

    def agents(self):
        """The background subagents of the chat still running: the item each runs on and its turn."""
        return [{"uid": child.id.rpartition(":")[0], "turn": child.id} for child in self.background if child.outcome is None]

    def record(self):
        """The chat as it is kept across server runs: what is settled, never the turn in flight."""
        return {"turns": self.turns, **self.conversation(), **({"reports": list(self.reports)} if self.reports else {}),
                "archive": [dict(stored, log=[dict(m) for m in stored["log"]]) for stored in self.archive]}

    @classmethod
    def restore(cls, uid, record):
        chat = cls(uid)
        turns = record.get("turns")
        chat.turns = turns if isinstance(turns, int) else 0
        live = cls._conversation(record)
        chat.log, chat.session, chat.setup, chat.started, chat.statement = live["log"], live["session"], live["setup"], live["started"], live["statement"]
        chat.session_connector = live.get("session_connector")
        chat.keep = live.get("keep") or {}
        chat.restore_state(live)
        chat.reports = [report for report in record.get("reports") or () if isinstance(report, str)]
        chat.archive = [cls._conversation(stored) for stored in record.get("archive") or () if isinstance(stored, dict) and isinstance(stored.get("log"), list)]
        return chat

    def restore_state(self, stored):
        """Take the scan mark, the denied recommendations and the pruning state of a kept conversation -- each part that is not of its shape
        starting anew."""
        self.scan = security.scan_mark.from_json(stored.get("scan"))
        self.denied = [key for key in stored.get("denied") or () if isinstance(key, str)] if isinstance(stored.get("denied"), list) else []
        prune, fresh = stored.get("prune"), pruning.new_state()
        self.prune = {**fresh, **{key: prune[key] for key in fresh if isinstance(prune, dict) and type(prune.get(key)) is type(fresh[key])}}

    @classmethod
    def _conversation(cls, stored):
        setup, started = stored.get("setup"), stored.get("started")
        setup = {key: value for key, value in (setup.items() if isinstance(setup, dict) else ()) if key in SETUP_KEYS}
        session, owner = stored.get("session"), stored.get("session_connector")  # a record from before owners belongs to the setup's connector
        return {"started": started if isinstance(started, (int, float)) and not isinstance(started, bool) else None,
                "log": [cls._message(m) for m in stored.get("log") or () if isinstance(m, dict) and isinstance(m.get("role"), str) and isinstance(m.get("text"), str)],
                "session": session, "statement": stored["statement"] if isinstance(stored.get("statement"), str) else None, "setup": setup,
                **({"keep": keep} if session and isinstance(keep := stored.get("keep"), dict) and isinstance(keep.get("context"), str) else {}),
                **({"session_connector": owner if isinstance(owner, str) else setup.get("connector")} if session else {}),
                **{key: stored[key] for key in ("scan", "denied", "prune") if key in stored}}

    @staticmethod
    def _message(stored):
        """A stored message with its cuts normalised; a record from before cuts marked a whole message `dropped` instead."""
        m = dict(stored)
        cuts = [[0, len(m["text"])]] if m.pop("dropped", False) else cut_ranges(m["text"], m.get("cuts"))
        m.pop("folded", None)
        m.pop("cuts", None)
        return {**m, "cuts": cuts} if cuts else m


def kill_group(proc):
    """Kill the process `proc` with its whole process group, one already gone left as it is."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


class JobRunner:
    """Single-flight subprocess runner: review runs stamp files and share the
    build tree, so exactly one job may be live at a time."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counter = 0
        self.current = None

    def start(self, argv, cwd, then=None):
        with self._lock:
            if self.current and self.current.returncode is None:
                raise ApiError(409, f"a run is already in progress (job {self.current.id})")
            self._counter += 1
            job = Job(self._counter, argv, then)
            try:
                job.proc = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True)
            except OSError as exc:
                raise ApiError(500, f"failed to start {argv[0]}: {exc}")
            self.current = job
        threading.Thread(target=self._pump, args=(job,), daemon=True).start()
        return job

    def _pump(self, job):
        for line in job.proc.stdout:
            job.say(line.rstrip("\n"))
        job.proc.wait()
        try:
            for line in job.then(job) if job.then else ():
                job.say(line)
        except Exception as err:
            job.say(f"{type(err).__name__}: {err}")
        with job.cond:
            job.returncode = job.proc.returncode
            job.cond.notify_all()

    def get(self, job_id):
        job = self.current
        return job if job and job.id == job_id else None

    def cancel(self, job=None):
        """End the live job (or `job`) with its whole process group -- asked to terminate, killed after a grace period -- and await
        its exit for at most another grace period."""
        job = job or self.current
        if not job or job.returncode is not None:
            return
        with job.cond:
            for signum, grace in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
                try:
                    os.killpg(job.proc.pid, signum)
                except ProcessLookupError:
                    pass
                if job.cond.wait_for(lambda: job.returncode is not None, timeout=grace):
                    return


class AssassinApp:
    def __init__(self, root=None, syngate_dir=None, coverage=(), cli_prefix=None, build_dir=DEFAULT_BUILD_DIR, token=None):
        self.root = syngatelib.find_root(root)
        self.syngate_dir = Path(syngate_dir) if syngate_dir else self.root / "syngate"
        self.run_coverage = str(self.root / RUN_COVERAGE)
        self.coverage = list(dict.fromkeys([*(str(p) for p in coverage), self.run_coverage]))
        self.cli_prefix = cli_prefix or [sys.executable, "-m", "ai_scratcher.syngate", "--root", str(self.root)]
        self.build_dir = build_dir
        self.token = token or secrets.token_urlsafe(24)
        # Which run of the server this is: a page seeing it change knows the chats, turns and jobs it holds count anew.
        self.boot = secrets.token_hex(8)
        # The engine watch: the sources as this process loaded them, and `relaunch` -- the argv re-executing the server, set by `serve`;
        # None keeps the engine from restarting itself. `execv` and `listener`, the listening socket, are what the restart hands over.
        self.engine_loaded = engine_stamp()
        self.engine = {"changed": [], "error": None, "requested": False, "restarting": False}
        self._preflown = None
        self.relaunch = None
        self.listener = None
        self.execv = os.execve
        self.jobs = JobRunner()
        self.chats_file = self.root / CHATS_FILE
        self.chats = self._read_chats()
        self.chats_version = 0
        self._chat_lock = threading.Condition()
        self._writer = None
        self.settings_file = self.root / SETTINGS_FILE
        self._settings_lock = threading.Lock()
        self.defaults_notice = None
        # A connector naming a settings section is set up by it, read at every use.
        self.connectors = {name: connector(cwd=self.root, **({"config": functools.partial(self.settings, connector.settings_section)}
                                                             if getattr(connector, "settings_section", None) else {}))
                           for name, connector in synthetic.CONNECTORS.items()}
        self.websurf = websurf.bridge(self.token)
        # The embedding and the reranker of the file measuring, set where a test or a caller brings its own; None serves them by the `orchestrator` settings.
        self.embed = self.rerank = None
        # The embedding vectors by the space they were computed in -- the model locator's connection and model, or the embedding set on the app -- and the
        # text: the server's memory only, so a text is embedded once per run and again only once it changed.
        self.vectors = {}
        # The health of the model services, checked by `serve` when the server starts and whenever a call to a role fails; the blocking alert it
        # raises -- `services_asked` -- is the `asked` of every chat while it stands.
        self.health = services.health(lambda: services.role_locators(self.settings("orchestrator")), services.prober(self.sync_connections),
                                      on_clear=self.services_cleared, on_fail=self.services_alert,
                                      resolve=lambda locator: services.resolve_locator(self.sync_connections(), locator))
        self.services_asked = None
        # The security scan's verdicts by the hash of the scanned text, the server's memory only, and the home whose `.ai-assassin` keeps the
        # findings the user accepted, the user's own unless a test names another.
        self.scan_verdicts = {}
        self.findings_home = None
        # The server's memory of the measuring, never written to disk: the message each heavy file of a chat was measured for, and the heavy files a
        # session then read, which feed the activity signal of later measurements.
        self.measured, self.misses = {}, []
        # How a new surf window is set beside the Assassin window, read once from the desktop: it goes out with every `open` but `browser`.
        self.tiling = tiling.method()
        # The step of the first setup under way, which every chat shows in place of its reply line's hint; None while none runs.
        self.setup_step = None
        self.detect_git()

    def first_setup(self, run=None):
        """Run the first setup -- `run(root, say)`, `assassin_setup.run` by default -- on a thread of its own while the server settings hold no
        `orchestrator` section, every step it says announced to the chats as `setup_step` until it ends. -> the thread, None while the section is held."""
        if SETUP_SECTION in synthetic.read_json(self.settings_file):
            return None
        run = run or (lambda root, say: assassin_setup.run(root, say=say))

        def said(step):
            with self._chat_lock:
                self.setup_step = f"{SETUP_PROGRESS} {step}"
                self._bump(settled=False)

        def setup():
            said("starting")
            try:
                run(self.root, said)
            except Exception as err:
                print(f"assassin: the first setup failed: {err}", file=sys.stderr)
            finally:
                with self._chat_lock:
                    self.setup_step = None
                    self._bump(settled=False)

        thread = threading.Thread(target=setup, daemon=True)
        thread.start()
        return thread

    def detect_git(self):
        """Read once whether git is at hand for the project, and take the library its chats are offered, the requirements of its prompts
        probed once in this server's run."""
        self.git = gitlib.at_hand(self.root)
        self.library = synthetic.offered_library(self.root)

    def rankers(self, section):
        """(embed, rerank) of the dense and rerank signals: the callables set on the app, else those over the model locator in use of the `embed`
        and `rerank` roles of the `orchestrator` section, read at every call so a role moved on serves the next call; None for a role given no
        locator of a connection that serves it. Vectors are kept per locator, never mixing two models' spaces."""
        def served(role, build):
            connections = self.sync_connections()
            if not any(hasattr(connections.get(locator["connection"]), "read_config") for locator in services.locators(section.get(role))):
                return None

            def call(*args):
                locator = self.health.locator(role)
                connection = self.sync_connections().get(locator["connection"]) if locator else None
                if not hasattr(connection, "read_config"):
                    raise services.service_error(f"the connection '{locator['connection'] if locator else None}' serves no {role}")
                built = build(connection, locator["model"])
                if role == "embed":
                    built = services.cached(built, self.vectors.setdefault(f"{locator['connection']}/{locator['model']}", {}))
                return built(*args)
            return call
        embed = services.cached(self.embed, self.vectors.setdefault(f"app:{id(self.embed)}", {})) if self.embed else served("embed", services.embedder)
        return self.held("embed", embed), self.held("rerank", self.rerank or served("rerank", services.reranker))

    def held(self, role, call):
        """`call` to the model of `role`, a failing call held on the blocking alert until the role answers again (`services.health.hold`); None stays None."""
        if call is None:
            return None
        return lambda *args, **kwargs: self.health.hold(role, lambda: call(*args, **kwargs), errors=(services.service_error, OSError))

    def services_alert(self):
        """Raise the blocking alert of the model services as the `asked` of every chat that holds no other question -- none, or the alert's earlier wording."""
        alert = self.health.alert()
        if alert != self.services_asked:  # told once per wording: the server's log says why every chat stands blocked
            print(f"assassin: model services alert, every chat blocked until it clears: {alert}", file=sys.stderr, flush=True)
        with self._chat_lock:
            previous, self.services_asked = self.services_asked, alert
            for chat in self.chats.values():
                if chat.asked is None or chat.asked == previous:
                    chat.asked = alert
            self._bump()

    def services_cleared(self):
        """Every role answers again: the alert leaves the chats running a turn, then `alert_cleared` frees the others."""
        with self._chat_lock:
            previous, self.services_asked = self.services_asked, None
            if previous is not None:
                print("assassin: model services alert cleared, every role answers", file=sys.stderr, flush=True)
            for chat in self.chats.values():
                if chat.running and previous is not None and chat.asked == previous:
                    chat.asked = None
        self.alert_cleared()

    def services_state(self):
        """The diagnosis of a stuck chat (ORCHESTRATOR-SERVICES-DIAGNOSE): the health of the model services -- the alert, each failing role with
        the locators tried and their failures, the locator in use of each role -- and every chat not idle: its state, what it is asked, its
        queued messages and its running turn, held or not."""
        with self._chat_lock:
            chats = {}
            for uid, chat in self.chats.items():
                state = self.chat_state(chat)
                if state["state"] == "waiting" and not chat.queue:
                    continue
                held = chat.turn.held if chat.running else None
                chats[uid] = {**state, "queue": [m["text"] for m in chat.queue], "turn": chat.turn.id if chat.running else None,
                              **({"held": held} if held is not None else {})}
            asked = self.services_asked
        return {**self.health.state(), "services_asked": asked, "chats": chats}

    def _measure(self, items, uid, message):
        """The measurement of the seed context of `uid` for `message`: the token budget and signal weights of the `orchestrator` settings, the chat's
        own activity and the notes of its misses fed in; a model service that fails leaves the signals that need no model."""
        section = self.settings("orchestrator")
        budget = section.get("budget")
        budget = budget if isinstance(budget, int) and not isinstance(budget, bool) and budget >= 0 else synthetic.FILE_BUDGET
        with self._chat_lock:
            chat = self.chats.get(uid)
            activity = tiering.activity_of(chat.log if chat else ())
            activity["read"] += [note["file"] for note in self.misses if note["uid"] == uid]
        embed, rerank = self.rankers(section)
        weights = section.get("weights") if isinstance(section.get("weights"), dict) else None
        try:
            return synthetic.measure_seed(items, uid, message, self.root, budget, embed, rerank, activity, weights)
        except (services.service_error, ValueError):
            return synthetic.measure_seed(items, uid, message, self.root, budget, None, None, activity, weights)

    def _session_context(self, connector, uid, message, text, session, keep, turn, retry, first, agent):
        """(system prompt, text) of one round of an exchange anchored at `uid`: a turn that starts a session measures the seed context for its
        `message`, composes the system prompt once and keeps it in `keep`; a later turn of the session sends the kept prompt unchanged and heads its
        text with the context update; a later round, the kept prompt alone. The prompt is None where the connection composes its own."""
        connection = self.sync_connections().get(connector)
        if agent is not None or connection is None or uid not in (items := self._load()):
            return None, text
        if first and not session:
            measured = self._measure(items, uid, message)
            context = synthetic.system_context(connection, items, uid, text, self.root, self.library, heavy=measured.heavy)
            keep.clear()
            keep.update(synthetic.new_keep(context, items, uid, measured, self.root))
            self.measured = {key: held for key, held in self.measured.items() if key[0] != uid}
            self._noted(uid, measured.heavy, message)
            if measured.heavy and turn:
                turn.add_step({"kind": "context", "text": "Files held back as references:\n" + "\n".join(measured.heavy.values()), "at": turn.elapsed()})
            return context, text
        if first and not retry and keep.get("context"):
            update, kept = synthetic.context_update(keep, items, uid, text, self._measure(items, uid, message), self.root, told=(uid,))
            keep.update(kept)
            self._noted(uid, kept["heavy"], message)
            if update:
                if turn:
                    turn.add_step({"kind": "context", "text": update, "at": turn.elapsed()})
                text = f"{update}\n\n{text}"
        return keep.get("context"), text

    def _noted(self, uid, heavy, message):
        """Note in the server's memory the message each of the `heavy` files was first measured for."""
        for rel in heavy:
            self.measured.setdefault((uid, rel), message)

    def _miss(self, uid, keep, call):
        """Note a miss -- a heavy file of the session read by a read call -- with the message it was measured for, in the server's memory alone."""
        path = call.get("path")
        rel = os.path.normpath(path) if isinstance(path, str) and path.strip() else None
        message = self.measured.get((uid, rel))
        if call.get("tool") == "read" and rel in (keep.get("heavy") or {}) and message is not None:
            note = {"uid": uid, "file": rel, "message": message}
            if note not in self.misses:
                self.misses.append(note)

    def offered(self):
        """(name, connector) of every connector the page offers: those that are not set up -- an API connection without a model or
        without the key it declares -- left out."""
        return [(name, connector) for name, connector in self.sync_connections().items() if getattr(connector, "available", lambda: True)()]

    def sync_connections(self):
        """The connectors, the API connections among them brought in line with the `connections` section of the server settings read
        now: one per entry by its id, in the section's order after the built-in connectors, whose names it cannot take; the connection
        of an id already held is kept, with its model listing and its stops."""
        held = {name: connector for name, connector in self.connectors.items() if isinstance(connector, api_connection.api_connection)}
        wanted = [name for name, entry in self.settings("connections").items() if isinstance(entry, dict)]  # the slow read comes first
        builtin = {name: connector for name, connector in self.connectors.items() if not isinstance(connector, api_connection.api_connection)}  # read last, so a concurrent change is kept
        self.connectors = {**builtin, **{name: held.get(name) or api_connection.api_connection(name, cwd=self.root, config=functools.partial(self.connection_settings, name))
                                         for name in wanted if name not in builtin}}
        return self.connectors

    def connection_settings(self, name):
        """The entry of the API connection `name` in the `connections` section of the server settings, read now; {} without one."""
        entry = self.settings("connections").get(name)
        return entry if isinstance(entry, dict) else {}

    def settings(self, section):
        """One feature's section of the server settings, read from `SETTINGS_FILE` at every use: {} while the file is missing or malformed
        or holds no such section."""
        value = synthetic.read_json(self.settings_file).get(section)
        return value if isinstance(value, dict) else {}

    def write_settings(self, section, value):
        """Set one section of the server settings, the others kept as they stand, the file replaced whole; False -- nothing written -- while the
        file holds no JSON object (a hand edit in progress is never overwritten) or cannot be written."""
        with self._settings_lock:
            try:
                data = json.loads(self.settings_file.read_text(encoding="utf-8")) if self.settings_file.exists() else {}
                if not isinstance(data, dict):
                    return False
                draft = self.settings_file.with_suffix(".json.tmp")
                draft.write_text(json.dumps({**data, section: value}, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(draft, self.settings_file)
            except (OSError, ValueError) as err:
                print(f"assassin: settings not saved to {self.settings_file}: {err}", file=sys.stderr)
                return False
        return True

    def mode_table(self):
        """{mode id: advanced} of every permission there is: the harness's own and those every connector lists."""
        table = {mode: False for mode in HARNESS_MODES}
        for connector in self.sync_connections().values():
            for mode in (connector.settings().get("modes", ()) if hasattr(connector, "settings") else ({"id": mode} for mode in getattr(connector, "modes", ()))):
                table[mode["id"]] = bool(mode.get("advanced"))
        return table

    def builtin_setup(self):
        """The setup of a new chat before anything was chosen: the first connector's defaults, the permissions that are on by default."""
        name, connector = next(iter(self.sync_connections().items()))
        if not hasattr(connector, "settings"):  # a connector that tells nothing of itself
            return {"connector": name, "model": None, "effort": None, "modes": [TREE_MODE["id"], PATCH_MODE["id"]]}
        settings = connector.settings()
        default = settings.get("default") or {}
        return {"connector": name, "model": default.get("model") or settings["models"][0]["id"], "effort": default.get("effort") or next(iter(settings["efforts"]), None),
                "modes": [mode["id"] for mode in [TREE_MODE, PATCH_MODE, *settings["modes"]] if mode.get("default") and not mode.get("advanced")]}

    def chat_defaults(self):
        """The setup of a new chat: the `chat` section of the settings, its permission list checked against the permissions there are and cut
        to the main ones -- advanced ones start off. A section whose list fails the check is replaced, in the file too, by the built-in setup and
        `defaults_notice` tells why. A model or effort the connector lists no longer is left to the page, which falls back to the connector's own."""
        builtin, stored, table = self.builtin_setup(), self.settings(CHAT_SECTION), self.mode_table()
        if not stored:
            return builtin
        modes = stored.get("modes")
        if modes is not None and not self.valid_modes(modes, table):
            self.defaults_notice = self.modes_problem(modes, table)
            self.write_settings(CHAT_SECTION, builtin)
            return builtin
        return {**builtin, **{key: stored[key] for key in ("connector", "model", "effort") if key in stored},
                **({"modes": [mode for mode in modes if not table[mode]]} if modes is not None else {})}

    @staticmethod
    def valid_modes(modes, table):
        """Whether `modes` is a list of permission ids that exist."""
        return isinstance(modes, list) and all(isinstance(mode, str) and mode in table for mode in modes)

    @staticmethod
    def modes_problem(modes, table):
        """What is wrong with a permission list, in words."""
        if not isinstance(modes, list):
            return f"not a list: {json.dumps(modes)}"
        return "unknown " + ", ".join(json.dumps(mode) for mode in modes if not isinstance(mode, str) or mode not in table)

    def keep_new_chat_setup(self, data, table, defaults):
        """Keep the setup chosen in a new chat -- the live one holds no message -- as the setup of every next new chat: the `chat` section
        takes the connector, model, effort and main permissions of `data`, the others as they were -- `defaults` -- advanced permissions
        never kept; `table` is the `mode_table`, both read by the caller outside the chats lock, since a connector may answer slowly."""
        chosen = {key: data[key] for key in SETUP_KEYS if key in data and key != recommend.BEHAVIOUR_KEY}  # the behaviour is the chat's own choice
        if "modes" in chosen:
            chosen["modes"] = [mode for mode in chosen["modes"] if mode in table and not table[mode]] if self.valid_modes(chosen["modes"], table) else None
            if chosen["modes"] is None:
                del chosen["modes"]
        if chosen and {**defaults, **chosen} != defaults:  # a choice the new chats start with anyway writes nothing
            self.write_settings(CHAT_SECTION, {**defaults, **chosen})

    def surf_lists(self):
        """(allow, block): the WebSurf host lists of the server settings, each the strings of its list; empty while it names none."""
        section = self.settings("websurf")
        return tuple([entry for entry in section[key] if isinstance(entry, str)] if isinstance(section.get(key), list) else [] for key in ("allow", "block"))

    def mermaid_url(self):
        """The ES module of the drawing library the diagram frame loads: `markdown.mermaid` of the server settings where it is an http or https
        URL of a host alone, with no character that would leave its place in the frame's script or policy, else `MERMAID_URL`."""
        url = self.settings("markdown").get("mermaid")
        parts = urlsplit(url) if isinstance(url, str) else None
        plain = parts is not None and not re.search(r"[\s'\"<>;\\]", url) and "@" not in parts.netloc
        return url if plain and parts.scheme in ("http", "https") and parts.hostname else MERMAID_URL

    def surf_rounds(self):
        """The rounds a turn that has surfed may run: `websurf.rounds` of the server settings, else `websurf.ROUNDS`."""
        rounds = self.settings("websurf").get("rounds")
        return rounds if type(rounds) is int and rounds > 0 else websurf.ROUNDS

    def turn_rounds(self):
        """The round fuse of a turn that has not surfed: `orchestrator.rounds` of the server settings, else `synthetic.QUERY_ROUNDS`."""
        rounds = self.settings("orchestrator").get("rounds")
        return rounds if type(rounds) is int and rounds > 0 else synthetic.QUERY_ROUNDS

    # -- model ------------------------------------------------------------

    def _coverage_files(self):
        return [p for p in self.coverage if Path(p).is_file()]

    def fingerprint(self):
        stat = hashlib.sha256()
        paths = sorted(self.syngate_dir.rglob("*.yml")) + [Path(p) for p in self._coverage_files()]
        for path in paths:
            try:
                meta = path.stat()
            except OSError:
                continue
            stat.update(f"{path}\0{meta.st_mtime_ns}\0{meta.st_size}\n".encode())
        if self.git:
            stat.update(gitlib.state(self.root).encode("utf-8", "surrogateescape"))
        if self.websurf.attached is not None:
            stat.update(b"websurf attached\n")
        stat.update(json.dumps(self.settings(CHAT_SECTION), sort_keys=True).encode())  # the new-chat setup is part of the page's model
        return stat.hexdigest()

    def _blocked(self, items, uids, discovered, uncommitted):
        """The uncommitted files of the review footprints of `uids`."""
        return sorted({path for uid in uids if uid in items for path in syngatelib.review_footprint(items, uid, discovered, self.root)} & uncommitted)

    def build_model(self):
        items, load_errors = syngatelib.load_tree(self.syngate_dir)
        discovered = syngatelib.discover_setups(items, syngatelib.discover_bindings(self.root), self.root)[0]
        records, coverage_errors = syngatelib.load_coverage(self._coverage_files())
        problems = syngatelib.item_problems(items, discovered)
        report = syngatelib.compute_status(items, records, problems)
        axes = syngatelib.compute_axes(items, records, problems)
        tree_errors = [message for uid, message in syngatelib.layout_problems(items) if uid is None]
        uncommitted = gitlib.uncommitted(self.root) if self.git else set()
        pending = self._pending(items, problems)
        content = gitlib.content_uncommitted(self.root, uncommitted) if uncommitted else set()  # review marks never block a review
        dirty = {uid: syngatelib.review_footprint(items, uid, discovered, self.root) & content for uid in pending} if content else {}

        payload, scopes, stampable, setups = {}, syngatelib.feature_scopes(items)[0], syngatelib.stampable(items), syngatelib.setup_scopes(items)
        for uid, entry in report.items():
            item = items[uid]
            bindings = None
            if item.is_leaf:
                bindings = [{
                    "name": name or "",
                    "sha": sha,
                    "locations": [{"path": loc.path, "line": loc.line, "name": loc.name}
                                  for loc in discovered.get((uid, name), [])],
                    "records": len(records.get((uid, name), [])),
                } for name, sha in item.tests.items()]
            payload[uid] = dict(entry, **axes[uid],
                                is_leaf=item.is_leaf,
                                features=scopes[uid],
                                stampable=uid in stampable,
                                description_raw=item.description,
                                path=str(item.path.relative_to(self.root)) if item.path.is_relative_to(self.root) else str(item.path),
                                stamp_fresh=(syngatelib.item_stamp(items, uid) == item.reviewed) if item.reviewed else None,
                                bindings=bindings,
                                setup=None if item.setup is None else dict(item.setup),
                                setup_from=setups[uid],
                                uncommitted=sorted(set().union(*(dirty[under] for under in syngatelib.items_under(items, uid) if under in dirty))))

        roots = sorted(uid for uid, item in items.items() if not item.parents)
        reachable, queue = set(), list(roots)
        while queue:
            uid = queue.pop()
            if uid in reachable:
                continue
            reachable.add(uid)
            queue.extend(payload[uid]["children"])
        counts = {}
        for entry in payload.values():
            counts[entry["test"]] = counts.get(entry["test"], 0) + 1
        job = self.jobs.current
        harness = [SURF_MODE] if self.websurf.attached is not None else []
        return {
            "fingerprint": self.fingerprint(),
            "items": payload,
            "roots": roots,
            "unreachable": sorted(set(payload) - reachable),
            "counts": counts,
            "load_errors": load_errors + tree_errors,
            "coverage": {"files": self._coverage_files(), "errors": coverage_errors},
            "build_dir": self.build_dir,
            "features": syngatelib.features(items),
            "connectors": {name: {**(settings := connector.settings()), "modes": [TREE_MODE, PATCH_MODE, *settings["modes"], *harness]} for name, connector in self.offered()},
            "chat_defaults": self.chat_defaults(),
            "recommendations": recommend.behaviour_of(None, self.settings("orchestrator").get(recommend.BEHAVIOUR_KEY)),  # the behaviour of a chat that chose none
            "git": self.git,
            "uncommitted": sorted(uncommitted),
            "job": job.id if job and job.returncode is None else None,
            "boot": self.boot,
            "engine": self.engine_state(),
        }

    @staticmethod
    def _pending(items, problems):
        """The items whose own review does not stand: unstamped, or with a validation problem of their own -- those a review stamps alone."""
        stampable = syngatelib.stampable(items)
        return {uid for uid, item in items.items() if uid in stampable and (not item.reviewed or problems.get(uid))}

    # -- mutations --------------------------------------------------------

    def _load(self):
        items, _ = syngatelib.load_tree(self.syngate_dir)
        return items

    # Every mutation from the page is the user's own act, so it passes `clear`:
    # the stamps it moves are dropped, where an AI-proxied call leaves them
    # standing over changed content and the review reads as violated.

    def save_item(self, uid, data):
        """Partial update through the core edit call; `base` carries the values
        the editor started from, so an autosave never silently overwrites an
        edit made on disk (agent, git, IDE) since the page loaded the item."""
        items = self._load()
        stored = _call(lambda: syngatelib.edit_item(items, uid, data, data.get("base"), clear=True))
        item = items[uid]
        return {"ok": True, "stamp_fresh": (syngatelib.item_stamp(items, uid) == item.reviewed) if item.reviewed else None, "stored": stored}

    def move_item(self, uid, data):
        items = self._load()
        written = _call(lambda: syngatelib.move_item(items, uid, data.get("to"), before=data.get("before"),
                                                     source=data.get("from"), link=bool(data.get("link")), clear=True))
        return {"ok": True, "written": written}

    def create_item(self, data):
        items = self._load()
        item = _call(lambda: syngatelib.add_item(items, str(data.get("uid") or ""), data.get("parents") or [],
                                                 description=data.get("description"), kind=data.get("kind"), folder=data.get("dir"),
                                                 order=data.get("order", 0), sources=data.get("sources"), syngate_dir=self.syngate_dir, clear=True))
        return {"ok": True, "path": str(item.path.relative_to(self.root))}

    def delete_item(self, uid):
        items = self._load()
        _call(lambda: syngatelib.delete_item(items, uid, clear=True))
        with self._chat_lock:
            chat = self.chats.get(uid)
            if chat and chat.running:
                self.stop_turn(chat.turn.id)
            if self.chats.pop(uid, None) is not None:
                self._bump()
        return {"ok": True}

    # -- linked project files ---------------------------------------------

    def _file_at(self, rel):
        """(absolute path, writable) for a normalised project-relative path;
        any file inside the project is served -- `_text` admits UTF-8 text alone -- but git's own folder
        and the server's settings and stored chats; only markdown is writable."""
        if not rel or Path(rel).is_absolute() or ".." in Path(rel).parts or rel != Path(rel).as_posix() or rel.startswith("-"):
            raise ApiError(400, f"'{rel}' is not a normalised project-relative path")
        path = (self.root / rel).resolve()
        if not path.is_relative_to(self.root.resolve()) or not path.is_file():
            raise ApiError(404, f"no file {rel}")
        inner = path.relative_to(self.root.resolve())
        if inner.parts[0] == ".git" or inner.as_posix() in UNREADABLE:
            raise ApiError(403, f"{rel} is not served: it is git's own or the server's")
        return path, path.suffix == ".md"

    @staticmethod
    def _text(path, rel):
        if path.stat().st_size > FILE_LIMIT:
            raise ApiError(413, f"{rel} exceeds {FILE_LIMIT >> 10} KiB")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise ApiError(415, f"{rel} is not UTF-8 text") from None
        if "\0" in text:
            raise ApiError(415, f"{rel} is not UTF-8 text")
        return text

    def read_file(self, rel):
        path, writable = self._file_at(rel)
        text = self._text(path, rel)
        return {"path": rel, "text": text, "sha": hashlib.sha256(text.encode()).hexdigest(), "writable": writable}

    def _walk(self):
        """(the project-relative paths of a walk of the project, hidden and build folders skipped; whether it ended past `FILES_LIMIT`)."""
        found = []
        for folder, dirs, names in os.walk(self.root):
            dirs[:] = sorted(d for d in dirs if not d.startswith((".", "cmake-build")) and d not in WALK_SKIPPED)
            found += [(Path(folder) / name).relative_to(self.root).as_posix() for name in sorted(names)]
            if len(found) > FILES_LIMIT:
                return found, True
        return found, False

    def list_files(self):
        """{files, truncated}: the project-relative files the mention hint offers -- the git-tracked ones while git is at hand, else a
        bounded walk -- sorted, never one that resolves outside the project nor an item file under `syngate/`."""
        root, items = self.root.resolve(), self.syngate_dir.resolve()
        if self.git:
            listed = gitlib.git(self.root, "ls-files", "-z")
            names, cut = [name for name in listed.stdout.split("\0") if name] if listed.returncode == 0 else [], False
        else:
            names, cut = self._walk()
        files = []
        for rel in sorted(names):
            path = root / rel
            try:
                inside = path.is_file() and path.resolve().is_relative_to(root)
                item_file = path.suffix == ".yml" and path.resolve().is_relative_to(items)  # items are mentioned by `@UID`, their files are not offered
            except OSError:
                continue
            if inside and not item_file:
                files.append(rel)
        return {"files": files[:FILES_LIMIT], "truncated": cut or len(files) > FILES_LIMIT}

    def file_shas(self, rels):
        shas = {}
        for rel in rels:
            try:
                shas[rel] = self.read_file(rel)["sha"]
            except ApiError:
                shas[rel] = None
        return shas

    def save_file(self, data):
        """Whole-file compare-and-swap against the text the page loaded, the
        file twin of `save_item`."""
        rel = str(data.get("path") or "")
        path, writable = self._file_at(rel)
        if not writable:
            raise ApiError(403, f"{rel}: only markdown is written from the page")
        text, base, before = str(data.get("text") or ""), data.get("base"), self._text(path, rel)
        if isinstance(base, str) and before != base and before != text:
            raise ApiError(409, f"{rel} changed on disk since the page loaded it", current={"file": before})
        if text != before:
            path.write_text(text, encoding="utf-8")
        return {"ok": True, "stored": {"file": text}, "sha": hashlib.sha256(text.encode()).hexdigest()}

    # -- chats --------------------------------------------------------------

    def chats_snapshot(self, since=None, wait=0):
        """Every chat as the server holds it; with `since`, awaited up to `wait` seconds for a change past that version -- one long poll
        serves a page however many turns run."""
        with self._chat_lock:
            if since is not None:
                self._chat_lock.wait_for(lambda: self.chats_version > since, timeout=wait)
            return {"version": self.chats_version, "chats": {uid: {**chat.snapshot(), **self.chat_state(chat)} for uid, chat in self.chats.items()},
                    **({"setup": self.setup_step} if self.setup_step else {})}

    def chat_state(self, chat, above=()):
        """{state[, asked]}: the server's state of the chat -- the first that holds of blocked (what a held turn or a blocking alert asks of the user, or
        a subagent the chat runs is blocked on: `asked` says what, naming the subagent's item), working, agents (the turn ended, background subagents
        run), failed, stopped (the last message of the log) and waiting; never unread, which is the tab's. Called under the chats lock; `above` are the
        chats whose subagents are being looked into."""
        asked = chat.asked
        for child in itertools.chain(chat.turn.children if chat.running else (), chat.background):
            uid = child.id.rpartition(":")[0]
            sub = self.chats.get(uid)
            if asked is None and child.outcome is None and sub is not None and sub is not chat and sub not in above:
                inner = self.chat_state(sub, (*above, chat))
                if inner["state"] == "blocked":
                    asked = f"@{uid} {inner['asked']}".rstrip()
        if asked is not None:
            return {"state": "blocked", "asked": asked, **({"services": True} if asked == self.services_asked else {})}
        last = chat.log[-1]["role"] if chat.log else None
        return {"state": "working" if chat.running else "agents" if chat.agents() else "failed" if last == "error" else "stopped" if last == "stopped" else "waiting"}

    def _chat(self, uid):
        chat = self.chats.get(uid)
        if chat is None:
            chat = self.chats[uid] = Chat(uid)
            chat.asked = self.services_asked  # a chat opened under the blocking alert stands under it too
        return chat

    def _bump(self, settled=True):
        """Announce a change of the chats; a settled one -- anything but the steps of a running turn -- is also written out, debounced."""
        self.chats_version += 1
        self._chat_lock.notify_all()
        if settled and self._writer is None:
            self._writer = threading.Timer(WRITE_DELAY, self.save_chats)
            self._writer.daemon = True
            self._writer.start()

    def _notify(self):
        with self._chat_lock:
            self._bump(settled=False)

    def _changed(self, chat):
        self._bump()
        return {**chat.snapshot(), **self.chat_state(chat), "version": self.chats_version}

    def _read_chats(self):
        """The stored chats of the items still in the tree -- an item whose file is unreadable right now keeps its chat; the store of the
        syngate-named era is read while the AI Assassin one is absent."""
        items, errors = syngatelib.load_tree(self.syngate_dir)
        known = set(items) | {error.split(":", 1)[0] for error in errors}
        stored = synthetic.read_json(self.chats_file if self.chats_file.exists() else self.root / LEGACY_CHATS_FILE)
        return {uid: Chat.restore(uid, record) for uid, record in stored.items() if uid in known and isinstance(record, dict)}

    def save_chats(self, force=False):
        """Write the chats pending a write -- or, `force`d, whatever is pending -- to `CHATS_FILE`, whole, at once."""
        with self._chat_lock:
            pending, self._writer = self._writer, None
            if pending is None and not force:
                return
            if pending is not None:
                pending.cancel()
            draft = self.chats_file.with_suffix(".json.tmp")
            try:
                draft.write_text(json.dumps({uid: chat.record() for uid, chat in self.chats.items()}, ensure_ascii=False, indent=1), encoding="utf-8")
                os.replace(draft, self.chats_file)
            except OSError as err:
                print(f"assassin: chats not saved to {self.chats_file}: {err}", file=sys.stderr)

    def update_chat(self, uid, data):
        """Change the item's chat in place: its setup, one message's cuts -- the spans of its text folded out of the exchange; a change of
        them ends the connector session, so the next turn carries the kept text -- the removal of a failed or stopped turn's message,
        `reset` -- the session dropped, the log kept -- `erase` of the live conversation, `begin` of a new one -- the live one filed --
        or `resume` of the filed one at that index, `unqueue` of the queued message at that index; everything but the setup and the
        queue is refused while a turn runs."""
        table, defaults = (self.mode_table(), self.chat_defaults()) if any(key in data for key in (*SETUP_KEYS, "begin")) else ({}, {})
        with self._chat_lock:
            chat = self._chat(uid)
            patch = data.get("message") if isinstance(data.get("message"), dict) else {}
            if chat.running and (data.get("erase") or data.get("reset") or data.get("begin") or "resume" in data or "cuts" in patch or patch.get("remove")):
                raise ApiError(409, f"a turn of {uid} is running; change the exchange once it ends")
            if "unqueue" in data:
                index = _number(data["unqueue"], "unqueue", int)
                if not 0 <= index < len(chat.queue):
                    raise ApiError(404, f"no queued message {index} of {uid} — it went to the AI already")
                del chat.queue[index]
            if data.get("erase"):
                chat.erase()
            if data.get("begin"):
                chat.file()
                self._advanced_off(chat, table)
            if "resume" in data:
                chat.resume(_number(data["resume"], "resume", int))
            if data.get("reset"):
                chat.session = None
            if (not chat.log or data.get("new")) and not chat.running:
                self.keep_new_chat_setup(data, table, defaults)
            chat.setup.update({key: data[key] for key in SETUP_KEYS if key in data})
            if "model" in data and (select := getattr(self.sync_connections().get(chat.setup.get("connector")), "select", None)):
                # a llama.cpp router loads the model chosen at once, so the load runs while the user writes
                threading.Thread(target=select, args=(chat.setup["model"],), daemon=True).start()
            if patch and 0 <= (index := _number(patch.get("index", -1), "index", int)) < len(chat.log):
                message = chat.log[index]
                if "cuts" in patch:
                    if not isinstance(patch["cuts"], list):
                        raise ApiError(400, "'cuts' must be a list of [from, to] spans")
                    cuts = cut_ranges(message["text"], patch["cuts"])
                    if cuts != message.get("cuts", []):
                        message.pop("cuts", None)
                        if cuts:
                            message["cuts"] = cuts
                        if message["role"] not in ("error", "stopped"):
                            chat.session = None
                if patch.get("remove"):
                    if message["role"] not in ("error", "stopped"):
                        raise ApiError(400, "only the message of a failed or stopped turn is removed from the log")
                    del chat.log[index]
            if isinstance(data.get("prune"), dict):
                self._switch_prune(chat, data["prune"])
            return self._changed(chat)

    @staticmethod
    def _switch_prune(chat, asked):
        """Set by hand whether the step `step` -- or the reply, `reply` -- of the logged turn `turn` is pruned: it takes effect with the chat's
        next message, brought into the running session by its connection, which goes on -- a running turn included."""
        number, step = asked.get("turn"), asked.get("step")
        logged = next((m for m in chat.log if isinstance(number, int) and m.get("turn") == number), None)
        steps = (logged or {}).get("steps") or []
        target = ({"kind": "message"} if logged and logged.get("role") == "ai" else None) if step == pruning.REPLY else \
            steps[step - 1] if type(step) is int and 1 <= step <= len(steps) else None
        if target is None:
            raise ApiError(404, f"no step {step} of turn {number} in the log of {chat.uid}")
        try:
            pruning.switch(chat.prune, number, step, target, bool(asked.get("pruned")))
        except pruning.refused as err:
            raise ApiError(400, str(err)) from None

    @staticmethod
    def _advanced_off(chat, table):
        """Switch the advanced permissions off in the setup of a chat that begins anew."""
        if isinstance(chat.setup.get("modes"), list):
            chat.setup["modes"] = [mode for mode in chat.setup["modes"] if not table.get(mode)]

    def start_turn(self, data, parent=None):
        """Start one turn of the item's chat -- the typed text joins the log, marked as an `agent` message when a parent turn sent it,
        a `statement` is the content itself and is not repeated as the first message of a conversation, `fresh` filing the live one
        first, and is announced into a conversation holding messages; a `retry` resends it without logging it again -- as a job the page
        polls through `turn_snapshot`, delegated by the `parent` turn from its start; -> `{"turn": "<UID>:<n>", "chat": …}`, the chat
        stamped with the chats `version`.
        A turn of a conversation whose anchored statement changed since its previous turn is headed by the `STATEMENT_NOTE` message.
        While a turn of the chat runs, a plain message marked `queue` joins the chat's queue instead -- the running turn hands it to the
        model at its next round, or the next turn starts with it once the running one ends -- and one marked `interrupt` joins it and
        stops the running turn, so the next turn carries it on in the same session; -> `{"queued": n, "chat": …}`. `queued` texts start
        a turn as messages of their own, sent together.
        The messages join the log first, before the turn is prepared: a failure preparing it is logged as an error under them and refused
        with the `chat`, so nothing the user sent is lost and a retry sends it again."""
        uid, text = str(data.get("uid") or ""), str(data.get("text") or "")
        with self._chat_lock:
            if self.engine["restarting"]:
                raise ApiError(503, RESTARTING)
            chat = self._chat(uid)
            plain = not (data.get("statement") or data.get("retry") or data.get("fresh") or data.get("agent"))
            if chat.running and plain and (data.get("queue") or data.get("interrupt")) and text.strip():
                chat.queue.append({"text": text})
                chat.setup.update({key: data[key] for key in SETUP_KEYS if key in data})
                running = chat.turn.id
                queued = {"queued": len(chat.queue), "chat": self._changed(chat)}
            elif chat.running:
                raise ApiError(409, f"a turn of {uid} is running ({chat.turn.id})")
            elif chat.asked is not None and plain and text.strip():  # under a blocking alert: kept queued, sent once every role answers
                chat.queue.append({"text": text})
                chat.setup.update({key: data[key] for key in SETUP_KEYS if key in data})
                running, queued = None, {"queued": len(chat.queue), "chat": self._changed(chat)}
            else:
                queued = None
                if data.get("fresh"):
                    chat.file()
                new, at = not chat.log, len(chat.log)  # the log ahead of this turn's messages
                if isinstance(data.get("queued"), list):
                    chat.log += [{"role": "user", "text": str(message)} for message in data["queued"]]
                elif not data.get("statement") and not data.get("retry"):
                    chat.log.append({"role": "user", "text": text, **({"agent": data["agent"]} if data.get("agent") else {})})
                self._bump()
        if queued:
            if data.get("interrupt") and running:
                self.stop_turn(running, withdraw=False)
            return queued
        try:
            return self._begin_turn(chat, data, text, parent, new, at)
        except Exception as err:
            failed = err if isinstance(err, ApiError) else ApiError(500, INTERRUPTED.format(error=f"{type(err).__name__}: {err}"))
            with self._chat_lock:
                chat.log.append({"role": "error", "text": str(failed)})
                raise ApiError(failed.status, str(failed), **{**failed.extra, "chat": self._changed(chat)}) from err

    def _queued_refused(self, chat, texts, err):
        """Keep the queued `texts` whose turn `start_turn` refused: a refusal carrying the `chat` logged them and its error already, any other
        -- refused ahead of them -- logs them now, under the error saying they were not sent."""
        if "chat" in err.extra:
            return
        with self._chat_lock:
            chat.log += [{"role": "user", "text": text} for text in texts]
            chat.log.append({"role": "error", "text": f"the queued message was not sent: {err}"})
            self._bump()

    def _begin_turn(self, chat, data, text, parent, new, at):
        """Prepare and start the turn of `chat` whose messages its log holds from index `at` on -- `new` where nothing was logged ahead of
        them -- the notices heading them inserted at `at`; -> `{"turn": "<UID>:<n>", "chat": …}`."""
        uid = chat.uid
        table, defaults = self.mode_table(), self.chat_defaults()  # read outside the lock: a connector may answer slowly
        item = self._load().get(uid)
        current = item.description.strip() if item else None
        with self._chat_lock:
            if chat.running:  # another start won the race meanwhile
                raise ApiError(409, f"a turn of {uid} is running ({chat.turn.id})")
            if data.get("fresh"):
                self._advanced_off(chat, table)
            if chat.started is None:
                chat.started = time.time()
            chat.setup.update({key: data[key] for key in SETUP_KEYS if key in data})
            if chat.session and chat.session_connector not in (None, chat.setup.get("connector")):
                chat.session = chat.session_connector = None  # handover: the new connector knows nothing of the old one's session, so the kept messages head its own
            problems = []
            if new and self.defaults_notice:  # the new-chat setup of the settings failed its check and was reset: the chat it starts says so
                problems.append(self.defaults_notice)
                self.defaults_notice = None
            if "modes" in chat.setup and not self.valid_modes(chat.setup["modes"], table):
                problems.append(self.modes_problem(chat.setup["modes"], table))
                chat.setup["modes"] = defaults["modes"]
            reset_note = MODES_RESET.format(why="; ".join(problems), modes=", ".join(chat.setup.get("modes") or ()) or "none") if problems else None
            replayed = None if data.get("retry") else self._replay(chat)  # no size ends a session: it shrinks by the verdicts brought in alone
            if replayed and replayed[0] == "forked":  # the turns since go with this message as their history, the block carrying their stubs
                text = f"{replayed[2]}\n\n{text}"
                pruning.take_stubs(chat.prune)
            if chat.session is None and not new:  # the conversation's next session: the verdicts that waited and the switches set by hand apply
                pruning.new_session(chat.prune)
                pruning.take_stubs(chat.prune)  # the head of the new session holds every stub in the place of what was cut
            kept, head = chat.kept(at), [] if chat.session else chat.head(at)
            history = head[:-1] if data.get("retry") else head
            changed = chat.statement is not None and current is not None and current != chat.statement
            heads = []  # the notices heading this turn's messages in the log
            if reset_note:
                heads.append({"role": "user", "text": reset_note, "notice": True})
                text = f"{reset_note}\n\n{text}"
            note = STATEMENT_NOTE.format(uid=uid, statement=current) if (at or heads) and not data.get("retry") and current and (data.get("statement") or changed) else None
            if note:
                heads.append({"role": "user", "text": note, "statement": True})
                text = note if data.get("statement") else f"{note}\n\n{text}"
            elif data.get("statement") and not data.get("retry"):
                text = current or text
            chat.log[at:at] = heads
            if current is not None:
                chat.statement = current
            turn = chat.next_turn(chat.setup.get("connector"), self._notify, parent)
            if replayed:
                how = {"replayed": REPLAYED, "rewritten": REWRITTEN}.get(replayed[0], FORKED)
                turn.add_step({"kind": "context", "text": how.format(turn=replayed[1]), "at": turn.elapsed()})
            sent = "".join(chat.reports) + text if chat.session else text  # without a session the kept history carries the reports
            pruning.message_sent(chat.prune, int(turn.id.rpartition(":")[2]))  # a prune verdict on an earlier turn arriving now is late
            sent = pruning.carry(sent, pruning.take_stubs(chat.prune))
            reports, chat.reports = chat.reports, []
            origin, asked = matching.turn_origin(data, parent), str(data.get("text") or "")
            exchange = {"uid": uid, "text": sent, "session": chat.session, "history": history, "keep": chat.keep, "retry": bool(data.get("retry")), **chat.setup}
            started = self._changed(chat)

        def run():
            waiting, name = [], None
            try:
                name = self._match(uid, asked, kept) if matching.matched(origin) else None
                outcome = (self.run_agent(name, {"uid": uid, "text": asked, "modes": self._cover(turn, name, list(exchange.get("modes") or ()))}, turn)
                           if name else self.chat(exchange, turn))
            except ApiError as err:
                outcome = {"error": str(err), "status": err.status, **err.extra}
            except Exception as err:
                outcome = {"error": INTERRUPTED.format(error=f"{type(err).__name__}: {err}"), "status": 500}
            with self._chat_lock:
                try:
                    if chat.turn is turn:
                        if outcome.get("session") and not name:  # a matched agent's session is its own, never the chat's
                            chat.session, chat.session_connector = outcome["session"], turn.connector
                        role = "ai" if "error" not in outcome else "stopped" if turn.stopped else "error"
                        if name and role == "ai":  # the matched exchange heads the next message the chat's session reads
                            chat.reports = [*reports, *chat.reports, matching.matched_report(name, asked, told(outcome))]
                        chat.log.append({"role": role, "text": outcome.get("error", outcome.get("reply")), **({"matched": name} if name else {}),
                                         **({"applied": outcome["applied"]} if outcome.get("applied") else {}),
                                         **({"turn": int(turn.id.rpartition(":")[2]), "time": time.time(), "steps": list(turn.steps)} if turn.steps else {})})
                        self._mirror(turn, chat.uid)
                        if role == "ai" and not name:  # an off-context agent's turn is never pruned
                            self._prune_turn(chat, turn, outcome)
                        self._bump()
                finally:
                    turn.finish(outcome)
                    if chat.turn is turn:
                        waiting, chat.queue = chat.queue, []
            if waiting:  # what the user queued and the turn did not take goes now, as the next turn of the same session
                try:
                    self.start_turn({**chat.setup, "uid": chat.uid, "text": "\n\n".join(m["text"] for m in waiting), "queued": [m["text"] for m in waiting]})
                except ApiError as err:
                    self._queued_refused(chat, [m["text"] for m in waiting], err)

        turn.thread = threading.Thread(target=run, daemon=True)
        turn.thread.start()
        return {"turn": turn.id, "chat": started}

    def _mirror(self, turn, anchor):
        """The report of every subagent the connector ran on an item -- not the anchor, not a delegated child -- as an agent message of
        that item's chat, its transcript as the message's steps."""
        delegated = {child.id.rpartition(":")[0] for child in turn.children}
        reported = [step for step in agent_steps(turn.steps, delegated) if step.get("uid") not in (None, anchor) and step.get("report") is not None]
        items = self._load() if reported else {}
        for step in reported:
            if step["uid"] in items:
                self._chat(step["uid"]).log.append({"role": "ai", "agent": turn.id, "prompt": step.get("prompt") or "", "text": step["report"],
                                                    "steps": list(step.get("steps") or ())})

    def _rename(self, items, anchor, call, turn):
        """Apply a rename call, refused while the item's chat runs a turn other than `turn`; the item's chat and its latest turn follow
        it to the new UID. -> the line reporting it."""
        uid = synthetic.call_target(anchor, call)
        with self._chat_lock:
            chat = self.chats.get(uid)
            if chat and chat.running and chat.turn is not turn:
                raise ApiError(409, f"a turn of {uid} is running ({chat.turn.id})")
            line = _call(lambda: synthetic.apply_call(items, anchor, call, syngate_dir=self.syngate_dir))
            if chat:
                chat.uid = call["new_uid"]
                self.chats[chat.uid] = self.chats.pop(uid)
                if chat.turn:
                    chat.turn.id = f"{chat.uid}:{chat.turn.id.rpartition(':')[2]}"
                self._bump()
            return line

    def hold(self, turn, asked, offer=None):
        """The user's answer to what the held `turn` asks: its chat blocked on `asked`, the turn staying the chat's turn, until `release`
        answers it -- no timeout; a stop meanwhile raises the turn's stop. The `offer` -- an asked recommendation with the behaviour in force, or
        the `review` of a security scan's findings -- is what the page shows as the recommendation message or the context review while the turn is held."""
        chat = self.chats.get(turn.id.rpartition(":")[0])
        with turn.cond:
            at = next((index for index, origin in enumerate(turn.origins) if origin is turn.batch), None) if turn.batch is not None else None
            if offer is not None and "review" not in offer and at is not None:
                offer = {**offer, "step": at}  # the batch whose first call waiting is the one held: the page shows the recommendation under it
            turn.held, turn.offer, turn.answer = asked, offer, None
        with self._chat_lock:
            chat.asked = asked
            self._bump(settled=False)
        try:
            with turn.cond:
                turn.cond.wait_for(lambda: turn.answer is not None or turn.stopped)
                if turn.answer is None:
                    raise ApiError(409, "turn stopped")
                return turn.answer
        finally:
            with turn.cond:
                turn.held = turn.offer = None
            with self._chat_lock:
                if chat.asked == asked:  # the blocking alert standing meanwhile stands over the chat again, never lifted by the answer
                    chat.asked = self.services_asked
                self._bump(settled=False)

    def _scan_hold(self, turn, call=None, recommendation=None):
        """Scan the external text the session of `turn` took since its last scan -- the results of its web fetch, web search and WebSurf steps --
        before the altering `call` is applied or the `recommendation` applied or asked: a step of the log when nothing is found, else the turn
        held on the alert until the user settled every finding -- `release` answering `accept`, `drop` or a list of them, one per finding --
        the accepted ones saved for the user. -> None for the call to go on, else the refusal the model reads."""
        chat = self.chats.get(turn.id.rpartition(":")[0])
        if chat is None:
            return None
        taken = turn.__dict__.setdefault("scan_taken", set())
        sources = turn.__dict__.setdefault("scan_sources", {})  # the external text of this turn -> the indexes of the steps that brought it
        with turn.cond:
            steps = list(enumerate(turn.steps))
        for index, step in steps:
            if index not in taken and step.get("kind") == "tool" and security.is_external(step.get("name")) and step.get("result") is not None:
                taken.add(index)
                chat.scan.take(str(step["result"]))
                sources.setdefault(str(step["result"]), []).append(index)
        texts = security.gate(chat.scan, call, recommendation)
        if not texts:
            return None
        judge = (lambda text: self.run_verdict("scan", text)) if synthetic.agent_locator(self.settings("orchestrator"), "scan") else None
        findings = security.scan(texts, judge, security.load_accepted(self.findings_home), self.scan_verdicts)
        chat.scan.scanned()
        line = security.scan_line(findings)
        turn.add_step({"kind": "tool", "name": "security scan", "input": {"texts": len(texts)}, "result": line, "findings": findings, "seconds": 0,
                       "at": turn.elapsed()})
        while findings:
            answer = self.hold(turn, line, {"review": security.review(texts, findings)})
            answers = answer if isinstance(answer, list) else [answer] * len(findings)
            verdict, refusal = security.settle(findings, answers)
            if verdict is None:
                continue
            for finding, given in zip(findings, answers):
                if given == "accept":
                    security.accept(finding, home=self.findings_home)
            if verdict == "refuse":  # the dropped results stay in the log, marked, and the conversation goes on in a new session without them
                dropped = {index for finding, given in zip(findings, answers) if given == "drop" for index in sources.get(texts[finding["index"]], ())}
                with turn.cond:
                    for index in dropped:
                        turn.steps[index] = {**turn.steps[index], "dropped": True}
                turn.changed()
                turn.scan_dropped = True
            return refusal
        return None

    def release(self, key, answer):
        """Answer the held turn `<UID>:<n>`, which goes on with `answer`; a turn not held refuses it."""
        turn = self._turn(key)
        with turn.cond:
            if turn.held is None or turn.outcome is not None:
                raise ApiError(409, f"turn {key} is not held")
            turn.answer = answer
            turn.cond.notify_all()
        return {"ok": True}

    def alert_cleared(self):
        """Every role answers again: the chats a blocking alert stood over without a turn are unblocked, each sending the messages queued
        under the alert by themselves, as one turn."""
        with self._chat_lock:
            freed = [chat for chat in self.chats.values() if not chat.running and chat.asked is not None]
            sends = []
            for chat in freed:
                chat.asked = None
                if chat.queue:
                    sends.append((chat, [m["text"] for m in chat.queue]))
                    chat.queue = []
            if freed:
                self._bump()
        for chat, texts in sends:
            try:
                self.start_turn({**chat.setup, "uid": chat.uid, "text": "\n\n".join(texts), "queued": texts})
            except ApiError as err:
                self._queued_refused(chat, texts, err)

    def _turn(self, key):
        """The turn `<UID>:<n>` addresses: the latest of its item's chat, readable until the next one starts."""
        chat = self.chats.get(key.rpartition(":")[0])
        turn = chat.turn if chat else None
        if turn is None or turn.id != key:
            raise ApiError(404, f"no such turn {key}")
        return turn

    def turn_snapshot(self, key, wait=0):
        """The turn's state, awaited up to `wait` seconds; its outcome is also the last message of its chat."""
        return self._turn(key).snapshot(wait)

    def stop_turn(self, key, withdraw=True):
        """End a running turn the instant the stop lands: its gate closes, so nothing of it is applied past this mark; the turns it
        delegated are stopped the same way, the test run it awaits is cancelled, the shell commands it runs are killed with their
        process groups and its connector's live process is interrupted;
        the exchange then reports as stopped. A stop the user pressed `withdraw`s the messages queued meanwhile, handing their texts
        back -- `unqueued` -- rather than sending them; the stop of a send-now keeps them for the next turn."""
        turn, unqueued = self._turn(key), []
        if withdraw:
            with self._chat_lock:
                chat = self.chats.get(key.rpartition(":")[0])
                if chat and chat.queue:
                    unqueued, chat.queue = [m["text"] for m in chat.queue], []
                    self._bump()
        with turn.cond:
            turn.stopped = True
            turn.cond.notify_all()
            procs = list(turn.procs)
        for proc in procs:
            kill_group(proc)
        for child in turn.children:
            if child.outcome is None and not child.stopped:
                self.stop_turn(child.id, withdraw=False)
        if turn.job is not None and turn.job is self.jobs.current and turn.job.returncode is None:
            threading.Thread(target=self.jobs.cancel, daemon=True).start()
        interrupt = getattr(self.connectors.get(turn.connector), "interrupt", None)
        if interrupt and turn.thread:
            interrupt(turn.thread.ident)
        return {"ok": True, **({"unqueued": unqueued} if unqueued else {})}

    def chat(self, data, turn=None):
        """One exchange anchored at `uid`: the item's seed context plus the user's text go to the chosen connector.
        A plain answer comes back as the reply; an answer of tool calls is applied to the tree -- its test calls joined
        into one awaited run through the page's runner after the rest, its agent calls then run as parallel turns of their items' chats
        -- and the results of every call, the changing ones included, go back into the same session for the next answer, until a text answer ends the turn.
        A refused call ends its batch and goes back the same way, with the results of the calls applied before it, for the next
        answer to correct it or to explain. The reply is the AI's own text alone: what was applied, ran or was reported is in the steps,
        and goes as `applied` -- each repeated line once, with its count -- to where a model reads the outcome without the log (`told`).
        `history` is the kept part of an exchange whose session was dropped: it travels with the text of the first round.
        A `turn` stopped while a round is out ends the exchange there, what was applied so far staying applied.
        A rename carries the item's chat to the new UID, and the exchange with it when the item is the anchor.
        The `tree` mode is the harness's own: without it the text is headed by `TREE_OFF`, the tree calls of a reply are refused and the
        connector never sees the mode. The `patch` mode is the same for the project's files: without it a patch call is refused. A git call runs whatever the modes, through the git tool's guard, and comes back like a query's result.
        A websurf call passes the WebSurf guard and goes to the attached browser, its answer coming back like a query's result, a screenshot
        as an image of the next prompt; its `fill` and `mouse` need the `websurf` mode, the harness's own Interactive WebSurf switch, and
        its `wait` is answered by the harness. Once the turn has surfed, every next prompt also carries the page events since the previous one,
        and the turn runs up to `surf_rounds` rounds in place of the read loop's `QUERY_ROUNDS`, told the rounds left once few remain.
        The steps of every round and the lines of every applied batch are recorded in the `turn` as they happen."""
        uid, text, session, applied, calls = data.get("uid"), str(data.get("text") or ""), data.get("session"), [], []
        message, keep = text, data["keep"] if isinstance(data.get("keep"), dict) else {}  # the message the files are measured for, the session's kept start
        history = [message for message in (data.get("history") or ()) if isinstance(message, dict)]
        agent, known, connector, model, effort = None, synthetic.CALLS, data.get("connector"), data.get("model"), data.get("effort")
        if data.get("agent_name"):
            agent, route = self.agent_of(str(data["agent_name"]))
            known, connector, model, effort = synthetic.agent_calls(agent, self.library), route["connection"], route["model"], route["effort"]
        offers = {mode["id"] for mode in getattr(self.sync_connections().get(connector), "settings", lambda: {})().get("modes", ())}
        modes = [mode for mode in data.get("modes") or () if mode in HARNESS_MODES or mode in offers]  # a stored mode the connector dropped is not sent
        tree, patch, interactive = "tree" in modes, "patch" in modes, "websurf" in modes
        events, images, rounds = websurf.watch(self.websurf), [], self.surf_rounds()
        if not tree and text.strip():
            text = TREE_OFF + "\n" + text
        halted = lambda: turn is not None and turn.stopped
        fuse, stalled, closed, last, repeats = self.turn_rounds(), False, False, None, 0
        changes, handover, restarted = 0, None, False  # the setup calls of this message; the first text and the start of the session an accepted model takes the turn over in
        bound = lambda: rounds if events.surfed else fuse
        change = Change(self.root)  # what the turn changed, for the report a delegating turn receives
        applied_lines = lambda lines: {**({"applied": tallied(lines)} if lines else {}), **({"changed": view} if (view := change.view()) else {})}

        def delivered(text):
            """The next prompt with the messages the user queued meanwhile, taken from the turn's chat and recorded as a step in place."""
            if turn is None:
                return text
            with self._chat_lock:
                chat = self.chats.get(turn.id.rpartition(":")[0])
                waiting = chat.queue if chat and chat.turn is turn else []
                if waiting:
                    chat.queue = []
            for message in waiting:
                turn.add_step({"kind": "user", "text": message["text"], "at": turn.elapsed()})
            return text + QUEUED_NOTE.format(text="\n\n".join(m["text"] for m in waiting)) if waiting else text

        def batch_step(lines, batch=(), inputs=(), final=True):
            """Announce the calls step of the batch: as the answer arrives and with every result while it runs -- the calls not answered yet its
            `pending` -- and once it is over, the calls it never ran its `skipped`; the same step each time, so its record is replaced."""
            if not turn or not (lines or turn.batch is not None or not final and batch):
                return
            answered = [*inputs, *[None] * (len(lines) - len(inputs))][:len(lines)]
            left = list(batch)
            for given in answered:
                for one in given if isinstance(given, list) else [given]:
                    if (found := next((index for index, entry in enumerate(left) if entry is one), None)) is not None:
                        del left[found]
            step = turn.batch if turn.batch is not None else {"kind": "calls", "at": turn.elapsed()}
            step.update(tools=[call.get("tool") for call in batch], lines=list(lines), inputs=answered)
            step.pop("pending", None)
            step.pop("skipped", None)
            if left:
                step["skipped" if final else "pending"] = left
            turn.batch = None if final else step
            turn.add_step(step)

        def heard(step, shift):
            """Record a step the connection announced; the calls of its answer, told ahead of its return, open the batch's step at once."""
            if step.get("kind") == "answer":  # no step of its own: a `calls` step a connection announces is one it ran itself
                batch_step((), [call for call in step.get("calls") or () if isinstance(call, dict)], final=False)
            else:
                turn.add_step(step, shift)

        def stopped(lines=(), batch=(), shown=(), inputs=()):
            batch_step(lines, batch or (turn.batch or {}).get("pending", ()) if turn else batch, inputs)  # calls announced and never run stay as skipped
            return ApiError(409, "turn stopped", session=session, **applied_lines([*applied, *shown]))

        for done in itertools.count():
            closing = stalled or done >= bound()
            if closing and closed:  # the closing prompt was answered with calls, or malformed
                out = synthetic.ROUNDS_OUT.format(rounds=bound()) if events.surfed else "answer refused: the exchange kept querying"
                raise ApiError(422, out, session=session, **applied_lines(applied))
            if closing:  # the turn is not failed at once: it is asked for its report
                closed, text, why = True, text + synthetic.TURN_CLOSING, synthetic.CLOSED_STALL if stalled else synthetic.CLOSED_FUSE
            on_step = (lambda step, shift=turn.elapsed(): heard(step, shift)) if turn else None
            context, text = self._session_context(connector, uid, message, text, session, keep, turn, data.get("retry"), done == 0 or restarted, agent)
            restarted = False
            try:
                reply, session = synthetic.query(self.sync_connections(), self._load(), uid, text, connector, model,
                                                 effort, agent=agent, modes=[mode for mode in modes if mode not in HARNESS_MODES], session=session,
                                                 history=history, root=self.root, on_step=on_step, stopped=halted if turn else None, library=self.library,
                                                 images=images, context=context)
                images = []
                if turn:
                    turn.rounds += 1
            except synthetic.query_error as err:
                raise ApiError(400, str(err)) from None
            except synthetic.connection_error as err:
                if halted():
                    raise stopped() from None
                batch_step(())  # calls announced by an answer that never came
                raise ApiError(502, str(err)) from None
            if halted():
                raise stopped()
            try:
                kind, payload = synthetic.parse_reply(reply, known)
            except synthetic.protocol_error as err:
                refusal = f"answer refused: {err}"  # the AI hears it as its next prompt and answers again, within the rounds of the turn
                batch_step([refusal], inputs=[reply])
                applied.append(f"- {refusal}")
                text = delivered(synthetic.ANSWER_REFUSED.format(error=err))
                continue
            if kind != "chat" and closed:  # the calls of a closing answer are not run
                out = synthetic.ROUNDS_OUT.format(rounds=bound()) if events.surfed else "answer refused: the exchange kept querying"
                raise ApiError(422, out, session=session, **applied_lines(applied))
            if kind == "chat":
                batch_step(())  # calls announced by an answer the connection then replaced
                return {"ok": True, "reply": synthetic.TURN_CLOSED.format(why=why) + payload if closed else payload, **applied_lines(applied), "session": session, **({"calls": calls} if calls else {})}
            items, results, shown, refusal, detail, inputs, refused = self._load(), [], [], None, "", [], None
            named = lambda call: synthetic.call_target(uid, call)
            denied = lambda line, err: f"- {line} refused: {err}"
            runs = [call for call in payload if synthetic.is_run(call)]
            delegations = [call for call in payload if synthetic.is_delegation(call)]
            for call in payload:
                batch_step(results, payload, inputs, final=False)  # the calls answered so far, then those waiting
                if synthetic.is_run(call) or synthetic.is_delegation(call):
                    continue
                if halted():
                    raise stopped(results, payload, shown, inputs)
                held = self._scan_hold(turn, call) if turn is not None and security.is_altering(call) else None
                if held:
                    refusal, refused = denied(call["tool"], ApiError(403, held)), call
                    if turn.__dict__.pop("scan_dropped", False):
                        session = None  # the drop session: composed anew, without the dropped result
                    break
                if synthetic.is_git(call):
                    try:
                        line, records = self._git(call)
                    except ApiError as err:
                        refusal, refused = denied(git_label(call), err), call
                        break
                    results.append(line)
                    inputs.append(call)
                    if records:
                        shown.append(line)
                    continue
                if synthetic.is_grep(call):
                    try:
                        results.append(self._grep(call))
                    except ApiError as err:
                        refusal, refused = denied(f"grep {call['command']}", err), call
                        break
                    inputs.append(call)
                    continue
                if synthetic.is_patch(call):
                    if not patch:
                        granted = self._permit(turn, agent, "patch", call, modes, shown)
                        if granted is not True:
                            refusal, refused = denied(call["tool"], ApiError(403, granted or PATCH_REFUSAL)), call
                            break
                        patch = True
                    try:
                        touched = change.paths(call)
                        line = self._patch(call)
                        change.note(touched)
                        synthetic.refresh_keep(keep, self.root, tiering.patched_paths(call))
                    except ApiError as err:
                        refusal, refused = denied(call["tool"], err), call
                        break
                    results.append(line)
                    inputs.append(call)
                    shown.append(line)
                    continue
                if synthetic.is_file(call):
                    label = f"{call['tool']} {call.get('path') or '.'}"
                    try:
                        results.append(self._file(call))
                        self._miss(uid, keep, call)
                    except ApiError as err:
                        refusal, refused = denied(label, err), call
                        break
                    inputs.append(call)
                    continue
                if synthetic.is_log(call):
                    label = loglib.label(call)
                    try:
                        results.append(self._log(uid, call))
                    except ApiError as err:
                        refusal, refused = denied(label, err), call
                        break
                    inputs.append(call)
                    continue
                if synthetic.is_setup(call):
                    label, switch = "models" if call["tool"] == "models" else f"setup {call['model']}", None
                    try:
                        if call["tool"] == "models":
                            results.append(self._models(connector, model))
                        else:
                            line, told_line, switch = self._settle_setup(call, turn, (connector, model, effort), agent, len(payload) == 1, changes)
                            changes += 1
                            results.append(line)
                            shown.append(told_line)
                    except ApiError as err:
                        refusal, refused = denied(label, err), call
                        break
                    inputs.append(call)
                    if switch:  # the accepted model takes the turn over in a new session of its own
                        connector, model, effort = switch
                        session, restarted = None, True
                        offers = {mode["id"] for mode in getattr(self.sync_connections().get(connector), "settings", lambda: {})().get("modes", ())}
                        modes = [mode for mode in modes if mode in HARNESS_MODES or mode in offers]
                        if turn:
                            turn.connector = connector
                        rec = recommend.model_recommendation(switch[0], switch[1], call["reason"], switch[2])
                        handover = lambda done_lines, rec=rec: ("" if tree else TREE_OFF + "\n") + recommend.handover_text(message, done_lines, rec)
                    continue
                if synthetic.is_shell(call):
                    if SHELL_MODE not in modes:
                        granted = self._permit(turn, agent, SHELL_MODE, call, modes, shown) if SHELL_MODE in offers else None
                        if granted is not True:
                            refusal, refused = denied(f"shell {call['command']}", ApiError(403, granted or SHELL_REFUSAL)), call
                            break
                    try:
                        line = self._shell(call, turn)
                    except ApiError as err:
                        refusal, refused = denied(f"shell {call['command']}", err), call
                        break
                    results.append(line)
                    inputs.append(call)
                    shown.append(line)
                    continue
                if synthetic.is_surf(call):
                    if call.get("action") in websurf.INTERACTIVE and not interactive:
                        granted = self._permit(turn, agent, "websurf", call, modes, shown)
                        if isinstance(granted, str):
                            refusal, refused = denied(websurf.label(call), ApiError(403, granted)), call
                            break
                        interactive = granted is True
                    try:
                        line, shot = self._surf(call, interactive, turn, halted, events)
                    except ApiError as err:
                        refusal, detail, refused = denied(websurf.label(call), err), err.extra.get("detail", ""), call  # the model reads the detail, the chat the line
                        break
                    results.append(line)
                    inputs.append(call)
                    images += shot
                    continue
                if call["tool"] in synthetic.TOOLS and not tree:
                    granted = self._permit(turn, agent, "tree", call, modes, shown)
                    if granted is not True:
                        refusal, refused = denied(f"{call['tool']} {named(call)}", ApiError(403, granted or TREE_REFUSAL)), call
                        break
                    tree = True
                renamed = named(call) if call["tool"] == "rename" else None
                try:
                    results.append(self._rename(items, uid, call, turn) if renamed else _call(
                        lambda: synthetic.apply_call(items, uid, call, syngate_dir=self.syngate_dir, library=self.library,
                                                     measure=lambda target, purpose: self._measure(items, target, purpose or message).heavy)))
                    if call["tool"] in tiering.TREE_EDITS:
                        synthetic.absorb(keep, items, [named(call), call.get("new_uid")])  # the session's own edits are no news to it
                        change.item(call, named(call))
                    inputs.append(call)
                except ApiError as err:
                    refusal, refused = denied(f"{call['tool']} {named(call)}", err), call
                    break
                if renamed == uid:
                    uid = call["new_uid"]
                if not synthetic.is_query(call):
                    shown.append(results[-1])
            if runs and refusal is None:
                if halted():
                    raise stopped(results, payload, shown, inputs)
                batch_step(results, payload, inputs, final=False)
                try:
                    results.append(self._run_calls(items, [(named(call), call.get("name") or None) for call in runs], turn))
                    inputs.append(runs[0] if len(runs) == 1 else runs)
                    shown.append(results[-1])
                except ApiError as err:
                    refusal, refused = denied(f"test {' '.join(dict.fromkeys(named(call) for call in runs))}", err), runs[0] if len(runs) == 1 else runs
            if delegations and refusal is None:
                batch_step(results, payload, inputs, final=False)
                reported = len(results)
                delegated = self._delegate(items, uid, data, delegations, turn, results, change)
                shown += results[reported:]
                by_line = lambda line: next((call for call in delegations if line.startswith(f"- agent {named(call)}:") or line == f"agent {named(call)}"), None)
                inputs += [by_line(line) for line in results[reported:]]
                if delegated:
                    err, line = delegated
                    refusal, refused = denied(line, err), by_line(line)
            if halted():
                raise stopped(results, payload, shown, inputs)
            if refusal:
                results.append(refusal + detail)
                inputs.append(refused)
                shown.append(refusal)
            batch_step(results, payload, inputs)
            applied += shown
            calls += payload
            mark = json.dumps([payload, results], sort_keys=True, default=str)
            repeats, last = (repeats + 1 if mark == last else 0), mark
            stalled = repeats >= 2
            text = delivered(synthetic.RESULTS_PREAMBLE + "\n".join(results) + websurf.events_text(events.take(), *self.surf_lists())
                             + synthetic.rounds_left(bound() - done - 1) + (synthetic.STALL_NUDGE if repeats == 1 else ""))
            if handover:
                text, handover = delivered(handover(applied)), None

    def agent_of(self, name):
        """(agent, locator) of the agent `name` of the library and the model locator -- connection, model, effort -- its role is served by now:
        the one in use of `agents.<name>`, else of `agents.default`; an unknown agent or one given no model locator is an `ApiError`."""
        agent = synthetic.load_agents(self.library).get(name)
        if agent is None:
            raise ApiError(404, f"unknown agent '{name}'")
        section = self.settings("orchestrator")
        locator = synthetic.agent_locator(section, name)
        if locator is None:
            raise ApiError(503, f"no model locator for the agent {name}: set `orchestrator.agents.default` or `orchestrator.agents.{name}` in the server settings")
        role = services.agent_role(section, name)
        active = self.health.locator(role) or locator
        while True:  # a `LOADED` locator naming no model now fails over as a call does
            try:
                active = services.resolve_locator(self.sync_connections(), active)
                break
            except services.service_error as err:
                active = self.health.failed(role, err)
                if active is None:
                    raise ApiError(503, f"no model for the agent {name}: {err}") from None
        return agent, {"connection": active["connection"], "model": active["model"], "effort": active.get("effort")}

    def _match(self, uid, message, history):
        """The off-context agent a user's `message` to the chat of `uid` is handed to -- the gate over the embedding the `orchestrator` settings route
        at their `match_threshold`, the match agent judging over the conversation's `history` on its `agents.match` model locators, else the cheap
        `matching.MATCH_LOCATOR` -- None when it stays with the DAG: no embedding, no match agent and a model service that fails all leave it there."""
        section = self.settings("orchestrator")
        embed = self.rankers(section)[0] if message.strip() else None
        if embed is None:  # checked before the prompt files are read: a server with no embedding pays nothing for the match
            return None
        agents = synthetic.load_agents(self.library)
        if "match" not in agents:
            return None
        own = services.locators(section["agents"].get("match") if isinstance(section.get("agents"), dict) else None)
        threshold = section.get("match_threshold")
        threshold = float(threshold) if isinstance(threshold, (int, float)) and not isinstance(threshold, bool) else matching.MATCH_THRESHOLD
        def judge(agent, data):
            ask = lambda locator: synthetic.verdict(self.sync_connections(), agent, data, locator["connection"], locator["model"], locator.get("effort"),
                                                    library=self.library)
            return self.health.serve("agents.match", ask, errors=(synthetic.connection_error,)) if own else ask(matching.MATCH_LOCATOR)
        try:
            return matching.match(agents["match"], self._load(), agents, message, history, embed, judge, threshold=threshold)
        except (services.service_error, ValueError, synthetic.connection_error, synthetic.query_error):
            return None

    def _cover(self, turn, name, modes):
        """The `modes` of the starting chat once it covers the lists of the off-context agent `name`: every tool and skill its lists name offered by the
        library at hand, and every permission its tools need (`AGENT_TOOL_MODES`) on and available to the agent's route -- a permission the chat has
        off asked in the chat of the starting `turn` as the recommendation to switch it on, a granted one on for the chat from then on. An agent that
        names a verdict schema needs nothing. A tool, skill or permission the chat lacks, or one denied, is an `ApiError` forbidding the whole run."""
        agent, route = self.agent_of(name)
        missing = [entry for entry in (*agent.tools, *agent.skills) if entry not in synthetic.agent_library(agent, self.library)]
        if missing:
            raise ApiError(403, f"the agent {name} is forbidden here: {', '.join(missing)} is not offered by this chat")
        offers = {mode["id"] for mode in getattr(self.sync_connections().get(route["connection"]), "settings", lambda: {})().get("modes", ())}
        covered, shown = list(modes), []
        for mode in dict.fromkeys(AGENT_TOOL_MODES[tool] for tool in agent.tools if tool in AGENT_TOOL_MODES):
            if mode not in HARNESS_MODES and mode not in offers:
                raise ApiError(403, f"the agent {name} is forbidden here: its tools need {mode}, which this chat's connection does not offer")
            if mode in covered:
                continue
            granted = self._permit(turn, None, mode, {"tool": "agent"}, covered, shown, reason=f"the agent {name} needs it")
            if granted is not True:
                raise ApiError(403, f"the agent {name} is forbidden here: {granted or f'its tools need {mode}, which is off for this chat'}")
        if turn is not None:
            for line in shown:
                turn.add_step({"kind": "context", "text": line, "at": turn.elapsed()})
        return covered

    def run_agent(self, name, data, turn=None):
        """Run the off-context agent `name` as an exchange of the chat `data` names -- its `uid`, text and permissions -- above the agent's
        prompt alone, on the connection and model its route names: only the calls of the tools its `tools` list names are applied, each
        as far as the permissions of the starting chat allow. -> the exchange's outcome, as `chat` gives it."""
        return self.chat({**data, "agent_name": name}, turn)

    def _replay(self, chat):
        """Bring a change of the pruning of the chat's session -- a verdict on a turn ahead of the tail, a switch set by hand -- into it before
        its next message, under the chats lock: the turns from the earliest changed one on, each with its span, are handed to the connection,
        which rewrites its stored messages, replays its transcript into a new one or rolls it back forked, where the pruning worth has it -- a
        switch set by hand asking no worth -- the pruning then settled. -> (how, the earliest changed turn, the replayed history block), None
        where the change waits or there is none."""
        connection = self.sync_connections().get(chat.setup.get("connector"))
        number = pruning.changed_turn(chat.prune) if chat.session else None
        spans = chat.prune.get("spans") or {}
        if number is None or str(number) not in spans or not callable(getattr(connection, "replay_session", None)):
            return None
        settled, was, turns = pruning.pruned_next(chat.prune), chat.prune["applied"], []
        for found in sorted((int(key) for key in spans if int(key) >= number)):
            record = chat.turn_record(found)
            if record is not None:
                turns.append({**record, "span": spans[str(found)],
                              "verdicts": {key: verdict for key, verdict in settled.items() if key.startswith(f"{found}:")},
                              "was": {key: verdict for key, verdict in was.items() if key.startswith(f"{found}:")}})
        if not turns:
            return None
        block = cc_transcript.history_block(turns)
        try:
            outcome = connection.replay_session(chat.session, turns, block, **({"force": True} if chat.prune["switches"] else {}))
        except (synthetic.connection_error, OSError, ValueError) as err:
            print(f"assassin: session {chat.session} not replayed: {err}", file=sys.stderr)
            return None
        if not outcome:
            return None
        if outcome[0] in ("replayed", "rewritten"):
            chat.session = outcome[1]
        pruning.settle(chat.prune)
        return outcome[0], number, block

    def _prune_turn(self, chat, turn, outcome):
        """Prune the ended `turn` of `chat`, its message logged, under the chats lock: its steps by rule at once and its AI texts by the prune
        agent on a thread of its own where the settings route one. A session its connection lets the harness rewrite has the verdicts cut out
        of it in place; any other is owned, its verdicts waiting for its connection's replay under the pruning worth."""
        number, steps, session, state = int(turn.id.rpartition(":")[2]), list(turn.steps), chat.session, chat.prune
        connection = self.sync_connections().get(turn.connector)
        owned = session is None or not callable(getattr(connection, "rewrite_session", None))
        keep = chat.keep or {}
        held = [rel for rel in keep.get("hashes") or {} if rel not in (keep.get("heavy") or {})]  # the files the system prompt holds whole
        before = set(state["applied"])
        pruning.end_turn(state, number, steps, held, owned)
        pruning.note_size(state, steps)
        if session and callable(getattr(connection, "turn_span", None)):  # a transcript the connection keeps: the span the replay starts from
            try:
                pruning.note_span(state, number, connection.turn_span(session, turn.rounds))
            except (synthetic.connection_error, OSError, ValueError) as err:
                print(f"assassin: no span of turn {turn.id} in session {session}: {err}", file=sys.stderr)
        self._cut(connection, session, number, steps, {found: v for found, v in state["applied"].items() if found not in before}, turn.rounds)
        if synthetic.agent_locator(self.settings("orchestrator"), pruning.AGENT):
            args = (chat, state, number, steps, str(outcome.get("reply") or ""), owned, session, connection, turn.rounds)
            turn.pruning = threading.Thread(target=self._judge_turn, args=args, daemon=True)
            turn.pruning.start()

    def _judge_turn(self, chat, state, number, steps, reply, owned, session, connection, rounds):
        """The prune agent's verdicts on the AI texts of the ended turn `number`, delivered to the conversation that ran it: cut out of its
        session where they arrive before the next message, else waiting for the next session; a conversation ended meanwhile takes none."""
        verdicts = pruning.judge_texts(lambda data: self.run_verdict(pruning.AGENT, data), number, steps, reply)
        with self._chat_lock:
            if chat.prune is not state or not verdicts:
                return
            before = set(state["applied"])
            pruning.deliver(state, number, verdicts, owned or chat.session != session)
            self._cut(connection, session, number, steps, {found: v for found, v in state["applied"].items() if found not in before}, rounds)
            self._bump()

    @staticmethod
    def _cut(connection, session, number, steps, verdicts, rounds):
        """Cut the `verdicts` on turn `number` out of the stored `session` of a connection the harness may rewrite; one it cannot keeps all."""
        if not (verdicts and session and callable(getattr(connection, "rewrite_session", None))):
            return
        try:
            connection.rewrite_session(session, lambda messages: pruning.rewrite(messages, number, steps, verdicts, rounds))
        except (synthetic.connection_error, OSError, ValueError) as err:
            print(f"assassin: session {session} not pruned: {err}", file=sys.stderr)

    def run_verdict(self, name, data):
        """The JSON answer of the verdict agent `name` judging `data`, on the model locator its role is served by, a call failing on it made again
        on the next answering locator of the role."""
        agent, _ = self.agent_of(name)
        if not synthetic.is_verdict(agent):
            raise ApiError(400, f"the agent {name} declares no answer schema")
        ask = lambda locator: synthetic.verdict(self.sync_connections(), agent, data, locator["connection"], locator["model"], locator.get("effort"),
                                                library=self.library)
        try:
            return self.health.serve(services.agent_role(self.settings("orchestrator"), name), ask, errors=(synthetic.connection_error,))
        except synthetic.query_error as err:
            raise ApiError(400, str(err)) from None
        except (synthetic.connection_error, synthetic.protocol_error) as err:
            raise ApiError(502, str(err)) from None

    def _patch(self, call):
        """Apply the unified diff of a patch call to the project's files through the patch tool's guard, all of it or none, or the exact
        replacement of a replace call. -> the line
        telling the paths it changed; a refusal is an `ApiError` carrying git's message for the section that failed."""
        try:
            if call["tool"] == "replace":
                changed = patchlib.replace(self.root, call["path"], call["old"], call.get("new") if isinstance(call.get("new"), str) else "")
            else:
                changed = patchlib.apply(self.root, call["diff"])
        except patchlib.refused as err:
            raise ApiError(403, str(err)) from None
        return f"- {call['tool']} changed {', '.join(changed)}"

    def _file(self, call):
        """Answer a list or read call of an answer through the files tool's guard, the server settings and the stored chats out of its reach. -> the line
        telling the folder's entries or the file's lines; a refusal is an `ApiError`."""
        path = call.get("path") if isinstance(call.get("path"), str) and call["path"].strip() else "."
        try:
            if call["tool"] == "list":
                return f"- list {path}:\n{filelib.listing(self.root, path, call.get('depth'), secret=UNREADABLE)}"
            return f"- read {filelib.read(self.root, path, call.get('from'), call.get('lines'), secret=UNREADABLE)}"
        except filelib.refused as err:
            raise ApiError(403, str(err)) from None

    def _log(self, uid, call):
        """Answer a log call of an answer from the record of every chat -- `uid` the chat the turn runs in -- the turns, the parts of a turn or the
        search the call asks for, the text the user folded out and the results a security finding dropped left out of them. -> the line telling
        them; a refusal is an `ApiError`."""
        with self._chat_lock:
            chats = {key: chat.turn_entries() for key, chat in self.chats.items()}
            folded = [text for chat in self.chats.values() for text in chat.folded_texts()]
        try:
            text = loglib.read(chats, folded, call, uid)
        except loglib.refused as err:
            raise ApiError(400, str(err)) from None
        return f"- {loglib.label(call)}:\n{text}"

    def _models(self, connector, model):
        """Answer a models call: every model of every connector the page offers, the chat's own `connector` and `model` marked. -> the line
        telling them, one JSON line each."""
        return synthetic.models_report(synthetic.models_listing(self.offered(), (connector, model)))

    def _recommend(self, call, connector, model):
        """Answer a setup call: the recommendation of a model of the models listing -- the chat's own `connector` and `model` marked in it -- and of
        an effort that model lists, which changes nothing of the chat's setup. -> the line telling the recommendation; a connection, model or
        effort the listing does not hold is an `ApiError`."""
        try:
            return synthetic.recommend_setup(synthetic.models_listing(self.offered(), (connector, model)), call)
        except synthetic.setup_error as err:
            raise ApiError(400, str(err)) from None

    def _settle_setup(self, call, turn, current, agent, sole, made):
        """Settle the setup call of a turn running on `current` (connector, model, effort) -- the sole call of its answer, the first of its message,
        naming another model of the listing and never an off-context `agent`'s -- through the behaviour of the turn's chat: applied at once, or asked
        by holding the turn until `release` answers it, a denied one kept against asking it again in the conversation.
        -> (the line the model reads, the line the log shows, the (connector, model, effort) the turn goes on on or None); a refusal is an `ApiError`."""
        if agent is not None:
            raise ApiError(403, recommend.OFF_CONTEXT_REFUSED)
        if not sole:
            raise ApiError(400, recommend.SOLE_REFUSED)
        if refused := recommend.once_refusal(made):
            raise ApiError(409, refused)
        connector, model, effort = current
        if (call["connection"], call["model"]) == (connector, model) and (call.get("effort") or effort) == effort:
            raise ApiError(400, recommend.SAME_REFUSED)
        line = self._recommend(call, connector, model)
        rec = recommend.model_recommendation(call["connection"], call["model"], call["reason"], call.get("effort"))
        with self._chat_lock:
            chat = self.chats.get(turn.id.rpartition(":")[0]) if turn else None
            if chat is not None and recommend.is_denied(chat.denied, rec):
                return line + recommend.DENIED_BEFORE, line + recommend.DENIED_BEFORE, None
            chosen = chat.setup.get(recommend.BEHAVIOUR_KEY) if chat else None
        behaviour = recommend.behaviour_of(chosen, self.settings("orchestrator").get(recommend.BEHAVIOUR_KEY))
        listing = synthetic.models_listing(self.offered(), (connector, model))
        accepted = recommend.decide(behaviour, recommend.direction(listing, (connector, model), rec)) == recommend.APPLIED
        if not accepted:
            if chat is None:
                return line + recommend.UNHELD, line + recommend.UNHELD, None
            accepted, chosen = recommend.answer_of(self.hold(turn, recommend.asked_text(rec), {**rec, "behaviour": behaviour}))
            with self._chat_lock:
                if chosen:
                    chat.setup[recommend.BEHAVIOUR_KEY] = chosen
                if not accepted:
                    chat.denied = recommend.deny(chat.denied, rec)
                self._bump()
            if not accepted:
                return line + recommend.DENIED, line + recommend.DENIED, None
        switch = (rec["connection"], rec["model"], rec["effort"])
        if chat is not None:
            with self._chat_lock:
                chat.setup.update(connector=switch[0], model=switch[1], effort=switch[2])
                chat.session = chat.session_connector = None
                self._bump()
        return line, recommend.applied_line(rec), switch

    def _permit(self, turn, agent, mode, call, modes, shown, reason=None):
        """Settle the permission `mode` that alone refuses the `call` of `turn`: the call held, the external text the session took scanned first,
        then the recommendation to switch `mode` on applied at once or asked through the chat's behaviour -- a denied one kept against asking it
        again in the conversation. Granted, the mode joins the turn's `modes` and the chat's setup, an applied one leaving its line in `shown`.
        -> True for the call to be applied, the scan's refusal, or None for the call's own refusal: no turn to hold, an off-context agent, a denial."""
        chat = self.chats.get(turn.id.rpartition(":")[0]) if turn is not None and agent is None else None
        rec = recommend.permission_recommendation(mode, reason or f"the {call['tool']} call of this turn needs it")
        if chat is None or recommend.is_denied(chat.denied, rec):
            return None
        scanned = self._scan_hold(turn, recommendation=rec)
        if scanned:
            return scanned
        behaviour = recommend.behaviour_of(chat.setup.get(recommend.BEHAVIOUR_KEY), self.settings("orchestrator").get(recommend.BEHAVIOUR_KEY))
        asked = recommend.decide(behaviour, recommend.direction((), (), rec)) == recommend.ASKED
        accepted, chosen = recommend.answer_of(self.hold(turn, recommend.asked_text(rec), {**rec, "behaviour": behaviour})) if asked else (True, None)
        with self._chat_lock:
            if chosen:
                chat.setup[recommend.BEHAVIOUR_KEY] = chosen
            if accepted:
                chat.setup["modes"] = [*(chat.setup.get("modes") or ()), *(() if mode in (chat.setup.get("modes") or ()) else (mode,))]
            else:
                chat.denied = recommend.deny(chat.denied, rec)
            self._bump()
        if not accepted:
            return None
        if mode not in modes:
            modes.append(mode)
        if not asked:
            shown.append(recommend.applied_line(rec))
        return True

    def _shell(self, call, turn=None):
        """Run the command line of a shell call with `sh -c` in the project root, without stdin, within `SHELL_TIMEOUT` seconds, in a process
        group of its own the stop of the `turn` kills. -> the line telling its exit status and output, cut past `SHELL_LIMIT` characters, or
        that it timed out or was stopped; a command naming the tree is refused as an `ApiError`."""
        command = call["command"]
        if SHELL_TREE_RE.search(command):
            raise ApiError(403, SHELL_TREE)
        try:
            proc = subprocess.Popen(command, shell=True, cwd=self.root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, errors="replace", start_new_session=True)
        except OSError as err:
            raise ApiError(500, f"the shell did not start: {err}") from None
        if turn is not None:
            with turn.cond:
                turn.procs.append(proc)
                stopped = turn.stopped
            if stopped:
                kill_group(proc)
        try:
            stdout, stderr = proc.communicate(timeout=SHELL_TIMEOUT)
        except subprocess.TimeoutExpired:
            kill_group(proc)
            proc.communicate()
            return f"- shell {command}:\ntimed out after {SHELL_TIMEOUT} s"
        finally:
            if turn is not None:
                with turn.cond:
                    turn.procs.remove(proc)
        if turn is not None and turn.stopped:
            return f"- shell {command}:\nstopped with the turn"
        output = stdout + stderr
        cut = f"\n… cut at {SHELL_LIMIT} characters" if len(output) > SHELL_LIMIT else ""
        return f"- shell {command}:\n" + f"exit {proc.returncode}\n{output[:SHELL_LIMIT]}{cut}".rstrip("\n")

    def _grep(self, call):
        """Run a grep call of an answer by the program of the grep prompt the chat's library offers, through the tool's guard, the server
        settings and the stored chats out of its reach. -> the line telling its exit status and output; a refusal is an `ApiError`."""
        name = greplib.program(self.library)
        if name is None:
            raise ApiError(403, GREP_ABSENT)
        try:
            words = greplib.guard(self.root, call["command"], name, UNREADABLE)
        except greplib.refused as err:
            raise ApiError(403, str(err)) from None
        return f"- grep {call['command']}:\n{greplib.run(self.root, words)}"

    def _git(self, call):
        """Run a git call of an answer through the tool's guard. -> (the line telling its outcome, whether it records)."""
        if not self.git:
            raise ApiError(403, GIT_ABSENT)
        try:
            words, records = gitlib.guard(call["command"])
            cwd = gitlib.workdir(self.root, call["path"]) if call.get("path") is not None else self.root
        except gitlib.refused as err:
            name = (call["command"].split() or [""])[0]
            raise ApiError(403, f"{err}; {GIT_SHELL_HINT}" if name in GIT_SHELL_COMMANDS else str(err)) from None
        return f"- {git_label(call)}:\n{gitlib.run(cwd, words)}", records

    def _surf(self, call, interactive, turn=None, halted=None, events=None):
        """Send a websurf call of an answer to the attached browser once the guard passes it -- a `fill` or `mouse` only while the
        Interactive WebSurf switch is on, an `open` or `close` only while no other running turn holds the surf tab, an `open` with the
        tiling method but `browser` and, under `kwin`, its new window tiled off the turn -- or await the next page event of the turn's
        `events` watch for a `wait`; the request is a `tool` step of the `turn`: its action and target, then its outcome and the size of
        the answer. -> (the line telling the answer, the images it attaches); a refusal is an `ApiError` whose `detail` is what the AI
        reads past its message -- the page a failed answer tells."""
        if call.get("action") in websurf.INTERACTIVE and not interactive:
            raise ApiError(403, SURF_OFF)
        allow, block = self.surf_lists()
        events = events or websurf.watch(self.websurf)
        try:
            request = websurf.guard(call, allow, block)
            if self.websurf.attached is None:
                raise websurf.refused(websurf.ABSENT)
            if request["action"] in ("open", "close"):
                self.websurf.hold(turn)
        except websurf.refused as err:
            raise ApiError(403, str(err)) from None
        if request["action"] == "open" and self.tiling != "browser":
            request["tiling"] = self.tiling
        step = {"kind": "tool", "name": "websurf", "input": websurf.step_input(request), "result": None, "seconds": None, "at": turn.elapsed() if turn else 0}
        if turn:
            turn.add_step(step)
        started = time.monotonic()
        try:
            if request["action"] == "wait":
                seen = websurf.plural(events.wait(request.get("seconds"), halted), "page event")
                step.update(result=seen, size=len(seen))
                return f"- {websurf.label(request)}: {seen}", []
            answer = self.websurf.surf(request, halted)
            events.sent(answer)
            if request.get("tiling") == "kwin" and answer.result.get("ok"):
                tiling.tile_later(answer.result.get("tile"))
            step["size"] = answer.size
            told = websurf.report(request, answer.result, allow, block)
            step["result"] = websurf.summary(request, answer.result)
            return told
        except websurf.refused as err:
            step["result"] = f"refused: {err}"
            raise ApiError(403, str(err), detail=err.detail) from None
        finally:
            step["seconds"] = round(time.monotonic() - started, 2)
            if turn:
                turn.add_step(step)

    def _delegate(self, items, anchor, data, calls, turn, results, change=None):
        """Every agent call of a batch as a turn of its item's chat with the call's prompt -- the standing instruction to carry out the
        item's statement without one, a prompt past `DELEGATION_PROMPT_LIMIT` refused -- in the setup of `data` the call may override,
        all running in parallel and awaited -- a stop of the parent `turn` starts none more and stops the running ones. Each child's
        report -- its closing text and cumulative change (`delegation_report`), the latter joining the parent's `change` --
        joins `results` and its transcript the parent's steps as an agent step; a call marked `background` is answered at once
        instead and not awaited -- see `_watch`; a child switches a harness mode -- `tree`, `websurf` -- on only when the parent has it;
        -> (error, line) of the call refused, which starts none after it."""
        started, refusal = [], None
        withheld = [mode for mode in HARNESS_MODES if mode not in (data.get("modes") or ())]
        offs = []
        for call in calls:
            if call.get("name"):
                try:
                    if turn and turn.stopped:
                        raise ApiError(409, "turn stopped")
                    off = self._off_context(anchor, call, data, turn, results)
                except ApiError as err:
                    refusal = (err, f"agent {call['name']}")
                    break
                if off:
                    offs.append(off)
                continue
            child = synthetic.call_target(anchor, call)
            setup = {**{key: data[key] for key in SETUP_KEYS if key in data}, **{key: call[key] for key in ("model", "effort", "modes") if key in call},
                     **({"connector": call["connection"]} if isinstance(call.get("connection"), str) else {})}
            own = setup["modes"] if "modes" in setup else self.chats[child].setup.get("modes") if child in self.chats else ()
            if "tree" in withheld or set(own or ()) & set(withheld):
                setup["modes"] = [mode for mode in own or () if mode not in withheld]
            prompt = call.get("prompt") if isinstance(call.get("prompt"), str) and call["prompt"].strip() else synthetic.DELEGATION_TEXT.format(uid=child)
            try:
                if turn and turn.stopped:
                    raise ApiError(409, "turn stopped")
                if len(prompt) > DELEGATION_PROMPT_LIMIT and "prompt" in call:
                    raise ApiError(400, DELEGATION_RESTATED)
                if child == anchor:
                    raise ApiError(409, "the anchored item runs this turn — delegate to another item or do the work in this turn")
                if child not in items:
                    raise ApiError(404, f"unknown UID '{child}'")
                if "connection" in call:  # the subagent's setup is a pair of the models listing
                    self._recommend({"connection": setup["connector"], "model": str(setup.get("model") or ""), "effort": call.get("effort"), "reason": "subagent setup"}, None, None)
                key = self.start_turn({**setup, "uid": child, "text": prompt, "agent": turn.id if turn else anchor}, parent=turn)["turn"]
            except ApiError as err:
                refusal = (err, f"agent {child}")
                break
            step, shift, run = {"kind": "agent", "uid": child, "prompt": prompt, "report": None, "steps": [], "at": 0}, turn.elapsed() if turn else 0, self._turn(key)
            if call.get("background"):
                step["report"] = f"started in the background (turn {key})"
                results.append(f"- agent {child}: {step['report']}")
                self._watch(self._chat(anchor), run)
            else:
                started.append((run, step, shift))
            if turn:
                turn.add_step(step, shift)
                turn.children.append(run)
                if turn.stopped:
                    self.stop_turn(key)
        for child, step, shift in started:
            outcome = child.snapshot(wait=None)
            step.update(report=outcome.get("reply", outcome.get("error")), steps=outcome.get("steps", []))
            if turn:
                turn.add_step(step, shift)
            if change is not None:
                change.merge(outcome.get("changed"))
            results.append(f"- agent {step['uid']}: {delegation_report(outcome)}")
        for thread, box, step, shift in offs:
            while thread.is_alive():
                thread.join(0.2)
                if turn and turn.stopped:
                    box["turn"].stopped = True
            outcome = box["outcome"]
            step.update(report=outcome.get("reply", outcome.get("error")), steps=list(box["turn"].steps))
            if turn:
                turn.add_step(step, shift)
            if change is not None:
                change.merge(outcome.get("changed"))
            results.append(f"- agent {step['name']}: {told(outcome)}")
        return refusal

    def _off_context(self, anchor, call, data, turn, results):
        """Start the off-context agent a named agent call names, its prompt the request, as an exchange of the anchored chat above the agent's
        prompt alone on its route, with the permissions of `data` -- on a thread, under a turn of its own the parent's stop stops.
        -> (thread, box of its turn and outcome, its agent step, shift) to await; None for a `background` call, answered at once in
        `results`, its report joining the anchored chat when it ends."""
        name = str(call["name"])
        prompt = call.get("prompt") if isinstance(call.get("prompt"), str) else ""
        if not prompt.strip():
            raise ApiError(400, f"a named agent call carries the request for the agent {name} as its prompt")
        agent, route = self.agent_of(name)
        if synthetic.is_verdict(agent):
            raise ApiError(400, f"the agent {name} is a verdict agent: the harness runs it, never an agent call")
        covered = self._cover(turn, name, list(data.get("modes") or ()))  # before any turn of the agent starts: a denial forbids the whole run
        child, box = Turn(f"{anchor}:{name}", route["connection"], self._notify, parent=turn), {}
        box["turn"] = child
        exchange = {"uid": anchor, "text": prompt, "modes": covered}

        def run():
            try:
                box["outcome"] = self.run_agent(name, exchange, child)
            except ApiError as err:
                box["outcome"] = {"error": str(err), "status": err.status}
            except Exception as err:
                box["outcome"] = {"error": INTERRUPTED.format(error=f"{type(err).__name__}: {err}"), "status": 500}

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        step, shift = {"kind": "agent", "uid": None, "name": name, "prompt": prompt, "report": None, "steps": [], "at": 0}, turn.elapsed() if turn else 0
        if turn:
            turn.add_step(step, shift)
        if not call.get("background"):
            return thread, box, step, shift
        step["report"] = "started in the background"
        results.append(f"- agent {name}: {step['report']}")
        parent = self._chat(anchor)

        def report():
            thread.join()
            outcome = box["outcome"]
            with self._chat_lock:
                parent.log.append({"role": "ai", "agent_report": name, "text": outcome.get("reply", outcome.get("error")), "steps": list(child.steps)})
                parent.reports.append(f"Report of the background agent {name}:\n{told(outcome)}\n\n")
                self._bump()

        threading.Thread(target=report, daemon=True).start()
        return None

    def _watch(self, parent, child):
        """Let the `parent` chat go on without the running `child` turn: when the child ends, its report joins the parent's log as an
        agent report message -- its transcript as the message's steps -- and waits in the chat's unreported reports to head the next
        message sent to the model."""
        with self._chat_lock:
            parent.background.append(child)
            self._bump(settled=False)

        def report():
            outcome = child.snapshot(wait=None)
            uid, text = child.id.rpartition(":")[0], outcome.get("reply", outcome.get("error"))
            with self._chat_lock:
                parent.background.remove(child)
                parent.log.append({"role": "ai", "agent_report": uid, "text": text, "steps": list(child.steps)})
                parent.reports.append(f"Report of the background subagent @{uid}:\n{delegation_report(outcome)}\n\n")
                self._bump()

        threading.Thread(target=report, daemon=True).start()

    def _run_calls(self, items, addressed, turn=None):
        """Every test call of a batch -- `addressed` being (uid, binding|None) -- as one run of the page's runner, awaited and held
        by the `turn` so its stop cancels it; -> its outcome as the AI reads it back. The run records apart and its records are then folded
        into the page's, so the outcome tells of this run alone, never of a binding's record left by an earlier one."""
        targets = list(dict.fromkeys((leaf, name) for uid, name in addressed for leaf in syngatelib.leaves_under(items, uid)))
        with tempfile.TemporaryDirectory() as scratch:
            fresh = Path(scratch) / RUN_COVERAGE
            job = self.jobs.get(self.start_run({"action": "test", "uids": [f"{leaf}:{name}" if name else leaf for leaf, name in targets]}, fresh)["job"])
            if turn:
                turn.job = job
                if turn.stopped:
                    self.jobs.cancel()
            output = list(job.stream())
            syngatelib.merge_coverage(self.run_coverage, fresh)
            return synthetic.run_report(items, targets, syngatelib.load_coverage([fresh])[0], output)

    def start_run(self, data, coverage_out=None):
        action = data.get("action")
        if action not in ("test", "review", "clear"):
            raise ApiError(400, "'action' must be 'test', 'review' or 'clear'")
        uids = data.get("uids")
        if not isinstance(uids, list) or not uids or not all(isinstance(u, str) and RUN_UID_RE.match(u) for u in uids):
            raise ApiError(400, "'uids' must be a non-empty list of UIDs or glob patterns")
        if self.engine["restarting"]:
            raise ApiError(503, RESTARTING)
        items = self._load()
        scopes = syngatelib.feature_scopes(items)[0]
        if action != "test" and not any(scopes[uid]["review"] for uid in uids if uid in scopes) and any(uid in scopes for uid in uids):
            raise ApiError(400, str(syngatelib.feature_off("review")))
        argv, then = [*self.cli_prefix, action], None
        if action == "clear":
            argv += uids
        else:
            under = syngatelib.items_under if action == "review" else syngatelib.leaves_under
            targets = list(dict.fromkeys(target for uid in uids for target in under(items, uid)))
            if not targets:
                raise ApiError(400, f"no leaf with a test under {', '.join(uids)}")
            if action == "review":
                targets, then = self._review_targets(items, uids, targets)
            argv += [*targets, "--build-dir", str(data.get("build_dir") or self.build_dir), "--coverage-out", str(coverage_out or self.run_coverage)]
        job = self.jobs.start(argv, cwd=self.root, then=then)
        return {"job": job.id}

    def _review_targets(self, items, uids, targets):
        """(the `targets` a review stamps -- those whose own review does not stand, an unknown UID passing through for the CLI to judge --,
        what closes the run: the review commit while git is at hand); refused when none needs review or, with git, while their review
        footprints hold uncommitted content -- review marks left uncommitted in them block nothing and join the review commit, so a
        review mark never shares a commit with content."""
        discovered = syngatelib.discover_setups(items, syngatelib.discover_bindings(self.root), self.root)[0]
        pending = self._pending(items, syngatelib.item_problems(items, discovered))
        targets = [target for target in targets if target not in items or target in pending]
        if not targets:
            raise ApiError(400, f"nothing under {', '.join(uids)} needs review")
        if not self.git:
            return targets, None
        uncommitted = gitlib.uncommitted(self.root)
        content = gitlib.content_uncommitted(self.root, uncommitted)
        blocked = self._blocked(items, targets, discovered, content)
        if blocked:
            raise ApiError(409, f"commit first: {', '.join(blocked)}", files=blocked)
        root = self.root.resolve()
        paths = [items[target].path.resolve().relative_to(root).as_posix() for target in targets if target in items and items[target].path.resolve().is_relative_to(root)]
        paths += [path for path in self._blocked(items, targets, discovered, uncommitted - content) if path not in paths]  # the marks left uncommitted
        return targets, lambda job: self._review_commit(job, paths, uids[0])

    def _review_commit(self, job, paths, uid):
        """Close a review run in a git work tree: of the item files `paths` -- the targets', and those whose uncommitted change was review
        marks alone when it started -- those uncommitted now are committed alone,
        as `Review: <subject>` of the one commit since the last review commit, else with the message the AI formulates in `uid`'s chat.
        -> the lines the console ends with."""
        stamped = sorted(set(paths) & gitlib.uncommitted(self.root))
        if not stamped:
            return ["review commit: nothing was stamped"]
        left = f"the stamps of {', '.join(stamped)} are left uncommitted"
        if job.proc.returncode < 0:
            return [f"review commit: the run was stopped, {left}"]
        subjects = gitlib.since_review(self.root)
        message = f"Review: {subjects[0]}" if len(subjects) == 1 else self._review_message(job, uid, subjects, stamped)
        if message is None:
            return [f"review commit: no message came from the chat of {uid}, {left}"]
        made, output = gitlib.commit(self.root, stamped, message)
        return [f"review commit{'' if made else ' failed'}: {line}" for line in output.splitlines() or [message]]

    def _review_message(self, job, uid, subjects, stamped):
        """The review commit's message, formulated by the AI in a turn of `uid`'s chat the `job` holds, so the run's cancel stops it;
        its reply's line opening with `Review`, else its last line so prefixed. None when the turn cannot start, fails or is stopped."""
        listed = "\n".join(f"- {subject}" for subject in subjects[:30]) or "- (none: the stamped items were committed before the last review commit)"
        text = REVIEW_MESSAGE.format(stamped=", ".join(Path(path).stem for path in stamped), subjects=listed)
        try:
            job.turn = self._turn(self.start_turn({**self._setup(uid), "uid": uid, "text": text, "agent": "review"})["turn"])
        except ApiError:
            return None
        outcome = job.turn.snapshot(wait=None)
        lines = [line.strip() for line in str(outcome.get("reply") or "").splitlines() if line.strip()]
        if "error" in outcome or not lines:
            return None
        line = next((line for line in lines if gitlib.REVIEW_RE.match(line)), lines[-1])
        return line if gitlib.REVIEW_RE.match(line) else f"Review: {line}"

    def _setup(self, uid):
        """The setup of a turn the harness starts in `uid`'s chat: the chat's own, else the first connector's default one."""
        chat, connectors = self.chats.get(uid), self.sync_connections()
        if chat and chat.setup.get("connector") in connectors:
            return dict(chat.setup)
        return self.chat_defaults()

    def cancel_job(self, job_id):
        job = self.jobs.get(job_id)
        if job is None:
            raise ApiError(404, f"no such job {job_id}")
        if job.turn is not None and job.turn.outcome is None:
            self.stop_turn(job.turn.id)
        threading.Thread(target=self.jobs.cancel, args=(job,), daemon=True).start()
        return {"ok": True}

    # -- engine watch -------------------------------------------------------

    def running(self):
        """How many turns -- background subagents' among them -- and runs are live; a held turn, or one waiting on a held one, is not
        waited for."""
        with self._chat_lock:
            turns = sum(chat.running and self.chat_state(chat)["state"] != "blocked" for chat in self.chats.values())
        job = self.jobs.current
        return turns + (1 if job and job.returncode is None else 0)

    def engine_state(self):
        """What the page shows of the engine: the sources changed since this process loaded them, the error that keeps them from loading,
        whether a restart was asked for or is under way, how many turns and runs it waits for and whether the engine restarts itself."""
        return {**self.engine, "changed": list(self.engine["changed"]), "running": self.running(), "watch": self.relaunch is not None}

    def check_engine(self):
        """One look at the engine sources: once they changed since this process loaded them -- or a restart was asked for -- they are
        compiled and imported in a fresh interpreter, once per state of theirs, and while that holds and nothing runs the server is
        re-executed in place, a turn or run started meanwhile refused. -> whether it restarted (only a stub `execv` returns)."""
        stamp = engine_stamp()
        self.engine["changed"] = sorted(name for name in stamp.keys() | self.engine_loaded.keys() if stamp.get(name) != self.engine_loaded.get(name))
        if self.relaunch is None or not (self.engine["changed"] or self.engine["requested"]):
            self.engine["error"] = None
            return False
        if stamp != self._preflown:
            self._preflown, self.engine["error"] = stamp, preflight()
        if self.engine["error"]:
            return False
        with self._chat_lock:
            if self.running():
                return False
            self.engine["restarting"] = True
        self.restart()
        return True

    def watch_engine(self):
        while True:
            time.sleep(ENGINE_POLL)
            try:
                self.check_engine()
            except Exception as err:
                print(f"assassin: engine watch: {type(err).__name__}: {err}", file=sys.stderr)

    def request_restart(self, stop=False):
        """Ask for a restart of the engine whether its sources changed or not; `stop` stops the running turns and runs first, which it
        otherwise waits for. -> the engine state."""
        if self.relaunch is None:
            raise ApiError(409, "this server does not restart itself (started with --no-reload)")
        self.engine["requested"] = True
        if stop:
            with self._chat_lock:
                running = [chat.turn.id for chat in self.chats.values() if chat.running and not chat.turn.stopped]
            for key in running:
                self.stop_turn(key)
            if self.jobs.current and self.jobs.current.returncode is None:
                threading.Thread(target=self.jobs.cancel, daemon=True).start()
        return self.engine_state()

    def restart(self):
        """Re-execute the server in place: the chats written out, the session token and the listening socket handed to the new process
        through the environment, so an open page goes on at the same URL. The held turns are ended as stopped first, a held turn having
        no timeout."""
        with self._chat_lock:
            held = [chat.turn for chat in self.chats.values() if chat.running and self.chat_state(chat)["state"] == "blocked"]
        for turn in held:
            self.stop_turn(turn.id, withdraw=False)
        for turn in held:
            turn.snapshot(wait=HELD_GRACE)
        self.save_chats(force=True)
        env = {**os.environ, TOKEN_ENV: self.token}
        if self.listener is not None:
            self.listener.set_inheritable(True)
            env[LISTEN_ENV] = str(self.listener.fileno())
        print("assassin: restarting the engine" + (f" on the change of {', '.join(self.engine['changed'])}" if self.engine["changed"] else ""), flush=True)
        try:
            self.execv(self.relaunch[0], self.relaunch, env)
        except OSError as err:
            self.engine.update(restarting=False, requested=False, error=f"the restart failed: {err}")


def page_source():
    """The page as it is served, before its nonces: its file with the markdown renderer inlined in its slot."""
    return PAGE_FILE.read_bytes().replace(MARKDOWN_SLOT, b"<script>\n" + MARKDOWN_FILE.read_bytes() + b"</script>", 1)


def page_sha(page=None):
    """The version of the page: the sha256 of its source as it is now, the markdown renderer included, the first 16 hex digits."""
    return hashlib.sha256(page_source() if page is None else page).hexdigest()[:16]


def _page_bytes(nonce):
    """The page with its script and style nonced and its version on the root element, which the page compares with the served one."""
    page = page_source()
    return (page.replace(b"<script>", b'<script nonce="' + nonce + b'">').replace(b"<style>", b'<style nonce="' + nonce + b'">')
            .replace(b'<html lang="en">', b'<html lang="en" data-page="' + page_sha(page).encode() + b'">', 1))


def engine_stamp():
    """{file name: (mtime, size)} of every Python source of the engine as it is now."""
    stamp = {}
    for path in sorted(ENGINE_DIR.glob("*.py")):
        try:
            meta = path.stat()
        except OSError:
            continue
        stamp[path.name] = (meta.st_mtime_ns, meta.st_size)
    return stamp


def preflight():
    """None when every engine source compiles and the server imports in a fresh interpreter, else the error that ended it."""
    sources = [str(path) for path in sorted(ENGINE_DIR.glob("*.py"))]
    try:
        done = subprocess.run([sys.executable, "-c", PREFLIGHT, *sources], cwd=Path(__file__).resolve().parent.parent,
                              capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as err:
        return f"{type(err).__name__}: {err}"
    return None if done.returncode == 0 else (done.stderr.strip() or f"exit {done.returncode}")


def _csp(nonce):
    return (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src-elem 'nonce-{nonce}'; style-src-attr 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; frame-src 'self'; base-uri 'none'; form-action 'none'")


def library_origin(url):
    """The origin of the drawing library's URL, as the diagram frame's policy admits it."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _frame_bytes(nonce, library):
    """The diagram frame with its script nonced and the drawing library's URL in it."""
    page = MARKDOWN_FRAME_FILE.read_bytes()
    return (page.replace(b'<script type="module">', b'<script type="module" nonce="' + nonce + b'">', 1)
            .replace(b"import(LIBRARY_URL)", b"import(" + json.dumps(library).replace("</", "<\\/").encode() + b")", 1))


def _frame_csp(nonce, library):
    return (f"default-src 'none'; script-src 'nonce-{nonce}' {library_origin(library)}; style-src 'unsafe-inline'; img-src data:; font-src data:; "
            "base-uri 'none'; form-action 'none'")


# Served without the token: browsers request it on their own, and it reveals nothing.
FAVICON = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><rect width="16" height="16" rx="3" fill="#2e5c6e"/>'
           b'<path d="M5 5.5v5M6 5.2l4 1.3M6 10.8l4-1.3" stroke="#fff" stroke-width="1.1" fill="none"/>'
           b'<circle cx="5" cy="4.5" r="1.7" fill="#d9a63d"/><circle cx="5" cy="11.5" r="1.7" fill="#7a7f87"/>'
           b'<circle cx="11" cy="7.2" r="1.7" fill="#3f7d52"/><circle cx="11" cy="9.8" r="1.7" fill="#a8482e"/></svg>')


class _Handler(http.server.BaseHTTPRequestHandler):
    app = None  # bound by make_server
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # keep the terminal for syngate.py output
        pass

    # -- plumbing ---------------------------------------------------------

    def _send(self, status, content_type, body, extra=()):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in extra:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, obj):
        self._send(status, "application/json; charset=utf-8", json.dumps(obj).encode())

    def _authorized(self):
        host = urlsplit("//" + (self.headers.get("Host") or "")).hostname
        if host not in LOOPBACK_HOSTS:
            self._json(403, {"error": "requests must address a loopback host"})
            return False
        query = parse_qs(urlsplit(self.path).query)
        supplied = self.headers.get("X-Assassin-Token") or (query.get("token") or [""])[0]
        if not hmac.compare_digest(supplied, self.app.token):
            self._json(401, {"error": "missing or invalid session token"})
            return False
        return True

    def _payload(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            raise ApiError(400, "request body must be JSON")
        if not isinstance(data, dict):
            raise ApiError(400, "request body must be a JSON object")
        return data

    # -- routes -----------------------------------------------------------

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/favicon.ico":
            self._send(200, "image/svg+xml", FAVICON, extra=[("Cache-Control", "max-age=86400")])
            return
        if path == websurf.PATH:
            self._websurf()
            return
        if path == MARKDOWN_FRAME_PATH:
            self._markdown_frame()
            return
        if not self._authorized():
            return
        try:
            if path == "/":
                nonce = secrets.token_urlsafe(16)
                self._send(200, "text/html; charset=utf-8", _page_bytes(nonce.encode()), extra=[("Content-Security-Policy", _csp(nonce))])
            elif path == "/api/tree":
                self._json(200, self.app.build_model())
            elif path == "/api/fingerprint":
                job = self.app.jobs.current
                self._json(200, {"fingerprint": self.app.fingerprint(),
                                 "job": job.id if job and job.returncode is None else None,
                                 "chats": self.app.chats_version,
                                 "boot": self.app.boot, "page": page_sha(), "engine": self.app.engine_state(),
                                 "files": self.app.file_shas(parse_qs(urlsplit(self.path).query).get("file", []))})
            elif path == "/api/files":
                self._json(200, self.app.list_files())
            elif path == "/api/file":
                self._json(200, self.app.read_file((parse_qs(urlsplit(self.path).query).get("path") or [""])[0]))
            elif path == "/api/chats":
                query = parse_qs(urlsplit(self.path).query)
                since = query.get("since")
                self._json(200, self.app.chats_snapshot(_number(since[0], "since", int) if since else None,
                                                        min(_number((query.get("wait") or ["0"])[0], "wait"), 30)))
            elif path == "/api/services":
                self._json(200, self.app.services_state())
            elif (match := re.fullmatch(TURN_ROUTE, path)):
                wait = (parse_qs(urlsplit(self.path).query).get("wait") or ["0"])[0]
                self._json(200, self.app.turn_snapshot(match.group(1), min(_number(wait, "wait"), 30)))
            elif (match := re.fullmatch(r"/api/job/(\d+)", path)):
                self._job_snapshot(int(match.group(1)))
            elif (match := re.fullmatch(r"/api/job/(\d+)/events", path)):
                self._job_events(int(match.group(1)))
            else:
                self._json(404, {"error": f"no route for GET {path}"})
        except ApiError as exc:
            self._json(exc.status, {"error": str(exc), **exc.extra})
        except ConnectionError:
            pass
        except Exception as exc:
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def do_POST(self):
        if not self._authorized():
            return
        path = urlsplit(self.path).path
        try:
            payload = self._payload()
            if (match := re.fullmatch(r"/api/item/([A-Za-z0-9_\-]+)", path)):
                self._json(200, self.app.save_item(match.group(1), payload))
            elif (match := re.fullmatch(r"/api/move/([A-Za-z0-9_\-]+)", path)):
                self._json(200, self.app.move_item(match.group(1), payload))
            elif path == "/api/new":
                self._json(200, self.app.create_item(payload))
            elif path == "/api/file":
                self._json(200, self.app.save_file(payload))
            elif (match := re.fullmatch(r"/api/delete/([A-Za-z0-9_\-]+)", path)):
                self._json(200, self.app.delete_item(match.group(1)))
            elif path == "/api/run":
                self._json(200, self.app.start_run(payload))
            elif path == "/api/chat":
                self._json(200, self.app.chat(payload))
            elif (match := re.fullmatch(r"/api/chat/([A-Za-z0-9_\-]+)", path)):
                self._json(200, self.app.update_chat(match.group(1), payload))
            elif path == "/api/turn":
                self._json(200, self.app.start_turn(payload))
            elif (match := re.fullmatch(TURN_ROUTE + "/stop", path)):
                self._json(200, self.app.stop_turn(match.group(1), withdraw=not payload.get("send")))  # `send`: the queue goes as the next turn
            elif (match := re.fullmatch(TURN_ROUTE + "/release", path)):
                if payload.get("answer") is None:
                    raise ApiError(400, "'answer' is missing: the answer to what the held turn asks")
                self._json(200, self.app.release(match.group(1), payload["answer"]))
            elif (match := re.fullmatch(r"/api/job/(\d+)/cancel", path)):
                self._json(200, self.app.cancel_job(int(match.group(1))))
            elif path == "/api/engine":
                self._json(200, self.app.request_restart(bool(payload.get("stop"))))
            elif path == "/api/services/retry":
                self.app.health.retry()
                self._json(200, {"alert": self.app.health.alert()})
            else:
                self._json(404, {"error": f"no route for POST {path}"})
        except ApiError as exc:
            self._json(exc.status, {"error": str(exc), **exc.extra})
        except ConnectionError:
            pass
        except Exception as exc:
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _markdown_frame(self):
        """The diagram frame on a loopback host, served without the token: it holds nothing of the session and runs sandboxed, an opaque origin."""
        if urlsplit("//" + (self.headers.get("Host") or "")).hostname not in LOOPBACK_HOSTS:
            self._json(403, {"error": "requests must address a loopback host"})
            return
        nonce, library = secrets.token_urlsafe(16), self.app.mermaid_url()
        self._send(200, "text/html; charset=utf-8", _frame_bytes(nonce.encode(), library),
                   extra=[("Content-Security-Policy", _frame_csp(nonce, library)), ("Cache-Control", "no-store")])

    def _websurf(self):
        """The WebSurf bridge: a WebSocket upgrade from a browser extension on a loopback host, refused otherwise, then served by the
        app's bridge on this handler's thread until it closes -- the session token travels in its first message, not in the URL."""
        if urlsplit("//" + (self.headers.get("Host") or "")).hostname not in LOOPBACK_HOSTS:
            self._json(403, {"error": "requests must address a loopback host"})
            return
        problem = websurf.upgrade_refusal(self.headers)
        if problem:
            self._json(403, {"error": problem})
            return
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", websurf.accept_key(self.headers["Sec-WebSocket-Key"]))
        self.end_headers()
        self.wfile.flush()
        self.close_connection = True
        self.app.websurf.serve(websurf.peer(self.connection, self.rfile, self.wfile))

    def _job_snapshot(self, job_id):
        job = self.app.jobs.get(job_id)
        if job is None:
            raise ApiError(404, f"no such job {job_id}")
        self._json(200, job.snapshot())

    def _job_events(self, job_id):
        job = self.app.jobs.get(job_id)
        if job is None:
            raise ApiError(404, f"no such job {job_id}")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        stream = job.stream()
        returncode = None
        while True:
            try:
                line = next(stream)
            except StopIteration as stop:
                returncode = stop.value
                break
            self.wfile.write(f"data: {line}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(f"event: done\ndata: {returncode}\n\n".encode())
        self.wfile.flush()


def project_port(root):
    """The port of the project at `root`: one of the PORT_SPAN ports above DEFAULT_PORT, by the sha256 of the resolved root."""
    digest = hashlib.sha256(str(Path(root).resolve()).encode("utf-8", "surrogateescape")).digest()
    return DEFAULT_PORT + 1 + int.from_bytes(digest[:8], "big") % PORT_SPAN


def project_ports(root):
    """Every port of the range, the project's own first, then the next ones, wrapping around."""
    first = project_port(root) - DEFAULT_PORT - 1
    return (DEFAULT_PORT + 1 + (first + step) % PORT_SPAN for step in range(PORT_SPAN))


def make_server(app, port=None, fd=None):
    """The server of `app` on the loopback `port`, else on the first free port of its project's range, else on an ephemeral one; or --
    given `fd` -- on the listening socket an earlier run of the engine handed over."""
    if port is None and fd is None:
        for candidate in project_ports(app.root):
            try:
                return make_server(app, candidate)
            except OSError:
                continue
        port = 0
    handler = type("BoundHandler", (_Handler,), {"app": app})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port or 0), handler, bind_and_activate=fd is None)
    if fd is not None:
        server.socket.close()
        server.socket = socket.socket(fileno=fd)
        server.socket.set_inheritable(False)
        server.server_address = server.socket.getsockname()
        server.server_name, server.server_port = server.server_address[:2]
    server.daemon_threads = True
    app.listener = server.socket
    return server


def running_server(root):
    """The URL of the live server the record in `root` names -- its process alive and its server answering the token -- else None."""
    record = synthetic.read_json(Path(root) / SERVER_FILE)
    pid, port, token = record.get("pid"), record.get("port"), record.get("token")
    if not (type(pid) is int and pid > 0 and type(port) is int and 0 < port < 65536 and isinstance(token, str) and token):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        pass
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=PROBE_TIMEOUT)
        try:
            conn.request("GET", "/api/fingerprint", headers={"X-Assassin-Token": token})
            if conn.getresponse().status != 200:
                return None
        finally:
            conn.close()
    except (OSError, http.client.HTTPException):
        return None
    return f"http://127.0.0.1:{port}/?token={token}"


def write_server_record(root, port, token):
    """Write the record of this process's server on `port` into `root`, whole, at once."""
    path = Path(root) / SERVER_FILE
    draft = path.with_suffix(".json.tmp")
    try:
        draft.write_text(json.dumps({"pid": os.getpid(), "port": port, "token": token}), encoding="utf-8")
        os.replace(draft, path)
    except OSError as err:
        print(f"assassin: server record not saved to {path}: {err}", file=sys.stderr)


def remove_server_record(root, token):
    """Remove the record in `root` while it is still this process's server's, holding `token`."""
    path = Path(root) / SERVER_FILE
    record = synthetic.read_json(path)
    if record.get("pid") == os.getpid() and record.get("token") == token:
        try:
            path.unlink()
        except OSError:
            pass


def bootstrap(root=None):
    """The managed project root -- `find_root`'s, else the working directory -- whose `syngate/`, while it holds no item file, gets one
    root item named after the project: the first `# ` heading of its README.md, else the folder's name, over a link to the README, both
    features off."""
    try:
        root = syngatelib.find_root(root)
    except FileNotFoundError:
        root = Path.cwd().resolve()
    syngate_dir = root / "syngate"
    if any(syngate_dir.rglob("*.yml")):
        return root
    uid = re.sub(r"[^A-Z0-9_]+", "-", root.name.upper()).strip("-")
    uid = uid if syngatelib.UID_RE.match(uid) else "PROJECT"
    readme = root / "README.md"
    lines = readme.read_text(encoding="utf-8", errors="replace").splitlines() if readme.is_file() else ()
    title = next((line[2:].strip() for line in lines if line.startswith("# ")), "") or root.name
    link = "\n\n[README.md](README.md)" if readme.is_file() else ""
    item = syngatelib.Item(uid=uid, path=syngate_dir / f"{uid}.yml", description=f"{title}{link}\n", parents=[])
    syngate_dir.mkdir(parents=True, exist_ok=True)
    syngatelib.write_item(item)
    print(f"assassin: bootstrapped {item.path.relative_to(root)}, the root item of {root}")
    return root


def serve(port=None, coverage=(), build_dir=DEFAULT_BUILD_DIR, open_browser=True, root=None, reload=True, argv=()):
    """Serve the page until Ctrl+C on `port`, else on the project's own port (see `make_server`); with `reload`, the engine re-executes itself with `argv` on a change of its sources, the restarted
    process taking the token and the listening socket over from the environment, which it then clears. A root already served by a live
    server (see `running_server`) has the browser opened at that server instead; a restarted engine is that server itself."""
    token, fd = os.environ.pop(TOKEN_ENV, None), os.environ.pop(LISTEN_ENV, None)
    root = bootstrap(root)
    running = None if fd else running_server(root)
    if running:
        print(f"assassin: {root} is already served at {running}", flush=True)
        if open_browser:
            webbrowser.open(running)
        return 0
    coverage = list(coverage) or [str(Path(root) / name) for name in DEFAULT_COVERAGE if (Path(root) / name).is_file()]
    app = AssassinApp(root=root, coverage=coverage, build_dir=build_dir, token=token)
    threading.Thread(target=app.health.check, daemon=True).start()  # the model services are checked when the server starts
    threading.Thread(target=app.health.watch, daemon=True).start()  # and the failed ones again while the alert stands
    try:
        server = make_server(app, port, fd=int(fd) if fd else None)
    except (OSError, ValueError) as exc:
        print(f"assassin: cannot bind 127.0.0.1{'' if port is None else f':{port}'}: {exc}", file=sys.stderr)
        return 1
    write_server_record(root, server.server_address[1], app.token)
    app.first_setup()
    if reload:
        app.relaunch = [sys.executable, "-m", "ai_scratcher.assassin_ui", *argv, *([] if "--no-browser" in argv else ["--no-browser"])]
        threading.Thread(target=app.watch_engine, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/?token={app.token}"
    print(f"assassin: {'serving AI Assassin' if fd is None else 'the engine restarted, serving'} at {url}", flush=True)
    open_browser = open_browser and fd is None
    if coverage:
        print(f"assassin: coloring statuses from {', '.join(coverage)}")
    else:
        print("assassin: no coverage files found; leaf statuses show as not run until tests are run from the page (or pass --coverage FILE)")
    print("assassin: loopback only; the URL token is this session's key. Ctrl+C stops the server.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nassassin: stopped")
    finally:
        app.jobs.cancel()
        app.save_chats()
        remove_server_record(root, app.token)
        server.server_close()
    return 0


def main():
    parser = argparse.ArgumentParser(prog="assassin", description=__doc__)
    parser.add_argument("--port", type=int, help=f"listen port on 127.0.0.1, bound exactly or failing; 0 = ephemeral (default: the project's own "
                                                 f"port above {DEFAULT_PORT}, derived from its root, the next free one while it is held, an ephemeral one past them)")
    parser.add_argument("--coverage", action="append", default=[], help="syngate_coverage.jsonl file(s) to color statuses; repeatable (default: well-known local files)")
    parser.add_argument("--build-dir", default=DEFAULT_BUILD_DIR, help="build tree the test runner uses for test and review runs")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    parser.add_argument("--root", help="managed project root (default: SYNGATE_ROOT, else the nearest ancestor of the working directory holding syngate/, else the working directory)")
    parser.add_argument("--no-reload", action="store_true", help="do not restart the engine in place when its Python sources change")
    args = parser.parse_args()
    return serve(port=args.port, coverage=args.coverage, build_dir=args.build_dir, open_browser=not args.no_browser, root=args.root,
                 reload=not args.no_reload, argv=sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
