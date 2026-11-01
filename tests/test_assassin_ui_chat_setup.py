# AI-Scratcher
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""AI Assassin UI: the setup and permissions of a new chat and of a running one, the notices and the refusals a turn tells the AI --
[AI_CHAT-DEFAULTS] [AI_CHAT-PERMISSION-ADVANCED-OFF] [AI_CHAT-PERMISSION-UNSUPPORTED] [AI_CHAT-PERMISSION-RESET] [AI_CHAT-INTERRUPT] [AI_CHAT-ANSWER-REFUSED]"""

import json

import pytest

import assassin_ui
import synthetic
from test_assassin_ui import app, call, server  # noqa: F401 -- the server fixtures of the page tests
from test_assassin_ui_api import SETUP, Scripted, calls, turn


class Advanced(Scripted):
    """A connector with one main and one advanced permission."""
    modes = ("edit", "raw")

    def settings(self):
        return {**super().settings(), "modes": [{"id": "edit", "label": "Edit files", "hint": "h", "default": True},
                                                {"id": "raw", "label": "Raw", "hint": "h", "default": False, "advanced": True}]}


class Other(Scripted):
    """A second connector listing a permission the first does not."""
    modes = ("workflows",)

    def settings(self):
        return {**super().settings(), "modes": [{"id": "workflows", "label": "Workflows", "hint": "h", "default": False, "advanced": True}]}


def saved(app):
    return json.loads(app.settings_file.read_text())


@pytest.mark.syngate("AI_CHAT-DEFAULTS", "api")
def test_the_setup_chosen_in_a_new_chat_is_kept_in_the_settings_for_new_chats_only(server):
    base, app = server
    app.connectors = {"echo": Advanced({"kind": "text", "text": "Hi"}), "other": Other()}
    app.settings_file.write_text(json.dumps({"websurf": {"rounds": 3}}))
    assert app.build_model()["chat_defaults"] == {"connector": "echo", "model": "model-a", "effort": "low", "modes": ["tree", "patch", "edit"]}
    call(base, app, "/api/chat/LEAF-001", {"connector": "other", "model": "model-a", "effort": "low", "modes": ["tree"]})
    assert saved(app) == {"websurf": {"rounds": 3}, "chat": {"connector": "other", "model": "model-a", "effort": "low", "modes": ["tree"]}}
    assert app.build_model()["chat_defaults"]["connector"] == "other"  # every block without a chat is offered it
    turn(base, app, "LEAF-001", "First", connector="echo", modes=["tree", "edit"])
    call(base, app, "/api/chat/LEAF-001", {"modes": ["tree"]})  # a chat holding messages keeps its choice to itself
    assert saved(app)["chat"]["modes"] == ["tree"] and app.chats["LEAF-001"].setup["modes"] == ["tree"] and app.chats["LEAF-001"].setup["connector"] == "echo"
    call(base, app, "/api/chat/LEAF-001", {"modes": ["tree", "edit"], "new": True})  # the tab's fresh view stands for a new conversation
    assert saved(app)["chat"]["modes"] == ["tree", "edit"]


@pytest.mark.syngate("AI_CHAT-PERMISSION-ADVANCED-OFF")
def test_advanced_permissions_stay_with_their_chat_and_are_off_in_a_new_one(server):
    base, app = server
    app.connectors = {"echo": (scripted := Advanced({"kind": "text", "text": "Hi"}))}
    call(base, app, "/api/chat/LEAF-001", {**SETUP, "modes": ["tree", "edit", "raw"]})
    assert saved(app)["chat"]["modes"] == ["tree", "edit"] and app.chats["LEAF-001"].setup["modes"] == ["tree", "edit", "raw"]
    assert app.build_model()["chat_defaults"]["modes"] == ["tree", "edit"]
    turn(base, app, "LEAF-001", "First", modes=["tree", "edit", "raw"])
    assert scripted.heard[0]["modes"] == ["edit", "raw"]
    call(base, app, "/api/chat/LEAF-001", {"begin": True})
    assert app.chats["LEAF-001"].setup["modes"] == ["tree", "edit"]
    app.settings_file.write_text(json.dumps({"chat": {"modes": ["tree", "raw"]}}))
    assert app.chat_defaults()["modes"] == ["tree"]


@pytest.mark.syngate("AI_CHAT-PERMISSION-UNSUPPORTED")
def test_a_permission_the_connector_does_not_list_is_ignored_without_an_error(server):
    base, app = server
    app.connectors = {"echo": (scripted := Scripted({"kind": "text", "text": "Hi"})), "other": Other()}
    outcome = turn(base, app, "LEAF-001", "First", modes=["tree", "edit", "workflows"])
    assert outcome["reply"] == "Hi" and scripted.heard[0]["modes"] == ["edit"]
    assert app.chats["LEAF-001"].setup["modes"] == ["tree", "edit", "workflows"] and len(app.chats["LEAF-001"].log) == 2


@pytest.mark.syngate("AI_CHAT-PERMISSION-RESET")
def test_an_unknown_permission_is_reset_to_the_defaults_at_its_source_with_a_notice_the_ai_is_told_too(server):
    base, app = server
    app.connectors = {"echo": (scripted := Scripted({"kind": "text", "text": "One"}, {"kind": "text", "text": "Two"}, {"kind": "text", "text": "Three"}))}
    turn(base, app, "LEAF-001", "First", modes=["tree", "edit", "bogus"])  # a stale name, as the old `edit` of the files switch once was
    chat = app.chats["LEAF-001"]
    notice = assassin_ui.MODES_RESET.format(why='unknown "bogus"', modes="tree, patch, edit")
    assert chat.setup["modes"] == ["tree", "patch", "edit"] and scripted.heard[0]["modes"] == ["edit"]
    assert chat.log[0] == {"role": "user", "text": notice, "notice": True} and scripted.heard[0]["text"] == f"{notice}\n\nFirst"
    chat.setup["modes"] = "tree"  # the stored list itself is damaged
    turn(base, app, "LEAF-001", "Second", modes=None)
    assert chat.setup["modes"] == ["tree", "patch", "edit"] and any(m.get("notice") and "not a list" in m["text"] for m in chat.log)

    app.settings_file.write_text(json.dumps({"chat": {"modes": ["tree", "nonsense"]}, "websurf": {"rounds": 3}}))
    turn(base, app, "LEAF-002", "Third")
    assert saved(app) == {"chat": app.builtin_setup(), "websurf": {"rounds": 3}}
    assert app.chats["LEAF-002"].log[0]["notice"] and 'unknown "nonsense"' in app.chats["LEAF-002"].log[0]["text"]


@pytest.mark.syngate("AI_CHAT-INTERRUPT")
def test_an_unexpected_error_ends_the_turn_with_a_message_telling_the_chat_was_interrupted(server):
    base, app = server
    app.connectors = {"echo": Scripted(RuntimeError("boom"))}
    outcome = turn(base, app, "LEAF-001", "First")
    assert outcome["error"] == assassin_ui.INTERRUPTED.format(error="RuntimeError: boom")
    assert app.chats["LEAF-001"].log[-1]["role"] == "error" and "interrupted" in app.chats["LEAF-001"].log[-1]["text"]


@pytest.mark.syngate("AI_CHAT-ANSWER-REFUSED")
def test_a_malformed_answer_is_refused_to_the_ai_as_its_next_prompt_and_answered_again(server):
    base, app = server
    app.connectors = {"echo": (scripted := Scripted(calls({"tool": "bogus"}), {"kind": "text", "text": "Fixed"}))}
    outcome = turn(base, app, "LEAF-001", "First", modes=["tree"])
    refusal = "answer refused: unknown tree call 'bogus'"
    assert scripted.heard[1]["text"] == synthetic.ANSWER_REFUSED.format(error="unknown tree call 'bogus'")
    assert outcome["reply"] == f"- {refusal}\nFixed"
