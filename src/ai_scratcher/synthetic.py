# Open Trader
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Synthetic agent library: the prompt library of skills and tools, item seed context, AI connections and the tool call protocol of a reply."""

import difflib
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

import yaml

from . import syngatelib

CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
CLAUDE_MODEL_EFFORTS = {"claude-fable-5-1": CLAUDE_EFFORTS, "claude-opus-5-5": CLAUDE_EFFORTS, "claude-sonnet-5": CLAUDE_EFFORTS,
                        "claude-haiku-4-5-20251001": ()}
CLAUDE_MODELS = tuple(CLAUDE_MODEL_EFFORTS)
AGENT_TOOLS = ("Agent", "Task")
WORKFLOW_TOOL = "Workflow"
ANSWER_TOOL = "StructuredOutput"
SNAPSHOT_SKIPPED = ("__pycache__", "node_modules")
SNAPSHOT_LIMIT = 1 << 20

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
DEFAULT_PROMPT = "default"
FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
SKILLS_ON_REQUEST = "# Skills on request\nLoad one with the `skill` tool:\n"


class prompt(NamedTuple):
    """One markdown file of the library: its stem is the name, its front matter the `kind` (skill|tool), the `description`
    listing it and, for a skill, whether it is in the default prompt; the text is the body after the front matter."""
    name: str
    kind: str
    description: str
    default: bool
    text: str


def read_prompt(path):
    raw = path.read_text(encoding="utf-8")
    match = FRONT_MATTER_RE.match(raw)
    meta = (yaml.safe_load(match.group(1)) if match else None) or {}
    body = raw[match.end():] if match else raw
    return prompt(path.stem, str(meta.get("kind") or "skill"), str(meta.get("description") or ""), bool(meta.get("default")),
                  body.strip("\n") + "\n")


def load_prompts(prompts_dir=PROMPTS_DIR):
    """The prompt library: name -> prompt of every markdown file under `prompts_dir`, the name being the file stem."""
    return {path.stem: read_prompt(path) for path in sorted(prompts_dir.glob("*.md"))}


def default_prompt(library):
    """The default prompt composed from the library: the default skills, the list of the skills on request by name and
    description, then every tool definition."""
    skills = [entry for entry in library.values() if entry.kind == "skill"]
    on_request = "\n".join(f"- `{entry.name}`: {entry.description}" for entry in skills if not entry.default) or "none"
    return "\n".join([*(entry.text for entry in skills if entry.default), SKILLS_ON_REQUEST + on_request + "\n",
                      *(entry.text for entry in library.values() if entry.kind == "tool")])


LIBRARY = load_prompts()
SKILLS = {name: entry for name, entry in LIBRARY.items() if entry.kind == "skill"}
PROMPTS = {**{name: entry.text for name, entry in LIBRARY.items()}, DEFAULT_PROMPT: default_prompt(LIBRARY)}
CALL_BLOCK_RE = re.compile(r"```syngate[ \t]*\n(.*?)\n[ \t]*```", re.DOTALL)
TOOLS = {"add": ("uid", "description"), "edit": ("uid",), "remove": ("uid",), "move": ("uid", "to")}
QUERIES = {"query": ("uid",), "context": ("uid",), "skill": ("name",)}
RUNS = {"test": ("uid",)}
DELEGATIONS = {"agent": ("uid", "prompt")}
CALLS = {**TOOLS, **QUERIES, **RUNS, **DELEGATIONS}
EDITABLE = ("description", "sources")
QUERY_ROUNDS = 8
RESULTS_PREAMBLE = "Results of the calls in your last answer:\n"
# A message names an item the way a file is named: `@UID` brings the item's statement into the turn.
REFERENCE_RE = re.compile(r"@([A-Z][A-Z_]*(?:-[A-Z0-9_]+)*)\b")
HISTORY_PREAMBLE = "The exchange so far, as kept by the user:\n"

STRING = {"type": "string"}
PATHS = {"type": "array", "items": STRING}
SOURCE_FENCE = "````"


def _call_schema(tool, **optional):
    return {"type": "object", "properties": {"tool": {"const": tool}, **{field: STRING for field in CALLS[tool]}, **optional},
            "required": ["tool", *CALLS[tool]], "additionalProperties": False}


# The structured answer: the tools of the Syngate API an answer may carry, as the JSON schema a
# connection hands its model, so the shape of a call is enforced by the model side rather than by the parser alone.
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"enum": ["text", "calls"]},
        "text": STRING,
        "calls": {"type": "array", "minItems": 1, "items": {"anyOf": [
            _call_schema("add", parent=STRING, description=STRING, sources=PATHS, kind={"enum": ["leaf", "branch"]}),
            _call_schema("edit", description=STRING, sources=PATHS),
            _call_schema("remove"),
            _call_schema("move", to=STRING, before=STRING, link={"type": "boolean"}, **{"from": STRING}),
            _call_schema("query"),
            _call_schema("context"),
            _call_schema("skill"),
            _call_schema("test", name=STRING),
            _call_schema("agent", model=STRING, effort=STRING, modes={"type": "array", "items": STRING}),
        ]}},
    },
    "required": ["kind"],
    "additionalProperties": False,
}


def seed_context(items, uid, prompt=DEFAULT_PROMPT, root=None):
    """The named prompt of the library, then the statements of every ancestor, parents first, the item's own and those of all
    its descendants in sibling order -- an item reached twice enters once, at its first occurrence -- then the key source files
    those items list, each once, read from `root`."""
    if uid not in items:
        raise syngatelib.unknown_uid(f"unknown UID '{uid}'")
    selection = syngatelib.walk(items, uid, descendants=True)
    statements = "".join(items[selected].description for selected in selection)
    sources = dict.fromkeys(rel for selected in selection for rel in items[selected].sources)
    return PROMPTS[prompt] + "\n" + statements + "".join(source_section(rel, root) for rel in sources)


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


def referenced(items, text):
    """The statements of the items named `@UID` in `text`, each as one more section after the seed context."""
    found = [uid for uid in dict.fromkeys(REFERENCE_RE.findall(text)) if uid in items]
    return "".join(f"\n@{uid}\n{items[uid].description}" for uid in found)


def transcript(history, text):
    """The user's text headed by the kept messages of an exchange that has no session to resume."""
    if not history:
        return text
    lines = [f"{'user' if message.get('role') == 'user' else 'assistant'}: {message.get('text') or ''}" for message in history]
    return HISTORY_PREAMBLE + "\n".join(lines) + "\n\n" + text


def item_view(items, uid):
    """The item as the AI reads it back: its fields, its kind and the UIDs of its children in sibling order."""
    if uid not in items:
        raise syngatelib.unknown_uid(f"unknown UID '{uid}'")
    item = items[uid]
    return {"uid": uid, "description": item.description, "parents": item.parents, "sources": list(item.sources),
            "children": syngatelib.sorted_children(items, syngatelib.children_map(items), uid),
            "kind": "branch" if item.tests is None else "leaf"}


def is_query(call):
    return call["tool"] in QUERIES


def is_run(call):
    return call["tool"] in RUNS


def is_delegation(call):
    return call["tool"] in DELEGATIONS


def run_report(items, targets, records):
    """The outcome of a run as the AI reads it back: one line per addressed leaf binding -- `targets` being (uid, binding|None),
    None standing for every binding of the leaf -- with pass/fail, a binding without a record having failed, then the captured
    output of every failed routine."""
    lines, logs = [], []
    for uid, name in targets:
        declared = [name] if name else list(items[uid].tests) if uid in items and items[uid].is_leaf else []
        for binding in declared or [found for found_uid, found in records if found_uid == uid] or [None]:
            found = list({record["name"]: record for record in records.get((uid, binding), [])}.values())
            label = f"{uid}:{binding}" if binding else uid
            lines.append(f"- {label}: {'pass' if found and all(record['passed'] for record in found) else 'fail'}")
            logs += [f"{label} output:\n{record['log']}" for record in found if not record["passed"] and record["log"]]
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


def parse_reply(reply):
    """("chat", text) for a plain answer, ("calls", [call, ...]) for one batch of tool calls: a structured answer
    shaped by `ANSWER_SCHEMA`, or text holding exactly one ```syngate block; anything mixed or malformed is refused."""
    if isinstance(reply, dict):
        calls = reply.get("calls")
        if reply.get("kind") == "text" and not calls:
            return "chat", reply.get("text") or ""
        if reply.get("kind") != "calls" or reply.get("text"):
            raise protocol_error("an answer is either text or one block of tree calls, never both")
    else:
        blocks = CALL_BLOCK_RE.findall(reply)
        if not blocks:
            return "chat", reply
        if len(blocks) > 1 or CALL_BLOCK_RE.sub("", reply, count=1).strip():
            raise protocol_error("an answer is either text or one block of tree calls, never both")
        try:
            calls = json.loads(blocks[0])
        except ValueError as exc:
            raise protocol_error(f"tree calls are not valid JSON: {exc}") from None
    if not isinstance(calls, list) or not calls or not all(isinstance(call, dict) for call in calls):
        raise protocol_error("tree calls must be a non-empty JSON list of objects")
    for call in calls:
        tool = call.get("tool")
        if tool not in CALLS:
            raise protocol_error(f"unknown tree call {tool!r}")
        missing = [name for name in CALLS[tool] if not (isinstance(call.get(name), str) and call[name].strip())]
        if missing:
            raise protocol_error(f"{tool}: missing {', '.join(missing)}")
        if tool == "edit" and not ((isinstance(call.get("description"), str) and call["description"].strip()) or isinstance(call.get("sources"), list)):
            raise protocol_error(f"edit: missing {' or '.join(EDITABLE)}")
    return "calls", calls


def apply_call(items, anchor, call, syngate_dir=None):
    """Perform one parsed Syngate API call against the loaded tree, `@` standing for the
    anchored item. -> the line reporting what it did, or what a query read; a refusal raises
    `syngatelib.tree_error`.

    No call passes `clear`: a stamp an AI answer moves is deliberately left
    standing over the changed content, so the user meets a violated review
    rather than a silently unreviewed item."""
    at = lambda value: anchor if value == "@" else value
    tool, uid = call["tool"], at(call.get("uid"))
    if tool in RUNS or tool in DELEGATIONS:
        raise syngatelib.tree_error(f"{tool} runs through the page's harness, not against the tree")
    if tool == "skill":
        if call["name"] not in SKILLS:
            raise syngatelib.tree_error(f"unknown skill '{call['name']}'")
        return f"- skill {call['name']}:\n{SKILLS[call['name']].text}"
    if tool == "query":
        return f"- {uid}: {json.dumps(item_view(items, uid), ensure_ascii=False)}"
    if tool == "context":
        return f"- context of {uid}:\n{seed_context(items, uid, root=Path(syngate_dir).parent if syngate_dir else None)}"
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
    source, target, link = at(call.get("from")), at(call["to"]), bool(call.get("link"))
    if source is None and uid in items and len(items[uid].parents) == 1:
        source = items[uid].parents[0]
    if source is None and uid in items and not link:
        raise syngatelib.tree_error(f"{uid} has several parents; name the one to re-point in 'from' or pass 'link'")
    syngatelib.move_item(items, uid, target, before=at(call.get("before")), source=source, link=link)
    return f"- moved {uid} under {target}"


def query(connectors, items, uid, text, connector, model, effort, modes=(), session=None, history=(), root=None, on_step=None):
    """(reply text, session id) of one exchange anchored at `uid`, sent through the named connection with the exact model, effort and call modes,
    every step of the turn reaching `on_step` as it happens.
    The seed context -- its key sources read from `root` -- grows by the statements the text references; without a session to resume,
    the kept `history` heads the text."""
    connection = connectors.get(connector)
    if uid not in items:
        raise query_error(f"unknown UID '{uid}'")
    if connection is None:
        raise query_error(f"unknown connector '{connector}'")
    if model not in connection.models or effort not in connection.efforts:
        raise query_error(f"unknown model '{model}' or effort '{effort}'")
    if not set(modes) <= set(connection.modes):
        raise query_error(f"unknown mode in {sorted(modes)}")
    if not text.strip():
        raise query_error("empty input")
    context = seed_context(items, uid, root=root) + referenced(items, text)
    return connection.dispatch(context, text if session else transcript(history, text), model=model, effort=effort, modes=modes, session=session,
                              on_step=on_step)


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
    text is a `message` step, but for a subagent's closing one, which is its report; the turn's answer is the structured output."""

    def __init__(self, on_step=None):
        self.on_step = on_step or (lambda step: None)
        self.started, self.wall = time.monotonic(), time.time()
        self.steps, self.result, self.noise = [], None, []
        self.open, self.agents, self.top, self.seen = {}, {}, {}, set()

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
            self.add(("reasoning", id(parent), block["thinking"]), {"kind": "reasoning", "text": block["thinking"]}, parent, at)
        elif kind == "text" and block.get("text"):
            self.add(("message", id(parent), block["text"]), {"kind": "message", "text": block["text"]}, parent, at)
        elif kind == "tool_use" and block.get("name") != ANSWER_TOOL and key not in self.seen:
            name, given = block.get("name"), block.get("input") if isinstance(block.get("input"), dict) else {}
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


class claude_code_connector:
    label = "Claude Code"
    models = CLAUDE_MODELS
    efforts = CLAUDE_EFFORTS
    model_efforts = CLAUDE_MODEL_EFFORTS
    always_allowed = ("Agent",)
    # Direct edits of the tree files are denied in every mode; the tree changes only through tree calls.
    denied = ("Edit(syngate/**)", "Write(syngate/**)")
    # Call modes: what a turn may do without prompting, as (label, hint, on by default, permission mode, allowed tools).
    modes = {
        "edit": ("Edit", "project files", True, "acceptEdits", ()),
        "internet": ("Internet", "access", True, None, ("WebSearch", "WebFetch")),
        "workflows": ("Workflows", "run subagents", False, None, ("Workflow",)),
    }

    def __init__(self, cli=("claude",), cwd=None, transcripts_dir=None):
        self.cli = list(cli)
        self.cwd = cwd
        self.transcripts_dir = transcripts_dir
        self.live = {}

    def interrupt(self, ident):
        """Kill the `claude` process of the turn the thread `ident` is running, if one is live."""
        proc = self.live.get(ident)
        if proc:
            proc.kill()

    def settings(self):
        return {"label": self.label,
                "models": [{"id": model, "name": model.removeprefix("claude-"), "efforts": list(self.model_efforts.get(model, ()))} for model in self.models],
                "efforts": list(self.efforts),
                "modes": [{"id": mode, "label": label, "hint": hint, "default": default} for mode, (label, hint, default, _, _) in self.modes.items()]}

    def dispatch(self, context, text, model=None, effort=None, modes=(), session=None, on_step=None):
        """(answer, session id) of one non-interactive `claude -p` turn, the answer being the structured output shaped by
        `ANSWER_SCHEMA`, else the reply text; the seed context, headed by the default prompt, is the appended system prompt
        and `session` continues an earlier one. The turn lasts until the process exits: a subagent or workflow launched in
        it is awaited by the CLI, which answers again on its report, and the answer of the turn is that last one.
        Its events stream into `on_step` as steps while it runs; once it exits, the subagents' own turns are read from the
        session's transcript and the project files it changed, from snapshots taken before and after, close it as a diff step.
        The effort, which is what asks the model for its reasoning, goes only with a model that has effort levels."""
        root = Path(self.cwd or os.getcwd())
        before, steps = project_snapshot(root), turn_steps(on_step)
        permission = next((self.modes[mode][3] for mode in modes if self.modes[mode][3]), None)
        tools = list(dict.fromkeys([*self.always_allowed, *(tool for mode in modes for tool in self.modes[mode][4])]))
        effort = effort if effort in self.model_efforts.get(model, self.efforts) else None
        with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8") as seed, tempfile.TemporaryFile("w+", encoding="utf-8") as errors:
            seed.write(context)
            seed.flush()
            argv = [*self.cli, "-p", text, "--output-format", "stream-json", "--verbose", "--forward-subagent-text",
                    "--json-schema", json.dumps(ANSWER_SCHEMA),
                    "--append-system-prompt-file", seed.name, "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']
            for flag, value in (("--model", model), ("--effort", effort), ("--resume", session), ("--permission-mode", permission),
                                ("--allowedTools", ",".join(tools)), ("--disallowedTools", ",".join(self.denied))):
                if value:
                    argv += [flag, value]
            ident = threading.get_ident()
            with subprocess.Popen(argv, cwd=self.cwd, stdout=subprocess.PIPE, stderr=errors, text=True) as done:
                self.live[ident] = done
                try:
                    for line in done.stdout:
                        steps.feed(line)
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
        if reply is None:
            raise connection_error((stderr or "\n".join(steps.noise)).strip() or f"claude exited with {done.returncode}")
        if done.returncode or reply.get("is_error"):
            raise connection_error(str(reply.get("result") or stderr.strip() or f"claude exited with {done.returncode}"))
        answer = reply.get("structured_output")
        return (reply.get("result") if answer is None else answer), reply.get("session_id")


CONNECTORS = {"claude_code": claude_code_connector}
