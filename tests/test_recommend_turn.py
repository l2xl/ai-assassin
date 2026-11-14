# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The setup recommendation in a turn (ORCHESTRATOR-RECOMMEND): the setup call settled through the chat's behaviour, an asked one holding the
turn until the user answers it, an accepted model taking the turn over in a new session, a subagent's recommendation its own chat's and an
off-context agent recommending nothing."""

import json
import threading
import time

import pytest

import assassin_ui
import synthetic
from ai_scratcher import recommend
from test_assassin_ui import app, call, server  # noqa: F401 -- the server fixtures of the page tests
from test_assassin_ui_api import SETUP, calls, turn
from test_setup_tool import Big, Listed

PICK = {"tool": "setup", "connection": "big", "model": "big-1", "reason": "hard"}
ASKED = recommend.asked_text(recommend.model_recommendation("big", "big-1", "hard"))


def held_turn(app, uid, wait=10):
    """The turn of `uid`'s chat once it is held on a question not answered yet, None past `wait` seconds."""
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        chat = app.chats.get(uid)
        if chat is not None and chat.turn is not None and chat.turn.held is not None and chat.turn.answer is None:
            return chat.turn
        time.sleep(0.02)
    return None


def answering(app, uid, answer):
    """A thread answering `answer` to the turn of `uid`'s chat once it is held."""
    thread = threading.Thread(target=lambda: (held := held_turn(app, uid)) and app.release(held.id, answer), daemon=True)
    thread.start()
    return thread


def state(app, uid):
    with app._chat_lock:
        return app.chat_state(app.chats[uid])


@pytest.mark.syngate("ORCHESTRATOR-RECOMMEND-MODEL")
def test_a_setup_call_of_the_chats_model_naming_another_is_a_recommendation_and_naming_its_own_is_refused(server):
    base, app = server
    own = {**PICK, "connection": "echo", "model": "model-a"}
    app.connectors = {"echo": (echo := Listed(calls(PICK), {"kind": "text", "text": "Stayed."}, calls(own), {"kind": "text", "text": "Ok."},
                                               calls(PICK), {"kind": "text", "text": "Again."})), "big": (big := Big())}
    answering(app, "ROOT", "deny")
    outcomes = [turn(base, app, "ROOT", "Pick.", modes=[], recommendations="ask") for _ in range(3)]
    assert [(outcome["reply"], outcome["applied"]) for outcome in outcomes] == [
        ("Stayed.", ["- setup big big-1: hard" + recommend.DENIED]),
        ("Ok.", [f"- setup model-a refused: {recommend.SAME_REFUSED}"]),
        ("Again.", ["- setup big big-1: hard" + recommend.DENIED_BEFORE])], outcomes  # a denied one is not asked again
    assert echo.heard[1]["text"] == synthetic.RESULTS_PREAMBLE + "- setup big big-1: hard" + recommend.DENIED and big.heard == []
    assert app.chats["ROOT"].setup["connector"] == "echo" and app.chats["ROOT"].denied == ["model:big/big-1@"]


@pytest.mark.syngate("ORCHESTRATOR-RECOMMEND-ANYTIME")
def test_a_setup_call_is_accepted_at_any_answer_of_a_session_as_the_sole_call_of_that_answer(server):
    base, app = server
    app.connectors = {"echo": (echo := Listed(calls({"tool": "query", "uid": "@"}), calls({"tool": "models"}, PICK), calls(PICK))), "big": (big := Big())}
    outcome = turn(base, app, "ROOT", "Pick.", modes=[], recommendations="auto")
    assert outcome["applied"] == [f"- setup big-1 refused: {recommend.SOLE_REFUSED}", "model → big-1: hard"], outcome
    assert echo.heard[2]["text"].endswith(f"- setup big-1 refused: {recommend.SOLE_REFUSED}")  # the models call beside it ran, the setup call did not
    assert len(echo.heard) == 3 and len(big.heard) == 1 and outcome["reply"] == "done"  # the third answer's setup call was applied


@pytest.mark.syngate("ORCHESTRATOR-RECOMMEND-PAUSE")
def test_an_asked_recommendation_holds_the_turn_until_the_user_accepts_or_denies_it(server):
    base, app = server
    app.connectors = {"echo": Listed(calls(PICK), {"kind": "text", "text": "Stayed."}), "big": (big := Big())}
    started = call(base, app, "/api/turn", {**SETUP, "uid": "ROOT", "text": "Pick.", "modes": [], "recommendations": "ask"})[1]
    held = held_turn(app, "ROOT")
    assert held is not None and held.id == started["turn"] and held.held == ASKED
    time.sleep(0.3)
    assert app.turn_snapshot(started["turn"])["running"] and state(app, "ROOT") == {"state": "blocked", "asked": ASKED}  # no timeout ends it
    app.release(started["turn"], {"accept": True, "recommendations": "auto"})
    outcome = call(base, app, f"/api/turn/{started['turn']}?wait=10")[1]
    assert outcome["applied"] == ["model → big-1: hard"] and outcome["reply"] == "done" and len(big.heard) == 1
    assert state(app, "ROOT")["state"] != "blocked" and app.chats["ROOT"].setup["recommendations"] == "auto"  # the drop-down's choice stands
    with pytest.raises(Exception, match="not held"):
        app.release(started["turn"], "accept")


@pytest.mark.syngate("ORCHESTRATOR-RECOMMEND-RESTART")
def test_an_accepted_model_takes_the_turn_over_in_a_new_session_holding_what_the_turn_did_so_far(server):
    base, app = server
    app.connectors = {"echo": (echo := Listed(calls({"tool": "query", "uid": "@"}), calls(PICK))), "big": (big := Big())}
    outcome = turn(base, app, "ROOT", "Pick.", modes=[], recommendations="auto")
    rec = recommend.model_recommendation("big", "big-1", "hard")
    assert outcome["reply"] == "done" and outcome["applied"] == ["model → big-1: hard"] and len(echo.heard) == 2
    handover = big.heard[0]
    assert handover == {"text": assassin_ui.TREE_OFF + "\n" + recommend.handover_text("Pick.", ["model → big-1: hard"], rec), "modes": [], "session": None}
    assert "Pick." in handover["text"] and "model → big-1: hard" in handover["text"]  # the same message, with what the turn did
    chat = app.chats["ROOT"]
    assert (chat.setup["connector"], chat.setup["model"], chat.session, chat.session_connector) == ("big", "big-1", "session-1", "big")


@pytest.mark.syngate("ORCHESTRATOR-RECOMMEND-SUBAGENT")
def test_a_delegated_turn_recommends_for_its_own_chat_alone_under_the_behaviour_it_was_started_with(server):
    base, app = server
    delegate = {"tool": "agent", "uid": "LEAF-001", "prompt": "Pick a model."}
    app.connectors = {"echo": Listed(calls(delegate), calls(PICK), {"kind": "text", "text": "Child stayed."}, {"kind": "text", "text": "Parent done."}),
                      "big": (big := Big())}
    started = call(base, app, "/api/turn", {**SETUP, "uid": "ROOT", "text": "Delegate.", "modes": [], "recommendations": "ask"})[1]
    held = held_turn(app, "LEAF-001")
    assert held is not None and held.held == ASKED  # asked under the behaviour the delegating chat started it with
    assert state(app, "LEAF-001") == {"state": "blocked", "asked": ASKED}
    assert state(app, "ROOT") == {"state": "blocked", "asked": f"@LEAF-001 {ASKED}"} and app.chats["ROOT"].turn.held is None
    app.release(held.id, "deny")
    outcome = call(base, app, f"/api/turn/{started['turn']}?wait=10")[1]
    assert outcome["reply"] == "Parent done." and big.heard == []
    assert app.chats["LEAF-001"].denied == ["model:big/big-1@"] and app.chats["ROOT"].denied == []  # the child's chat alone
    assert app.chats["LEAF-001"].setup["recommendations"] == "ask" and app.chats["ROOT"].setup["connector"] == "echo"


ADD = {"tool": "add", "uid": "NEW-001", "description": "New leaf\nis new."}
TREE = recommend.permission_recommendation("tree", "the add call of this turn needs it")


@pytest.mark.syngate("ORCHESTRATOR-RECOMMEND-PERMISSION")
def test_a_call_only_a_switched_off_permission_refuses_is_held_on_the_harnesss_recommendation_the_scan_standing_first(server):
    base, app = server
    scanned, scan_hold = [], app._scan_hold
    app._scan_hold = lambda turn, call=None, recommendation=None: (scanned.append((call, recommendation)), scan_hold(turn, call, recommendation))[1]
    app.connectors = {"echo": Listed(calls(ADD), {"kind": "text", "text": "Held."})}
    started = call(base, app, "/api/turn", {**SETUP, "uid": "ROOT", "text": "Add it.", "modes": []})[1]  # the default behaviour asks a raise
    held = held_turn(app, "ROOT")
    assert held is not None and held.held == recommend.asked_text(TREE) == "recommendation permission → tree: the add call of this turn needs it"
    assert scanned[-1] == (None, TREE) and "NEW-001" not in app._load()  # the raise scanned before it was asked, the call held, not applied
    assert state(app, "ROOT") == {"state": "blocked", "asked": held.held}
    app.release(held.id, "deny")
    call(base, app, f"/api/turn/{started['turn']}?wait=10")
    app.connectors = {"echo": Listed(calls(ADD), {"kind": "text", "text": "Plain."})}
    import assassin_ui
    outcome = call(base, app, "/api/chat", {**SETUP, "uid": "LEAF-001", "text": "Add it.", "modes": []})[1]  # no turn to hold: refused as it was
    assert outcome["applied"] == [f"- add NEW-001 refused: {assassin_ui.TREE_REFUSAL}"]


@pytest.mark.syngate("ORCHESTRATOR-RECOMMEND-GRANTED")
def test_an_accepted_permission_is_switched_on_for_the_chat_and_the_held_call_applied(server):
    base, app = server
    app.connectors = {"echo": Listed(calls(ADD), calls({**ADD, "uid": "NEW-002"}))}
    started = call(base, app, "/api/turn", {**SETUP, "uid": "ROOT", "text": "Add it.", "modes": [], "recommendations": "ask"})[1]
    app.release(held_turn(app, "ROOT").id, "accept")
    outcome = call(base, app, f"/api/turn/{started['turn']}?wait=10")[1]
    assert (outcome["reply"], outcome["applied"]) == ("", ["- added NEW-001 under ROOT"]) and "NEW-001" in app._load()
    assert app.chats["ROOT"].setup["modes"] == ["tree"]  # on for the chat from then on
    outcome = turn(base, app, "LEAF-001", "Add it.", modes=[], recommendations="auto")  # applied at once: its line in the log
    assert outcome["applied"] == [recommend.applied_line(TREE), "- added NEW-002 under LEAF-001"] and app.chats["LEAF-001"].setup["modes"] == ["tree"]


@pytest.mark.syngate("ORCHESTRATOR-RECOMMEND-REFUSED")
def test_a_denied_permission_leaves_its_held_call_refused_to_the_model(server):
    import assassin_ui
    base, app = server
    app.connectors = {"echo": (echo := Listed(calls(ADD), {"kind": "text", "text": "Could not."}, calls(ADD), {"kind": "text", "text": "Again not."}))}
    answering(app, "ROOT", "deny")
    outcomes = [turn(base, app, "ROOT", "Add it.", modes=[]) for _ in range(2)]
    refusal = f"- add NEW-001 refused: {assassin_ui.TREE_REFUSAL}"
    assert [(outcome["reply"], outcome["applied"]) for outcome in outcomes] == [("Could not.", [refusal]), ("Again not.", [refusal])]
    assert echo.heard[1]["text"] == synthetic.RESULTS_PREAMBLE + refusal and "NEW-001" not in app._load()
    assert app.chats["ROOT"].denied == ["permission:tree"] and "tree" not in (app.chats["ROOT"].setup.get("modes") or ())  # not asked again


class Routed(Listed):
    """A listed connector an off-context agent's route may name: its dispatch takes the agent."""

    def dispatch(self, *args, agent=None, **kwargs):
        self.agents = [*getattr(self, "agents", []), agent.name if agent else None]
        return super().dispatch(*args, **kwargs)


@pytest.mark.syngate("ORCHESTRATOR-RECOMMEND-OFF-CONTEXT")
def test_an_off_context_agent_runs_on_the_route_of_the_settings_and_its_setup_call_is_refused(app):
    folder = app.root.parent / "fixture_prompts"
    folder.mkdir(exist_ok=True)
    (folder / "picker.md").write_text("---\nkind: agent\ndescription: Picks\ntools: [setup]\n---\n# Picker\nPick a model.\n")
    app.library = {**synthetic.read_library(app.library), "picker": synthetic.read_prompt(folder / "picker.md")}
    app.connectors = {"echo": (echo := Routed(calls(PICK), {"kind": "text", "text": "Picked nothing."})), "big": (big := Big())}
    app.settings_file.write_text(json.dumps({"orchestrator": {"agents": {"default": {"connection": "echo", "model": "model-a"}}, "recommendations": "auto"}}))
    outcome = app.run_agent("picker", {"uid": "ROOT", "text": "Pick.", "modes": [], "connector": "big", "model": "big-1"})
    assert outcome["reply"] == "Picked nothing." and outcome["applied"] == [f"- setup big-1 refused: {recommend.OFF_CONTEXT_REFUSED}"], outcome
    assert echo.agents == ["picker", "picker"] and big.heard == []  # the route, not the starting chat's setup, and no switch even under auto
