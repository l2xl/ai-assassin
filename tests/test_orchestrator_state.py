# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Stored state of the Orchestrator (ORCHESTRATOR-STATE-CHAT, -VECTORS, -MEMORY): what a conversation keeps with its chat log and drops
with its reset, and what the server keeps in its memory alone."""

import dataclasses
import json

import pytest

import assassin_ui
import syngatelib
from ai_scratcher import pruning, recommend, security
from test_assassin_ui import app  # noqa: F401 -- the app fixture of the page tests


def stateful(uid="LEAF-001"):
    """A chat whose live conversation holds every part of the conversation state."""
    chat = assassin_ui.Chat(uid)
    chat.log, chat.started = [{"role": "user", "text": "Hi", "turn": 1}], 1.0
    chat.session, chat.session_connector, chat.keep = "s1", "echo", {"context": "SYSTEM PROMPT"}
    chat.setup = {"connector": "echo", recommend.BEHAVIOUR_KEY: "ask"}
    chat.scan.take("fetched page")
    chat.denied = recommend.deny([], recommend.model_recommendation("echo", "model-b", "harder"))
    pruning.switch(chat.prune, 1, 2, {"kind": "tool", "name": "read"}, True)
    chat.prune = pruning.deliver(chat.prune, 1, {pruning.key(1, 3): {"rule": "agent", "stub": "[turn 1 step 3: tool read — read with log]"}})
    return chat


def assert_state(chat, original):
    assert chat.keep["context"] == "SYSTEM PROMPT"
    assert chat.scan.marked and chat.scan.pending == ["fetched page"]
    assert chat.denied == original.denied and recommend.is_denied(chat.denied, recommend.model_recommendation("echo", "model-b", "other"))
    assert chat.prune == original.prune and chat.prune["switches"] and chat.prune["applied"]
    assert chat.setup[recommend.BEHAVIOUR_KEY] == "ask"


@pytest.mark.syngate("ORCHESTRATOR-STATE-CHAT")
def test_the_conversation_state_is_kept_with_the_chat_log_and_ends_with_its_reset(app):
    chat = stateful()
    app.chats["LEAF-001"] = chat
    app.save_chats(force=True)
    assert set(json.loads(app.chats_file.read_text())["LEAF-001"]) >= {"keep", "scan", "denied", "prune", "setup"}
    restored = app._read_chats()["LEAF-001"]
    assert_state(restored, chat)

    restored.file()  # the reset: a new conversation begins
    assert restored.keep == {} and not restored.scan.marked and restored.denied == [] and restored.prune == pruning.new_state()
    assert recommend.BEHAVIOUR_KEY not in restored.setup
    blank = restored.conversation()
    assert not {"keep", "scan", "denied", "prune"} & set(blank)

    restored.resume(0)  # the filed conversation comes back with its own state
    assert_state(restored, chat)
    restored.erase()
    assert not restored.scan.marked and restored.denied == [] and restored.prune == pruning.new_state()


@pytest.mark.syngate("ORCHESTRATOR-STATE-VECTORS")
def test_the_embedding_vectors_are_kept_in_memory_and_computed_anew_at_every_start_and_for_every_changed_text(app):
    embedded = []

    def embed(texts):
        embedded.append(list(texts))
        return [[float(len(text)), 1.0] for text in texts]

    app.embed = embed
    items, _ = syngatelib.load_tree(app.syngate_dir)
    app._measure(items, "ROOT", "Fix the leaf")
    assert sorted(embedded[0]) == sorted(["Fix the leaf", *(assassin_ui.tiering.embedded_text(items, uid) for uid in ("ROOT", "LEAF-001"))])
    app._measure(items, "ROOT", "Fix the leaf")
    assert len(embedded) == 1  # nothing changed, nothing embedded
    items = {**items, "LEAF-001": dataclasses.replace(items["LEAF-001"], description="It shall leaf twice.\n")}
    app._measure(items, "ROOT", "Fix the leaf")
    assert embedded[1] == [assassin_ui.tiering.embedded_text(items, "LEAF-001")]

    app.save_chats(force=True)
    assert "twice" not in (app.chats_file.read_text() if app.chats_file.exists() else "")
    fresh = assassin_ui.AssassinApp(root=app.root, syngate_dir=app.syngate_dir, cli_prefix=app.cli_prefix)
    fresh.embed = embed
    fresh._measure(items, "ROOT", "Fix the leaf")
    assert len(embedded[2]) == 3  # a new start computes every vector anew


@pytest.mark.syngate("ORCHESTRATOR-STATE-MEMORY")
def test_the_scan_verdicts_and_the_miss_records_are_kept_in_memory_and_rebuilt_by_every_run(app):
    app.scan_verdicts[security.text_key("fetched page")] = {"verdict": "clean"}
    app.misses.append({"uid": "ROOT", "file": "src/b.py", "message": "Fix a.py"})
    app.chats["ROOT"] = stateful("ROOT")
    app.save_chats(force=True)
    saved = app.chats_file.read_text()
    assert security.text_key("fetched page") not in saved and "src/b.py" not in saved
    fresh = assassin_ui.AssassinApp(root=app.root, syngate_dir=app.syngate_dir, cli_prefix=app.cli_prefix)
    assert fresh.scan_verdicts == {} and fresh.misses == []
