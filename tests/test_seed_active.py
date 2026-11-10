# Open Trader
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""SYNTHETIC-SEED-ACTIVE: the active item mark of the seed context and the label of the syngate context call."""

import pytest

import syngatelib
import synthetic


@pytest.mark.syngate("SYNTHETIC-SEED-ACTIVE")
def test_the_seed_context_marks_the_one_statement_it_is_formed_for_with_the_active_item_label_or_the_label_a_context_call_names(syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root.\n", parents=())
    make_item(syngate_dir, "SIDE-A", "Side A.\n", parents=("ROOT",), order=10)
    make_item(syngate_dir, "SIDE-B", "Side B.\n", parents=("ROOT",), order=20)
    items, errors = syngatelib.load_tree(syngate_dir)
    assert not errors
    head = synthetic.PROMPTS[synthetic.DEFAULT_PROMPT]
    body = synthetic.seed_context(items, "SIDE-A").removeprefix(head)
    assert body.endswith("\n@ROOT\nRoot.\n\n@SIDE-A (active item)\nSide A.\n") and body.count("(active item)") == 1 and "@SIDE-B" not in body
    whole = synthetic.seed_context(items, "ROOT").removeprefix(head)
    assert "\n@ROOT (active item)\nRoot.\n" in whole and "\n@SIDE-A\nSide A.\n" in whole and whole.count("(active item)") == 1
    named = synthetic.seed_context(items, "SIDE-A", label="item to split").removeprefix(head)
    assert named.endswith("\n@SIDE-A (item to split)\nSide A.\n") and "(active item)" not in named
    assert synthetic.seed_context(items, "SIDE-A", label="two\n  lines").endswith("\n@SIDE-A (two lines)\nSide A.\n")
    unlabeled = {"tool": "context", "uid": "SIDE-A"}
    labeled = {"tool": "context", "uid": "@", "label": "parent candidate"}
    assert synthetic.apply_call(items, "SIDE-A", unlabeled) == "- context of SIDE-A:\n" + synthetic.seed_context(items, "SIDE-A")
    assert synthetic.apply_call(items, "SIDE-A", labeled) == "- context of SIDE-A:\n" + synthetic.seed_context(items, "SIDE-A", label="parent candidate")
    assert synthetic.parse_reply({"kind": "calls", "calls": [labeled]}) == ("calls", [labeled])
    for bad in ("  ", 3):
        with pytest.raises(synthetic.protocol_error, match="label"):
            synthetic.parse_reply({"kind": "calls", "calls": [{"tool": "context", "uid": "@", "label": bad}]})
    shape = next(shape for shape in synthetic.ANSWER_SCHEMA["properties"]["calls"]["items"]["anyOf"] if shape["properties"]["tool"]["const"] == "context")
    assert shape["properties"]["label"] == {"type": "string"} and shape["required"] == ["tool", "uid"]
    assert synthetic.referenced(items, "See @SIDE-B.", ()) == "\n@SIDE-B\nSide B.\n"
    seen = {}

    class Recorder:
        models, efforts, modes = ("model-a",), ("low",), ()

        def dispatch(self, context, text, **_):
            seen["context"] = context
            return "ok", None
    synthetic.query({"rec": Recorder()}, items, "SIDE-A", "Compare @SIDE-B.", "rec", "model-a", "low")
    assert seen["context"].endswith("\n@SIDE-A (active item)\nSide A.\n\n@SIDE-B\nSide B.\n")
