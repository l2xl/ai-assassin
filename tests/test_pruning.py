# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Turn pruning (ORCHESTRATOR-PRUNE-*, SYNTHETIC-AGENT-PRUNE): what of an ended turn the rules and the prune agent -- an injected callable -- cut
out of the session, when the cut waits for the next session, the stubs it leaves and the switches set by hand."""

import pytest

import synthetic
from ai_scratcher import pruning


def batch(*pairs):
    """A calls step of the (input, result line) pairs given."""
    return {"kind": "calls", "tools": [call["tool"] for given, _ in pairs for call in (given if isinstance(given, list) else [given])],
            "lines": [line for _, line in pairs], "inputs": [given for given, _ in pairs]}


def call(tool, **fields):
    return {"tool": tool, **fields}


TREE = batch((call("query", uid="A"), '- A: {"uid": "A"}'))
TEXT = {"kind": "message", "text": "I will edit the item."}


def verdict_of(steps, **options):
    return pruning.rule_verdicts(1, steps, **options)[0]


def answer(*flags):
    """The prune agent's answer telling the texts handed under 1, 2, ... new or not."""
    return {"texts": [{"index": index, "new": new} for index, new in enumerate(flags, 1)]}


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-INPUT")
def test_the_prune_input_is_the_numbered_texts_of_the_ended_turn_and_the_stubs_of_its_steps_alone():
    steps = [{"kind": "user", "text": "queued by the user"}, {"kind": "tool", "name": "Read", "input": {}, "result": "SECRET RESULT"},
             TEXT, {"kind": "message", "text": "Edited the item."}]
    handed = pruning.prune_input(7, steps, "Done.")
    assert handed.indices == {1: "7:3", 2: "7:4", 3: "7:reply"}
    assert "[1]\nI will edit the item.\n" in handed.data and "[2]\nEdited the item.\n" in handed.data and handed.data.endswith("[3]\nDone.")
    assert "[turn 7 step 2: tool Read — read with log]" in handed.data and "[turn 7 step 1: user message — read with log]" in handed.data
    assert "SECRET RESULT" not in handed.data and "queued by the user" not in handed.data and "step 3" not in handed.data
    assert pruning.prune_input(7, [steps[1]]).data == "" and pruning.prune_input(7, [steps[1]]).indices == {}


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-LATE")
def test_a_verdict_of_the_prune_agent_arriving_after_the_next_message_waits_for_the_next_session():
    ask = lambda data: answer(False)
    state = pruning.new_state()
    early, late = pruning.judge_texts(ask, 1, [TEXT]), pruning.judge_texts(ask, 2, [TEXT])
    pruning.deliver(state, 1, early)  # arrives before the next message
    assert list(state["applied"]) == ["1:1"] and state["waiting"] == {}
    pruning.message_sent(state, 3)  # the message after turn 2 is sent before the agent answers
    pruning.deliver(state, 2, late)
    assert list(state["applied"]) == ["1:1"] and list(state["waiting"]) == ["2:1"]
    assert pruning.take_stubs(state) == [early["1:1"]["stub"]]  # nothing of the late one reaches the running session
    pruning.new_session(state)
    assert list(state["applied"]) == ["1:1", "2:1"] and state["waiting"] == {} and pruning.take_stubs(state) == [late["2:1"]["stub"]]


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-RULE-BATCH")
def test_an_applied_batch_is_pruned_to_one_line_for_each_of_its_calls():
    step = batch((call("edit", uid="A"), "- edited A\nlong detail"), (call("add", uid="B"), "- added B under P"), (call("query", uid="A"), "- A: {}"))
    verdict = verdict_of([step])["1:1"]
    assert verdict["rule"] == "batch" and verdict["lines"] == ["- edited A", "- added B under P", "- A: {}"]
    assert pruning.form(verdict) == verdict["lines"] and verdict["stub"] == "[turn 1 step 1: applied batch, 3 calls — read with log]"
    refused = batch((call("edit", uid="A"), "- edited A"), (call("edit", uid="B"), "- edit refused: unknown UID 'B'"))
    other = batch((call("edit", uid="A"), "- edited A"), (call("skill", name="x"), "- skill x:\ntext"))
    assert verdict_of([refused, other]) == {}  # a refused batch is not applied; a call no rule prunes keeps its batch


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-RULE-PASS")
def test_a_passing_run_of_tests_has_its_output_pruned_by_rule():
    run = [call("test", uid="A"), call("test", uid="B")]
    passing, failing = batch((run, "- A: pass\n- B: pass")), batch((run, "- A: pass\n- B: fail\nB output:\nassert 1 == 2"))
    assert verdict_of([passing]) == {"1:1": {"rule": "pass", "stub": "[turn 1 step 1: test run, 2 passed — read with log]"}}
    assert verdict_of([failing]) == {}


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-RULE-REREAD")
def test_the_read_of_a_file_the_system_prompt_holds_whole_is_pruned_by_rule():
    held, step = ("src/a.py",), batch((call("read", path="./src/a.py"), "- read src/a.py\nbody"))
    assert verdict_of([step], held=held) == {"1:1": {"rule": "reread", "stub": "[turn 1 step 1: file re-read of src/a.py — read with log]"}}
    assert verdict_of([batch((call("read", path="src/other.py"), "body"))], held=held) == {}


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-RULE-TREE")
def test_a_tree_read_has_its_result_pruned_by_rule():
    both = batch((call("query", uid="A"), "- A: {}"), (call("context", uid="A"), "- context of A:\n..."))
    assert verdict_of([TREE, both]) == {"1:1": {"rule": "tree", "stub": "[turn 1 step 1: tree read — read with log]"},
                                       "1:2": {"rule": "tree", "stub": "[turn 1 step 2: tree read — read with log]"}}
    assert verdict_of([batch((call("skill", name="x"), "- skill x:\ntext"))]) == {}


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-TEXT")
def test_an_ai_text_is_pruned_when_the_prune_agent_finds_it_states_nothing_new():
    steps, heard = [TEXT, {"kind": "message", "text": "Found: the leaf was stale."}], []
    ask = lambda data: heard.append(data) or answer(False, True, False)
    verdicts = pruning.judge_texts(ask, 4, steps, "Done.")
    assert list(verdicts) == ["4:1", "4:reply"] and verdicts["4:reply"] == {"rule": "text", "stub": "[turn 4 reply: AI text — read with log]"}
    assert len(heard) == 1 and "[2]\nFound: the leaf was stale." in heard[0]
    assert pruning.judge_texts(lambda data: answer(True, True), 4, steps) == {}
    assert pruning.judge_texts(lambda data: json_text(answer(False, False)), 4, steps).keys() == {"4:1", "4:2"}  # an answer as JSON text reads too
    assert pruning.judge_texts(lambda data: 1 / 0, 4, steps) == {} and pruning.judge_texts(lambda data: {"texts": "no"}, 4, steps) == {}
    assert pruning.judge_texts(lambda data: heard.append("called"), 4, [TREE]) == {} and heard[-1] != "called"  # no text, no call


def json_text(value):
    import json
    return json.dumps(value)


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-USER")
def test_a_user_message_is_never_pruned():
    user = {"kind": "user", "text": "queued"}
    assert not pruning.prunable(user) and pruning.prunable(TEXT)
    assert verdict_of([user, TREE]) == {"1:2": verdict_of([user, TREE])["1:2"]}  # the user's step 1 has no verdict
    verdicts = pruning.judge_texts(lambda data: {"texts": [{"index": 1, "new": False}, {"index": 2, "new": False}]}, 1, [user, TEXT])
    assert list(verdicts) == ["1:2"]  # the agent is never handed the user's text, and a number it was not handed prunes nothing
    with pytest.raises(pruning.refused):
        pruning.switch(pruning.new_state(), 1, 1, user, True)


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-TAIL")
def test_the_pruned_tail_is_the_ended_turn_alone_and_earlier_turns_stay_as_they_were_sent():
    state = pruning.new_state()
    pruning.end_turn(state, 1, [TREE])
    before = dict(state["applied"])
    pruning.end_turn(state, 2, [TEXT, TREE])
    assert state["applied"] == {**before, "2:2": state["applied"]["2:2"]} and state["applied"]["1:1"] is before["1:1"]
    with pytest.raises(ValueError):
        pruning.put(state, "applied", 3, before)  # a verdict naming a step of another turn is refused
    assert list(state["applied"]) == ["1:1", "2:2"]


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-READ")
def test_the_first_read_of_a_file_in_the_session_is_never_pruned():
    first, again = batch((call("read", path="src/b.py"), "body")), batch((call("read", path="src/b.py"), "body"))
    mixed = batch((call("edit", uid="A"), "- edited A"), (call("read", path="src/c.py"), "body"))
    assert verdict_of([first, mixed, again], held=("src/a.py",)) == {}  # no rule prunes a first read, nor the batch holding one
    state = pruning.new_state()
    pruning.end_turn(state, 1, [first])
    assert state["read"] == ["src/b.py"] and state["applied"] == {}
    held_first = batch((call("read", path="src/a.py"), "body"))
    assert list(verdict_of([held_first], held=("src/a.py",))) == ["1:1"]  # a file the prompt holds whole is a re-read at once


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-STUB", "unit")
def test_a_pruned_step_leaves_one_stub_line_carried_in_the_next_message_of_the_harness():
    assert pruning.stub_line(7, 3, "test run, 12 passed") == "[turn 7 step 3: test run, 12 passed — read with log]"
    assert pruning.stub_line(7, "reply", "AI text") == "[turn 7 reply: AI text — read with log]"
    state, steps = pruning.new_state(), [TEXT, TREE]
    pruning.end_turn(state, 2, steps)
    stubs = pruning.take_stubs(state)
    assert stubs == ["[turn 2 step 2: tree read — read with log]"] and pruning.take_stubs(state) == []
    assert pruning.carry("Next.", stubs) == stubs[0] + "\n\nNext." and pruning.carry("Next.", []) == "Next."
    assert steps == [TEXT, TREE] and TEXT["text"] == "I will edit the item."  # nothing is written into an AI message


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-OWNED", "unit")
def test_an_owned_session_is_pruned_only_when_a_new_session_starts_the_verdicts_waiting_until_then():
    state = pruning.new_state()
    pruning.end_turn(state, 1, [TEXT, TREE], owned=True)
    pruning.deliver(state, 1, pruning.judge_texts(lambda data: answer(False), 1, [TEXT, TREE]), owned=True)
    assert state["applied"] == {} and list(state["waiting"]) == ["1:2", "1:1"] and pruning.take_stubs(state) == []
    assert pruning.pruned_now(state) == {}
    pruning.new_session(state)
    assert sorted(state["applied"]) == ["1:1", "1:2"] and state["waiting"] == {} and len(pruning.take_stubs(state)) == 2


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-STATE", "unit")
def test_a_pruned_message_stays_in_the_log_in_full_under_a_pruned_mark_apart_from_the_fold():
    steps = [{"kind": "message", "text": "kept", "folded": True}, {**TREE, "dropped": "x"}, {"kind": "user", "text": "u"}]
    shown = pruning.marked(1, steps, {"1:2": {}, "1:3": {}})
    assert shown[1] == {**steps[1], "pruned": True} and shown[0] == steps[0] and shown[0] is not steps[0]  # whole, the other states untouched
    assert "pruned" not in steps[1] and "folded" not in shown[1] and "pruned" not in shown[0]


def test_the_shipped_prune_agent_schema_is_the_shape_of_the_answer_the_library_reads(tmp_path):  # SYNTHETIC-AGENT-PRUNE is bound in test_agents.py
    agent = synthetic.load_agents()[pruning.AGENT]
    assert synthetic.is_verdict(agent)
    texts = agent.schema["properties"]["texts"]
    assert agent.schema["required"] == ["texts"] and texts["type"] == "array" and texts["items"]["required"] == ["index", "new"]
    assert texts["items"]["properties"]["index"]["type"] == "integer" and texts["items"]["properties"]["new"]["type"] == "boolean"
    assert list(pruning.judge_texts(lambda data: answer(False, True), 1, [TEXT, TEXT])) == ["1:1"]  # an answer of that shape is what the library reads


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-SWITCH", "unit")
def test_the_prune_switch_returns_a_pruned_message_or_cuts_a_kept_one_with_the_next_session_alone():
    state = pruning.new_state()
    pruning.end_turn(state, 1, [TEXT, TREE])
    pruning.take_stubs(state)
    pruning.switch(state, 1, 2, TREE, False)  # back into the session
    pruning.switch(state, 1, 1, TEXT, True)  # out of it
    assert list(pruning.pruned_now(state)) == ["1:2"]  # the running session is not ended
    assert list(pruning.pruned_next(state)) == ["1:1"] and pruning.pruned_next(state)["1:1"]["stub"] == "[turn 1 step 1: AI text — read with log]"
    pruning.new_session(state)
    assert list(state["applied"]) == ["1:1"] and state["switches"] == {} and pruning.take_stubs(state) == ["[turn 1 step 1: AI text — read with log]"]
