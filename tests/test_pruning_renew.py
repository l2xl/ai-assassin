# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""ORCHESTRATOR-PRUNE-RENEW: the session renewal -- a session whose last request took the renewal bound of input tokens is followed by the
conversation's next session at its next message, the verdicts that waited applied and the stubs carried, the turn saying so."""

import json

import pytest

from ai_scratcher import pruning
from test_assassin_ui import app, call, server  # noqa: F401 -- the server fixtures of the page tests
from test_assassin_ui_api import Scripted, calls, turn

TREE = {"kind": "calls", "tools": ["query"], "inputs": [{"tool": "query", "uid": "LEAF-001"}], "lines": ["- LEAF-001: It shall leaf."]}


def usage(tokens):
    return {"kind": "usage", "seconds": 1.0, "cost_usd": None, "input_tokens": tokens, "output_tokens": 10}


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-RENEW", "unit")
def test_a_session_is_due_for_renewal_once_its_last_request_took_the_bound_and_a_new_session_starts_it_anew():
    assert pruning.renew_bound({}) == pruning.RENEW_TOKENS == 100000
    assert pruning.renew_bound({"renew_tokens": 5000}) == 5000 and pruning.renew_bound({"renew_tokens": 0}) == 0
    assert all(pruning.renew_bound({"renew_tokens": bad}) == pruning.RENEW_TOKENS for bad in (-1, "9", True, 1.5, None))
    assert pruning.session_size([usage(120), TREE, usage(900), {"kind": "usage", "input_tokens": None}]) == 900  # the last request counted
    assert pruning.session_size([TREE]) is None
    state = pruning.new_state()
    assert state["size"] == 0 and not pruning.due(state, 1000)
    pruning.note_size(state, [usage(999)])
    assert not pruning.due(state, 1000)
    pruning.note_size(state, [TREE])  # a turn without a counted request leaves the size as it was
    assert state["size"] == 999
    pruning.note_size(state, [usage(1000)])
    assert pruning.due(state, 1000) and not pruning.due(state, 0)  # 0 never renews
    pruning.end_turn(state, 1, [TREE], owned=True)
    assert list(state["waiting"]) == ["1:1"]
    pruning.new_session(state)
    assert state["size"] == 0 and list(state["applied"]) == ["1:1"] and not pruning.due(state, 1000)


def grown(tokens, text="Read it."):
    """A scripted reply recording a request of `tokens` input tokens, then answering in text."""
    return lambda on_step: (on_step(usage(tokens)), {"kind": "text", "text": text})[1]


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-RENEW", "page")
def test_an_owned_session_grown_past_the_bound_is_renewed_at_the_next_message_carrying_the_stubs_that_waited(server):
    base, app = server
    app.settings_file.write_text(json.dumps({"orchestrator": {"renew_tokens": 50000}}))
    app.connectors = {"echo": (connection := Scripted(calls({"tool": "query", "uid": "LEAF-001"}), grown(60000),
                                                      grown(1000, "Small."), grown(1000, "Again.")))}
    turn(base, app, "LEAF-001", "Look")
    assert app.chats["LEAF-001"].session and app.chats["LEAF-001"].prune["size"] == 60000
    waiting = app.chats["LEAF-001"].prune["waiting"]
    assert [verdict["rule"] for verdict in waiting.values()] == ["tree"]  # owned: the tree read waits for the next session
    second = turn(base, app, "LEAF-001", "Next")
    heard = connection.heard[2]
    assert heard["session"] is None and "tree read — read with log]" in heard["text"]  # a fresh session carries the stub that waited
    assert any(step.get("kind") == "context" and "renewed" in step["text"] and "60000" in step["text"] for step in second["steps"])
    assert app.chats["LEAF-001"].prune["waiting"] == {} and app.chats["LEAF-001"].prune["size"] == 1000
    turn(base, app, "LEAF-001", "Then")
    assert connection.heard[3]["session"] == "session-3"  # under the bound the session carries on


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-RENEW", "retry")
def test_a_retry_and_a_bound_of_zero_keep_the_running_session(server):
    base, app = server
    app.settings_file.write_text(json.dumps({"orchestrator": {"renew_tokens": 0}}))
    app.connectors = {"echo": (connection := Scripted(grown(900000), grown(10, "Next.")))}
    turn(base, app, "LEAF-001", "Look")
    turn(base, app, "LEAF-001", "Next")
    assert connection.heard[1]["session"] == "session-1"  # 0 never renews
    app.settings_file.write_text(json.dumps({"orchestrator": {"renew_tokens": 100}}))
    app.connectors = {"echo": (again := Scripted(grown(500), {"kind": "text", "text": "retried"}))}
    app.chats["LEAF-001"].prune["size"] = 500
    app.chats["LEAF-001"].log.append({"role": "error", "text": "it failed"})
    turn(base, app, "LEAF-001", "Next", retry=True)
    assert again.heard[0]["session"] == "session-2"  # a retry resends the message in the same session
