# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Turn pruning on the page (ORCHESTRATOR-PRUNE-STUB, -OWNED, -STATE, -SWITCH): a page turn's end prunes it, a session the harness writes is
cut in place and the stubs go with the next message, an owned one waits for the next session, the log marks what is pruned and the switch sets
the next session's verdict."""

import json

import pytest

import assassin_ui
import synthetic
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


class Replaying(Scripted):
    """A scripted connection owning its session: it tells a span for every turn and keeps every replay it is asked for, answering with
    `outcome` -- a replayed session by default."""

    def __init__(self, *answers, outcome=("replayed", "replayed-1")):
        super().__init__(*answers)
        self.replays, self.outcome = [], outcome

    def turn_span(self, session, rounds):
        return {"session": session, "first": "a", "last": "b", "tokens": 1000}

    def replay_session(self, session, turns, block, **options):
        self.replays.append((session, turns, options))
        return self.outcome


def usage(tokens):
    return {"kind": "usage", "seconds": 1.0, "cost_usd": None, "input_tokens": tokens, "output_tokens": 10}


def grown(tokens, text="Read it."):
    """A scripted reply recording a request of `tokens` input tokens, then answering in text."""
    return lambda on_step: (on_step(usage(tokens)), {"kind": "text", "text": text})[1]


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-OWNED", "page")
def test_an_owned_session_takes_its_verdicts_through_its_connections_replay_with_the_next_message_and_is_never_restarted_for_them(server):
    base, app = server
    connection = Replaying(calls({"tool": "query", "uid": "LEAF-001"}), {"kind": "text", "text": "Read it."})
    message = read_turn(base, app, connection)
    assert "pruned" not in message["steps"][calls_step(message) - 1] and connection.replays == []  # the verdict waits for the next message
    second = turn(base, app, "LEAF-001", "Next")
    session, turns, options = connection.replays[0]
    assert session == "session-2" and options == {} and [record["turn"] for record in turns] == [1]  # under the worth: nothing forces it
    assert [verdict["rule"] for verdict in turns[0]["verdicts"].values()] == ["tree"] and turns[0]["was"] == {}
    heard = connection.heard[2]
    assert heard["session"] == "replayed-1" and f"[turn 1 step {calls_step(message)}: {STUB}" in heard["text"]  # the session its connection replayed, not a new one
    assert synthetic.HISTORY_PREAMBLE not in heard["text"] and any(step.get("kind") == "context" and "replayed from turn 1" in step["text"] for step in second["steps"])
    assert logged(base, app)[1]["steps"][calls_step(message) - 1]["pruned"] is True

    waiting = Replaying(calls({"tool": "query", "uid": "LEAF-001"}), {"kind": "text", "text": "Read it."}, outcome=None)
    call(base, app, "/api/chat/LEAF-001", {"erase": True})
    read_turn(base, app, waiting)
    turn(base, app, "LEAF-001", "Next")
    assert len(waiting.replays) == 1 and waiting.heard[2]["session"] == "session-2" and STUB not in waiting.heard[2]["text"]  # not worth it: the change waits


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-SESSION-HEAD", "page")
def test_a_new_session_is_headed_by_its_turns_as_the_pruning_holds_them_the_kept_results_whole_and_the_stubs_in_place(server):
    base, app = server
    connection = Scripted(calls({"tool": "query", "uid": "LEAF-001"}), calls({"tool": "list"}), {"kind": "text", "text": "Read it."})
    message = read_turn(base, app, connection)
    listed = next(step for step in message["steps"] if step.get("kind") == "calls" and step["tools"] == ["list"])
    call(base, app, "/api/chat/LEAF-001", {"reset": True})
    turn(base, app, "LEAF-001", "Fresh")
    sent = connection.heard[3]
    assert sent["session"] is None and sent["text"].startswith(synthetic.HISTORY_PREAMBLE + "user: Look\n")
    assert f"harness: [turn 1 step {calls_step(message)}: {STUB}" in sent["text"] and sent["text"].count(STUB) == 1  # the stub stands where the cut result stood
    assert "harness: " + "\n".join(listed["lines"]) in sent["text"] and "assistant: Read it." in sent["text"]  # a result no verdict cut is whole
    assert "It shall leaf." not in sent["text"].split("harness: ")[1]


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-CONTINUITY", "page")
def test_a_session_of_any_size_goes_on_with_the_next_message_and_no_setting_bounds_it(server):
    base, app = server
    app.settings_file.write_text(json.dumps({"orchestrator": {"renew_tokens": 100}}))
    app.connectors = {"echo": (connection := Scripted(grown(900000), grown(900000, "Next."), grown(10, "Then.")))}
    turns = [turn(base, app, "LEAF-001", text) for text in ("Look", "Next", "Then")]
    assert [heard["session"] for heard in connection.heard] == [None, "session-1", "session-2"]  # the one session, never started anew
    assert app.chats["LEAF-001"].prune["size"] == 10
    assert not any(step.get("kind") == "context" and "renew" in step["text"] for outcome in turns for step in outcome["steps"])
    assert not hasattr(assassin_ui, "RENEWED") and "renew_tokens" not in (assassin_ui.PAGE.read_text() if hasattr(assassin_ui, "PAGE") else "")


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-STATE", "page")
def test_the_log_keeps_a_pruned_step_whole_under_its_pruned_mark(server):
    base, app = server
    message = read_turn(base, app, Rewritable(calls({"tool": "query", "uid": "LEAF-001"}), {"kind": "text", "text": "Read it."}))
    step = message["steps"][calls_step(message) - 1]
    assert step["pruned"] is True and step["lines"] and step["lines"][0].startswith("- LEAF-001: ")
    assert message["text"] == "Read it." and "pruned" not in message  # the reply was not judged without a prune agent


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-SWITCH", "page")
def test_the_prune_switch_marks_every_step_and_ai_message_and_takes_effect_with_the_next_message_in_the_running_session(server):
    base, app = server
    page = (assassin_ui.Path(assassin_ui.__file__).parent / "assassin_ui.html").read_text(encoding="utf-8")
    assert 'class="prune-mark' in page and "togglePrune(chat" in page and 'pruneMark(index, "reply", m)' in page  # the mark of a step line and of an AI message
    connection = Rewritable(calls({"tool": "query", "uid": "LEAF-001"}), {"kind": "text", "text": "Read it."})
    connection.replays = []
    connection.turn_span = lambda session, rounds: {"session": session, "start": 0, "rounds": rounds, "tokens": None}
    connection.replay_session = lambda session, turns, block, **options: connection.replays.append((session, turns, options)) or ("rewritten", session)
    message = read_turn(base, app, connection)
    number = calls_step(message)
    call(base, app, "/api/chat/LEAF-001", {"prune": {"turn": 1, "step": number, "pruned": False}})
    call(base, app, "/api/chat/LEAF-001", {"prune": {"turn": 1, "step": "reply", "pruned": True}})
    shown = logged(base, app)[-1]
    assert shown["steps"][number - 1]["pruned"] is True and shown["steps"][number - 1]["prune_next"] is False  # the running session is as it was
    assert shown["prune_next"] is True and "pruned" not in shown and connection.replays == []
    with pytest.raises(Exception):
        call(base, app, "/api/chat/LEAF-001", {"prune": {"turn": 9, "step": 1, "pruned": True}})
    second = turn(base, app, "LEAF-001", "Next")
    session, turns, options = connection.replays[0]
    assert session == "session-2" and options == {"force": True}  # a switch set by hand asks no worth
    assert list(turns[0]["verdicts"]) == ["1:reply"] and list(turns[0]["was"]) == [f"1:{number}"]
    heard = connection.heard[2]
    assert heard["session"] == "session-2" and "[turn 1 reply: AI text — read with log]" in heard["text"] and STUB not in heard["text"]
    assert any(step.get("kind") == "context" and "brought in from turn 1" in step["text"] for step in second["steps"])
    shown = logged(base, app)[1]
    assert shown["pruned"] is True and "pruned" not in shown["steps"][number - 1] and "prune_next" not in shown
