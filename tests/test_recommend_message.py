# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The recommendation message (ORCHESTRATOR-RECOMMEND-MESSAGE): a turn held on an asked recommendation stands in the log as the recommended
model as a pill, the deny mark and the behaviour drop-down, which answer the held turn from the page."""

import time

import pytest

from test_assassin_ui import app, chrome, enter_reply, item_page, send, server  # noqa: F401 -- the page fixtures
from test_assassin_ui_api import calls
from test_setup_tool import Big, Listed

PICK = {"tool": "setup", "connection": "big", "model": "big-1", "reason": "hard"}
MESSAGE = "document.querySelector('#doc .block[data-uid=LEAF-001] .chat-log .chat-msg.recommendation')"
SHOWN = (f"(() => {{ const m = {MESSAGE}, log = m.closest('.chat-log'); return {{ pill: m.querySelector('.pill.rec-accept').textContent, "
         "deny: Boolean(m.querySelector('button.rec-deny svg circle')), behaviour: m.querySelector('select.rec-behaviour').value, "
         "options: [...m.querySelectorAll('select.rec-behaviour option')].map((o) => o.value), "
         f"turn: Boolean(log.querySelector('.turn-activity, .chat-msg.note:not(.recommendation)')) }}; }})()")


def until(check, seconds=10):
    deadline = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.02)


@pytest.mark.syngate("ORCHESTRATOR-RECOMMEND-MESSAGE")
def test_a_held_recommendation_shows_its_pill_deny_mark_and_behaviour_drop_down_in_place_of_the_turn(server, chrome):
    base, app = server
    page = item_page(server, chrome, echo=Listed(calls(PICK), {"kind": "text", "text": "Stayed."}, calls({**PICK, "effort": "high"})), big=Big())
    enter_reply(page, "LEAF-001")
    send(page, "LEAF-001", "Pick.")
    page.wait(MESSAGE)
    assert page.eval(SHOWN) == {"pill": "Scripted · big-1", "deny": True, "behaviour": "auto_lower", "options": ["ask", "auto_lower", "auto"], "turn": False}
    page.eval(f"(() => {{ const pick = {MESSAGE}.querySelector('select.rec-behaviour'); pick.value = 'ask'; pick.dispatchEvent(new Event('change', {{ bubbles: true }})); }})()")
    until(lambda: app.chats["LEAF-001"].setup.get("recommendations") == "ask")
    page.eval(f"{MESSAGE}.querySelector('.rec-deny').click()")
    until(lambda: [m["text"] for m in app.chats["LEAF-001"].log][-1:] == ["Stayed."])
    page.wait(f"!{MESSAGE}")
    assert app.chats["LEAF-001"].denied == ["model:big/big-1@"] and app.chats["LEAF-001"].setup["model"] == "model-a"  # denied: the setup stays
    send(page, "LEAF-001", "Again.")
    page.wait(MESSAGE)
    assert page.eval(SHOWN)["pill"] == "Scripted · big-1 · high" and page.eval(SHOWN)["behaviour"] == "ask"  # the chat's own choice
    page.eval(f"{MESSAGE}.querySelector('.rec-accept').click()")
    until(lambda: [m["text"] for m in app.chats["LEAF-001"].log][-1:] == ["done"])
    assert (app.chats["LEAF-001"].setup["connector"], app.chats["LEAF-001"].setup["model"]) == ("big", "big-1")
