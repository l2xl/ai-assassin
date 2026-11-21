# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The call lines of a batch (AI_CHAT-CALL-LINES): the calls of an answer are announced as it arrives and again with every result, every call
a request line followed by its response line -- running, waiting, answered or not run -- and a held recommendation stands under the request
of the call it holds."""

import json
import threading

import pytest

import synthetic
from test_assassin_ui import app, call, chrome, enter_reply, item_page, send, server  # noqa: F401 -- the page fixtures
from test_assassin_ui_api import SETUP, calls
from test_recommend_message import until
from test_recommend_turn import held_turn
from test_setup_tool import Listed

FIRST, ADD, LAST = {"tool": "query", "uid": "@"}, {"tool": "add", "uid": "NEW-001", "description": "New leaf\nis new."}, {"tool": "query", "uid": "ROOT"}


@pytest.mark.syngate("AI_CHAT-CALL-LINES", "live")
def test_a_batch_is_announced_as_its_answer_arrives_and_again_with_every_result_the_calls_never_run_kept_as_skipped(server):
    base, app = server
    app.connectors = {"echo": Listed(calls(FIRST, ADD, LAST), {"kind": "text", "text": "Held."})}
    started = call(base, app, "/api/turn", {**SETUP, "uid": "ROOT", "text": "Add it.", "modes": []})[1]  # tree off: the add call is held
    held = held_turn(app, "ROOT")
    assert held is not None
    snapshot = app.chats["ROOT"].snapshot()
    at = next(index for index, step in enumerate(snapshot["steps"]) if step["kind"] == "calls")
    live = snapshot["steps"][at]
    assert (live["inputs"], live["pending"], len(live["lines"])) == ([FIRST], [ADD, LAST], 1)  # answered so far, then what waits, the held call first
    assert snapshot["held"]["recommendation"]["step"] == at  # the recommendation knows the batch it holds
    app.release(held.id, "deny")
    call(base, app, f"/api/turn/{started['turn']}?wait=10")
    logged = next(step for step in app.chats["ROOT"].log[-1]["steps"] if step["kind"] == "calls")
    assert logged["inputs"] == [FIRST, ADD] and logged["skipped"] == [LAST] and "pending" not in logged  # the refusal ended the batch
    assert logged["lines"][1].startswith("- add NEW-001 refused")


@pytest.mark.syngate("AI_CHAT-CALL-LINES", "early")
def test_the_calls_a_connection_tells_ahead_of_its_return_are_shown_while_it_still_holds_the_answer(server):
    base, app = server
    told, gate = threading.Event(), threading.Event()

    def slow(on_step):
        on_step({"kind": "answer", "calls": [FIRST, LAST]})
        told.set()
        gate.wait(10)
        return calls(FIRST, LAST)

    app.connectors = {"echo": Listed(slow, {"kind": "text", "text": "Read."})}
    started = call(base, app, "/api/turn", {**SETUP, "uid": "ROOT", "text": "Read it.", "modes": []})[1]
    assert told.wait(10)
    live = [step for step in app.chats["ROOT"].snapshot()["steps"] if step["kind"] == "calls"]
    assert [(step["lines"], step["pending"]) for step in live] == [([], [FIRST, LAST])]  # requested, the answer not returned yet
    gate.set()
    call(base, app, f"/api/turn/{started['turn']}?wait=10")
    logged = [step for step in app.chats["ROOT"].log[-1]["steps"] if step["kind"] == "calls"]
    assert len(logged) == 1 and logged[0]["inputs"] == [FIRST, LAST] and "pending" not in logged[0]  # the same step, answered
    heard = []  # the Claude Code connector tells them as its answer tool is called, ahead of the result closing the CLI's turn
    steps = synthetic.turn_steps(None, heard.append)
    use = lambda **given: {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"s{len(heard)}{given['kind']}", "name": synthetic.ANSWER_TOOL, "input": given}]}}
    steps.feed(json.dumps(use(kind="calls", calls=[FIRST])))
    steps.feed(json.dumps(use(kind="text")))
    assert heard == [[FIRST]] and steps.result is None


LEAF = "document.querySelector('#doc .block[data-uid=LEAF-001] .chat-log')"
ROWS = (f"[...{LEAF}.querySelectorAll(':scope > .call-request, :scope > .call-response, :scope > .recommendation')].map((el) => "
        "[el.classList.contains('recommendation') ? 'recommendation' : el.classList[1], "
        "(el.querySelector('.call-text') || el.querySelector('.step-line, .call-state, .msg-from')).textContent.slice(0, 20)])")


def shown(line):
    """The text of a call's response as the page shows it: what the AI is sent, less the bullet and a first line that only names the call again."""
    text = line[2:] if line.startswith("- ") else line
    head, _, rest = text.partition("\n")
    return rest if rest.strip() and head.rstrip().endswith(":") else text


@pytest.mark.syngate("AI_CHAT-CALL-LINES", "page")
def test_every_call_is_a_request_line_and_a_response_line_the_held_one_carrying_its_recommendation(server, chrome):
    base, app = server
    page = item_page(server, chrome, echo=Listed(calls(FIRST, ADD, LAST), {"kind": "text", "text": "Held."}))
    enter_reply(page, "LEAF-001")
    page.eval("updateChat('LEAF-001', { modes: [] })")  # tree edits off: the add call is held on the permission
    page.wait("state.chats.get('LEAF-001')?.modes?.length === 0")
    send(page, "LEAF-001", "Add it.")
    page.wait(f"{LEAF}.querySelector('.recommendation')")
    assert page.eval(ROWS) == [["call-request", "query@"], ["call-response", 'LEAF-001: {"uid": "L'],  # the text the AI is sent, no label of the harness
                               ["call-request", "addNEW-001 New leaf"], ["recommendation", "recommendation: swit"],  # under the call it holds
                               ["call-request", "queryROOT"], ["call-response", "waiting"]]
    assert page.eval(f"Boolean({LEAF}.querySelector('.turn-activity'))")  # the turn stays shown
    page.eval(f"{LEAF}.querySelector('.recommendation .rec-deny').click()")
    until(lambda: [m["text"] for m in app.chats["LEAF-001"].log][-1:] == ["Held."])
    page.wait(f"!{LEAF}.querySelector('.recommendation') && {LEAF}.querySelector('.chat-msg.ai:not(.interim)')")
    assert page.eval(ROWS) == [["call-request", "query@"], ["call-response", 'LEAF-001: {"uid": "L'],
                               ["call-request", "addNEW-001 New leaf"], ["call-response", "add NEW-001 refused:"],  # a one-line result is kept whole
                               ["call-request", "queryROOT"], ["call-response", "not run"]]
    line = shown(next(step for step in app.chats["LEAF-001"].log[-1]["steps"] if step["kind"] == "calls")["lines"][0])  # what the AI was sent for the call
    handle, sent = f"{LEAF}.querySelector('.call-response .step-line')", f"{LEAF}.querySelector('.call-response .call-text')"
    look = (f"[{sent}.textContent, {sent}.children.length, getComputedStyle({sent}).whiteSpace, getComputedStyle({sent}).webkitLineClamp, "
            f"{sent}.parentElement.className, getComputedStyle({sent}.parentElement).backgroundColor !== 'rgba(0, 0, 0, 0)', {handle}.textContent, "
            f"{handle}.getAttribute('aria-label'), {LEAF}.querySelectorAll('.call-response .step-detail, .call-response .step-label, .call-response .step-kind').length]")
    assert page.eval(look) == [line, 0, "pre-wrap", "2", "msg-body call-body", True, "", "unfold the response", 0]  # verbatim in an AI message's body, its first lines
    level = f"Math.abs({handle}.getBoundingClientRect().top - {sent}.parentElement.getBoundingClientRect().top) < 1 && {sent}.parentElement.getBoundingClientRect().left >= {handle}.getBoundingClientRect().right"
    assert page.eval(level)  # the body starts level with its handle, beside it
    spans = page.eval(f"[...{LEAF}.querySelectorAll('.call-answer')].map((row) => {{ const body = row.querySelector('.call-body').getBoundingClientRect(), "
                      "handle = row.querySelector('.step-line').getBoundingClientRect(), all = row.getBoundingClientRect(), "
                      "request = row.parentElement.previousElementSibling.querySelector('.step-line .step-kind').getBoundingClientRect(); "
                      "return [Math.round(body.left - all.left), Math.round(all.right - body.right), Math.round(handle.left - request.left), Math.round(body.left - handle.right)]; })")
    assert len(spans) == 2 and spans[0] == spans[1]  # a long result and a short one: bodies of one width
    assert spans[0][1] > 30 and spans[0][2:] == [0, 0]  # up to the column kept for the prune mark, from the handle standing under the first letter of the request's tool name
    marks = page.eval(f"[...{LEAF}.querySelectorAll('.call-answer > .prune-mark')].map((mark) => {{ const at = mark.getBoundingClientRect(), row = mark.parentElement, "
                      "body = row.querySelector('.call-body').getBoundingClientRect(); return [at.left >= body.right, at.right <= row.getBoundingClientRect().right + 1, Math.abs(at.top - body.top) < 8]; })")
    assert marks and all(mark == [True, True, True] for mark in marks)  # a prune mark stands in that column, level with the first line
    assert page.eval(f"[...{LEAF}.querySelectorAll('.call-request')].filter((row) => row.nextElementSibling?.querySelector('.call-answer') && row.querySelector('.prune-mark')).length") == 0  # never on the request of an answered call
    page.eval(f"{handle}.click()")
    page.wait(f"{handle}.getAttribute('aria-expanded') === 'true'")
    assert page.eval(look) == [line, 0, "pre-wrap", "none", "msg-body call-body", True, "", "fold the response", 0]  # the whole of it in place, shown once
    texts = ["- context of LEAF-001:\n# Seed\ntext", "- grep -n x src:\nexit 1", "- read a.py lines 1-2 of 2\n1\tx", "- LEAF-001: {}", "- shell ls:\n", "plain:\nmore"]
    assert page.eval(f"{json.dumps(texts)}.map(callText)") == [shown(text) for text in texts] == [
        "# Seed\ntext", "exit 1", "read a.py lines 1-2 of 2\n1\tx", "LEAF-001: {}", "shell ls:\n", "more"]  # the heading naming the call again is dropped, no other line
    request = f"{LEAF}.querySelector('.call-request .step-line')"
    page.eval(f"{request}.click()")
    page.wait(f"{request}.parentElement.querySelector('.step-detail')")
    assert page.eval(f"[...{request}.parentElement.querySelectorAll('.step-detail > *')].map((el) => el.textContent)")[0] == "call"
