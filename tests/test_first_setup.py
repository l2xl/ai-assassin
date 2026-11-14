# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""ORCHESTRATOR-SETUP-FIRST: the server runs the first setup by itself while the settings hold no orchestrator section, every chat showing
its progress in place of the reply line's hint."""

import json
import threading

import pytest

from test_assassin_ui import REST_HINT, app, chrome, item_page, server  # noqa: F401 -- the fixtures

PLACEHOLDER = "document.querySelector('#doc .block[data-uid=\"%s\"] .chat-input').placeholder"


@pytest.mark.syngate("ORCHESTRATOR-SETUP-FIRST")
def test_the_server_runs_the_first_setup_while_no_orchestrator_section_is_held_every_chat_showing_its_step(server, chrome):
    base, app = server
    page = item_page(server, chrome)
    steps, go, runs = threading.Event(), threading.Event(), []

    def run(root, say):
        runs.append(root)
        say("hardware: asking for a card")
        steps.set()
        go.wait(10)
        (root / "assassin_settings.json").write_text(json.dumps({"orchestrator": {"budget": 1}}))
        return {"wrote": ["orchestrator.budget"], "unrouted": []}

    thread = app.first_setup(run)
    assert steps.wait(10) and runs == [app.root]
    shown = "setting up the model services… hardware: asking for a card"
    assert app.chats_snapshot()["setup"] == shown
    for uid in ("ROOT", "LEAF-001"):  # every chat, one never begun included
        page.wait(f"{PLACEHOLDER % uid} === {json.dumps(shown)}")
    go.set()
    thread.join(10)
    assert "setup" not in app.chats_snapshot()
    page.wait(f"{PLACEHOLDER % 'LEAF-001'} === {json.dumps(REST_HINT)}")

    assert app.first_setup(run) is None and len(runs) == 1  # the section is held now: nothing runs again

    def broken(root, say):
        say("hardware: asking for a card")
        raise RuntimeError("settings unreadable")

    (app.root / "assassin_settings.json").unlink()
    app.first_setup(broken).join(10)
    assert "setup" not in app.chats_snapshot()  # a setup that fails ends its progress too
