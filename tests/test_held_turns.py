# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""ORCHESTRATOR-HELD: a turn waiting for the user is held and stays the chat's turn; ORCHESTRATOR-SERVICES-QUEUE: a message under a blocking
alert waits as the chat's queued message."""

import sys
import time

import pytest

import assassin_ui
from test_assassin_ui import app  # noqa: F401 -- the app fixture
from test_assassin_ui_api import SETUP, Scripted, calls

ASKED = "recommends Raw command"


def holding(app, uid, answers):
    """A reply that holds the running turn of `uid` on `ASKED` and answers with what the user gave it, every answer kept in `answers`."""
    def reply(on_step):
        try:
            answers.append(app.hold(app.chats[uid].turn, ASKED))
        except assassin_ui.ApiError as err:
            answers.append(err)
            raise
        return {"kind": "text", "text": f"held on {answers[-1]}"}
    return reply


def until(check, seconds=10):
    deadline = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.02)


def state(app, uid):
    with app._chat_lock:
        return app.chat_state(app.chats[uid])


def held_turn(app, answers):
    app.connectors = {"echo": Scripted(holding(app, "LEAF-001", answers))}
    key = app.start_turn({**SETUP, "uid": "LEAF-001", "text": "Hold on."})["turn"]
    until(lambda: state(app, "LEAF-001")["state"] == "blocked")
    return key


@pytest.mark.syngate("ORCHESTRATOR-HELD")
def test_a_held_turn_waits_for_the_users_answer_and_stays_the_chats_turn(app):
    answers = []
    key = held_turn(app, answers)
    assert state(app, "LEAF-001") == {"state": "blocked", "asked": ASKED} and app.chats["LEAF-001"].running and app.chats["LEAF-001"].turn.id == key
    time.sleep(0.3)
    assert app.turn_snapshot(key)["running"] and answers == []  # no timeout: it waits
    with pytest.raises(assassin_ui.ApiError) as again:
        app.start_turn({**SETUP, "uid": "LEAF-001", "text": "Another"})
    assert again.value.status == 409  # still the chat's turn
    app.release(key, "yes")
    assert app.turn_snapshot(key, wait=10)["reply"] == "held on yes" and answers == ["yes"]
    assert state(app, "LEAF-001") == {"state": "waiting"}
    with pytest.raises(assassin_ui.ApiError) as unheld:
        app.release(key, "again")
    assert unheld.value.status == 409


@pytest.mark.syngate("ORCHESTRATOR-HELD-CHILD")
def test_a_held_delegated_turn_is_held_in_its_own_chat_and_shows_blocked_in_the_chat_it_was_started_from(app):
    answers = []
    app.connectors = {"echo": Scripted(calls({"tool": "agent", "uid": "LEAF-001"}), holding(app, "LEAF-001", answers), {"kind": "text", "text": "Reported."})}
    parent = app.start_turn({**SETUP, "uid": "ROOT", "text": "Delegate."})["turn"]
    until(lambda: "LEAF-001" in app.chats and state(app, "LEAF-001")["state"] == "blocked")
    child = app.chats["LEAF-001"].turn
    assert state(app, "LEAF-001") == {"state": "blocked", "asked": ASKED} and app.chats["ROOT"].asked is None  # the hold stands in its own chat
    assert state(app, "ROOT") == {"state": "blocked", "asked": f"@LEAF-001 {ASKED}"} and app.turn_snapshot(parent)["running"]  # and waits
    app.release(child.id, "go")
    assert app.turn_snapshot(parent, wait=10)["reply"] == "Reported." and answers == ["go"]


@pytest.mark.syngate("ORCHESTRATOR-HELD-QUEUE")
def test_a_message_typed_while_a_turn_is_held_queues_behind_it(app):
    key = held_turn(app, [])
    queued = app.start_turn({**SETUP, "uid": "LEAF-001", "text": "Then this.", "queue": True})
    assert queued["queued"] == 1 and queued["chat"]["queue"] == [{"text": "Then this."}] and app._turn(key).outcome is None
    app.release(key, "yes")
    until(lambda: [m["text"] for m in app.chats["LEAF-001"].log][-1:] == ["done"])
    assert [m["text"] for m in app.chats["LEAF-001"].log] == ["Hold on.", "held on yes", "Then this.", "done"]


@pytest.mark.syngate("ORCHESTRATOR-HELD-RESET")
def test_a_reset_and_a_rename_of_the_chat_are_refused_while_its_turn_is_held(app):
    key = held_turn(app, [])
    for change in ({"reset": True}, {"erase": True}, {"begin": True}):
        with pytest.raises(assassin_ui.ApiError) as refused:
            app.update_chat("LEAF-001", change)
        assert refused.value.status == 409
    with pytest.raises(assassin_ui.ApiError) as renamed:
        app._rename(app._load(), "ROOT", {"tool": "rename", "uid": "LEAF-001", "new_uid": "LEAF-002"}, None)
    assert renamed.value.status == 409 and "LEAF-001" in app._load()
    app.release(key, "yes")


@pytest.mark.syngate("ORCHESTRATOR-HELD-STOP")
def test_stop_ends_a_held_turn_as_it_ends_a_running_one(app):
    answers = []
    key = held_turn(app, answers)
    app.stop_turn(key)
    outcome = app.turn_snapshot(key, wait=10)
    assert outcome["running"] is False and outcome["error"] == "turn stopped" and isinstance(answers[0], assassin_ui.ApiError)
    assert app.chats["LEAF-001"].log[-1]["role"] == "stopped" and state(app, "LEAF-001") == {"state": "stopped"}


@pytest.mark.syngate("ORCHESTRATOR-HELD-RESTART")
def test_a_restart_does_not_wait_for_a_held_turn_and_ends_it_as_stopped(app, tmp_path, monkeypatch):
    folder = tmp_path / "engine"
    folder.mkdir()
    (folder / "core.py").write_text("ANSWER = 1\n")
    monkeypatch.setattr(assassin_ui, "ENGINE_DIR", folder)
    app.engine_loaded, restarts = assassin_ui.engine_stamp(), []
    app.relaunch = [sys.executable, "-m", "ai_scratcher.assassin_ui", "--no-browser"]
    app.execv = lambda path, argv, env: restarts.append(argv)
    key = held_turn(app, [])
    (folder / "core.py").write_text("ANSWER = 2\n")
    assert app.engine_state()["running"] == 0  # a held turn has no timeout: the restart does not wait for it
    assert app.check_engine() and len(restarts) == 1
    assert app.turn_snapshot(key)["running"] is False and app.chats["LEAF-001"].log[-1]["role"] == "stopped"
    assert assassin_ui.Chat.restore("LEAF-001", app.chats["LEAF-001"].record()).log[-1]["role"] == "stopped"  # written out as stopped


@pytest.mark.syngate("ORCHESTRATOR-SERVICES-QUEUE")
def test_a_message_under_a_blocking_alert_waits_queued_and_is_sent_by_itself_once_every_role_answers(app):
    scripted = Scripted()
    app.connectors = {"echo": scripted}
    app._chat("LEAF-001").asked = "rerank → cuda-4gb-rerank: connection refused"
    queued = app.start_turn({**SETUP, "uid": "LEAF-001", "text": "Meanwhile."})
    assert queued["queued"] == 1 and queued["chat"]["queue"] == [{"text": "Meanwhile."}] and queued["chat"]["state"] == "blocked"
    assert not app.chats["LEAF-001"].running and scripted.heard == []  # not dispatched
    app.alert_cleared()
    until(lambda: [m["text"] for m in app.chats["LEAF-001"].log] == ["Meanwhile.", "done"])
    assert len(scripted.heard) == 1 and scripted.heard[0]["text"].endswith("Meanwhile.") and state(app, "LEAF-001") == {"state": "waiting"}
