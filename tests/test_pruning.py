# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Turn pruning (ORCHESTRATOR-PRUNE-*, SYNTHETIC-AGENT-PRUNE): what of an ended turn the rules and the prune agent -- an injected callable -- cut
out of the session, when the cut waits for the next session, the stubs it leaves and the switches set by hand."""

import uuid

import pytest

import api_connection
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
    reading = batch((call("read", path="src/a.py"), "SECRET BODY"), (call("query", uid="LEAF-001"), "- LEAF-001: SECRET"))
    named = pruning.prune_input(7, [reading, TEXT]).data
    assert "[1] [turn 7 step 1: read src/a.py, query LEAF-001 — read with log]" in named and "SECRET" not in named  # a reading is named by what it read


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-LATE")
def test_a_verdict_of_the_prune_agent_arriving_after_the_next_message_counts_as_one_on_a_turn_ahead_of_the_tail():
    ask = lambda data: answer(False)
    state = pruning.new_state()
    early, late = pruning.judge_texts(ask, 1, [TEXT]), pruning.judge_texts(ask, 2, [TEXT])
    pruning.deliver(state, 1, early)  # arrives before the next message
    assert list(state["applied"]) == ["1:1"] and state["waiting"] == {}
    pruning.message_sent(state, 3)  # the message after turn 2 is sent before the agent answers
    pruning.deliver(state, 2, late)
    assert list(state["applied"]) == ["1:1"] and list(state["waiting"]) == ["2:1"]
    assert pruning.take_stubs(state) == [early["1:1"]["stub"]]  # nothing of the late one reaches the running session
    assert pruning.changed_turn(state) == 2  # turn 2 is ahead of the tail now: its verdict is brought in under the pruning worth
    pruning.settle(state)
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
    told = " ".join(synthetic.read_library()[pruning.AGENT].text.split())
    assert "superseded by a later text of the turn" in told and "its closing reply above all" in told  # such a text states nothing new either


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
def test_the_verdicts_of_an_owned_session_wait_for_its_connections_replay_which_brings_them_in_without_a_new_session():
    state = pruning.new_state()
    pruning.end_turn(state, 1, [TEXT, TREE], owned=True)
    pruning.deliver(state, 1, pruning.judge_texts(lambda data: answer(False), 1, [TEXT, TREE]), owned=True)
    assert state["applied"] == {} and list(state["waiting"]) == ["1:2", "1:1"] and pruning.take_stubs(state) == []
    assert pruning.pruned_now(state) == {}
    pruning.note_span(state, 1, {"session": "s", "first": "a", "last": "b", "tokens": 700})
    assert pruning.changed_turn(state) == 1  # where its connection's replay starts
    pruning.settle(state)  # the replay brought them in: the session is not restarted, its spans and size stay
    assert sorted(state["applied"]) == ["1:1", "1:2"] and state["waiting"] == {} and len(pruning.take_stubs(state)) == 2
    assert list(state["spans"]) == ["1"] and state["size"] == 700 and pruning.changed_turn(state) is None


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
    assert agent.schema["required"] == ["texts", "readings"] and texts["type"] == "array" and texts["items"]["required"] == ["index", "new"]
    assert texts["items"]["properties"]["index"]["type"] == "integer" and texts["items"]["properties"]["new"]["type"] == "boolean"
    assert list(pruning.judge_texts(lambda data: answer(False, True), 1, [TEXT, TEXT])) == ["1:1"]  # an answer of that shape is what the library reads


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-SWITCH", "unit")
def test_the_prune_switch_returns_a_pruned_message_or_cuts_a_kept_one_with_the_next_message_the_running_session_kept():
    state = pruning.new_state()
    pruning.end_turn(state, 1, [TEXT, TREE])
    pruning.take_stubs(state)
    pruning.switch(state, 1, 2, TREE, False)  # back into the session
    pruning.switch(state, 1, 1, TEXT, True)  # out of it
    assert list(pruning.pruned_now(state)) == ["1:2"]  # the running session is not ended
    assert list(pruning.pruned_next(state)) == ["1:1"] and pruning.pruned_next(state)["1:1"]["stub"] == "[turn 1 step 1: AI text — read with log]"
    assert pruning.changed_turn(state) == 1
    pruning.settle(state)  # what the next message brings in
    assert list(state["applied"]) == ["1:1"] and state["switches"] == {} and pruning.take_stubs(state) == ["[turn 1 step 1: AI text — read with log]"]


def usage(tokens):
    return {"kind": "usage", "seconds": 1.0, "cost_usd": None, "input_tokens": tokens, "output_tokens": 10}


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-CONTINUITY", "unit")
def test_no_token_bound_stands_in_the_pruning_and_a_session_of_any_size_shrinks_by_its_verdicts_alone():
    assert not any(hasattr(pruning, name) for name in ("renew_bound", "due", "RENEW_TOKENS"))
    state = pruning.new_state()
    pruning.note_size(state, [usage(900000)])
    pruning.end_turn(state, 1, [TREE])
    pruning.message_sent(state, 2)
    assert state["size"] == 900000 and list(state["applied"]) == ["1:1"] and state["spans"] == {}  # the size is told, nothing is ended by it
    pruning.note_size(state, [TREE])  # a turn without a counted request leaves the size as it was
    assert state["size"] == 900000 and pruning.session_size([usage(120), TREE, usage(900)]) == 900


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-WORTH")
def test_a_verdict_ahead_of_the_tail_waits_for_an_expired_cache_or_a_cut_of_at_least_what_is_resent_and_one_on_the_tail_goes_in_at_once(tmp_path):
    now = 10000.0
    assert pruning.worth(cut=0, sent=500, last=now - pruning.CACHE_TTL, now=now) and pruning.worth(cut=0, sent=1, last=None, now=now)
    assert pruning.worth(cut=500, sent=500, last=now - 1, now=now) and not pruning.worth(cut=499, sent=500, last=now - 1, now=now)
    assert not pruning.worth(cut=-100, sent=10, last=now - 1, now=now)
    state = pruning.new_state()
    pruning.end_turn(state, 1, [TREE])
    assert list(state["applied"]) == ["1:1"] and state["waiting"] == {}  # a verdict on the tail is brought in at once
    pruning.message_sent(state, 2)
    pruning.deliver(state, 1, {"1:reply": {"rule": "text", "stub": "[r]"}})
    assert list(state["waiting"]) == ["1:reply"] and list(state["applied"]) == ["1:1"] and pruning.changed_turn(state) == 1  # ahead of the tail: it waits

    connection, session = api_connection.api_connection("local", config=lambda: {}, sessions_dir=tmp_path), uuid.uuid4().hex
    body = "- src/b.py lines 1-2 of 2"
    step = batch((call("read", path="src/b.py"), body))
    messages = [{"role": "user", "content": "Look"}, {"role": "assistant", "content": "{}"}, {"role": "user", "content": "Results:\n" + body},
                {"role": "assistant", "content": "Read."}, {"role": "user", "content": "Next " + "y" * 4000}, {"role": "assistant", "content": "Done."}]
    connection.write_session(session, messages)
    assert connection.turn_span(session, 1) == {"session": session, "start": 4, "rounds": 1, "tokens": None} and connection.turn_span(session, 4) is None
    turns = [{"turn": 1, "span": {"start": 0, "rounds": 2}, "steps": [step], "reply": "Read.", "verdicts": {"1:1": {"rule": "unused", "stub": "[s]"}}, "was": {}},
             {"turn": 2, "span": {"start": 4, "rounds": 1}, "steps": [], "reply": "Done.", "verdicts": {}, "was": {}}]
    written = connection.session_path(session).stat().st_mtime
    assert connection.replay_session(session, turns, now=written + 1) is None and connection.read_session(session) == messages  # a small cut of a cached session waits
    assert connection.replay_session(session, turns, now=written + pruning.CACHE_TTL) == ("rewritten", session)  # the cache expired
    cut = connection.read_session(session)
    assert cut[2]["content"] == "Results:\n[s]" and [cut[at] for at in (0, 1, 3, 4, 5)] == [messages[at] for at in (0, 1, 3, 4, 5)]
    back = [{**turns[0], "verdicts": {}, "was": turns[0]["verdicts"]}, turns[1]]
    assert connection.replay_session(session, back, now=0, force=True) == ("rewritten", session) and connection.read_session(session) == messages  # a switch asks no worth
    heavy = "- " + "x" * 40000
    connection.write_session(session, [{**messages[2], "content": heavy} if at == 2 else m for at, m in enumerate(messages)])
    turns[0]["steps"] = [batch((call("read", path="src/b.py"), heavy))]
    assert connection.replay_session(session, turns, now=connection.session_path(session).stat().st_mtime + 1) == ("rewritten", session)  # the cut outweighs what is resent


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-UNUSED")
def test_a_reading_the_prune_agent_finds_the_turn_did_not_rest_on_is_pruned_to_its_stub():
    steps = [batch((call("read", path="src/a.py"), "body")), TEXT, batch((call("edit", uid="A"), "- edited A")),
             batch((call("grep", command="-n foo src"), "src/b.py:1:foo")), batch((call("read", path="src/x.py"), "read src/x.py refused: no file"))]
    handed = pruning.prune_input(3, steps, "Done.")
    assert handed.readings == {1: "3:1", 2: "3:4"}  # a change and a refused call are no readings
    assert "[1] [turn 3 step 1: read src/a.py — read with log]" in handed.data and "[2] [turn 3 step 4: grep -n foo src — read with log]" in handed.data
    assert "body" not in handed.data and "1:foo" not in handed.data  # the agent tells from the stubs, never from the results
    told = {"texts": [{"index": 1, "new": True}, {"index": 2, "new": True}],
            "readings": [{"index": 1, "used": True}, {"index": 2, "used": False}, {"index": 9, "used": False}, "no"]}
    verdicts = pruning.judge_texts(lambda data: told, 3, steps, "Done.")
    assert verdicts == {"3:4": {"rule": "unused", "stub": "[turn 3 step 4: unused reading, grep -n foo src — read with log]"}}
    state = pruning.new_state()
    pruning.end_turn(state, 3, steps)
    pruning.deliver(state, 3, verdicts)
    assert sorted(state["applied"]) == ["3:3", "3:4"] and pruning.form(state["applied"]["3:4"]) == [verdicts["3:4"]["stub"]]
    assert pruning.judge_texts(lambda data: {"texts": [], "readings": "no"}, 3, steps, "Done.") == {}


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-RULE-SUPERSEDED")
def test_a_reading_is_pruned_by_rule_in_whatever_turn_it_stands_once_a_later_one_of_the_same_item_or_file_or_a_change_of_it_follows():
    first, again = batch((call("read", path="src/b.py"), "old body")), batch((call("read", path="./src/b.py"), "new body"))
    state = pruning.new_state()
    pruning.end_turn(state, 1, [first])
    assert state["applied"] == {} and state["waiting"] == {}  # the latest reading stays
    pruning.end_turn(state, 2, [TEXT, again])
    assert state["waiting"] == {"1:1": {"rule": "superseded", "stub": "[turn 1 step 1: superseded reading of src/b.py — read with log]"}}
    assert state["applied"] == {} and pruning.changed_turn(state) == 1  # a verdict on a turn ahead of the tail
    pruning.end_turn(state, 3, [batch((call("replace", path="src/b.py", old="a", new="b"), "- replace changed src/b.py"))])
    assert sorted(state["waiting"]) == ["1:1", "2:2"]  # a call of the session changed the file since

    same = pruning.new_state()
    pruning.end_turn(same, 1, [first, again])
    assert list(same["applied"]) == ["1:1"] and same["waiting"] == {}  # within the ended turn it is of the tail

    two = pruning.new_state()
    pruning.end_turn(two, 1, [batch((call("read", path="src/b.py"), "b"), (call("read", path="src/c.py"), "c"))])
    pruning.end_turn(two, 2, [again])
    assert two["waiting"] == {}  # the step still holds the latest reading of src/c.py
    pruning.end_turn(two, 3, [{"kind": "context", "text": "Context update\n\nFile brought in whole:\n# Source src/c.py\n````\nc\n````\n"}])
    assert list(two["waiting"]) == ["1:1"] and "src/b.py, src/c.py" in two["waiting"]["1:1"]["stub"]  # a file of a context update is a later reading

    mixed = pruning.new_state()
    pruning.end_turn(mixed, 1, [batch((call("read", path="src/b.py"), "b"), (call("git", command="status"), "clean"))])
    pruning.end_turn(mixed, 2, [again])
    assert mixed["waiting"] == {}  # a step that did more than read is not a reading to supersede


@pytest.mark.syngate("ORCHESTRATOR-PRUNE-SESSION-HEAD", "unit")
def test_the_head_of_a_new_session_holds_a_turn_as_the_pruning_holds_it_not_its_message_texts_alone():
    kept = batch((call("read", path="src/b.py"), "body"))
    steps = [{"kind": "user", "text": "queued"}, TEXT, TREE, kept, usage(10), {"kind": "tool", "name": "Read", "input": {"file_path": "x.py"}, "result": "R"},
             {"kind": "agent", "uid": "LEAF-002", "prompt": "p", "report": "Reported."}]
    head = pruning.head(2, steps, "Done.", {"2:3": {"rule": "tree", "stub": "[stub]"}})
    assert head == [{"role": "user", "text": "queued"}, {"role": "ai", "text": "I will edit the item."}, {"role": "harness", "text": "[stub]"},
                    {"role": "harness", "text": "body"}, {"role": "harness", "text": "tool Read x.py\nR"},
                    {"role": "harness", "text": "agent @LEAF-002: Reported."}, {"role": "ai", "text": "Done."}]
    assert pruning.head(2, [], "Done.", {"2:reply": {"rule": "text", "stub": "[r]"}}) == [{"role": "harness", "text": "[r]"}]
    sent = synthetic.transcript(head, "Next")
    assert "user: queued\nassistant: I will edit the item.\nharness: [stub]\nharness: body\n" in sent and sent.endswith("assistant: Done.\n\nNext")
