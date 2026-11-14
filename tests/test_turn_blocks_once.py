# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""AI_CHAT-TURN-ONCE: a message the AI said on the way is one block of the turn however many ways the connection reported it."""

import pytest

import syngatelib
import synthetic


class Streaming:
    """A connection that streams the given texts as message steps while it works, then answers `reply`."""
    label, models, efforts, modes, library_delivery = "Streaming", ("model-a",), ("low",), {}, "text"

    def __init__(self, streamed, reply):
        self.streamed, self.reply = streamed, reply

    def dispatch(self, context, text, model=None, effort=None, modes=(), session=None, on_step=None, stopped=lambda: False, library=None, images=()):
        for streamed in self.streamed:
            on_step({"kind": "message", "text": streamed, "at": 0.1})
        return self.reply, "session-1"


def run(syngate_tree, streamed, beside):
    """The steps `synthetic.query` hands to the turn when the connection streamed `streamed` and answered calls with `beside` said beside them."""
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root branch\n", parents=())
    items, _ = syngatelib.load_tree(syngate_dir)
    reply = {"kind": "calls", "text": beside, "calls": [{"tool": "query", "uid": "@"}]}
    steps = []
    synthetic.query({"streaming": Streaming(streamed, reply)}, items, "ROOT", "Go.", "streaming", "model-a", "low", on_step=steps.append)
    return [step["text"] for step in steps if step["kind"] == "message"]


@pytest.mark.syngate("AI_CHAT-TURN-ONCE")
def test_the_text_beside_the_calls_is_no_second_message_when_the_connection_streamed_it_already(syngate_tree):
    assert run(syngate_tree, ["Let me look first."], "Let me look first.") == ["Let me look first."]  # the same text twice is one block
    assert run(syngate_tree, ["Let me look\nfirst. "], "Let me look first.") == ["Let me look\nfirst. "]  # differing in whitespace only
    assert run(syngate_tree, ["Let me look first.\n\nThen read."], "Then read.") == ["Let me look first.\n\nThen read."]  # said within a streamed message
    assert run(syngate_tree, ["Earlier."], "Let me look first.") == ["Earlier.", "Let me look first."]  # text nobody streamed is still added
    assert run(syngate_tree, [], "Let me look first.") == ["Let me look first."]  # a connection that streams nothing keeps its beside text
