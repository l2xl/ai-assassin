# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Turn pruning of the Orchestrator (ORCHESTRATOR-PRUNE, design/orchestrator/turn_pruning.md): what of an ended turn adds nothing to the
session, judged by rule from its steps and by the prune agent -- an injected callable -- from its AI texts. Pure: no chat, no connection and
no file is touched; the page keeps the state `new_state` makes with its chat log and does the sending, the log and the page marks."""

import json
import posixpath
import re

AGENT = "prune"
# The calls of the harness that change the project or the tree: a batch of them applied is pruned to one line each.
CHANGING = ("add", "edit", "remove", "move", "rename", "patch", "replace")
TREE_READS = ("query", "context")
LINE_LIMIT = 120  # characters of the line one call of a pruned batch keeps
REFUSED_RE = re.compile(r"\brefused: |\Aanswer refused")
PASS_RE, FAIL_RE = re.compile(r": pass\b"), re.compile(r": fail\b")
RENEW_TOKENS = 100_000  # the input tokens of a session's last request past which its conversation starts its next session
REPLY = "reply"  # the step part of the key of the turn's closing text, which is no step


class refused(Exception):
    """A switch the pruning does not allow."""


def key(turn, number):
    """The key of a step -- or of the `REPLY` -- of a turn in the state and in the verdicts."""
    return f"{turn}:{number}"


def new_state():
    """The pruning state of one conversation, kept with its chat log and dropped with its reset: the turn last sent, the files read in the
    session, the verdicts applied to the running session and those waiting for the next one, the switches set by hand and the stubs not
    yet carried, the size of the running session -- the input tokens of its last request -- and, by turn, the span each of its turns left in
    a transcript its connection keeps. Every value is JSON."""
    return {"sent": 0, "read": [], "applied": {}, "waiting": {}, "switches": {}, "stubs": [], "size": 0, "spans": {}}


def prunable(step):
    """Whether a step may be pruned at all: what the user wrote never is."""
    return step.get("kind") != "user"


def first_line(text):
    """The first line of `text` that holds anything, cut at `LINE_LIMIT` characters."""
    line = next((line.strip() for line in str(text or "").splitlines() if line.strip()), "")
    return line if len(line) <= LINE_LIMIT else line[:LINE_LIMIT - 1] + "…"


def stub_line(turn, number, what):
    """The one line a pruned step leaves in the session: its turn, its step and what it was."""
    return f"[turn {turn} {REPLY if number == REPLY else f'step {number}'}: {what} — read with log]"


def describe(step):
    """What a step was, in a few words: the stub of one pruned by hand, and the stubs handed to the prune agent."""
    kind = step.get("kind") or "step"
    if kind == "tool":
        return f"tool {step.get('name')}"
    if kind == "calls":
        return f"calls {', '.join(step.get('tools') or ())}".strip()
    if kind == "agent":
        return "agent" + (f" @{step['uid']}" if step.get("uid") else "")
    return {"user": "user message", "message": "AI text", "diff": "file changes"}.get(kind, kind)


def given_calls(given):
    """The calls a calls step records as the input of one result: a call, the list of calls a run joins, or nothing."""
    return [call for call in (given if isinstance(given, list) else [given]) if isinstance(call, dict)]


def paths_of(given):
    return [posixpath.normpath(str(call.get("path") or "")) for call in given_calls(given) if call.get("tool") == "read"]


def judge_pair(given, line, held):
    """The rule -- 'tree', 'pass', 'reread' or 'batch' -- the one call of a calls step falls under, None where no rule prunes it: a call
    refused, one that is no tree read, passing run, read of a file `held` whole or change, or a read of a file not held."""
    tools = [call.get("tool") for call in given_calls(given)]
    if not tools or REFUSED_RE.search(str(line)):
        return None
    if all(tool in TREE_READS for tool in tools):
        return "tree"
    if all(tool == "test" for tool in tools):
        return "pass" if PASS_RE.search(str(line)) and not FAIL_RE.search(str(line)) else None
    if all(tool == "read" for tool in tools):
        return "reread" if all(path in held for path in paths_of(given)) else None
    return "batch" if all(tool in CHANGING for tool in tools) else None


def judge_step(turn, number, step, held):
    """The verdict {rule, stub[, lines]} of a calls step by rule, None where it stays: every call of it must fall under a rule. A step of
    one kind of read or run is cut to its stub; one of changing calls, or of several kinds, is an applied batch, cut to one line for each
    of its calls."""
    lines, inputs = [str(line) for line in step.get("lines") or ()], list(step.get("inputs") or ())
    if step.get("kind") != "calls" or not lines:
        return None
    rules = [judge_pair(given, line, held) for given, line in zip([*inputs, *[None] * len(lines)], lines)]
    if None in rules:
        return None
    if len(set(rules)) == 1 and rules[0] != "batch":
        what = {"tree": "tree read", "pass": f"test run, {sum(len(PASS_RE.findall(line)) for line in lines)} passed",
                "reread": "file re-read of " + ", ".join(path for given in inputs for path in paths_of(given))}[rules[0]]
        return {"rule": rules[0], "stub": stub_line(turn, number, what)}
    return {"rule": "batch", "stub": stub_line(turn, number, f"applied batch, {len(lines)} call{'s' if len(lines) > 1 else ''}"),
            "lines": [first_line(line) for line in lines]}


def rule_verdicts(turn, steps, held=(), read=()):
    """(verdicts, read) of the steps of the ended turn by rule, without a model: the verdicts by step number, `held` being the files the
    system prompt holds whole and `read` the files read earlier in the session; the read returned is the files read by the turn's end.
    A first read -- of a file neither held nor read before -- is never pruned, nor is a step holding one."""
    held, read, verdicts = {posixpath.normpath(path) for path in held}, {posixpath.normpath(path) for path in read}, {}
    for number, step in enumerate(steps, 1):
        if not prunable(step):
            continue
        paths = [path for given in step.get("inputs") or () for path in paths_of(given)]
        verdict = None if any(path not in held and path not in read for path in paths) else judge_step(turn, number, step, held)
        if verdict:
            verdicts[key(turn, number)] = verdict
        read.update(paths)
    return verdicts, frozenset(read)


def texts_of(turn, steps, reply=""):
    """The AI texts of the ended turn, numbered from 1 in order: [(number, key, text)] of its `message` steps and then its closing `reply`."""
    found = [(key(turn, number), step["text"]) for number, step in enumerate(steps, 1) if step.get("kind") == "message" and str(step.get("text") or "").strip()]
    found += [(key(turn, REPLY), reply)] if str(reply or "").strip() else []
    return [(index, found_key, text) for index, (found_key, text) in enumerate(found, 1)]


class prune_input:
    """What the prune agent is handed: the AI texts of the ended turn, numbered, and the stubs of its steps -- never the session. `data` is
    the text for the agent, "" with no text to judge; `indices` the key each number stands for."""

    def __init__(self, turn, steps, reply=""):
        texts = texts_of(turn, steps, reply)
        stubs = [stub_line(turn, number, describe(step)) for number, step in enumerate(steps, 1) if step.get("kind") != "message"]
        self.indices = {index: found_key for index, found_key, _ in texts}
        self.data = "\n".join(["Steps of the turn:", *(stubs or ["none"]), "", "AI texts of the turn:", *(f"\n[{index}]\n{text}" for index, _, text in texts)]) if texts else ""


def judge_texts(ask, turn, steps, reply=""):
    """The verdicts of the prune agent on the AI texts of the ended turn, by key: of every text it finds states nothing new. `ask` is the
    injected callable taking the handed text and returning the agent's JSON answer -- `{"texts": [{"index", "new"}]}` -- so no connection is
    bound here. No text means no call; a number not handed, a malformed entry or an `ask` that fails prunes nothing."""
    handed = prune_input(turn, steps, reply)
    if not handed.indices:
        return {}
    try:
        answer = ask(handed.data)
        entries = (answer if isinstance(answer, dict) else json.loads(answer)).get("texts")
    except Exception:  # pruning is best effort: an agent that cannot answer leaves the session whole
        return {}
    verdicts = {}
    for entry in entries if isinstance(entries, list) else ():
        found = handed.indices.get(entry.get("index")) if isinstance(entry, dict) else None
        if found and entry.get("new") is False:
            number = found.partition(":")[2]
            verdicts[found] = {"rule": "text", "stub": stub_line(turn, number if number == REPLY else int(number), "AI text")}
    return verdicts


def form(verdict):
    """What the session holds in place of the pruned step: one line for each call of an applied batch, else the stub."""
    return list(verdict["lines"]) if verdict.get("lines") else [verdict["stub"]]


def put(state, bucket, turn, verdicts):
    """Record the `verdicts` of the ended `turn` in `bucket` -- each key of that turn alone: the earlier turns stay as they were sent; those
    put in the running session leave their stubs to be carried by the next message."""
    for found, verdict in verdicts.items():
        if not found.startswith(f"{turn}:"):
            raise ValueError(f"{found} is not a step of turn {turn}")
        state[bucket][found] = verdict
        if bucket == "applied":
            state["stubs"].append(verdict["stub"])
    return state


def message_sent(state, turn):
    """Note that the message opening `turn` has been sent: a verdict for an earlier turn arriving now is late."""
    state["sent"] = max(state["sent"], turn)
    return state


def end_turn(state, turn, steps, held=(), owned=False):
    """Prune the ended `turn` by rule: its verdicts join the running session -- or, with an `owned` session of a connection the harness
    cannot rewrite, wait for the next one -- and the files it read join those read in the session."""
    verdicts, read = rule_verdicts(turn, steps, held, state["read"])
    state["read"] = sorted(read)
    return put(state, "waiting" if owned else "applied", turn, verdicts)


def deliver(state, turn, verdicts, owned=False):
    """The verdicts of the prune agent on the ended `turn`: they join the running session, unless it is `owned`, or the next message was
    sent before they arrived -- then they wait for the conversation's next session."""
    return put(state, "waiting" if owned or state["sent"] > turn else "applied", turn, verdicts)


def switch(state, turn, number, step, pruned):
    """Set by hand whether the message `number` of `turn` -- the `step` itself handed -- is pruned: it returns a pruned one to the session or
    cuts a kept one, in the conversation's next session; the running one is not changed. What the user wrote is never cut."""
    if not prunable(step):
        raise refused("a user message is never pruned")
    state["switches"][key(turn, number)] = {"rule": "hand", "stub": stub_line(turn, number, describe(step))} if pruned else None
    return state


def pruned_now(state):
    """The verdicts the running session holds, by key."""
    return dict(state["applied"])


def pruned_next(state):
    """The verdicts the next session will hold, by key: those applied and those waiting, the switches set by hand over them."""
    settled = {**state["applied"], **state["waiting"], **state["switches"]}
    return {found: verdict for found, verdict in settled.items() if verdict}


def settle(state):
    """Bring the running session to the pruning its next session would hold -- the verdicts that waited and the switches set by hand applied
    together, their stubs left for the next message to carry -- as a replay of its turns does; its spans and size stay."""
    settled = pruned_next(state)
    standing = {verdict["stub"] for verdict in settled.values()}  # a stub not yet carried of a step switched back stays out
    state["stubs"] = [stub for stub in state["stubs"] if stub in standing] + [verdict["stub"] for found, verdict in settled.items() if found not in state["applied"]]
    state["applied"], state["waiting"], state["switches"] = settled, {}, {}
    return state


def new_session(state):
    """Start the conversation's next session: `settle`, the old session's size and spans dropped with it."""
    settle(state)
    state["size"], state["spans"] = 0, {}
    return state


def changed_turn(state):
    """The earliest turn holding a step or reply the next session would hold otherwise than the running one -- a verdict that waited, a
    switch set by hand either way -- None while there is none."""
    changed = set(state["applied"]) ^ set(pruned_next(state))
    return min((int(found.split(":", 1)[0]) for found in changed), default=None)


def note_span(state, turn, span):
    """Keep the `span` the ended `turn` left in its connection's transcript, its last request's tokens being the size of the session; a turn
    the transcript does not show -- None -- leaves both as they were."""
    if span:
        state["spans"][str(turn)] = span
        if type(span.get("tokens")) is int:
            state["size"] = span["tokens"]
    return state


def renew_bound(section):
    """The renewal bound of the `orchestrator` settings: its `renew_tokens`, an integer of zero or more -- 0 never renewing -- else `RENEW_TOKENS`."""
    value = section.get("renew_tokens") if isinstance(section, dict) else None
    return value if type(value) is int and value >= 0 else RENEW_TOKENS


def session_size(steps):
    """The input tokens of the last request among the turn's `steps` that counted them, None where none did."""
    return next((step["input_tokens"] for step in reversed(steps) if step.get("kind") == "usage" and type(step.get("input_tokens")) is int), None)


def note_size(state, steps):
    """Take the size of the running session from the ended turn's `steps`; a turn that counted no request leaves it as it was."""
    size = session_size(steps)
    if size is not None:
        state["size"] = size
    return state


def due(state, bound):
    """Whether the running session grew to the renewal `bound`, its conversation then starting its next session at the next message."""
    return bound > 0 and state.get("size", 0) >= bound


def take_stubs(state):
    """The stubs of the steps pruned since the last message, taken once."""
    stubs, state["stubs"] = state["stubs"], []
    return stubs


def carry(text, stubs):
    """The harness's next message `text` carrying the `stubs`: they stand ahead of it, never in an AI message."""
    return "\n".join([*stubs, "", text]) if stubs else text


def marked(turn, steps, verdicts):
    """The steps of the turn as the log keeps them: whole, each pruned one with the `pruned` mark added -- a state apart from the fold and
    drop marks, which stay as they were."""
    return [{**step, "pruned": True} if key(turn, number) in verdicts else dict(step) for number, step in enumerate(steps, 1)]


def log_view(message, state):
    """A message of the chat log as the page shows it: whole, every step and the reply of its turn the running session holds pruned carrying
    the `pruned` mark and, where the conversation's next session will hold it otherwise, `prune_next` telling how -- marks apart from the fold."""
    number, now, upcoming = message.get("turn"), state["applied"], pruned_next(state)
    if not isinstance(number, int) or not (now or upcoming):
        return dict(message)

    def marks(found):
        return {**({"pruned": True} if found in now else {}), **({"prune_next": found in upcoming} if (found in now) != (found in upcoming) else {})}
    steps = message.get("steps")
    return {**message, **(marks(key(number, REPLY)) if message.get("role") == "ai" else {}),
            **({"steps": [{**step, **marks(key(number, at))} for at, step in enumerate(steps, 1)]} if isinstance(steps, list) else {})}


def reply_pruned(message, state):
    """Whether the running session holds the closing reply of the logged `message` pruned."""
    return isinstance(message.get("turn"), int) and key(message["turn"], REPLY) in state["applied"]


def _replaced(message, old, new):
    """The session message with the first `old` of its text -- a string, or the text blocks of a list content -- made `new`."""
    content = message.get("content")
    if isinstance(content, str):
        return {**message, "content": content.replace(old, new, 1)}
    if isinstance(content, list):
        return {**message, "content": [{**block, "text": block["text"].replace(old, new, 1)} if isinstance(block, dict) and isinstance(block.get("text"), str) else block
                                        for block in content]}
    return message


def _unsaid(message, text=None):
    """The session's answer with the AI `text` said in it taken out -- its whole reply where `text` is None: the `text` field of a structured
    answer, else the text itself. Nothing is written in its place: the stub goes with the harness's next message."""
    content = message.get("content")
    if not isinstance(content, str):
        return message
    try:
        answer = json.loads(content)
    except ValueError:
        answer = None
    if isinstance(answer, dict):
        if text is None or str(answer.get("text") or "").strip() == str(text).strip():
            return {**message, "content": json.dumps({**answer, "text": ""}, ensure_ascii=False)}
        return message
    return {**message, "content": "" if text is None else content.replace(text, "", 1)}


def rewrite(messages, turn, steps, verdicts, rounds):
    """The messages of a session the harness writes with the `verdicts` on the ended `turn` cut out of it: the turn is its last `rounds`
    exchanges -- a user message and the answer to it each -- the results of a pruned batch made its `form` in the prompt that carried them,
    a pruned AI text taken out of the answer that said it, the closing reply out of the last answer. The messages before the turn stay as
    they were sent; a session holding fewer messages than the turn's rounds is left whole."""
    start, out = len(messages) - 2 * rounds, list(messages)
    if rounds < 1 or start < 0:
        return out
    held = 0  # the round whose answer the next AI text was said in
    for number, step in enumerate(steps, 1):
        verdict = verdicts.get(key(turn, number))
        if step.get("kind") == "calls":
            prompt, held = start + 2 * (held + 1), held + 1
            if verdict and prompt < len(out) and step.get("lines"):
                out[prompt] = _replaced(out[prompt], "\n".join(step["lines"]), "\n".join(form(verdict)))
        elif step.get("kind") == "message" and verdict and start + 2 * held + 1 < len(out):
            out[start + 2 * held + 1] = _unsaid(out[start + 2 * held + 1], step.get("text"))
    if key(turn, REPLY) in verdicts:
        out[-1] = _unsaid(out[-1])
    return out
