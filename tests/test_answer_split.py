# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The answer of a turn may carry text beside its tool calls: the text is split off as a message of the turn, the calls apply."""

import json

import pytest

import syngatelib
import synthetic


class Answering:
    """A connection answering the given reply, recording the steps it is handed."""
    label, models, efforts, modes, library_delivery = "Answering", ("model-a",), ("low",), {}, "text"

    def __init__(self, reply):
        self.reply = reply

    def dispatch(self, context, text, model=None, effort=None, modes=(), session=None, on_step=None, stopped=lambda: False, library=None, images=()):
        return self.reply, "session-1"


@pytest.mark.syngate("SYNTHETIC-ANSWER-MIXED", "split")
def test_text_beside_the_calls_of_an_answer_is_split_off_and_the_calls_apply():
    calls = [{"tool": "remove", "uid": "X"}]
    block = "```syngate\n" + json.dumps(calls) + "\n```"
    assert synthetic.split_reply({"kind": "text", "text": "Both.", "calls": calls}) == ("Both.", calls)
    assert synthetic.split_reply({"kind": "calls", "text": "Both.", "calls": calls}) == ("Both.", calls)
    assert synthetic.parse_reply({"kind": "calls", "text": "Both.", "calls": calls}) == ("calls", calls)
    assert synthetic.parse_reply(f"Here you go:\n{block}\nDone.") == ("calls", calls)
    assert synthetic.split_reply(f"Here you go:\n{block}\nDone.") == ("Here you go:\n\nDone.", calls)
    second = [{"tool": "query", "uid": "@"}]
    assert synthetic.split_reply(f"{block}\nthen\n```syngate\n{json.dumps(second)}\n```") == ("then", [*calls, *second])
    assert synthetic.split_reply("Plain prose.") == ("Plain prose.", None)
    assert synthetic.split_reply({"kind": "text", "text": "Talk."}) == ("Talk.", None)
    with pytest.raises(synthetic.protocol_error, match="not valid JSON"):
        synthetic.parse_reply(f"Prose.\n```syngate\n[{{\n```")
    cut = "The two edits.\n```syngate\n[{\"tool\": \"edit\", \"uid\": \"X\", \"description\": \"D"
    with pytest.raises(synthetic.protocol_error, match="cut off"):
        synthetic.parse_reply(cut)


@pytest.mark.syngate("SYNTHETIC-ANSWER-MIXED", "message")
def test_a_query_hands_the_text_of_a_mixed_answer_to_the_turn_as_a_message_and_returns_the_answer_for_its_calls(syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root branch\n", parents=())
    items, _ = syngatelib.load_tree(syngate_dir)
    reply = {"kind": "calls", "text": "I will remove it.", "calls": [{"tool": "query", "uid": "@"}]}
    steps = []
    answer, session = synthetic.query({"mixed": Answering(reply)}, items, "ROOT", "Go.", "mixed", "model-a", "low", on_step=steps.append)
    assert answer == reply and session == "session-1"
    assert steps == [{"kind": "message", "text": "I will remove it."}]
    assert synthetic.parse_reply(answer) == ("calls", reply["calls"])
