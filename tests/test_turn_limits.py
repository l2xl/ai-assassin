# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Turn limits: the round fuse, the stall breaker and the closing report of a turn the harness closes -- [SYNTHETIC-TURN-LIMITS]."""

import itertools

import pytest

import assassin_ui
import synthetic
from test_assassin_ui import app, call, server  # noqa: F401 -- the server fixtures of the page tests
from test_assassin_ui_api import turn


def query(uid):
    return {"tool": "query", "uid": uid}


def calls(*batch):
    return {"kind": "calls", "calls": list(batch)}


def said(reply):
    return {"kind": "text", "text": reply}


def last(prompt):
    return prompt.rpartition("\n")[2]


class Responder:
    """A connection answering every prompt with what `answer` makes of its text, keeping the prompts."""
    label, models, efforts, modes = "Responder", ("model-a",), ("low",), ()

    def __init__(self, answer):
        self.answer, self.prompts = answer, []

    def dispatch(self, context, text, model=None, effort=None, modes=(), session=None, on_step=None, stopped=None):
        self.prompts.append(text)
        return self.answer(text), f"session-{len(self.prompts)}"


def connect(app, answer):
    app.connectors = {"echo": (connection := Responder(answer))}
    return connection


def work(app):
    return app.chat({"uid": "ROOT", "connector": "echo", "model": "model-a", "effort": "low", "modes": ["tree"], "text": "Work."})


def closing(report, otherwise):
    """The answer of a turn that reports `report` once asked to close and else answers `otherwise()`."""
    return lambda text: said(report) if synthetic.TURN_CLOSING in text else otherwise()


def varied():
    """A new refused read every round, so no round repeats the one before."""
    rounds = itertools.count()
    return lambda: calls(query(f"GONE-{next(rounds)}"))


def repeated():
    return lambda: calls(query("LEAF-009"))


def headed(why, report):
    """The reply of a turn the harness closed: the report under the harness's line telling why."""
    return synthetic.TURN_CLOSED.format(why=why) + report


@pytest.mark.syngate("SYNTHETIC-TURN-FUSE")
def test_a_turn_that_has_not_surfed_runs_up_to_the_round_fuse_of_the_settings_and_is_then_asked_to_close(app):
    assert app.turn_rounds() == synthetic.QUERY_ROUNDS == 100
    connection = connect(app, closing("Closed.", varied()))
    result = work(app)
    assert len(connection.prompts) == 101 and result["reply"] == headed(synthetic.CLOSED_FUSE, "Closed.") and len(result["applied"]) == 100  # no settings: 100 rounds, then the closing prompt
    assert synthetic.TURN_CLOSING not in connection.prompts[99] and connection.prompts[100].endswith(synthetic.TURN_CLOSING)
    for rounds in (0, -1, "9", True, 1.5):  # anything but a positive integer leaves the default
        app.write_settings("orchestrator", {"rounds": rounds})
        assert app.turn_rounds() == 100
    app.write_settings("orchestrator", {"rounds": 5})
    assert app.turn_rounds() == 5
    connection = connect(app, closing("Closed.", varied()))
    result = work(app)
    assert result["reply"] == headed(synthetic.CLOSED_FUSE, "Closed.") and len(connection.prompts) == 6 and len(result["applied"]) == 5
    assert [synthetic.TURN_CLOSING in prompt for prompt in connection.prompts] == [False] * 5 + [True]
    notice = synthetic.ROUNDS_LEFT.partition("{left}")[0].strip()
    assert notice not in connection.prompts[1] and [last(prompt) for prompt in connection.prompts[2:5]] == [synthetic.ROUNDS_LEFT.format(left=left).strip() for left in (3, 2, 1)]


@pytest.mark.syngate("SYNTHETIC-TURN-STALL")
def test_a_round_repeating_the_one_before_is_told_the_first_time_and_closes_the_turn_the_second_time(app):
    connection = connect(app, closing("Stalled.", repeated()))
    result = work(app)
    assert len(connection.prompts) == 4 and result["reply"] == headed(synthetic.CLOSED_STALL, "Stalled.")
    assert [synthetic.STALL_NUDGE in prompt for prompt in connection.prompts] == [False, False, True, False]
    assert [synthetic.TURN_CLOSING in prompt for prompt in connection.prompts] == [False, False, False, True]
    assert result["applied"] == ["- query LEAF-009 refused: unknown UID 'LEAF-009' (×3)"]
    script = [calls(query("LEAF-009")), calls(query("LEAF-009")), calls(query("LEAF-008")), calls(query("LEAF-008")), said("Fine.")]
    connection = connect(app, lambda text: script.pop(0))
    result = work(app)
    assert [synthetic.STALL_NUDGE in prompt for prompt in connection.prompts] == [False, False, True, False, True]
    assert synthetic.TURN_CLOSING not in "".join(connection.prompts) and result["reply"] == "Fine."  # a nudge alone closes nothing: a different round starts the count again


@pytest.mark.syngate("SYNTHETIC-TURN-CLOSING")
def test_the_closing_prompt_asks_one_text_answer_that_is_the_reply_and_calls_or_a_malformed_answer_end_the_turn_refused(server):
    base, app = server
    connection = connect(app, closing("Did X; tests showed Y; Z is left.", repeated()))
    result = work(app)
    assert result["reply"] == headed(synthetic.CLOSED_STALL, "Did X; tests showed Y; Z is left.") and result["session"] == "session-4" and len(connection.prompts) == 4  # the stalled turn's report is its reply, headed by why it was closed
    add = {"tool": "add", "uid": "NEW-001", "description": "New leaf\n\nIt shall be new."}
    for further in (calls(query("LEAF-009")), calls({"tool": "nope"}), calls(add)):  # the closing prompt answered with calls, with a malformed answer
        connection = connect(app, lambda text, further=further: further if synthetic.TURN_CLOSING in text else calls(query("LEAF-009")))
        with pytest.raises(assassin_ui.ApiError, match="kept querying") as refused:
            work(app)
        assert refused.value.status == 422 and refused.value.extra["session"] == "session-4" and len(connection.prompts) == 4
    assert "NEW-001" not in app._load()  # the calls of a closing answer are not run

    def delegating(text):
        if "- agent LEAF-001:" in text:
            return said("Parent done.")
        if text == "Delegate.":
            return calls({"tool": "agent", "uid": "LEAF-001"})
        return said("Child report.") if synthetic.TURN_CLOSING in text else calls(query("LEAF-009"))

    connect(app, delegating)
    outcome = turn(base, app, "ROOT", "Delegate.", modes=["tree"])  # the delegated turn stalls and reports what it was asked to
    assert outcome["reply"] == "Parent done." and len(outcome["applied"]) == 1
    report = headed(synthetic.CLOSED_STALL, "Child report.")
    assert outcome["applied"][0].startswith("- agent LEAF-001: ") and outcome["applied"][0].endswith("\n" + report)  # the delegating turn reads why it was closed
    assert app.chats["LEAF-001"].log[-1]["role"] == "ai" and app.chats["LEAF-001"].log[-1]["text"] == report
