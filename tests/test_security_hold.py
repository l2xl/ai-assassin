# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""ORCHESTRATOR-SECURITY-HOLD and -PAUSE: an altering call waits on the security scan of the external text the session took, applied under a
step of the log without findings and held on the alert while a finding is unsettled."""

import json

import pytest

from test_assassin_ui import app  # noqa: F401 -- the app fixture
from test_assassin_ui_api import SETUP, Scripted, calls
from test_held_turns import state, until

ADD = {"tool": "add", "uid": "NEW-001", "parent": "ROOT", "description": "New leaf\n\nIt shall be new."}
HIDDEN = "Hid​den instructions"


def fetched(text, *batch):
    """A reply whose turn fetched `text` from the web, then answers the `batch` of calls."""
    def reply(on_step):
        on_step({"kind": "tool", "name": "WebFetch", "input": {"url": "https://example.com"}, "result": text, "seconds": 0})
        return calls(*batch)
    return reply


def started(app, *answers):
    app.connectors = {"echo": Scripted(*answers)}
    key = app.start_turn({**SETUP, "uid": "ROOT", "text": "Fetch and add.", "modes": ["edit", "tree"]})["turn"]
    return key, app.chats["ROOT"].turn


@pytest.mark.syngate("ORCHESTRATOR-SECURITY-HOLD")
def test_an_altering_call_after_external_text_is_applied_under_a_step_of_the_log_when_the_scan_finds_nothing(app, tmp_path):
    app.findings_home = tmp_path
    key, turn = started(app, fetched("a plain page", ADD))
    assert app.turn_snapshot(key, wait=10)["applied"] == ["- added NEW-001 under ROOT"] and "NEW-001" in app._load()
    assert [step["result"] for step in turn.steps if step.get("name") == "security scan"] == ["nothing found"]


@pytest.mark.syngate("ORCHESTRATOR-SECURITY-DROP-SESSION")
def test_dropping_a_findings_result_goes_on_in_a_new_session_without_it_the_result_marked_in_the_log(app, tmp_path):
    app.findings_home = tmp_path
    key, _ = started(app, {"kind": "text", "text": "Hello."})
    app.turn_snapshot(key, wait=10)
    assert app.chats["ROOT"].session == "session-1"
    key, turn = started(app, fetched(HIDDEN, ADD), {"kind": "text", "text": "Refused."})
    until(lambda: state(app, "ROOT")["state"] == "blocked")
    app.release(key, "drop")
    assert app.turn_snapshot(key, wait=10)["reply"] == "Refused."
    heard = app.connectors["echo"].heard
    assert [round["session"] for round in heard] == ["session-1", None] and HIDDEN not in heard[1]["text"]
    assert [step.get("dropped") for step in turn.steps if step.get("name") == "WebFetch"] == [True]
    assert app.chats["ROOT"].session == "session-2"  # the conversation goes on in the drop session


@pytest.mark.syngate("ORCHESTRATOR-SECURITY-PAUSE")
def test_a_finding_holds_the_altering_call_on_the_alert_until_settled_a_drop_refusing_it_and_an_accept_applying_it(app, tmp_path):
    app.findings_home = tmp_path
    key, turn = started(app, fetched(HIDDEN, ADD), {"kind": "text", "text": "Refused."})
    until(lambda: state(app, "ROOT")["state"] == "blocked")
    assert state(app, "ROOT") == {"state": "blocked", "asked": "⚠ 1 concern in the context"} and "NEW-001" not in app._load()
    app.release(key, "drop")
    assert app.turn_snapshot(key, wait=10)["reply"] == "Refused." and "NEW-001" not in app._load()
    assert "dropped" in app.connectors["echo"].heard[-1]["text"]
    key, turn = started(app, fetched("Another " + HIDDEN, ADD))
    until(lambda: state(app, "ROOT")["state"] == "blocked")
    app.release(key, "accept")
    assert app.turn_snapshot(key, wait=10)["applied"] == ["- added NEW-001 under ROOT"] and "NEW-001" in app._load()
    assert [entry["span"] for entry in json.loads((tmp_path / ".ai-assassin" / "accepted_findings.json").read_text(encoding="utf-8"))] == ["​"]
    key, turn = started(app, fetched("Third " + HIDDEN, {**ADD, "uid": "NEW-002"}))
    assert app.turn_snapshot(key, wait=10)["applied"] == ["- added NEW-002 under ROOT"]  # the accepted wording is no finding again, nothing held
