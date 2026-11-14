# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Turn pruning on the page (ORCHESTRATOR-PRUNE-STUB, -OWNED, -STATE, -SWITCH): a page turn's end prunes it, a session the harness writes is
cut in place and the stubs go with the next message, an owned one waits for the next session, the log marks what is pruned and the switch sets
the next session's verdict."""

import pytest

from test_assassin_ui import app, call, server  # noqa: F401 -- the server fixtures of the page tests
from test_assassin_ui_api import Scripted, calls, turn

STUB = "tree read — read with log]"
SESSION = [{"role": "user", "content": "Look"}, {"role": "assistant", "content": "{}"}, {"role": "user", "content": "results"},
           {"role": "assistant", "content": "{}"}]


class Rewritable(Scripted):
    """A scripted connection whose sessions the harness writes: every rewrite it is asked for is kept."""

    def __init__(self, *answers):
        super().__init__(*answers)
        self.rewrites = []

    def rewrite_session(self, session, rewrite):
        self.rewrites.append((session, rewrite(list(SESSION))))


def read_turn(base, app, connection):
    """Run a turn that reads the tree and answers in text; -> the logged AI message."""
    app.connectors = {"echo": connection}
    turn(base, app, "LEAF-001", "Look")
    return logged(base, app)[-1]


def logged(base, app):
    return call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]["log"]


def calls_step(message):
    return next(number for number, step in enumerate(message["steps"], 1) if step.get("kind") == "calls")


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-STUB", "page")
def test_a_page_turn_ending_on_a_tree_read_is_cut_from_its_written_session_and_its_stub_heads_the_next_message(server):
    base, app = server
    connection = Rewritable(calls({"tool": "query", "uid": "LEAF-001"}), {"kind": "text", "text": "Read it."})
    message = read_turn(base, app, connection)
    assert message["turn"] == 1 and connection.rewrites and connection.rewrites[0][0] == "session-2"
    turn(base, app, "LEAF-001", "Next")
    sent = connection.heard[2]["text"]
    assert f"\n[turn 1 step {calls_step(message)}: {STUB}\n" in f"\n{sent}" and sent.index(STUB) < sent.rindex("Next")
    turn(base, app, "LEAF-001", "Again")
    assert STUB not in connection.heard[3]["text"]  # a stub is carried once


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-OWNED", "page")
def test_a_session_the_harness_cannot_write_keeps_its_turns_until_the_conversation_starts_its_next_session(server):
    base, app = server
    connection = Scripted(calls({"tool": "query", "uid": "LEAF-001"}), {"kind": "text", "text": "Read it."})
    message = read_turn(base, app, connection)
    assert "pruned" not in message["steps"][calls_step(message) - 1]
    turn(base, app, "LEAF-001", "Next")
    assert STUB not in connection.heard[2]["text"]
    call(base, app, "/api/chat/LEAF-001", {"reset": True})
    turn(base, app, "LEAF-001", "Fresh")
    assert connection.heard[3]["session"] is None and f"[turn 1 step {calls_step(message)}: {STUB}" in connection.heard[3]["text"]


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-STATE", "page")
def test_the_log_keeps_a_pruned_step_whole_under_its_pruned_mark(server):
    base, app = server
    message = read_turn(base, app, Rewritable(calls({"tool": "query", "uid": "LEAF-001"}), {"kind": "text", "text": "Read it."}))
    step = message["steps"][calls_step(message) - 1]
    assert step["pruned"] is True and step["lines"] and step["lines"][0].startswith("- LEAF-001: ")
    assert message["text"] == "Read it." and "pruned" not in message  # the reply was not judged without a prune agent


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-SWITCH", "page")
def test_the_prune_switch_of_a_logged_step_sets_the_next_sessions_verdict_and_refuses_a_step_not_logged(server):
    base, app = server
    connection = Rewritable(calls({"tool": "query", "uid": "LEAF-001"}), {"kind": "text", "text": "Read it."})
    message = read_turn(base, app, connection)
    number = calls_step(message)
    call(base, app, "/api/chat/LEAF-001", {"prune": {"turn": 1, "step": number, "pruned": False}})
    call(base, app, "/api/chat/LEAF-001", {"prune": {"turn": 1, "step": "reply", "pruned": True}})
    shown = logged(base, app)[-1]
    assert shown["steps"][number - 1]["pruned"] is True and shown["steps"][number - 1]["prune_next"] is False  # the running session is kept
    assert shown["prune_next"] is True and "pruned" not in shown
    with pytest.raises(Exception):
        call(base, app, "/api/chat/LEAF-001", {"prune": {"turn": 9, "step": 1, "pruned": True}})
    call(base, app, "/api/chat/LEAF-001", {"reset": True})
    turn(base, app, "LEAF-001", "Fresh")
    assert STUB not in connection.heard[2]["text"] and "[turn 1 reply: AI text — read with log]" in connection.heard[2]["text"]
