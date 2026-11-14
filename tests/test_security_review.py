# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The context review (ORCHESTRATOR-SECURITY-REVIEW): a turn held on the security scan's findings stands in the log as the external results
with every finding highlighted under its category and reason, each settled from the page by its accept pill or its drop mark."""

import json

import pytest

from test_assassin_ui import app, chrome, enter_reply, item_page, send, server  # noqa: F401 -- the page fixtures
from test_assassin_ui_api import Scripted
from test_held_turns import until
from test_security_hold import ADD, fetched

FETCHED = f"Step{chr(0x200b)}one and then{chr(0x202e)}back"
REVIEW = "document.querySelector('#doc .block[data-uid=LEAF-001] .chat-log .chat-msg.context-review')"
SHOWN = (f"(() => {{ const m = {REVIEW}; return {{ text: m.querySelector('.review-text').textContent, "
         "marks: [...m.querySelectorAll('.review-text mark')].map((x) => x.textContent), "
         "findings: [...m.querySelectorAll('.finding')].map((f) => [f.querySelector('.finding-category').textContent, f.querySelector('.finding-reason').textContent]), "
         f"settled: [...m.querySelectorAll('.finding')].map((f) => f.dataset.settled || '') }}; }})()")


@pytest.mark.syngate("ORCHESTRATOR-SECURITY-REVIEW")
def test_a_held_scan_shows_the_external_result_with_its_findings_highlighted_each_settled_by_accept_or_drop(server, chrome, tmp_path):
    base, app = server
    app.findings_home = tmp_path
    page = item_page(server, chrome, echo=Scripted(fetched(FETCHED, ADD), {"kind": "text", "text": "Refused."}))
    enter_reply(page, "LEAF-001")
    send(page, "LEAF-001", "Fetch and add.")
    page.wait(REVIEW)
    shown = page.eval(SHOWN)
    assert shown["text"].startswith("Step") and "one and then" in shown["text"] and shown["text"].endswith("back")
    assert shown["marks"] == ["U+200B", "U+202E"] and shown["settled"] == ["", ""]
    assert shown["findings"] == [["invisible", "ZERO WIDTH SPACE"], ["bidirectional", "RIGHT-TO-LEFT OVERRIDE"]]

    page.eval(f"{REVIEW}.querySelectorAll('.finding')[0].querySelector('.finding-accept').click()")
    page.wait(f"{REVIEW}.querySelectorAll('.finding')[0].dataset.settled === 'accept'")
    assert app.chats["LEAF-001"].running and app.chats["LEAF-001"].turn.held is not None  # one finding is still unsettled: the turn waits

    page.eval(f"{REVIEW}.querySelectorAll('.finding')[1].querySelector('.finding-drop').click()")
    until(lambda: [m["text"] for m in app.chats["LEAF-001"].log][-1:] == ["Refused."])
    page.wait(f"!{REVIEW}")
    assert "NEW-001" not in app._load()  # a dropped finding refuses the held call
    assert "dropped" in app.connectors["echo"].heard[-1]["text"]
    accepted = json.loads((tmp_path / ".ai-assassin" / "accepted_findings.json").read_text(encoding="utf-8"))
    assert [entry["span"] for entry in accepted] == [chr(0x200b)]
