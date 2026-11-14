# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The setup tool of the AI (SYNTHETIC-TOOL-SETUP): the models call listing every model a chat may run on with its family, tier, strengths
and efforts, and the setup call recommending one of them, both as calls of a turn that keep it going."""

import json

import pytest

import synthetic
from test_assassin_ui import app, server  # noqa: F401 -- the server fixtures of the page tests
from test_assassin_ui_api import Scripted, calls, turn


class Listed(Scripted):
    """A scripted connector whose settings list its models with the family, tier, strengths and efforts a connection's settings give."""
    models, efforts = ("model-a", "model-b"), ("low",)
    entries = {"model-a": {"family": "alpha", "tier": 1, "strengths": "routine work", "efforts": ["low"]}, "model-b": {"efforts": []}}

    def settings(self):
        return {**super().settings(), "models": [{"id": model, "name": model, **self.entries[model]} for model in self.models]}


class Big(Listed):
    models, efforts = ("big-1",), ("low", "high")
    entries = {"big-1": {"family": "beta", "tier": 3, "strengths": "hard design", "efforts": ["low", "high"]}}


@pytest.mark.syngate("SYNTHETIC-TOOL-SETUP-MODELS")
def test_models_call_lists_every_model_of_every_connection_with_the_chats_own_setup_marked(server):
    base, app = server
    app.connectors = {"echo": (scripted := Listed(calls({"tool": "models"}), {"kind": "text", "text": "Read."})), "big": Big()}
    outcome = turn(base, app, "ROOT", "Which model?", modes=[])  # every permission off
    heard = scripted.heard[1]["text"]
    listed = synthetic.RESULTS_PREAMBLE + "- models:\n"
    assert heard.startswith(listed)
    assert [json.loads(line) for line in heard[len(listed):].split("\n")] == [
        {"connection": "echo", "model": "model-a", "family": "alpha", "tier": 1, "strengths": "routine work", "efforts": ["low"], "current": True},
        {"connection": "echo", "model": "model-b", "efforts": []},
        {"connection": "big", "model": "big-1", "family": "beta", "tier": 3, "strengths": "hard design", "efforts": ["low", "high"]}]
    assert (outcome["reply"], outcome.get("applied", [])) == ("Read.", [])  # a read is no change the chat reports


@pytest.mark.syngate("SYNTHETIC-TOOL-SETUP-CALL")
def test_setup_call_recommends_a_listed_model_and_refuses_an_unlisted_one_or_a_missing_reason(server):
    known = {"tool": "setup", "connection": "big", "model": "big-1", "reason": "a hard design"}
    assert synthetic.parse_reply(calls({"tool": "models"})) == ("calls", [{"tool": "models"}])
    assert synthetic.parse_reply(calls(known)) == ("calls", [known])
    with pytest.raises(synthetic.protocol_error, match="setup: missing reason"):
        synthetic.parse_reply(calls({field: value for field, value in known.items() if field != "reason"}))
    base, app = server
    asked = [{**known, "effort": "high"}, {**known, "connection": "nowhere"}, {**known, "model": "model-a"}, {**known, "effort": "max"}]
    answers = [answer for call in asked for answer in (calls(call), {"kind": "text", "text": "Heard."})]
    app.connectors = {"echo": Listed(*answers), "big": Big()}
    from test_recommend_turn import answering
    answering(app, "ROOT", "deny")  # the switch is asked under the default behaviour: denied, the turn goes on
    outcomes = [turn(base, app, "ROOT", "Recommend.", modes=[]) for _ in asked]
    assert [outcome.get("applied") for outcome in outcomes] == [
        ["- setup big big-1 at high: a hard design — denied: go on on the model you have"],
        ["- setup big-1 refused: big-1 of nowhere is not in the models listing — call models and name one of its entries"],
        ["- setup model-a refused: model-a of big is not in the models listing — call models and name one of its entries"],
        ["- setup big-1 refused: big-1 of big lists no effort 'max' — its efforts: low, high"]], outcomes


@pytest.mark.syngate("SYNTHETIC-TOOL-SETUP")
def test_the_setup_tool_defines_the_models_and_setup_calls_none_naming_a_permission_and_both_keep_the_turn_going(server):
    wanted = {"models": (), "setup": ("connection", "model", "reason")}
    assert {tool: fields for tool, fields in synthetic.library_calls(synthetic.LIBRARY).items() if tool in wanted} == wanted
    shapes = {shape["properties"]["tool"]["const"]: shape for shape in synthetic.ANSWER_SCHEMA["properties"]["calls"]["items"]["anyOf"]}
    assert set(shapes["models"]["properties"]) == {"tool"} and set(shapes["setup"]["properties"]) == {"tool", "connection", "model", "effort", "reason"}
    base, app = server
    recommend = {"tool": "setup", "connection": "big", "model": "big-1", "reason": "hard"}
    app.connectors = {"echo": (scripted := Listed(calls({"tool": "models"}), calls(recommend), {"kind": "text", "text": "Done."})), "big": Big()}
    from test_recommend_turn import answering
    answering(app, "ROOT", "deny")  # the switch is asked under the default behaviour: denied, the turn goes on
    outcome = turn(base, app, "ROOT", "Pick.", modes=[])
    assert outcome["reply"] == "Done." and len(scripted.heard) == 3  # both calls came back as the next prompt and the turn went on
    assert scripted.heard[2]["text"].startswith(synthetic.RESULTS_PREAMBLE + "- setup big big-1: hard")
