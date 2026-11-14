# Open Trader
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""AI Assassin UI: the state of a chat.

The server tells every state of a chat but unread beside the chat; the tab adds unread, and one mark shows the state on the outline row, on a
hidden chat's arrow and on a subagent's indicator."""

import threading

import pytest

import assassin_ui
from test_assassin_ui import (LEAF_BLOCK, FlakyConnector, GatedConnector, Page, RunningAgentConnector, app, call, chrome, css_color, item_page,  # noqa: F401
                              open_chat, send, server)
from test_assassin_ui_api import SETUP, Scripted, held

ROW_MARK = ("(() => { const el = document.querySelector('#tree [data-uid=\"%s\"] .chat-state'); return [el.hidden, el.className, el.title, el.textContent, "
            "Boolean(el.querySelector('.spinner')), Boolean(el.querySelector('.spinner.hollow')), getComputedStyle(el).color]; })()")


def row_state(uid, name):
    """The page expression for the chat state mark of the outline row of `uid` while it reads `name`."""
    return f"document.querySelector('#tree [data-uid=\"{uid}\"] .chat-state.{name}')"


def mark_of(page, uid):
    """[hidden, class, title, glyph, spins, hollow, color] of the chat state mark on the outline row of `uid`."""
    return page.eval(ROW_MARK % uid)


def snapshot(app, uid):
    """The chat of `uid` as the server tells it to every page."""
    return app.chats_snapshot()["chats"][uid]


def settle(app, uid, state, asked="recommends Raw command"):
    """Brings the chat of `uid` into `state` the way the server's own bookkeeping would hold it, and announces it to the pages."""
    with app._chat_lock:
        chat = app._chat(uid)
        chat.erase()
        chat.background.clear()
        chat.asked = asked if state == "blocked" else None
        chat.log = [{"role": "user", "text": "Question"}, {"role": {"failed": "error", "stopped": "stopped"}.get(state, "ai"), "text": "Answer"}]
        if state in ("working", "blocked"):
            chat.next_turn("echo", app._notify)
        if state == "agents":
            chat.background.append(assassin_ui.Turn("LEAF-001:1", "echo"))
        app._bump(settled=False)


def block_mark(uid, selector):
    """The page expression for the first element of `selector` in the document block of `uid`."""
    return f"document.querySelector('#doc .block[data-uid=\"{uid}\"] {selector}')"


@pytest.mark.syngate("AI_CHAT-STATE-WORKING")
def test_a_chat_with_a_turn_running_is_working_and_marked_by_a_spinner(server, chrome):
    _, app = server
    gated = GatedConnector()
    page = open_chat(server, chrome, echo=gated)
    send(page, "LEAF-001", "Slow one")
    page.wait(row_state("LEAF-001", "working"))
    assert snapshot(app, "LEAF-001")["state"] == "working"
    hidden, name, title, glyph, spins, hollow, _ = mark_of(page, "LEAF-001")
    assert [hidden, name, glyph, spins, hollow] == [False, "chat-state working", "", True, False] and title.startswith("working")
    app.chats["LEAF-001"].asked = "recommends Raw command"
    assert snapshot(app, "LEAF-001")["state"] == "blocked"  # what is asked outranks the running turn
    app.chats["LEAF-001"].asked = None
    gated.release.set()
    page.wait(row_state("LEAF-001", "waiting"))


@pytest.mark.syngate("AI_CHAT-STATE-AGENTS")
def test_a_chat_that_ended_its_turn_while_subagents_it_started_run_is_agents_and_marked_by_a_hollow_spinner(server, chrome):
    _, app = server
    page = item_page(server, chrome)
    settle(app, "ROOT", "agents")
    page.wait(row_state("ROOT", "agents"))
    assert snapshot(app, "ROOT")["state"] == "agents"
    hidden, name, title, glyph, spins, hollow, _ = mark_of(page, "ROOT")
    assert [hidden, name, glyph, spins, hollow] == [False, "chat-state agents", "", True, True] and title.startswith("agents")
    with app._chat_lock:
        app.chats["ROOT"].next_turn("echo", app._notify)
    assert snapshot(app, "ROOT")["state"] == "working"  # a turn of its own running again: working comes first
    with app._chat_lock:
        app.chats["ROOT"].turn.finish({"reply": ""})
        app.chats["ROOT"].background[0].finish({"reply": "Done"})
    assert snapshot(app, "ROOT")["state"] == "waiting"  # the subagents reported


@pytest.mark.syngate("AI_CHAT-STATE-FAILED")
def test_a_chat_whose_last_turn_ended_on_an_error_is_failed_and_marked_by_a_warning_sign(server, chrome):
    _, app = server
    page = open_chat(server, chrome, echo=FlakyConnector("claude exited with 1"))
    send(page, "LEAF-001", "Doomed")
    page.wait(row_state("LEAF-001", "failed"))
    assert snapshot(app, "LEAF-001")["state"] == "failed"
    hidden, name, title, glyph, _, _, color = mark_of(page, "LEAF-001")
    assert [hidden, name, glyph, color] == [False, "chat-state failed", "⚠", css_color(page, "--red")] and title.startswith("failed")
    send(page, "LEAF-001", "Again")  # the next turn answers: the failure is behind
    page.wait(row_state("LEAF-001", "waiting"))


@pytest.mark.syngate("AI_CHAT-STATE-STOPPED")
def test_a_chat_whose_last_turn_was_stopped_is_stopped_and_marked_by_a_square(server, chrome):
    _, app = server
    gated = GatedConnector()
    page = open_chat(server, chrome, echo=gated)
    send(page, "LEAF-001", "Slow one")
    page.wait(row_state("LEAF-001", "working"))
    app.stop_turn(app.chats["LEAF-001"].turn.id)
    gated.release.set()
    page.wait(row_state("LEAF-001", "stopped"))
    assert snapshot(app, "LEAF-001")["state"] == "stopped"
    hidden, name, title, glyph, _, _, color = mark_of(page, "LEAF-001")
    assert [hidden, name, glyph, color] == [False, "chat-state stopped", "■", css_color(page, "--dim")] and title.startswith("stopped")


@pytest.mark.syngate("AI_CHAT-STATE-BLOCKED")
def test_a_chat_with_a_held_turn_a_blocked_subagent_or_a_blocking_alert_is_blocked_and_marked_by_a_pause(server, chrome):
    _, app = server
    page = item_page(server, chrome)
    settle(app, "ROOT", "blocked")  # a held turn: it is still the chat's turn, and what it asks outranks working
    page.wait(row_state("ROOT", "blocked"))
    assert [snapshot(app, "ROOT")[key] for key in ("state", "asked")] == ["blocked", "recommends Raw command"]
    hidden, name, title, glyph, _, _, color = mark_of(page, "ROOT")
    assert [hidden, name, glyph, title, color] == [False, "chat-state blocked", "⏸", "blocked — recommends Raw command", css_color(page, "--yellow-text")]

    settle(app, "LEAF-001", "blocked", asked="security alert")  # a blocked subagent blocks the chat running it, which names it
    settle(app, "ROOT", "working")
    with app._chat_lock:
        child = app.chats["LEAF-001"].turn
        app.chats["ROOT"].turn.children.append(child)
    assert [snapshot(app, "ROOT")[key] for key in ("state", "asked")] == ["blocked", "@LEAF-001 security alert"]
    child.finish({"reply": "Done"})
    assert snapshot(app, "ROOT")["state"] == "working"  # the subagent's turn ended
    settle(app, "ROOT", "waiting")
    app.chats["ROOT"].asked = "rerank → cuda-4gb-rerank: connection refused"  # a blocking alert of the model services, with no turn
    assert [snapshot(app, "ROOT")[key] for key in ("state", "asked")] == ["blocked", "rerank → cuda-4gb-rerank: connection refused"]


@pytest.mark.syngate("AI_CHAT-STATE-WAITING")
def test_a_chat_waiting_for_the_users_message_is_waiting_and_marked_by_a_circle_shown_or_hidden_alike(server, chrome):
    _, app = server
    gated = GatedConnector()
    gated.release.set()
    page = open_chat(server, chrome, echo=gated)
    send(page, "LEAF-001", "Quick one")
    page.wait(row_state("LEAF-001", "waiting"))
    assert snapshot(app, "LEAF-001")["state"] == "waiting"
    hidden, name, title, glyph, _, _, color = mark_of(page, "LEAF-001")
    assert [hidden, name, glyph, color] == [False, "chat-state waiting", "○", css_color(page, "--dim")] and title.startswith("waiting")
    page.eval(f"{LEAF_BLOCK}.querySelector('.chat-hide').click()")  # hidden: the arrow carries the mark of the same state
    page.wait(block_mark("LEAF-001", ".chat-show .state-mark.waiting"))
    assert page.eval(block_mark("LEAF-001", ".chat-show") + ".textContent") == "○▾" and mark_of(page, "LEAF-001")[1] == "chat-state waiting"


@pytest.mark.syngate("AI_CHAT-STATE-UNREAD")
def test_a_reply_a_tab_has_not_shown_reads_unread_there_while_the_server_calls_the_chat_waiting(server, chrome):
    base, app = server
    gated = GatedConnector()
    page = open_chat(server, chrome, echo=gated)
    other = Page(chrome, f"{base}/?token={app.token}")
    other.wait(row_state("LEAF-001", "waiting").replace(".chat-state.waiting", ""))
    send(page, "LEAF-001", "Slow one")
    other.wait(row_state("LEAF-001", "working"))
    gated.release.set()
    other.wait(row_state("LEAF-001", "unread"))
    page.wait(row_state("LEAF-001", "waiting"))
    hidden, name, title, glyph, _, _, color = mark_of(other, "LEAF-001")
    assert [hidden, name, glyph, color] == [False, "chat-state unread", "●", css_color(other, "--accent")] and title.startswith("unread")
    assert snapshot(app, "LEAF-001")["state"] == "waiting"  # the server's state is the same for both tabs: the reply is the tab's to call unread
    assert mark_of(page, "LEAF-001")[1] == "chat-state waiting"  # the tab that shows the reply reads waiting
    other.eval(row_state("LEAF-001", "unread") + ".click()")
    other.wait(row_state("LEAF-001", "waiting"))  # shown here now


@pytest.mark.syngate("AI_CHAT-STATE-MARK")
def test_the_state_mark_is_the_same_on_the_outline_row_a_hidden_chats_arrow_and_a_subagents_indicator(server, chrome):
    _, app = server
    gated = RunningAgentConnector()
    page = open_chat(server, chrome, echo=gated)
    send(page, "LEAF-001", "Slow one")
    indicator = f"{LEAF_BLOCK}.querySelector('a.agent-run .state-mark')"
    page.wait(indicator)
    assert page.eval(f"[{indicator}.className, {indicator}.textContent, Boolean({indicator}.querySelector('.spinner'))]") == ["state-mark working", "", True]  # no chat of its own yet
    settle(app, "ROOT", "blocked")
    page.wait(row_state("ROOT", "blocked") + " && " + block_mark("ROOT", ".chat-show .state-mark.blocked") + f" && {indicator}.classList.contains('blocked')")
    marks = "[" + row_state("ROOT", "blocked") + ", " + indicator + ", " + block_mark("ROOT", ".chat-show .state-mark") + "]"
    shown = page.eval(f"{marks}.map((el) => [el.classList.contains('blocked'), el.textContent, el.title])")
    assert shown == [[True, "⏸", "blocked — recommends Raw command"]] * 3
    gated.release.set()
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai') && !{LEAF_BLOCK}.querySelector('.agent-run')")


@pytest.mark.syngate("AI_CHAT-STATE-TITLE")
def test_the_title_of_a_state_mark_names_its_state_and_for_blocked_what_is_asked(server, chrome):
    _, app = server
    page = item_page(server, chrome)
    page.eval("state.seen.set('ROOT', 2)")  # the settled replies count as shown: waiting, not unread
    titles = {}
    for name in ("blocked", "working", "agents", "failed", "stopped", "waiting"):
        settle(app, "ROOT", name)
        page.wait(row_state("ROOT", name))
        titles[name] = mark_of(page, "ROOT")[2]
    page.eval("state.seen.set('ROOT', 0); renderChatMarks()")
    page.wait(row_state("ROOT", "unread"))
    titles["unread"] = mark_of(page, "ROOT")[2]
    assert {name: title.split(" — ")[0] for name, title in titles.items()} == {name: name for name in titles}
    assert titles["blocked"] == "blocked — recommends Raw command"
    page.eval("state.seen.set('ROOT', 2)")
    settle(app, "ROOT", "blocked", asked="")  # blocked on nothing it can name
    page.wait(f"{row_state('ROOT', 'blocked')}?.title === 'blocked'")


@pytest.mark.syngate("AI_CHAT-STATE-SERVER")
def test_the_state_is_told_by_the_server_with_every_chat_alike_to_every_page_and_never_unread(server):
    base, app = server
    gate = threading.Event()
    app.connectors = {"echo": Scripted(held(gate))}
    started = call(base, app, "/api/turn", {**SETUP, "uid": "LEAF-001", "text": "Slow"})[1]
    assert started["chat"]["state"] == "working"  # sent with the chat the start answers
    assert call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]["state"] == "working"
    gate.set()
    call(base, app, f"/api/turn/{started['turn']}?wait=10")
    first, second = (call(base, app, "/api/chats")[1]["chats"] for _ in range(2))
    assert first == second and first["LEAF-001"]["state"] == "waiting"  # the same for every page; a reply no page has shown is still waiting
    assert call(base, app, "/api/chat/LEAF-001", {"model": "model-a"})[1]["state"] == "waiting"  # and sent with the chat a change answers
    assert "unread" in assassin_ui.CHAT_STATES and all(chat["state"] in set(assassin_ui.CHAT_STATES) - {"unread"} for chat in first.values())

