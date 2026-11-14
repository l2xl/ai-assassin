# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The behaviour control (ORCHESTRATOR-RECOMMEND-CONTROL): a pill among the chat's setup controls showing the chat's recommendation behaviour --
its own choice, else the default of the settings -- and opening a menu of the three, which changes it at any time."""

import time

import pytest

from test_assassin_ui import app, chrome, enter_reply, item_page, server  # noqa: F401 -- the page fixtures

PILL = "document.querySelector('#doc .block[data-uid=LEAF-001] .block-ai .pill.chat-behaviour')"
MENU = "[...document.querySelectorAll('#status-menu [data-chat-behaviour]')].map((b) => [b.dataset.chatBehaviour, b.getAttribute('aria-checked')])"


def until(check, seconds=10):
    deadline = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.02)


@pytest.mark.syngate("ORCHESTRATOR-RECOMMEND-CONTROL")
def test_the_behaviour_pill_shows_the_settings_default_until_the_chat_chooses_one_from_its_menu(server, chrome):
    base, app = server
    app.write_settings("orchestrator", {"recommendations": "ask"})
    page = item_page(server, chrome)
    enter_reply(page, "LEAF-001")
    page.wait(PILL)
    assert page.eval(f"{PILL}.textContent").startswith("ask")  # no recommendation was ever shown: the pill stands anyway
    page.eval(f"{PILL}.click()")
    page.wait("document.querySelector('#status-menu [data-chat-behaviour]')")
    assert page.eval(MENU) == [["ask", "true"], ["auto_lower", "false"], ["auto", "false"]]
    page.eval("document.querySelector('#status-menu [data-chat-behaviour=auto]').click()")
    until(lambda: "LEAF-001" in app.chats and app.chats["LEAF-001"].setup.get("recommendations") == "auto")
    page.wait(f"{PILL}.textContent.startsWith('auto ')")
    page.eval(f"{PILL}.click()")
    page.wait("document.querySelector('#status-menu [data-chat-behaviour=auto][aria-checked=true]')")
