# Open Trader
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Local Synergy Context Gate (syngate) tree editor: a loopback web UI over syngatelib.

`syngate ui` (or `python scripts/syngate_ui.py`) serves a single-page editor for the
tree under `syngate/`: the DAG with live status rollup, per-field item edits
(autosave) and drag-and-drop placement through the canonical writer, and
review / clear runs driven through `syngate.py` subprocesses with output streamed
to the browser over SSE. Stamping stays in the CLI code path, so the browser
button and the terminal command are the same user action.

The server binds 127.0.0.1 only. Every request must carry the per-session
token from the URL printed at startup (`X-Syngate-Token` header or `?token=`),
and the Host header must be a loopback name -- the jupyter-style defense
against CSRF and DNS rebinding for localhost tools that run subprocesses.
"""

import argparse
import copy
import hashlib
import hmac
import http.server
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import syngatelib
from . import synthetic

DEFAULT_PORT = 8712
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
# The chats of the items, kept next to the tree across server runs; a settled change is written this many seconds after the first.
CHATS_FILE = "syngate_chats.json"
WRITE_DELAY = 0.5
# The harness's own permission, first among every connector's modes: whether a reply's add, edit, move and remove calls are
# applied; its reads -- query, context, skill -- always are.
TREE_MODE = {"id": "tree", "label": "Tree edit", "hint": "add, edit, move and remove items; reading the tree stays on", "default": True, "advanced": False}
TREE_OFF = "The tree is read-only for this chat: add, edit, move and remove are refused — answer in text and say what you would change."
TREE_REFUSAL = "tree edits are off for this chat — switch Tree edit on"


class ApiError(Exception):
    def __init__(self, status, message, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


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
    def __init__(self, job_id, argv):
        self.id = job_id
        self.argv = argv
        self.lines = []
        self.returncode = None
        self.proc = None
        self.cond = threading.Condition()

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


class Turn:
    """One chat exchange run on its own thread: the page awaits its outcome by polling, re-attaching after a reload, and may stop it.
    Its steps are recorded as they happen, every change announced through `changed`."""

    def __init__(self, turn_id, connector, changed=lambda: None):
        self.id = turn_id
        self.connector = connector
        self.changed = changed
        self.thread = None
        self.outcome = None
        self.stopped = False
        self.started = time.monotonic()
        self.steps, self.origins = [], []
        self.children, self.job = [], None
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


SETUP_KEYS = ("connector", "model", "effort", "modes")


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
        self.erase()

    def erase(self):
        self.log = []
        self.session = None
        self.setup = {}
        self.turn = None
        self.started = None

    def conversation(self):
        return {"started": self.started, "log": [dict(m) for m in self.log], "session": self.session, "setup": dict(self.setup)}

    def file(self):
        """Begin a new conversation: the live one joins the filed ones when it holds messages, the setup staying with the live one."""
        if self.log:
            self.archive.append(self.conversation())
            self.archive.sort(key=lambda stored: stored["started"] or 0)
        self.log, self.session, self.started = [], None, None

    def resume(self, index):
        """The filed conversation `index` becomes the live one, with its setup, the live one filed in its place."""
        if not isinstance(index, int) or not 0 <= index < len(self.archive):
            raise ApiError(404, f"no conversation {index} of {self.uid}")
        stored = self.archive.pop(index)
        self.file()
        self.log, self.session, self.started = stored["log"], stored["session"], stored["started"]
        self.setup = dict(stored["setup"]) or self.setup

    @staticmethod
    def summary(stored):
        """A filed conversation as the page lists it: its start, first line of text and message count."""
        first = next((m["text"] for m in stored["log"] if m.get("text")), "")
        return {"started": stored["started"], "title": first.strip().split("\n", 1)[0][:120], "messages": len(stored["log"])}

    @property
    def running(self):
        return self.turn is not None and self.turn.outcome is None

    def next_turn(self, connector, changed):
        self.turns += 1
        self.turn = Turn(f"{self.uid}:{self.turns}", connector, changed)
        return self.turn

    def kept(self):
        """The exchange as it travels: every message but a failed or stopped turn's, its cuts taken out, one left empty left out."""
        kept = []
        for m in self.log:
            text = kept_text(m["text"], m.get("cuts"))
            if m["role"] not in ("error", "stopped") and text.strip():
                kept.append({"role": m["role"], "text": text})
        return kept

    def snapshot(self):
        return {"uid": self.uid, "log": [dict(m) for m in self.log], "session": self.session, "started": self.started, **self.setup,
                "archive": [self.summary(stored) for stored in self.archive], "turn": self.turn.id if self.running else None,
                **({"steps": list(self.turn.steps)} if self.running else {})}

    def record(self):
        """The chat as it is kept across server runs: what is settled, never the turn in flight."""
        return {"turns": self.turns, **self.conversation(), "archive": [dict(stored, log=[dict(m) for m in stored["log"]]) for stored in self.archive]}

    @classmethod
    def restore(cls, uid, record):
        chat = cls(uid)
        turns = record.get("turns")
        chat.turns = turns if isinstance(turns, int) else 0
        live = cls._conversation(record)
        chat.log, chat.session, chat.setup, chat.started = live["log"], live["session"], live["setup"], live["started"]
        chat.archive = [cls._conversation(stored) for stored in record.get("archive") or () if isinstance(stored, dict) and isinstance(stored.get("log"), list)]
        return chat

    @classmethod
    def _conversation(cls, stored):
        setup, started = stored.get("setup"), stored.get("started")
        return {"started": started if isinstance(started, (int, float)) and not isinstance(started, bool) else None,
                "log": [cls._message(m) for m in stored.get("log") or () if isinstance(m, dict) and isinstance(m.get("role"), str) and isinstance(m.get("text"), str)],
                "session": stored.get("session"),
                "setup": {key: value for key, value in (setup.items() if isinstance(setup, dict) else ()) if key in SETUP_KEYS}}

    @staticmethod
    def _message(stored):
        """A stored message with its cuts normalised; a record from before cuts marked a whole message `dropped` instead."""
        m = dict(stored)
        cuts = [[0, len(m["text"])]] if m.pop("dropped", False) else cut_ranges(m["text"], m.get("cuts"))
        m.pop("folded", None)
        m.pop("cuts", None)
        return {**m, "cuts": cuts} if cuts else m


class JobRunner:
    """Single-flight subprocess runner: review runs stamp files and share the
    build tree, so exactly one job may be live at a time."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counter = 0
        self.current = None

    def start(self, argv, cwd):
        with self._lock:
            if self.current and self.current.returncode is None:
                raise ApiError(409, f"a run is already in progress (job {self.current.id})")
            self._counter += 1
            job = Job(self._counter, argv)
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
            with job.cond:
                job.lines.append(line.rstrip("\n"))
                job.cond.notify_all()
        job.proc.wait()
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


class SyngateUIApp:
    def __init__(self, root=None, syngate_dir=None, coverage=(), cli_prefix=None, build_dir=DEFAULT_BUILD_DIR):
        self.root = syngatelib.find_root(root)
        self.syngate_dir = Path(syngate_dir) if syngate_dir else self.root / "syngate"
        self.run_coverage = str(self.root / RUN_COVERAGE)
        self.coverage = list(dict.fromkeys([*(str(p) for p in coverage), self.run_coverage]))
        self.cli_prefix = cli_prefix or [sys.executable, "-m", "ai_scratcher.syngate", "--root", str(self.root)]
        self.build_dir = build_dir
        self.token = secrets.token_urlsafe(24)
        self.jobs = JobRunner()
        self.chats_file = self.root / CHATS_FILE
        self.chats = self._read_chats()
        self.chats_version = 0
        self._chat_lock = threading.Condition()
        self._writer = None
        self.connectors = {name: connector(cwd=self.root) for name, connector in synthetic.CONNECTORS.items()}

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
        return stat.hexdigest()

    def build_model(self):
        items, load_errors = syngatelib.load_tree(self.syngate_dir)
        discovered = syngatelib.discover_bindings(self.root)
        records, coverage_errors = syngatelib.load_coverage(self._coverage_files())
        problems = syngatelib.item_problems(items, discovered)
        report = syngatelib.compute_status(items, records, problems)
        axes = syngatelib.compute_axes(items, records, problems)
        tree_errors = [message for uid, message in syngatelib.layout_problems(items) if uid is None]

        payload = {}
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
                                description_raw=item.description,
                                path=str(item.path.relative_to(self.root)) if item.path.is_relative_to(self.root) else str(item.path),
                                stamp_fresh=(syngatelib.item_stamp(items, uid) == item.reviewed) if item.reviewed else None,
                                bindings=bindings)

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
            "connectors": {name: {**(settings := connector.settings()), "modes": [TREE_MODE, *settings["modes"]]} for name, connector in self.connectors.items()},
            "job": job.id if job and job.returncode is None else None,
        }

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
        secrets sit untracked next to the tree (keys, databases), so anything
        outside git is served only when it is markdown."""
        if not rel or Path(rel).is_absolute() or ".." in Path(rel).parts or rel != Path(rel).as_posix() or rel.startswith("-"):
            raise ApiError(400, f"'{rel}' is not a normalised project-relative path")
        path = (self.root / rel).resolve()
        if not path.is_relative_to(self.root.resolve()) or not path.is_file():
            raise ApiError(404, f"no file {rel}")
        writable = path.suffix == ".md"
        if not writable and not self._tracked(rel):
            raise ApiError(403, f"{rel} is neither tracked by git nor markdown")
        return path, writable

    def _tracked(self, rel):
        try:
            return subprocess.run(["git", "ls-files", "--error-unmatch", "--", rel], cwd=self.root, capture_output=True).returncode == 0
        except OSError:
            return False

    @staticmethod
    def _text(path, rel):
        if path.stat().st_size > FILE_LIMIT:
            raise ApiError(413, f"{rel} exceeds {FILE_LIMIT >> 10} KiB")
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise ApiError(415, f"{rel} is not UTF-8 text")

    def read_file(self, rel):
        path, writable = self._file_at(rel)
        text = self._text(path, rel)
        return {"path": rel, "text": text, "sha": hashlib.sha256(text.encode()).hexdigest(), "writable": writable}

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
            return {"version": self.chats_version, "chats": {uid: chat.snapshot() for uid, chat in self.chats.items()}}

    def _chat(self, uid):
        chat = self.chats.get(uid)
        if chat is None:
            chat = self.chats[uid] = Chat(uid)
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
        return {**chat.snapshot(), "version": self.chats_version}

    def _read_chats(self):
        """The stored chats of the items still in the tree -- an item whose file is unreadable right now keeps its chat."""
        items, errors = syngatelib.load_tree(self.syngate_dir)
        known = set(items) | {error.split(":", 1)[0] for error in errors}
        stored = synthetic.read_json(self.chats_file)
        return {uid: Chat.restore(uid, record) for uid, record in stored.items() if uid in known and isinstance(record, dict)}

    def save_chats(self):
        """Write the chats pending a write to `CHATS_FILE`, whole, at once."""
        with self._chat_lock:
            pending, self._writer = self._writer, None
            if pending is None:
                return
            pending.cancel()
            draft = self.chats_file.with_suffix(".json.tmp")
            try:
                draft.write_text(json.dumps({uid: chat.record() for uid, chat in self.chats.items()}, ensure_ascii=False, indent=1), encoding="utf-8")
                os.replace(draft, self.chats_file)
            except OSError as err:
                print(f"syngate ui: chats not saved to {self.chats_file}: {err}", file=sys.stderr)

    def update_chat(self, uid, data):
        """Change the item's chat in place: its setup, one message's cuts -- the spans of its text folded out of the exchange; a change of
        them ends the connector session, so the next turn carries the kept text -- the removal of a failed or stopped turn's message,
        `reset` -- the session dropped, the log kept -- `erase` of the live conversation, `begin` of a new one -- the live one filed --
        or `resume` of the filed one at that index; everything but the setup is refused while a turn runs."""
        with self._chat_lock:
            chat = self._chat(uid)
            patch = data.get("message") if isinstance(data.get("message"), dict) else {}
            if chat.running and (data.get("erase") or data.get("reset") or data.get("begin") or "resume" in data or "cuts" in patch or patch.get("remove")):
                raise ApiError(409, f"a turn of {uid} is running; change the exchange once it ends")
            if data.get("erase"):
                chat.erase()
            if data.get("begin"):
                chat.file()
            if "resume" in data:
                chat.resume(_number(data["resume"], "resume", int))
            if data.get("reset"):
                chat.session = None
            chat.setup.update({key: data[key] for key in SETUP_KEYS if key in data})
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
            return self._changed(chat)

    def start_turn(self, data):
        """Start one turn of the item's chat -- the typed text joins the log, marked as an `agent` message when a parent turn sent it,
        a `statement` is the content itself and is not repeated, a `retry` resends it without logging it again, `fresh` files the live
        conversation first -- as a job the page polls through `turn_snapshot`; -> `{"turn": "<UID>:<n>", "chat": …}`, the chat stamped
        with the chats `version`."""
        uid, text = str(data.get("uid") or ""), str(data.get("text") or "")
        with self._chat_lock:
            chat = self._chat(uid)
            if chat.running:
                raise ApiError(409, f"a turn of {uid} is running ({chat.turn.id})")
            if data.get("fresh"):
                chat.file()
            if chat.started is None:
                chat.started = time.time()
            chat.setup.update({key: data[key] for key in SETUP_KEYS if key in data})
            kept = chat.kept()
            history = [] if chat.session else kept[:-1] if data.get("retry") else kept
            if not data.get("statement") and not data.get("retry"):
                chat.log.append({"role": "user", "text": text, **({"agent": data["agent"]} if data.get("agent") else {})})
            turn = chat.next_turn(chat.setup.get("connector"), self._notify)
            exchange = {"uid": uid, "text": text, "session": chat.session, "history": history, **chat.setup}
            started = self._changed(chat)

        def run():
            try:
                outcome = self.chat(exchange, turn)
            except ApiError as err:
                outcome = {"error": str(err), "status": err.status, **err.extra}
            except Exception as err:
                outcome = {"error": f"{type(err).__name__}: {err}", "status": 500}
            with self._chat_lock:
                try:
                    if chat.turn is turn:
                        if outcome.get("session"):
                            chat.session = outcome["session"]
                        role = "ai" if "error" not in outcome else "stopped" if turn.stopped else "error"
                        chat.log.append({"role": role, "text": outcome.get("error", outcome.get("reply")), **({"steps": list(turn.steps)} if turn.steps else {})})
                        self._mirror(turn, uid)
                        self._bump()
                finally:
                    turn.finish(outcome)

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

    def stop_turn(self, key):
        """End a running turn the instant the stop lands: its gate closes, so nothing of it is applied past this mark; the turns it
        delegated are stopped the same way, the test run it awaits is cancelled and its connector's live process is interrupted;
        the exchange then reports as stopped."""
        turn = self._turn(key)
        turn.stopped = True
        for child in turn.children:
            if child.outcome is None and not child.stopped:
                self.stop_turn(child.id)
        if turn.job is not None and turn.job is self.jobs.current and turn.job.returncode is None:
            threading.Thread(target=self.jobs.cancel, daemon=True).start()
        interrupt = getattr(self.connectors.get(turn.connector), "interrupt", None)
        if interrupt and turn.thread:
            interrupt(turn.thread.ident)
        return {"ok": True}

    def chat(self, data, turn=None):
        """One exchange anchored at `uid`: the item's seed context plus the user's text go to the chosen connector.
        A plain answer comes back as the reply; an answer of tool calls is applied to the tree -- its test calls joined
        into one awaited run through the page's runner after the rest, its agent calls then run as parallel turns of their items' chats
        -- and while it carries queries, runs or delegations their results go back into the same session for the next answer.
        A refused call ends its batch and goes back the same way, with the results of the calls applied before it, for the next
        answer to correct it or to explain. The reply lists what was applied, ran or was reported; what was read stays in the steps.
        `history` is the kept part of an exchange whose session was dropped: it travels with the text of the first round.
        A `turn` stopped while a round is out ends the exchange there, what was applied so far staying applied.
        The `tree` mode is the harness's own: without it the text is headed by `TREE_OFF`, the tree calls of a reply are refused and the
        connector never sees the mode. The steps of every round and the lines of every applied batch are recorded in the `turn` as they happen."""
        uid, text, session, applied, calls = data.get("uid"), str(data.get("text") or ""), data.get("session"), [], []
        history = [message for message in (data.get("history") or ()) if isinstance(message, dict)]
        modes = list(data.get("modes") or ())
        tree = "tree" in modes
        if not tree and text.strip():
            text = TREE_OFF + "\n" + text
        halted = lambda: turn is not None and turn.stopped

        def batch_step(lines, batch=()):
            if turn and lines:
                turn.add_step({"kind": "calls", "tools": [call["tool"] for call in batch], "lines": list(lines), "at": turn.elapsed()})

        def stopped(lines=(), batch=(), shown=()):
            batch_step(lines, batch)
            return ApiError(409, "\n".join([*applied, *shown, "turn stopped"]), session=session)

        for _ in range(synthetic.QUERY_ROUNDS):
            on_step = (lambda step, shift=turn.elapsed(): turn.add_step(step, shift)) if turn else None
            try:
                reply, session = synthetic.query(self.connectors, self._load(), uid, text, data.get("connector"), data.get("model"),
                                                 data.get("effort"), modes=[mode for mode in modes if mode != "tree"], session=session, history=history,
                                                 root=self.root, on_step=on_step, stopped=halted if turn else None)
            except synthetic.query_error as err:
                raise ApiError(400, str(err)) from None
            except synthetic.connection_error as err:
                if halted():
                    raise stopped() from None
                raise ApiError(502, str(err)) from None
            if halted():
                raise stopped()
            try:
                kind, payload = synthetic.parse_reply(reply)
            except synthetic.protocol_error as err:
                raise ApiError(422, f"answer refused: {err}", session=session) from None
            if kind == "chat":
                return {"ok": True, "reply": "\n".join([*applied, payload]), "session": session, **({"calls": calls} if calls else {})}
            items, results, shown, refusal = self._load(), [], [], None
            named = lambda call: synthetic.call_target(uid, call)
            denied = lambda line, err: f"- {line} refused: {err}"
            runs = [call for call in payload if synthetic.is_run(call)]
            delegations = [call for call in payload if synthetic.is_delegation(call)]
            for call in payload:
                if synthetic.is_run(call) or synthetic.is_delegation(call):
                    continue
                if halted():
                    raise stopped(results, payload, shown)
                if call["tool"] in synthetic.TOOLS and not tree:
                    refusal = denied(f"{call['tool']} {named(call)}", ApiError(403, TREE_REFUSAL))
                    break
                try:
                    results.append(_call(lambda: synthetic.apply_call(items, uid, call, syngate_dir=self.syngate_dir)))
                except ApiError as err:
                    refusal = denied(f"{call['tool']} {named(call)}", err)
                    break
                if not synthetic.is_query(call):
                    shown.append(results[-1])
            if runs and refusal is None:
                if halted():
                    raise stopped(results, payload, shown)
                try:
                    results.append(self._run_calls(items, [(named(call), call.get("name") or None) for call in runs], turn))
                    shown.append(results[-1])
                except ApiError as err:
                    refusal = denied(f"test {' '.join(dict.fromkeys(named(call) for call in runs))}", err)
            if delegations and refusal is None:
                reported = len(results)
                delegated = self._delegate(items, uid, data, delegations, turn, results)
                shown += results[reported:]
                if delegated:
                    err, line = delegated
                    refusal = denied(line, err)
            if halted():
                raise stopped(results, payload, shown)
            if refusal:
                results.append(refusal)
                shown.append(refusal)
            batch_step(results, payload)
            applied += shown
            calls += payload
            if refusal is None and not any(synthetic.is_query(call) for call in payload) and not runs and not delegations:
                return {"ok": True, "reply": "\n".join(applied), "session": session, "calls": calls}
            text = synthetic.RESULTS_PREAMBLE + "\n".join(results)
        raise ApiError(422, "\n".join([*applied, "answer refused: the exchange kept querying"]), session=session)

    def _delegate(self, items, anchor, data, calls, turn, results):
        """Every agent call of a batch as a turn of its item's chat with the call's prompt, in the setup of `data` the call may override,
        all running in parallel and awaited -- a stop of the parent `turn` starts none more and stops the running ones. Each child's
        report joins `results` and its transcript the parent's steps as an agent step; a child switches the `tree` mode on only when the
        parent has it; -> (error, line) of the call refused, which starts none after it."""
        started, refusal = [], None
        for call in calls:
            child = synthetic.call_target(anchor, call)
            setup = {**{key: data[key] for key in SETUP_KEYS if key in data}, **{key: call[key] for key in ("model", "effort", "modes") if key in call}}
            if "tree" not in (data.get("modes") or ()):
                own = setup["modes"] if "modes" in setup else self.chats[child].setup.get("modes") if child in self.chats else ()
                setup["modes"] = [mode for mode in own or () if mode != "tree"]
            try:
                if turn and turn.stopped:
                    raise ApiError(409, "turn stopped")
                if child == anchor:
                    raise ApiError(409, "the anchored item runs this turn — delegate to another item or do the work in this turn")
                if child not in items:
                    raise ApiError(404, f"unknown UID '{child}'")
                key = self.start_turn({**setup, "uid": child, "text": call["prompt"], "agent": turn.id if turn else anchor})["turn"]
            except ApiError as err:
                refusal = (err, f"agent {child}")
                break
            step, shift = {"kind": "agent", "uid": child, "prompt": call["prompt"], "report": None, "steps": [], "at": 0}, turn.elapsed() if turn else 0
            started.append((self._turn(key), step, shift))
            if turn:
                turn.add_step(step, shift)
                turn.children.append(started[-1][0])
                if turn.stopped:
                    self.stop_turn(key)
        for child, step, shift in started:
            outcome = child.snapshot(wait=None)
            step.update(report=outcome.get("reply", outcome.get("error")), steps=outcome.get("steps", []))
            if turn:
                turn.add_step(step, shift)
            results.append(f"- agent {step['uid']}: {step['report']}")
        return refusal

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
        items = self._load()
        if action != "test" and not syngatelib.features(items)["review"]:
            raise ApiError(400, str(syngatelib.feature_off("review")))
        argv = [*self.cli_prefix, action]
        if action == "clear":
            argv += uids
        else:
            under = syngatelib.items_under if action == "review" else syngatelib.leaves_under
            targets = list(dict.fromkeys(target for uid in uids for target in under(items, uid)))
            if not targets:
                raise ApiError(400, f"no leaf with a test under {', '.join(uids)}")
            argv += [*targets, "--build-dir", str(data.get("build_dir") or self.build_dir), "--coverage-out", str(coverage_out or self.run_coverage)]
        job = self.jobs.start(argv, cwd=self.root)
        return {"job": job.id}

    def cancel_job(self, job_id):
        job = self.jobs.get(job_id)
        if job is None:
            raise ApiError(404, f"no such job {job_id}")
        threading.Thread(target=self.jobs.cancel, args=(job,), daemon=True).start()
        return {"ok": True}


def _page_bytes(nonce):
    page = (Path(__file__).resolve().parent / "syngate_ui.html").read_bytes()
    return page.replace(b"<script>", b'<script nonce="' + nonce + b'">').replace(b"<style>", b'<style nonce="' + nonce + b'">')


def _csp(nonce):
    return (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src-elem 'nonce-{nonce}'; style-src-attr 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'")


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
        supplied = self.headers.get("X-Syngate-Token") or (query.get("token") or [""])[0]
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
                                 "files": self.app.file_shas(parse_qs(urlsplit(self.path).query).get("file", []))})
            elif path == "/api/file":
                self._json(200, self.app.read_file((parse_qs(urlsplit(self.path).query).get("path") or [""])[0]))
            elif path == "/api/chats":
                query = parse_qs(urlsplit(self.path).query)
                since = query.get("since")
                self._json(200, self.app.chats_snapshot(_number(since[0], "since", int) if since else None,
                                                        min(_number((query.get("wait") or ["0"])[0], "wait"), 30)))
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
                self._json(200, self.app.stop_turn(match.group(1)))
            elif (match := re.fullmatch(r"/api/job/(\d+)/cancel", path)):
                self._json(200, self.app.cancel_job(int(match.group(1))))
            else:
                self._json(404, {"error": f"no route for POST {path}"})
        except ApiError as exc:
            self._json(exc.status, {"error": str(exc), **exc.extra})
        except ConnectionError:
            pass
        except Exception as exc:
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

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


def make_server(app, port=DEFAULT_PORT):
    handler = type("BoundHandler", (_Handler,), {"app": app})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server


def serve(port=DEFAULT_PORT, coverage=(), build_dir=DEFAULT_BUILD_DIR, open_browser=True, root=None):
    root = syngatelib.find_root(root)
    coverage = list(coverage) or [str(Path(root) / name) for name in DEFAULT_COVERAGE if (Path(root) / name).is_file()]
    app = SyngateUIApp(root=root, coverage=coverage, build_dir=build_dir)
    try:
        server = make_server(app, port)
    except OSError as exc:
        print(f"syngate ui: cannot bind 127.0.0.1:{port}: {exc}", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{server.server_address[1]}/?token={app.token}"
    print(f"syngate ui: serving the syngate editor at {url}", flush=True)
    if coverage:
        print(f"syngate ui: coloring statuses from {', '.join(coverage)}")
    else:
        print("syngate ui: no coverage files found; leaf statuses show as not run until tests are run from the page (or pass --coverage FILE)")
    print("syngate ui: loopback only; the URL token is this session's key. Ctrl+C stops the server.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nsyngate ui: stopped")
    finally:
        app.jobs.cancel()
        app.save_chats()
        server.server_close()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"listen port on 127.0.0.1 (default {DEFAULT_PORT}, 0 = ephemeral)")
    parser.add_argument("--coverage", action="append", default=[], help="syngate_coverage.jsonl file(s) to color statuses; repeatable (default: well-known local files)")
    parser.add_argument("--build-dir", default=DEFAULT_BUILD_DIR, help="build tree the test runner uses for test and review runs")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    parser.add_argument("--root", help="managed project root (default: SYNGATE_ROOT, else the nearest ancestor of the working directory holding syngate/)")
    args = parser.parse_args()
    return serve(port=args.port, coverage=args.coverage, build_dir=args.build_dir, open_browser=not args.no_browser, root=args.root)


if __name__ == "__main__":
    sys.exit(main())
