# Open Trader
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Synthetic, the AI harness core of AI Assassin: the prompt library of skills and tools, item seed context, AI connections and the tool call protocol of a reply."""

import difflib
import hashlib
import json
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

import yaml

from . import cc_transcript, syngatelib
from . import tiering

CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
CLAUDE_MODEL_EFFORTS = {"fable": CLAUDE_EFFORTS, "opus": CLAUDE_EFFORTS, "sonnet": CLAUDE_EFFORTS, "haiku": CLAUDE_EFFORTS}
CLAUDE_MODELS = tuple(CLAUDE_MODEL_EFFORTS)
AGENT_TOOLS = ("Agent", "Task")
WORKFLOW_TOOL = "Workflow"
ANSWER_TOOL = "StructuredOutput"
SNAPSHOT_SKIPPED = ("__pycache__", "node_modules")
SNAPSHOT_LIMIT = 1 << 20
PLUGIN_NAME = "synthetic"

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
DEFAULT_PROMPT = "default"
FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
SKILLS_ON_REQUEST = "# Skills on request\nLoad one with the `skill` tool:\n"
# The library deliveries a connection declares, and a skill may name to enter the system prompts of those connections alone.
DELIVERIES = ("text", "native")
# The tokens the content of the files of a seed context may take before the rest is held back as references (`orchestrator.budget` of the server settings).
FILE_BUDGET = 50000
HELD_BACK = "File held back: {reference} -- not included, read it with the files tool\n"
CONTEXT_UPDATE = "Context update -- what changed since this session started:\n"


class prompt(NamedTuple):
    """One markdown file of the library: its stem is the name, its front matter the `kind` (skill|tool|agent), the `description`
    listing it and whether it is default -- a skill in the default prompt, a tool in every agent but a verdict one; the text is the body after the front matter. A tool's `calls`
    map each call it defines to its `required` string fields and its `optional` JSON-schema properties. An agent's `tools` and `skills`
    are the lists of the library prompts its system prompt holds, its `schema` the answer schema of a verdict agent and its
    `examples` the phrasings it is matched from a message by. A skill's `delivery` names the library delivery of the connections
    whose system prompts it enters, None for every connection. Its `requires` are the commands it needs to be offered, its `feature` the
    facility it serves as one of several alternatives, preferred by its `rank`."""
    name: str
    kind: str
    description: str
    default: bool
    text: str
    calls: dict | None = None
    tools: tuple = ()
    skills: tuple = ()
    schema: dict | None = None
    examples: tuple = ()
    delivery: str | None = None
    requires: tuple = ()
    feature: str | None = None
    rank: int | None = None


def names_of(value):
    return tuple(str(name) for name in value) if isinstance(value, list) else ()


def requirements_of(value):
    """The entries of a `requires` field as given, one entry standing alone taken as a list of it; () without the field."""
    return () if value is None else tuple(value) if isinstance(value, list) else (value,)


def rank_of(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def read_prompt(path):
    raw = path.read_text(encoding="utf-8")
    match = FRONT_MATTER_RE.match(raw)
    meta = (yaml.safe_load(match.group(1)) if match else None) or {}
    body = raw[match.end():] if match else raw
    return prompt(path.stem, str(meta.get("kind") or "skill"), str(meta.get("description") or ""), bool(meta.get("default")),
                  body.strip("\n") + "\n", meta.get("calls") or None, names_of(meta.get("tools")), names_of(meta.get("skills")),
                  meta.get("schema") if isinstance(meta.get("schema"), dict) else None, names_of(meta.get("examples")),
                  meta["delivery"] if meta.get("delivery") in DELIVERIES else None, requirements_of(meta.get("requires")),
                  str(meta["feature"]) if meta.get("feature") else None, rank_of(meta.get("rank")))


def load_prompts(prompts_dir=None):
    """The prompt library: name -> prompt of every markdown file under `prompts_dir` (`PROMPTS_DIR` as it is set at the call), the name
    being the file stem -- read from the files at every call, nothing of it kept."""
    return {path.stem: read_prompt(path) for path in sorted(Path(prompts_dir or PROMPTS_DIR).glob("*.md"))}


class live_mapping(Mapping):
    """A mapping built anew by `build` at every access -- for the library, the prompt files read again -- holding nothing of what it maps;
    a reader wanting one consistent view takes `dict(mapping.items())`, one build."""

    def __init__(self, build):
        self.build = build

    def __getitem__(self, key):
        return self.build()[key]

    def __iter__(self):
        return iter(self.build())

    def __len__(self):
        return len(self.build())

    def __contains__(self, key):
        return key in self.build()

    def keys(self):
        return self.build().keys()

    def items(self):
        return self.build().items()

    def values(self):
        return self.build().values()

    def __repr__(self):
        return f"live_mapping({self.build()!r})"


def read_library(library=None):
    """One consistent view of `library` -- the shipped one by default -- read from the prompt files at this call when it is a live one."""
    return load_prompts() if library is None else dict(library.items())


def skills_of(library):
    return {name: entry for name, entry in library.items() if entry.kind == "skill"}


def prompt_texts(library):
    """Every prompt's text by name, and the default prompt composed from them."""
    return {**{name: entry.text for name, entry in library.items()}, DEFAULT_PROMPT: default_prompt(library)}


def delivers(entry, delivery):
    """Whether the skill enters a system prompt sent over a connection of the library `delivery`: it names none, or that one."""
    return entry.delivery in (None, delivery)


def default_prompt(library):
    """The default prompt composed from the library: the default skills of text delivery, the list of the skills on request by
    name and description, then every tool definition."""
    skills = [entry for entry in library.values() if entry.kind == "skill"]
    on_request = "\n".join(f"- `{entry.name}`: {entry.description}" for entry in skills if not entry.default) or "none"
    return "\n".join([*(entry.text for entry in skills if entry.default and delivers(entry, "text")), SKILLS_ON_REQUEST + on_request + "\n",
                      *(entry.text for entry in library.values() if entry.kind == "tool")])


def native_prompt(library):
    """The head of a seed context for a connection that takes the library natively: the default skills of native delivery only, the
    skills on request and the tool definitions reaching the provider through its own configuration."""
    return "\n".join(entry.text for entry in library.values() if entry.kind == "skill" and entry.default and delivers(entry, "native"))


def library_calls(library):
    """The calls the tools of `library` define: name -> its required fields."""
    return {name: tuple(spec.get("required") or ()) for entry in library.values() if entry.kind == "tool" for name, spec in (entry.calls or {}).items()}


def load_agents(library=None):
    """The agents by name: the prompts of `kind: agent` of the library -- the shipped one by default -- and no others."""
    return {name: entry for name, entry in read_library(library).items() if entry.kind == "agent"}


def is_verdict(agent):
    """Whether the agent is a verdict agent: one whose prompt declares an answer schema."""
    return agent.schema is not None


def agent_library(agent, library=None, delivery=None):
    """The prompts of the library an agent's lists name -- its skills, then its tools, in their order -- then the default tools of the library
    its tool list lacks, the library's other prompts left out; a verdict agent has none. With a `delivery`, a listed skill naming another one
    is left out too."""
    library = read_library(library)
    if is_verdict(agent):
        return {}
    listed = {**{name: library[name] for name in agent.skills if name in library and library[name].kind == "skill"
                 and (delivery is None or delivers(library[name], delivery))},
              **{name: library[name] for name in agent.tools if name in library and library[name].kind == "tool"}}
    return {**listed, **{name: entry for name, entry in library.items() if entry.kind == "tool" and entry.default and name not in listed}}


def agent_prompt(agent, library=None, delivery="text"):
    """The whole system prompt of an agent's turn on a connection of the library `delivery`: its own text, then the skills and tools
    its lists name, a skill naming another delivery left out."""
    return "\n".join([agent.text, *(entry.text for entry in agent_library(agent, library, delivery).values())])


def agent_calls(agent, library=None):
    """The calls an agent's answer may carry: those of the tools its `tools` list names, with their required fields."""
    return library_calls(agent_library(agent, library))


def agent_schema(agent, library=None, text=True):
    """The answer schema of an agent's turn: a verdict agent's own, else the structured answer of the tools its `tools` list names, with
    its `text` field or without as `answer_schema` builds it."""
    return agent.schema if is_verdict(agent) else answer_schema(agent_library(agent, library), text)


def agent_locator(section, name):
    """The model locator of the agent `name` in the `orchestrator` section of the server settings -- the head of the `agents` entry of its name,
    one locator or a list of them best first, else of the `default` one -- as {connection, model, effort}; None while neither names one."""
    agents = section.get("agents") if isinstance(section, dict) and isinstance(section.get("agents"), dict) else {}
    for entry in (agents.get(name), agents.get("default")):
        for locator in entry if isinstance(entry, list) else [entry]:
            if isinstance(locator, dict) and all(isinstance(locator.get(key), str) and locator[key].strip() for key in ("connection", "model")):
                return {"connection": locator["connection"], "model": locator["model"],
                        "effort": locator.get("effort") if isinstance(locator.get("effort"), str) else None}
    return None


# The shipped library and what derives from it, each re-read from the prompt files whenever it is read: an edit of a prompt reaches the
# next turn of every session without a restart.
LIBRARY = live_mapping(load_prompts)
SKILLS = live_mapping(lambda: skills_of(load_prompts()))
PROMPTS = live_mapping(lambda: prompt_texts(load_prompts()))
CALL_BLOCK_RE = re.compile(r"```syngate[ \t]*\n(.*?)\n[ \t]*```", re.DOTALL)
TOOLS = {"add": ("uid", "description"), "edit": ("uid",), "remove": ("uid",), "move": ("uid", "to"), "rename": ("uid", "new_uid")}
QUERIES = {"query": ("uid",), "context": ("uid",), "skill": ("name",)}
# The mark of the statement a seed context is formed for, the exchange's own item; a `context` call of another item names its own label instead.
ACTIVE_LABEL = "active item"
RUNS = {"test": ("uid",)}
# An agent call names the item it delegates to by `uid`, or the off-context agent of the library it runs by `name`: one of the two.
DELEGATIONS = {"agent": ()}
# The message a delegated turn starts with when its agent call names no prompt: the item's statement, in the seed context it is anchored
# at, is the task, so the parent need not restate it.
DELEGATION_TEXT = ("Carry out @{uid}: its statement, with the context this chat is seeded with, is your task. Bring the project to what it "
                   "states, then report what you did and what still blocks it.")
GITS = {"git": ("command",)}
GREPS = {"grep": ("command",)}
SURFS = {"websurf": ("action",)}
PATCHES = {"patch": ("diff",), "replace": ("path", "old")}
SHELLS = {"shell": ("command",)}
FILES = {"list": (), "read": ("path",)}
LOGS = {"log": ()}
SETUPS = {"models": (), "setup": ("connection", "model", "reason")}
CALLS = {**TOOLS, **QUERIES, **RUNS, **DELEGATIONS, **GITS, **GREPS, **SURFS, **PATCHES, **SHELLS, **FILES, **LOGS, **SETUPS}
# The Raw command call mode as a connection without a shell of its own lists it: its shell calls run through the harness only while it
# is on. The Claude Code connector lists its own `bash` mode, which allows the CLI's Bash tool.
BASH_MODE = {"id": "bash", "label": "Raw command", "hint": "run shell commands", "default": False, "advanced": True}
# Seconds the command of a prompt's requirement may run before it counts as unmet.
PROBE_TIMEOUT = 10
EDITABLE = ("description", "sources", "tests", "setup")
QUERY_ROUNDS = 100  # a fuse far above normal work, `orchestrator.rounds` of the server settings in its place: a count of rounds cannot tell a loop from work
# What a turn the harness closes -- at its fuse or stalled -- is asked with its last prompt: one text answer, the turn's reply.
TURN_CLOSING = ("\nThe harness closes this turn here: answer now in text alone, with no calls -- what you did, what its tests showed and what is left. "
                "Calls in this answer end the turn refused.")
# The line heading the reply of a turn the harness closed, `why` telling the limit: the turn that delegated it reads it and decides how the task goes on.
TURN_CLOSED = "[turn closed by the harness: {why} — this is its closing report, the task may be unfinished]\n"
CLOSED_FUSE, CLOSED_STALL = "it reached its round fuse", "it stalled, repeating the same calls with the same results"
# What a turn is told the first time a round repeats the calls and results of the round before; the second repetition closes it.
STALL_NUDGE = ("\nThis round repeated the calls and results of the round before: change what you do, or answer in text. "
               "One more such round closes the turn.")
# A turn is told the rounds it has left once this few remain, so it finishes in text rather than runs out; a round past its bound is refused.
ROUNDS_WARNING = 3
ROUNDS_LEFT = "\nRounds of calls left in this turn: {left} — answer in text before they run out."
ROUNDS_OUT = "answer refused: the turn ran out of its {rounds} rounds (`websurf.rounds` of the server settings sets the bound of a turn that surfs)"
RUN_TAIL = 40
ANSWER_REFUSED = "Your last answer was refused, none of it was applied: {error}\nAnswer again in the answer format."
# A text answer ends the turn as its reply, so one with no text would end it on nothing.
EMPTY_ANSWER = "a text answer carries no text: write the reply that ends the turn, or hand over calls"
RESULTS_PREAMBLE = "Results of the calls in your last answer:\n"
# A message names an item the way a file is named: `@UID` brings the item's statement into the turn.
REFERENCE_RE = re.compile(r"@([A-Z][A-Z_]*(?:-[A-Z0-9_]+)*)\b")
HISTORY_PREAMBLE = "The exchange so far, as kept by the user:\n"
TREE_FEATURES = "\n# Tree features\ntest: {}\n"

STRING = {"type": "string"}
SOURCE_FENCE = "````"


def _call_schema(tool, spec):
    required = list(spec.get("required") or ())
    return {"type": "object", "properties": {"tool": {"const": tool}, **{field: STRING for field in required}, **(spec.get("optional") or {})},
            "required": ["tool", *required], "additionalProperties": False}


def answer_schema(library, text=True):
    """The structured answer as the JSON schema a connection hands its model, built from the call definitions of the library's tools --
    their texts as the description of the answer -- so the shape of a call is enforced by the model side rather than by the parser alone.
    Without `text` it has no field for the text: the schema of a carrier whose model writes its text outside the answer."""
    tools = [entry for entry in library.values() if entry.kind == "tool"]
    shapes = list({name: _call_schema(name, spec) for entry in tools for name, spec in (entry.calls or {}).items()}.values())  # one shape per call, as `library_calls` keeps it
    return {"type": "object", "description": "\n".join(entry.text for entry in tools),
            "properties": {"kind": {"enum": ["text", "calls"] if shapes else ["text"]}, **({"text": STRING} if text else {}),
                           **({"calls": {"type": "array", "minItems": 1, "items": {"anyOf": shapes}}} if shapes else {})},
            "required": ["kind"], "additionalProperties": False}


ANSWER_SCHEMA = live_mapping(lambda: answer_schema(load_prompts()))


def seed_context(items, uid, prompt=DEFAULT_PROMPT, root=None, head=None, label=None, heavy=None):
    """The named prompt of the library -- or the `head` text given in its place -- then the tree's test switch, then the statements of every
    ancestor, parents first, the item's own and those of all its descendants in sibling order -- an item reached twice enters once, at its
    first occurrence -- then the design files their statements link that no key source lists, each once, then the key source files those
    items list, each once, all read from `root`. The item's own statement is the one marked, with the `label` -- one line, the active item
    unless the caller names another -- after its `@UID`. The `heavy` files -- path -> reference -- stay out of the file sections: every item
    naming one keeps its reference under its statement, the statements themselves never cut."""
    if uid not in items:
        raise syngatelib.unknown_uid(f"unknown UID '{uid}'")
    selection = syngatelib.walk(items, uid, descendants=True)
    label = " ".join(str(label or ACTIVE_LABEL).split()) or ACTIVE_LABEL
    heavy = heavy or {}
    statements = "".join(statement_section(selected, items[selected].description, label if selected == uid else None) + held_back(items, selected, heavy)
                         for selected in selection)
    designs, sources = seed_files(items, selection, root)
    return ((PROMPTS[prompt] if head is None else head) + features_section(items, uid) + statements
            + "".join(design_section(rel, root) for rel in designs if rel not in heavy) + "".join(source_section(rel, root) for rel in sources if rel not in heavy))


def seed_files(items, selection, root=None):
    """(designs, sources) of a selection: the key source files its items list, each once in order, and the design files their statements link
    that no key source lists and that exist under `root`."""
    sources = list(dict.fromkeys(rel for selected in selection for rel in items[selected].sources))
    designs = [rel for rel in dict.fromkeys(rel for selected in selection for rel in syngatelib.linked_files(items[selected].description))
               if rel not in sources and (Path(root or syngatelib.ROOT) / rel).is_file()]
    return designs, sources


def held_back(items, uid, heavy):
    """The lines under an item's statement naming the heavy files it names, each as its reference; \"\" for an item naming none."""
    return "".join(HELD_BACK.format(reference=heavy[rel]) for rel in tiering.item_files(items, uid) if rel in heavy)


def features_section(items, uid=None):
    """The test switch as a section of the seed context -- the anchored item's, the tree's without one -- which tells the delivery skill whether the items await tests."""
    return TREE_FEATURES.format("enabled" if syngatelib.features(items, uid)["test"] else "disabled")


def statement_section(uid, description, label=None):
    """One item's statement as a section of the seed context: its `@UID` line -- followed by the `label` in parentheses where one is given -- over its text, ending in a line break."""
    return f"\n@{uid}{f' ({label})' if label else ''}\n{description}" + ("" if description.endswith("\n") else "\n")


def design_section(rel, root=None):
    """One design file a statement links as a section of the seed context: its root-relative path under `# Design` over its text in a fence."""
    text = (Path(root or syngatelib.ROOT) / rel).read_text(encoding="utf-8", errors="replace")
    return f"\n# Design {rel}\n{SOURCE_FENCE}\n{text}{'' if text.endswith(chr(10)) else chr(10)}{SOURCE_FENCE}\n"


def source_section(rel, root=None):
    """One key source file as a section of the seed context: its root-relative path over its text in a fence."""
    path = Path(root or syngatelib.ROOT) / rel
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return f"\n# Source {rel}\n(file not found)\n"
    if not text.endswith("\n"):
        text += "\n"
    return f"\n# Source {rel}\n{SOURCE_FENCE}\n{text}{SOURCE_FENCE}\n"


def referenced(items, text, contained=()):
    """The statements of the items named `@UID` in `text` that the seed context lacks -- `contained` being the UIDs it holds --
    each as one more section after the seed context."""
    found = [uid for uid in dict.fromkeys(REFERENCE_RE.findall(text)) if uid in items and uid not in contained]
    return "".join(statement_section(uid, items[uid].description) for uid in found)


def system_context(connection, items, uid, text, root=None, library=None, heavy=None):
    """The system prompt of a session on `connection` anchored at `uid`: the head its library delivery calls for over the seed context -- the
    `heavy` files held back -- and the statements `text` names."""
    library = read_library(library)
    head = native_prompt(library) if getattr(connection, "library_delivery", "text") == "native" else default_prompt(library)
    return seed_context(items, uid, root=root, head=head, heavy=heavy) + referenced(items, text, syngatelib.walk(items, uid, descendants=True))


def read_text(root, rel):
    """The text of the project file `rel` under `root`, None when it is no readable file."""
    try:
        return (Path(root or syngatelib.ROOT) / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def file_digest(root, rel):
    """The digest of the project file `rel` under `root`, None when it is no readable file."""
    try:
        return hashlib.sha1((Path(root or syngatelib.ROOT) / rel).read_bytes()).hexdigest()
    except OSError:
        return None


def selection_files(items, selection):
    """The files the items of a selection name, key sources and linked designs, each once in order."""
    return list(dict.fromkeys(rel for selected in selection for rel in tiering.item_files(items, selected)))


def measure_seed(items, uid, message, root=None, budget=FILE_BUDGET, embed=None, rerank=None, activity=None, weights=None):
    """The `tiering.measurement` of the seed context of `uid` for `message`: the files of its selection taken into the token `budget` in the order
    of their items' importance, which the signals of the message -- dense with an `embed`, reranked with a `rerank`, lexical, and the chat's
    `activity` -- fused under `weights` rank."""
    selection = syngatelib.walk(items, uid, descendants=True)
    rankings = tiering.signals(items, selection, message, embed=embed, rerank=rerank, activity=activity)
    contents = {rel: read_text(root, rel) for rel in selection_files(items, selection)}
    return tiering.measure(items, selection, message, uid, rankings, contents, budget, weights)


def new_keep(context, items, uid, measured, root=None):
    """What a session keeps of its start: the composed system prompt, the statements it holds, the heavy files by reference and the digest of every
    file its items name."""
    selection = list(measured.statements)
    return {"context": context, "statements": dict(measured.statements), "heavy": dict(measured.heavy),
            "hashes": {rel: file_digest(root, rel) for rel in selection_files(items, selection)}}


def refresh_keep(keep, root=None, paths=None):
    """Take the files as they are now for the session's own: the `paths` among those the session holds, else all of them."""
    hashes = keep.get("hashes")
    if isinstance(hashes, dict):
        for rel in list(hashes) if paths is None else [os.path.normpath(path) for path in paths if os.path.normpath(path) in hashes]:
            hashes[rel] = file_digest(root, rel)


def absorb(keep, items, uids):
    """Take the statements of the items `uids` as they are now for the session's own, so its own edits are no news to it: one the tree no longer
    holds is dropped."""
    held = keep.get("statements")
    if isinstance(held, dict):
        for uid in uids:
            if isinstance(uid, str):
                if uid in items:
                    held[uid] = items[uid].description
                else:
                    held.pop(uid, None)


def context_update(keep, items, uid, text, measured, root=None, told=()):
    """(update, kept) of a session since it started: the update heading its next prompt -- an item added, a statement edited, a heavy or new file
    the message `measured` now brings in whole, the files held back, a file changed by someone other than the session named and not resent, the
    statements `text` names -- \"\" when nothing changed; and the state kept, the system prompt in it untouched and no file taken back.
    A file the measurement now takes whole is brought in; an edit of an item in `told` is told elsewhere and left out."""
    selection = syngatelib.walk(items, uid, descendants=True)
    held, heavy, hashes = keep.get("statements") or {}, dict(keep.get("heavy") or {}), keep.get("hashes") or {}
    parts = []
    for selected in selection:
        description = items[selected].description
        if selected not in held:
            parts.append("\nItem added:" + statement_section(selected, description))
        elif held[selected] != description and selected not in told:
            parts.append("\nStatement edited, it now reads:" + statement_section(selected, description))
    files = selection_files(items, selection)
    digests = {rel: file_digest(root, rel) for rel in files}
    contents = {rel: read_text(root, rel) for rel in files if rel in heavy or rel not in hashes}
    whole = [rel for rel in measured.whole if contents.get(rel) is not None]
    still = [rel for rel in measured.heavy if contents.get(rel) is not None and rel not in heavy]
    sources = {rel for selected in selection for rel in items[selected].sources}
    for rel in whole:
        parts.append("\nFile brought in whole:" + (source_section(rel, root) if rel in sources else design_section(rel, root)))
    parts += ["\n" + HELD_BACK.format(reference=tiering.reference(rel, contents[rel])) for rel in still if rel not in heavy]
    parts += [f"\nFile changed by someone else, not resent -- read it with the files tool: {rel}\n"
              for rel in files if rel in hashes and rel not in heavy and hashes[rel] != digests[rel]]
    if named := referenced(items, text, selection):
        parts.append("\nItems you were pointed to:" + named)
    kept = {**keep, "statements": {selected: items[selected].description for selected in selection},
            "heavy": {**{rel: ref for rel, ref in heavy.items() if rel in files and rel not in whole},
                      **{rel: tiering.reference(rel, contents[rel]) for rel in still}}, "hashes": digests}
    return (CONTEXT_UPDATE + "".join(parts) if parts else ""), kept


def transcript(history, text):
    """The user's text headed by the kept messages of an exchange that has no session to resume."""
    if not history:
        return text
    lines = [f"{message.get('role') if message.get('role') in ('user', 'harness') else 'assistant'}: {message.get('text') or ''}" for message in history]
    return HISTORY_PREAMBLE + "\n".join(lines) + "\n\n" + text


def rounds_left(left):
    """The line closing a results prompt once `left` rounds or fewer remain of the turn, "" before."""
    return ROUNDS_LEFT.format(left=left) if left <= ROUNDS_WARNING else ""


def item_view(items, uid):
    """The item as the AI reads it back: its fields, its kind, the UIDs of its children in sibling order, for a leaf the names
    of its test bindings, "" naming the default one, and, for an item carrying one, its test setup."""
    if uid not in items:
        raise syngatelib.unknown_uid(f"unknown UID '{uid}'")
    item = items[uid]
    return {"uid": uid, "description": item.description, "parents": item.parents, "sources": list(item.sources),
            "children": syngatelib.sorted_children(items, syngatelib.children_map(items), uid),
            "kind": "branch" if item.tests is None else "leaf", **({} if item.tests is None else {"tests": [name or "" for name in item.tests]}),
            **({} if item.setup is None else {"setup": dict(item.setup)})}


def is_query(call):
    return call["tool"] in QUERIES


def is_run(call):
    return call["tool"] in RUNS


def is_delegation(call):
    return call["tool"] in DELEGATIONS


def is_git(call):
    return call["tool"] in GITS


def is_grep(call):
    return call["tool"] in GREPS


def is_surf(call):
    return call["tool"] in SURFS


def is_patch(call):
    return call["tool"] in PATCHES


def is_shell(call):
    return call["tool"] in SHELLS


def is_file(call):
    return call["tool"] in FILES


def is_log(call):
    return call["tool"] in LOGS


def is_setup(call):
    return call["tool"] in SETUPS


class setup_error(ValueError):
    """A setup call naming a connection, a model or an effort the models listing does not hold."""


def models_listing(connectors, current=None):
    """The models a chat may run on, one entry per model of every (name, connector) of `connectors` that tells its settings: its `connection`
    and `model`, the `family`, `tier` and `strengths` its settings give it, its `efforts`, and `current` on the model of the chat's own
    setup, `current` being its (connection, model)."""
    return [{"connection": name, "model": model["id"], **{field: model[field] for field in ("family", "tier", "strengths") if field in model},
             "efforts": list(model.get("efforts") or ()), **({"current": True} if current == (name, model["id"]) else {})}
            for name, connector in connectors if hasattr(connector, "settings") for model in connector.settings().get("models") or ()]


def models_report(listing):
    """The listing as the AI reads it back: one JSON line per model under a heading line."""
    return "\n".join(["- models:", *(json.dumps(entry, ensure_ascii=False) for entry in listing)]) if listing else "- models: none"


def recommend_setup(listing, call):
    """The line reporting the recommendation a setup call makes: the connection and model it names must be an entry of `listing`, and the
    effort it names, when it names one, one that entry lists; anything else raises `setup_error`."""
    chosen = next((entry for entry in listing if (entry["connection"], entry["model"]) == (call["connection"], call["model"])), None)
    if chosen is None:
        raise setup_error(f"{call['model']} of {call['connection']} is not in the models listing — call models and name one of its entries")
    effort = call.get("effort") or None
    if effort is not None and effort not in chosen["efforts"]:
        raise setup_error(f"{call['model']} of {call['connection']} lists no effort '{effort}' — its efforts: {', '.join(chosen['efforts']) or 'none'}")
    return f"- setup {call['connection']} {call['model']}{f' at {effort}' if effort else ''}: {' '.join(str(call['reason']).split())}"


def requirement_key(entry):
    """(argv, output) of a well-formed requirement -- a mapping of a `command` that is a non-empty list of words and an optional `output`
    text --, None of any other entry."""
    if not isinstance(entry, dict):
        return None
    command, output = entry.get("command"), entry.get("output")
    if not (isinstance(command, list) and command and all(isinstance(word, str) for word in command)) or not (output is None or isinstance(output, str)):
        return None
    return tuple(command), output


def probe(root, command, output=None, timeout=None):
    """Whether a requirement is met: `command` run in `root` without a shell or stdin exits 0 within `timeout` seconds (`PROBE_TIMEOUT`)
    and, where `output` is named, prints it on its stdout or stderr."""
    try:
        done = subprocess.run(list(command), cwd=root, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace",
                              timeout=PROBE_TIMEOUT if timeout is None else timeout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and (output is None or output in done.stdout or output in done.stderr)


class requirement_probes:
    """The outcomes of the requirements probed in one server's run for the project `root`, keyed by command and output: each probed once,
    at its first need, and kept for every later read."""

    def __init__(self, root=None):
        self.root, self.outcomes, self.lock = Path(root or syngatelib.ROOT), {}, threading.Lock()

    def met(self, entry):
        """Whether the requirement `entry` is met, a malformed one never."""
        key = requirement_key(entry)
        if key is None:
            return False
        with self.lock:
            if key not in self.outcomes:
                self.outcomes[key] = probe(self.root, *key)
            return self.outcomes[key]


def offer(library, probes):
    """The offered part of `library`, in its order: every prompt whose requirements `probes` finds met, and of the prompts naming one feature
    only the first by rank -- a lower one first, an unranked one after every ranked, ties by name -- whose requirements are, the others
    of the feature probed no further."""
    taken, offered = set(), set()
    for entry in sorted(library.values(), key=lambda entry: (entry.rank is None, entry.rank or 0, entry.name)):
        if entry.feature is not None and entry.feature in taken:
            continue
        if all(probes.met(requirement) for requirement in entry.requires):
            offered.add(entry.name)
            if entry.feature is not None:
                taken.add(entry.feature)
    return {name: entry for name, entry in library.items() if name in offered}


def offered_library(root=None, library=None, probes=None):
    """The library a chat on the project `root` is offered: the `offer` of `library` -- the shipped one by default -- under `probes`, those of
    one server's run, a new set without them; a live view taking the prompt files as they are at every access, a requirement once probed
    not run again."""
    probes = requirement_probes(root) if probes is None else probes
    return live_mapping(lambda: offer(read_library(library), probes))


def run_report(items, targets, records, output=()):
    """The outcome of a run as the AI reads it back: one line per addressed leaf binding -- `targets` being (uid, binding|None),
    None standing for every binding of the leaf -- with pass/fail, a binding without a record having failed, then the captured
    output of every failed routine; a failed binding no routine output tells of -- one the runner could not run or address --
    shows the lines of the run's `output` naming its item, else the run's last lines."""
    lines, logs = [], []
    for uid, name in targets:
        declared = [name] if name else list(items[uid].tests) if uid in items and items[uid].is_leaf else []
        for binding in declared or [found for found_uid, found in records if found_uid == uid] or [None]:
            found = list({record["name"]: record for record in records.get((uid, binding), [])}.values())
            label = f"{uid}:{binding}" if binding else uid
            passed = bool(found) and all(record["passed"] for record in found)
            lines.append(f"- {label}: {'pass' if passed else 'fail'}")
            told = [record["log"] for record in found if not record["passed"] and record["log"]]
            if not passed and not told:
                told = ["\n".join([line for line in output if uid in line] or list(output)[-RUN_TAIL:]) or "the run left no record and no output"]
            logs += [f"{label} output:\n{log}" for log in told]
    return "\n".join(lines + logs)


class connection_error(Exception):
    pass


class query_error(ValueError):
    pass


class protocol_error(ValueError):
    pass


def call_target(anchor, call):
    """What a call addresses, as its refusal names it: the item, `@` standing for the anchored one, or the skill."""
    if "uid" not in call:
        return call["name"]
    return anchor if call["uid"] == "@" else call["uid"]


def split_reply(reply):
    """(text, calls) of an answer: the text said beside its calls, "" when none, and the calls -- None for a plain text answer. A structured
    answer carries them as its `calls` and `text` fields; a plain one as the `syngate` blocks, which join in order, the prose around them
    being its text with leaked tool markup taken out. Malformed JSON in a block is refused, and so are calls written as native tool-use
    markup with no block, which would otherwise end the turn as text."""
    if isinstance(reply, dict):
        calls = reply.get("calls")
        if reply.get("kind") == "text" and not calls:
            if LEAKED_CALL_RE.search(str(reply.get("text") or "")):
                raise protocol_error(LEAKED_CALL)
            return reply.get("text") or "", None
        return reply.get("text") or "", calls
    blocks = CALL_BLOCK_RE.findall(reply)
    if "```syngate" in CALL_BLOCK_RE.sub("", reply):
        raise protocol_error("tree calls are cut off before their closing fence")
    if not blocks:
        if LEAKED_CALL_RE.search(reply):
            # a model trained on native tool use may write its calls that way: ending the turn on them as text would leave them unrun
            raise protocol_error(LEAKED_CALL)
        return reply, None
    calls = []
    for block in blocks:
        try:
            parsed = json.loads(block)
        except ValueError as exc:
            raise protocol_error(f"tree calls are not valid JSON: {exc}") from None
        if not isinstance(parsed, list):
            raise protocol_error("tree calls must be a non-empty JSON list of objects")
        calls += parsed
    return TOOL_MARKUP_RE.sub("", CALL_BLOCK_RE.sub("", reply)).strip(), calls


def parse_reply(reply, known=CALLS):
    """("chat", text) for a plain answer, ("calls", [call, ...]) for the tree calls of an answer, the text said beside them split off by
    `split_reply` (`query` hands it to the chat as a message). Every call is checked against `known`, the calls the answer may carry with
    their required fields, those of the tool library by default; a plain answer carrying no text is refused."""
    text, calls = split_reply(reply)
    if calls is None:
        if not str(text).strip():
            raise protocol_error(EMPTY_ANSWER)
        return "chat", text
    if not isinstance(calls, list) or not calls or not all(isinstance(call, dict) for call in calls):
        raise protocol_error("tree calls must be a non-empty JSON list of objects")
    for call in calls:
        tool = call.get("tool")
        if tool not in known:
            raise protocol_error(f"unknown tree call {tool!r}")
        missing = [name for name in known[tool] if not (isinstance(call.get(name), str) and call[name].strip())]
        if missing:
            raise protocol_error(f"{tool}: missing {', '.join(missing)}")
        if tool == "agent" and not any(isinstance(call.get(field), str) and call[field].strip() for field in ("uid", "name")):
            raise protocol_error("agent: missing uid or name")
        if "background" in call and not isinstance(call["background"], bool):
            raise protocol_error(f"{tool}: background must be true or false")
        if tool == "context" and "label" in call and not (isinstance(call["label"], str) and call["label"].strip()):
            raise protocol_error("context: label must be a line of text")
        if tool == "context" and "for" in call and not (isinstance(call["for"], str) and call["for"].strip()):
            raise protocol_error("context: for must be a line of text")
        if tool == "edit" and not ((isinstance(call.get("description"), str) and call["description"].strip())
                                   or any(isinstance(call.get(field), list) for field in ("sources", "tests"))
                                   or "setup" in call and (call["setup"] is None or isinstance(call["setup"], dict))):
            raise protocol_error(f"edit: missing {' or '.join(EDITABLE)}")
    return "calls", calls


def apply_call(items, anchor, call, syngate_dir=None, measure=None, library=None):
    """Perform one parsed Syngate API call against the loaded tree, `@` standing for the
    anchored item. -> the line reporting what it did, or what a query read; a refusal raises
    `syngatelib.tree_error`.

    No call passes `clear`: a stamp an AI answer moves is deliberately left
    standing over the changed content, so the user meets a violated review
    rather than a silently unreviewed item.

    A `context` call is measured when `measure` -- (uid, purpose) -> the heavy files by path and reference -- is given, `purpose` being the
    call's `for` text or None; without it every file enters whole. A `skill` call brings a skill of `library`, the shipped one by default."""
    at = lambda value: anchor if value == "@" else value
    tool, uid = call["tool"], at(call.get("uid"))
    if tool in RUNS or tool in DELEGATIONS or tool in GITS or tool in GREPS or tool in SURFS or tool in PATCHES or tool in SHELLS or tool in FILES or tool in LOGS or tool in SETUPS:
        raise syngatelib.tree_error(f"{tool} runs through the page's harness, not against the tree")
    if tool == "skill":
        skill = skills_of(read_library(library)).get(call["name"])
        if skill is None:
            raise syngatelib.tree_error(f"unknown skill '{call['name']}'")
        return f"- skill {call['name']}:\n{skill.text}"
    if tool == "query":
        return f"- {uid}: {json.dumps(item_view(items, uid), ensure_ascii=False)}"
    if tool == "context":
        heavy = measure(uid, call.get("for")) if measure and uid in items else None
        return f"- context of {uid}:\n{seed_context(items, uid, root=Path(syngate_dir).parent if syngate_dir else None, label=call.get('label'), heavy=heavy)}"
    if tool == "add":
        parent = at(call.get("parent") or "@")
        family = syngatelib.sorted_children(items, syngatelib.children_map(items), parent) if parent in items else []
        last = items[family[-1]] if family else items.get(parent)
        syngatelib.add_item(items, uid, [parent], description=call["description"], kind=call.get("kind") or "leaf",
                            folder=last.folder if last else None, order=last.order + 10 if family else 0,
                            sources=call.get("sources"), syngate_dir=syngate_dir)
        return f"- added {uid} under {parent}"
    if tool == "edit":
        syngatelib.edit_item(items, uid, {field: call[field] for field in EDITABLE if field in call})
        return f"- edited {uid}"
    if tool == "remove":
        syngatelib.delete_item(items, uid)
        return f"- removed {uid}"
    if tool == "rename":
        syngatelib.rename_item(items, uid, call["new_uid"])
        return f"- renamed {uid} to {call['new_uid']}"
    if tool != "move":
        raise syngatelib.tree_error(f"{tool} is not a call of the tree")
    source, target, link = at(call.get("from")), at(call["to"]), bool(call.get("link"))
    if source is None and uid in items and len(items[uid].parents) == 1:
        source = items[uid].parents[0]
    if source is None and uid in items and not link:
        raise syngatelib.tree_error(f"{uid} has several parents; name the one to re-point in 'from' or pass 'link'")
    syngatelib.move_item(items, uid, target, before=at(call.get("before")), source=source, link=link)
    return f"- moved {uid} under {target}"


def squeezed(text):
    """The text with every run of whitespace turned into one space, the ends stripped: how two reports of one message are compared."""
    return " ".join(str(text).split())


def query(connectors, items, uid, text, connector, model, effort, modes=(), session=None, history=(), root=None, on_step=None, stopped=None,
          library=None, images=(), agent=None, context=None):
    """(reply text, session id) of one exchange anchored at `uid` -- or, for an off-context `agent`, started from its chat above the agent's
    prompt alone, without seed context, the agent handed to the dispatch -- sent through the named connection with the exact model, effort and call modes,
    every step of the turn reaching `on_step` as it happens; `stopped` tells the connection whether the turn was stopped meanwhile.
    The `images` -- each `{media_type, data}`, the data in base64 -- go with the text, handed to the dispatch only when there are any.
    The seed context -- its key sources read from `root` -- grows by the statements the text references; without a session to resume,
    the kept `history` heads the text. The prompt `library` (the shipped one by default) heads the seed context as the default prompt, or,
    for a connection with native library delivery, only by its default skills; it is handed to the dispatch of every connection that
    declares its library delivery. The text said beside the calls of the answer becomes a message step only when the connection has not
    streamed it already -- as a message of its own or within one, whitespace aside -- so a text is one block however it was reported.
    A model listing no efforts goes with the effort None. A `context` given -- the system prompt a session
    composed once -- is sent as it stands in place of one composed now."""
    connection = connectors.get(connector)
    if uid not in items:
        raise query_error(f"unknown UID '{uid}'")
    if connection is None:
        raise query_error(f"unknown connector '{connector}'")
    if model not in connection.models or effort not in (*connection.efforts, None):
        raise query_error(f"unknown model '{model}' or effort '{effort}'")
    if not set(modes) <= set(connection.modes):
        raise query_error(f"unknown mode in {sorted(modes)}")
    if not text.strip():
        raise query_error("empty input")
    library = read_library(library)
    if agent is not None:
        context = agent_prompt(agent, library, getattr(connection, "library_delivery", "text"))
    elif context is None:
        context = system_context(connection, items, uid, text, root, library)
    streamed = []

    def hear(step):
        if step.get("kind") == "message":
            streamed.append(squeezed(step.get("text")))
        if on_step:
            on_step(step)

    answer, session = connection.dispatch(context, text if session else transcript(history, text), model=model, effort=effort, modes=modes,
                                          session=session, on_step=hear if on_step else None, **({"stopped": stopped} if stopped else {}),
                                          **({"library": library} if hasattr(connection, "library_delivery") else {}),
                                          **({"images": list(images)} if images else {}), **({"agent": agent} if agent is not None else {}))
    try:
        beside, calls = split_reply(answer)
    except protocol_error:
        beside, calls = "", None  # the turn refuses the malformed calls itself
    said = squeezed(beside)
    if on_step and calls is not None and said and not any(said in earlier for earlier in streamed):
        on_step({"kind": "message", "text": beside})
    return answer, session


def verdict(connectors, agent, data, connector, model, effort=None, library=None):
    """The JSON answer of a verdict `agent` judging `data`, which goes in fenced as the message of one fresh turn above the agent's prompt
    alone, its schema the answer schema; an answer that is no JSON object raises `protocol_error`, since the harness reads it."""
    connection = connectors.get(connector)
    if connection is None:
        raise query_error(f"unknown connector '{connector}'")
    library = read_library(library)
    answer, _ = connection.dispatch(agent_prompt(agent, library), f"{SOURCE_FENCE}\n{data}\n{SOURCE_FENCE}", model=model, effort=effort, agent=agent,
                                    **({"library": library} if hasattr(connection, "library_delivery") else {}))
    if isinstance(answer, str):
        try:
            answer = json.loads(answer)
        except ValueError:
            raise protocol_error(f"the {agent.name} agent answered no JSON") from None
    if not isinstance(answer, dict):
        raise protocol_error(f"the {agent.name} agent answered no JSON object")
    return answer


def result_text(content):
    if isinstance(content, list):
        return "\n".join(str(block.get("text") or "") for block in content if isinstance(block, dict) and block.get("type") == "text")
    return "" if content is None else content if isinstance(content, str) else json.dumps(content)


def anchor_of(prompt):
    """The item a subagent prompt opens with, `@UID` on its first line."""
    match = REFERENCE_RE.search(prompt.split("\n", 1)[0])
    return match.group(1) if match else None


def read_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def read_jsonl(path):
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


class turn_steps:
    """The steps of one `claude` turn folded from its stream-json events as they come. A step is announced through `on_step` when it
    starts and again, as the same top-level object, whenever it or a step nested in it changes; `at` counts seconds since the start.
    The events of a subagent nest in its agent step; those inside a workflow stay out, a workflow being one opaque step. An assistant's
    text is a `message` step, but for a subagent's closing one, which is its report; the turn's answer is the structured output.
    A text of the turn's own is held back until what follows tells which it is: a message once a tool call of the CLI's own or a calls
    answer follows, the reply -- no step, kept as `text` -- on a text answer or at the result. `text` is what the model wrote ahead of
    its last answer, "" where a call made it a message; None while no answer tool was called and nothing was written ahead of the result."""

    def __init__(self, on_step=None):
        self.on_step = on_step or (lambda step: None)
        self.started, self.wall = time.monotonic(), time.time()
        self.steps, self.result, self.noise, self.text = [], None, [], None
        self.open, self.agents, self.top, self.seen, self.held = {}, {}, {}, set(), []

    def now(self):
        return round(time.monotonic() - self.started, 2)

    def at_of(self, entry):
        try:
            return round(datetime.fromisoformat(str(entry["timestamp"]).replace("Z", "+00:00")).timestamp() - self.wall, 2)
        except (KeyError, ValueError):
            return self.now()

    def feed(self, line):
        try:
            event = json.loads(line)
        except ValueError:
            if line.strip():
                self.noise.append(line.strip())
            return
        if not isinstance(event, dict):
            return
        parent = event.get("parent_tool_use_id")
        if event.get("type") == "result":
            self.result = event
            written = self.release(False)
            if self.text is None:  # no answer tool was called: the text ahead of the stream's end is the reply
                self.text = written or None
        elif parent is None or parent in self.agents:
            self.fold(event, self.agents.get(parent), self.now())

    def fold(self, event, parent, at):
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else ():
            if isinstance(block, dict) and (block.get("type") != "text" or event.get("type") == "assistant"):
                self.block(block, parent, at)

    def block(self, block, parent, at):
        kind, key = block.get("type"), block.get("id")
        if kind == "thinking" and block.get("thinking"):
            self.say(("reasoning", id(parent), block["thinking"]), {"kind": "reasoning", "text": block["thinking"]}, parent, at)
        elif kind == "text" and block.get("text"):
            self.say(("message", id(parent), block["text"]), {"kind": "message", "text": block["text"]}, parent, at)
        elif kind == "tool_use" and key not in self.seen:
            name, given = block.get("name"), block.get("input") if isinstance(block.get("input"), dict) else {}
            if parent is None:
                written = self.release(name != ANSWER_TOOL or bool(given.get("calls")))
                if name == ANSWER_TOOL:
                    self.text = written  # whatever text the tool was given is not read: the answer's text is what was written
            if name == ANSWER_TOOL:
                if key is not None:
                    self.seen.add(key)
                return
            if name in AGENT_TOOLS:
                prompt = str(given.get("prompt") or "")
                step = self.agents[key] = {"kind": "agent", "uid": anchor_of(prompt), "prompt": prompt, "report": None, "steps": []}
            elif name == WORKFLOW_TOOL:
                step = {"kind": "workflow", "input": given, "result": None}
            else:
                step = {"kind": "tool", "name": name, "input": given, "result": None, "seconds": None}
            self.open[key] = step
            self.add(key, step, parent, at)
        elif kind == "tool_result" and block.get("tool_use_id") in self.open:
            step = self.open.pop(block["tool_use_id"])
            step["report" if step["kind"] == "agent" else "result"] = result_text(block.get("content"))
            if step["kind"] == "tool":
                step["seconds"] = round(max(at - step["at"], 0), 2)
            self.settle(step)

    def say(self, key, step, parent, at):
        """Take what the model said as a step: a text of the turn's own is held back until what follows tells a message from the reply,
        the reasoning written behind a held text waiting with it for its place."""
        if parent is None and (step["kind"] == "message" or self.held):
            self.held.append((key, step, at))
        else:
            self.add(key, step, parent, at)

    def release(self, said):
        """Settle what was held back: its texts are messages when a call followed them -- `said` -- else the reply, no step; the
        reasoning held behind them is a step either way, each at the time it was written. -> the texts of the reply, joined; "" when none."""
        held, self.held = self.held, []
        written = []
        for key, step, at in held:
            if said or step["kind"] != "message":
                self.add(key, step, None, at)
            else:
                written.append(step["text"])
        return "\n\n".join(written)

    def settle(self, step):
        """Announce the step once more, a subagent's closing message dropped when it is the report the step already holds."""
        nested = step.get("steps") or []
        if nested and nested[-1]["kind"] == "message" and nested[-1]["text"].strip() == (step["report"] or "").strip():
            nested.pop()
        self.on_step(self.top[id(step)])

    def add(self, key, step, parent=None, at=None):
        if key in self.seen:
            return
        self.seen.add(key)
        step["at"] = self.now() if at is None else at
        (parent["steps"] if parent else self.steps).append(step)
        self.top[id(step)] = self.top[id(parent)] if parent else step
        self.on_step(self.top[id(step)])

    def attach_transcripts(self, folder, session):
        """Fold the subagents' own turns read from the session's transcript under `folder` into their agent steps: the per-agent files
        `<session>/subagents/agent-*.jsonl`, matched by the tool use their `.meta.json` names, and the sidechain entries of `<session>.jsonl`,
        matched by the prompt opening them. Unknown shapes are ignored."""
        groups = {}
        for entry in read_jsonl(Path(folder) / f"{session}.jsonl"):
            if entry.get("isSidechain") and entry.get("agentId"):
                groups.setdefault(str(entry["agentId"]), (None, []))[1].append(entry)
        for path in sorted((Path(folder) / session / "subagents").glob("*.jsonl")):
            meta = read_json(path.with_suffix(".meta.json"))
            groups[path.stem.removeprefix("agent-")] = (meta.get("toolUseId"), read_jsonl(path))
        pending = list(groups.values())
        while ready := [(entries, agent) for tool_use, entries in pending if (agent := self.agent_of(tool_use, entries))]:
            pending = [group for group in pending if all(group[1] is not entries for entries, _ in ready)]
            for entries, agent in ready:
                for entry in entries:
                    if entry.get("type") in ("assistant", "user"):
                        self.fold(entry, agent, self.at_of(entry))
                self.settle(agent)

    def agent_of(self, tool_use, entries):
        if tool_use in self.agents:
            return self.agents[tool_use]
        opening = next((entry["message"].get("content") for entry in entries if entry.get("type") == "user" and isinstance(entry.get("message"), dict)), None)
        return next((agent for agent in self.agents.values() if isinstance(opening, str) and opening.strip() == agent["prompt"].strip()), None)


def project_files(root):
    """The root-relative paths of the project's files: git's tracked and unignored ones in a work tree, else every file outside hidden
    and tool folders."""
    try:
        listed = subprocess.run(["git", "ls-files", "-z", "-c", "-o", "--exclude-standard"], cwd=root, capture_output=True, check=True).stdout
        return [rel for rel in listed.decode("utf-8", "surrogateescape").split("\0") if rel]
    except (OSError, subprocess.CalledProcessError):
        files = []
        for folder, dirs, names in os.walk(root):
            dirs[:] = [name for name in dirs if not name.startswith(".") and name not in SNAPSHOT_SKIPPED]
            files += [os.path.relpath(os.path.join(folder, name), root) for name in names]
        return files


def project_snapshot(root):
    """Every project file up to `SNAPSHOT_LIMIT` bytes by its root-relative path, with its content."""
    snapshot = {}
    for rel in project_files(root):
        path = Path(root) / rel
        try:
            if path.is_file() and path.stat().st_size <= SNAPSHOT_LIMIT:
                snapshot[rel] = path.read_bytes()
        except OSError:
            continue
    return snapshot


def file_hunks(old, new):
    if b"\0" in old + new:
        return ""
    try:
        before, after = (text.decode("utf-8").splitlines(keepends=True) for text in (old, new))
    except UnicodeDecodeError:
        return ""
    return "".join(line if line.endswith("\n") else line + "\n" for line in list(difflib.unified_diff(before, after))[2:])


def project_diff(before, after):
    """The files changed between two snapshots, each with git's short status letter and the unified diff hunks of a text file."""
    return [{"path": rel, "status": "A" if rel not in before else "D" if rel not in after else "M",
             "hunks": file_hunks(before.get(rel, b""), after.get(rel, b""))}
            for rel in sorted(before.keys() | after.keys()) if before.get(rel) != after.get(rel)]


def claude_transcripts_dir(root):
    """Where the `claude` CLI keeps the transcripts of the sessions run in `root`."""
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return config / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(Path(root).resolve()))


def send(proc, message):
    try:
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass


def close(proc):
    try:
        proc.stdin.close()
    except (BrokenPipeError, OSError):
        pass


def message_content(text, images=()):
    """The content of a user message: the plain text, or, with `images`, its text block followed by one base64 image block each."""
    if not images:
        return text
    return [{"type": "text", "text": text},
            *({"type": "image", "source": {"type": "base64", "media_type": image["media_type"], "data": image["data"]}} for image in images)]


def write_skill_plugin(folder, library):
    """Write the skills on request of `library` into `folder` as a Claude Code plugin, each a `skills/<name>/SKILL.md` whose front matter
    carries the skill's name and description over its text. -> whether there is any skill to hand to the CLI."""
    skills = [entry for entry in library.values() if entry.kind == "skill" and not entry.default]
    if skills:
        (Path(folder) / ".claude-plugin").mkdir()
        (Path(folder) / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": PLUGIN_NAME, "description": "Skills on request of the prompt library"}))
    for entry in skills:
        (Path(folder) / "skills" / entry.name).mkdir(parents=True)
        (Path(folder) / "skills" / entry.name / "SKILL.md").write_text(
            f"---\nname: {entry.name}\ndescription: {json.dumps(entry.description)}\n---\n{entry.text}", encoding="utf-8")
    return bool(skills)


class claude_code_connector:
    label = "Claude Code"
    models = CLAUDE_MODELS
    efforts = CLAUDE_EFFORTS
    model_efforts = CLAUDE_MODEL_EFFORTS
    library_delivery = "native"
    default_model = "sonnet"
    default_effort = "high"
    # The tree files are closed to the turn in every mode, to read as to write: the tree is read and changed only through tree calls. The
    # connector's own edit tools are off in every mode too: project files change only through the patch call of the harness. So are its own
    # subagent tools: every subagent starts through the agent call of the harness.
    denied = ("Read(syngate/**)", "Edit(syngate/**)", "Write(syngate/**)", "Edit", "MultiEdit", "Write", "NotebookEdit", *AGENT_TOOLS)
    # The built-in tools a turn has whatever its modes. The CLI is named its whole tool set -- these, the tools of the modes that are on and
    # `Skill` while a skill on request is delivered -- so a tool the connector does not name is not in the model's context, whatever the CLI ships.
    own = ("Read",)
    # What keeps the machine's Claude Code configuration out of every call: no setting source -- user, project, local, with their CLAUDE.md
    # files, skills, hooks and permission rules -- and, by the environment, neither auto memory nor bundled skills.
    isolation = ("--setting-sources", "")
    environment = {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS": "1"}
    # Call modes: what a turn may do without prompting, as (label, hint, on by default, advanced, permission mode, allowed tools);
    # an advanced mode is kept out of the page's switch row, in its drop-down list.
    modes = {
        "internet": ("Internet", "search and fetch the web", True, False, None, ("WebSearch", "WebFetch")),
        "bash": ("Raw command", "run shell commands", False, True, None, ("Bash",)),
        "workflows": ("Workflows", "run workflow scripts", False, True, None, ("Workflow",)),
    }
    # What the CLI's closing `result` event tells of the turn's cost, folded into the closing `usage` step when present.
    usage_fields = ("duration_ms", "total_cost_usd", "usage")

    # Seconds a `claude` process asked to interrupt its turn may take to end before it is killed with its process group.
    grace = 5.0

    def __init__(self, cli=("claude",), cwd=None, transcripts_dir=None):
        self.cli = list(cli)
        self.cwd = cwd
        self.transcripts_dir = transcripts_dir
        self.live = {}
        self.forks = {}  # session -> the entry the next call resumes it at, forked: a rollback of its pruning

    def interrupt(self, ident):
        """End the turn the thread `ident` is running: its `claude` process is asked to interrupt -- the model stops and the session records
        it -- and killed with its process group if it is still there after `grace` seconds."""
        proc = self.live.get(ident)
        if proc is None:
            return
        send(proc, {"type": "control_request", "request_id": f"stop-{proc.pid}", "request": {"subtype": "interrupt"}})

        def kill():
            try:
                proc.wait(self.grace)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        threading.Thread(target=kill, daemon=True).start()

    def settings(self):
        return {"label": self.label, "library": self.library_delivery,
                "models": [{"id": model, "name": model.removeprefix("claude-"), "efforts": list(self.model_efforts.get(model, ()))} for model in self.models],
                "efforts": list(self.efforts), "default": {"model": self.default_model, "effort": self.default_effort},
                "modes": [{"id": mode, "label": label, "hint": hint, "default": default, "advanced": advanced}
                          for mode, (label, hint, default, advanced, _, _) in self.modes.items()]}

    def dispatch(self, context, text, model=None, effort=None, modes=(), session=None, on_step=None, stopped=lambda: False, library=None, images=(),
                 agent=None):
        """(answer, session id) of one non-interactive `claude -p` turn, the answer being the structured output shaped by
        the `answer_schema` of the prompt `library` (the shipped one by default) less its text field -- the text the model wrote ahead
        of a text answer put back into it, the result's own text where the stream told none -- else the reply text; the seed context is the
        appended system prompt and `session` continues an earlier one. The library's skills on request go to the CLI as the
        skills of a plugin folder, its tools as the calls of the answer schema; neither is in the seed context. The text goes in on stdin as the user message of a stream-json input, which
        keeps the stdin open for an `interrupt`; with `images` the message is the text block followed by their base64 image blocks. The turn lasts until the process exits: a subagent or workflow launched in
        it is awaited by the CLI, which answers again on its report, and the answer of the turn is that last one.
        Its events stream into `on_step` as steps while it runs; once it exits, the subagents' own turns are read from the
        session's transcript, the project files it changed, from snapshots taken before and after, follow as a diff step and the
        wall time, cost and token counts the result event reports close it as a usage step.
        The effort, which is what asks the model for its reasoning, goes only with a model that has effort levels.
        The turn of an off-context `agent` is a fresh call of the CLI -- no session resumed but the agent's own -- whose system prompt is
        the `context`, the agent's prompt, in place of the CLI's own, every tool of the CLI's own denied, no plugin handed and the
        `agent_schema` as the answer schema.
        Every call names the CLI its whole built-in tool set and is started without the machine's Claude Code configuration.
        A turn `stopped` before its process is spawned spawns none."""
        root = Path(self.cwd or os.getcwd())
        if stopped():
            raise connection_error("turn stopped")
        before, steps = project_snapshot(root), turn_steps(on_step)
        permission = next((self.modes[mode][4] for mode in modes if self.modes[mode][4]), None)
        tools = list(dict.fromkeys(tool for mode in modes for tool in self.modes[mode][5]))
        effort = effort if effort in self.model_efforts.get(model, self.efforts) else None
        library = read_library(library)
        if agent is not None:
            permission, tools = None, []
        with (tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8") as seed, tempfile.TemporaryFile("w+", encoding="utf-8") as errors,
              tempfile.TemporaryDirectory() as plugin):
            seed.write(context)
            seed.flush()
            argv = [*self.cli, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose", "--forward-subagent-text",
                    "--json-schema", json.dumps(answer_schema(library, text=False) if agent is None else agent_schema(agent, library, text=False)),
                    "--append-system-prompt-file" if agent is None else "--system-prompt-file", seed.name,
                    "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', *self.isolation]
            if agent is None and write_skill_plugin(plugin, library):
                argv += ["--plugin-dir", plugin]
                tools.append("Skill")
            argv += ["--tools", ",".join((*self.own, *tools) if agent is None else ())]
            for flag, value in (("--model", model), ("--effort", effort), ("--resume", session), ("--permission-mode", permission),
                                ("--allowedTools", ",".join(tools)), ("--disallowedTools", ",".join(self.denied))):
                if value:
                    argv += [flag, value]
            if session and (fork := self.forks.pop(session, None)):
                argv += ["--resume-session-at", fork, "--fork-session"]
            ident = threading.get_ident()
            with subprocess.Popen(argv, cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, text=True,
                                  start_new_session=True, env={**os.environ, **self.environment}) as done:
                self.live[ident] = done
                try:
                    send(done, {"type": "user", "message": {"role": "user", "content": message_content(text, images)}})
                    if stopped():
                        self.interrupt(ident)
                    for line in done.stdout:
                        steps.feed(line)
                        if steps.result is not None:
                            close(done)
                    done.wait()
                finally:
                    self.live.pop(ident, None)
            errors.seek(0)
            stderr = errors.read()
        reply = steps.result
        if reply and reply.get("session_id"):
            steps.attach_transcripts(self.transcripts_dir or claude_transcripts_dir(root), str(reply["session_id"]))
        changed = project_diff(before, project_snapshot(root))
        if changed:
            steps.add("diff", {"kind": "diff", "files": changed})
        if reply and any(field in reply for field in self.usage_fields):
            steps.add("usage", self.usage_step(reply, steps.now()))
        if reply is None:
            raise connection_error((stderr or "\n".join(steps.noise)).strip() or f"claude exited with {done.returncode}")
        if done.returncode or reply.get("is_error"):
            raise connection_error(str(reply.get("result") or stderr.strip() or f"claude exited with {done.returncode}"))
        answer, written = reply.get("structured_output"), reply.get("result") if steps.text is None else steps.text
        if answer is None:
            return written, reply.get("session_id")
        if isinstance(answer, dict) and not answer.get("calls") and (agent is None or not is_verdict(agent)):
            answer = {**answer, "text": written if isinstance(written, str) else ""}  # what the model wrote, never a field of the answer tool
        return answer, reply.get("session_id")

    def transcript_path(self, session):
        """The file the CLI keeps the transcript of `session` in."""
        return Path(self.transcripts_dir or claude_transcripts_dir(Path(self.cwd or os.getcwd()))) / f"{session}.jsonl"

    def turn_span(self, session, rounds):
        """{session, first, last, tokens}: the span the turn that ended `session` after `rounds` rounds left in its transcript; None where the
        transcript does not show it."""
        found = cc_transcript.span(cc_transcript.read(self.transcript_path(session)), rounds)
        return {"session": session, **found} if found else None

    def replay_session(self, session, turns, block, now=None, force=False):
        """Bring the pruning settled for `turns` -- {turn, span, steps, reply, verdicts} each, from the earliest changed turn on, in order --
        into the session before its next call, where that is worth it. A transcript the replay knows is written anew, the old one kept: what
        stands ahead of the first turn copied as it is, every turn rebuilt from the transcript its span names -> ("replayed", new session). Any
        other is rolled back: the next call resumes `session` forked at the answer ahead of the first turn, the `block` heading its message
        -> ("forked", None). None where neither is worth it or can be done: the change waits; with `force` -- a switch set by hand -- the
        worth is not asked."""
        rows, now = cc_transcript.read(self.transcript_path(session)), cc_transcript.now() if now is None else now
        first = turns[0]["span"].get("first") if turns else None
        at = next((index for index, row in enumerate(rows) if first and row.get("uuid") == first), None)
        if at is None:
            return None
        held, last = cc_transcript.tokens(rows[at:]), cc_transcript.last_at(rows)
        if cc_transcript.replayable(rows):
            sources, rebuilt = {session: rows}, []
            for record in turns:
                source = record["span"].get("session")
                if source not in sources:
                    sources[source] = cc_transcript.read(self.transcript_path(source))
                part = cc_transcript.turn_rows(sources[source], record["span"])
                if part is None:
                    rebuilt = None
                    break
                rebuilt.append(cc_transcript.prune_rows(part, record["turn"], record["steps"], record["verdicts"], record.get("reply") or ""))
            if rebuilt is not None:
                sent = cc_transcript.tokens([row for part, _ in rebuilt for row in part])
                if not force and not cc_transcript.worth(held - sent, sent, last, now):
                    return None
                replayed = str(uuid.uuid4())
                cc_transcript.write(self.transcript_path(replayed), cc_transcript.assemble(rows[:at], rebuilt, replayed))
                return "replayed", replayed
        resume = cc_transcript.anchor(rows, first)
        sent = len(block) // 4
        if resume is None or not (force or cc_transcript.worth(held - sent, sent, last, now)):
            return None
        self.forks[session] = resume
        return "forked", None

    @staticmethod
    def usage_step(result, elapsed):
        """The turn's wall time in seconds, its cost in dollars and its input -- the cache included -- and output tokens, each None
        when the result event lacks it."""
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        counted = [usage.get(key) for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens") if isinstance(usage.get(key), int)]
        return {"kind": "usage", "seconds": round(result["duration_ms"] / 1000, 2) if isinstance(result.get("duration_ms"), (int, float)) else elapsed,
                "cost_usd": result.get("total_cost_usd"), "input_tokens": sum(counted) if counted else None, "output_tokens": usage.get("output_tokens")}


# Native tool-use markup a model trained on it may leak around a fenced call block when its tools come as text.
TOOL_MARKUP_RE = re.compile(r"</?(?:antml:)?(?:function_calls|invoke|parameter)\b[^>]*>")
# Such markup naming a tool with no call block beside it: the calls the model meant, written where the harness does not read them.
LEAKED_CALL_RE = re.compile(r"<(?:antml:)?invoke\s+name=\"[^\"]+\"")
LEAKED_CALL = "tool calls written as native tool-use markup (<invoke name=…>) are not run: write them as JSON in one ```syngate block"


# The built-in connectors; the OpenAI-compatible API connections come from the server settings (`api_connection`).
CONNECTORS = {"claude_code": claude_code_connector}
