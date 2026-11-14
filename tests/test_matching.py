# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The pure part of agent match (ORCHESTRATOR-MATCH, ORCHESTRATOR-MATCH-GATE, ORCHESTRATOR-ORIGIN): the gate over an injected embedding,
the match agent's confirmation over an injected judge and the origins a match is tried for; and the matched exchange in the chat
(ORCHESTRATOR-MATCH-LOG)."""

import json
import types

import pytest

import assassin_ui
import matching
import synthetic


def agent(name, examples, schema=None, description=""):
    return synthetic.prompt(name, "agent", description or f"the {name} agent", False, "", examples=tuple(examples), schema=schema)


AGENTS = {"test": agent("test", ["run the tests"]), "commit": agent("commit", ["commit the changes"]),
          "match": agent("match", ["run the tests"], schema={"type": "object"})}
ITEMS = {"Q": types.SimpleNamespace(uid="Q", description="Queue\nholds the queue test", parents=[], sources=[])}
WORDS = ("run", "tests", "commit", "queue", "fail")


def embed(texts, calls=None):
    if calls is not None:
        calls.append(list(texts))
    return [[text.lower().count(word) for word in WORDS] for text in texts]


@pytest.mark.syngate("ORCHESTRATOR-MATCH-GATE")
def test_gate_selects_an_agent_alone_above_the_threshold_and_judges_only_the_agents_among_several():
    calls = []
    assert matching.gate(ITEMS, AGENTS, "run the tests", lambda texts: embed(texts, calls)) == (["test"], 0)
    assert len(calls) == 1 and calls[0][0] == "run the tests"
    assert matching.gate(ITEMS, AGENTS, "why does the queue test fail", embed, threshold=0.5) == ([], 1)
    assert matching.gate(ITEMS, {"plain": agent("plain", [])}, "anything", lambda texts: pytest.fail("embedded")) == ([], 0)
    judged = []

    def judge(match_agent, data):
        judged.append((match_agent.schema["properties"]["agent"]["enum"], json.loads(data)))
        return {"agent": "commit"}
    assert matching.match(MATCH, ITEMS, AGENTS, "run the tests", [], embed, judge) == "test" and judged == []  # alone: no model asked
    assert matching.match(MATCH, ITEMS, AGENTS, "why does the queue test fail", [], embed, judge, threshold=0.5) is None and judged == []
    assert matching.match(MATCH, ITEMS, AGENTS, "commit and run the tests", [], embed, judge, threshold=0.5) == "commit"
    assert judged[-1][0] == ["test", "commit", None] and [entry["name"] for entry in judged[-1][1]["agents"]] == ["test", "commit"]
    tie = {"T": types.SimpleNamespace(uid="T", description="run the tests", parents=[], sources=[])}
    assert matching.match(MATCH, tie, AGENTS, "run the tests", [], embed, judge) is None  # an item in too: the judge sees the agent alone
    assert judged[-1][0] == ["test", None] and "T" not in json.dumps(judged[-1][1]["agents"])


MATCH = synthetic.load_agents()["match"]
HISTORY = [{"role": "user", "text": "old"}, {"role": "assistant", "text": "old reply"},
           {"role": "user", "text": "fix the queue"}, {"role": "assistant", "text": "fixed it"}]


@pytest.mark.syngate("ORCHESTRATOR-MATCH")
def test_a_message_goes_to_an_off_context_agent_selected_alone_or_confirmed_by_the_match_agent():
    narrowed = matching.shortlisted(MATCH, ["test"])
    assert narrowed.schema["properties"]["agent"]["enum"] == ["test", None]
    assert "enum" not in MATCH.schema["properties"]["agent"]
    seen = []

    def judge(match_agent, data):
        seen.append((match_agent, json.loads(data)))
        return {"agent": answer}
    for answer, expected in (("test", "test"), (None, None), ("commit", None), ("explore", None)):
        assert matching.confirm(MATCH, AGENTS, ["test"], "run the tests", HISTORY, judge) == expected
    used, data = seen[0]
    assert used.schema["properties"]["agent"]["enum"] == ["test", None]
    assert data["message"] == "run the tests"
    assert data["last_exchange"] == HISTORY[2:]
    assert data["agents"] == [{"name": "test", "description": "the test agent", "examples": ["run the tests"]}]
    assert matching.confirm(MATCH, AGENTS, [], "run the tests", HISTORY, lambda *_: pytest.fail("judged")) is None
    assert matching.confirm(MATCH, AGENTS, ["test"], "x", HISTORY, lambda *_: "not json") is None
    assert matching.match(MATCH, ITEMS, AGENTS, "run the tests", HISTORY, embed, lambda *_: pytest.fail("judged")) == "test"
    several = (MATCH, ITEMS, AGENTS, "commit and run the tests", HISTORY, embed)
    assert matching.match(*several, lambda a, d: {"agent": "test"}, threshold=0.5) == "test"
    assert matching.match(*several, lambda a, d: {"agent": None}, threshold=0.5) is None


@pytest.mark.syngate("ORCHESTRATOR-ORIGIN")
def test_only_a_users_message_is_matched():
    assert [origin for origin in matching.ORIGINS if matching.matched(origin)] == [matching.USER_MESSAGE]
    never = lambda *_: pytest.fail("asked")
    for origin in matching.ORIGINS[1:]:
        assert matching.match(MATCH, ITEMS, AGENTS, "run the tests", HISTORY, never, never, origin=origin) is None
    assert matching.match(MATCH, ITEMS, AGENTS, "run the tests", HISTORY, embed, lambda a, d: {"agent": "test"},
                          origin=matching.USER_MESSAGE) == "test"


class MatchingConnection:
    """Answers the match agent with the test agent, the test agent with its report and a DAG turn with its own text, keeping every DAG prompt."""
    label, models, efforts, modes = "Scripted", ("model-a",), ("low",), ()

    def __init__(self):
        self.prompts = []

    def dispatch(self, context, text, session=None, agent=None, **kwargs):
        if agent is not None and agent.name == "match":
            return {"agent": "test"}, None
        if agent is not None:
            return {"kind": "text", "text": "3 tests passed"}, "agent-session"
        self.prompts.append((text, session))
        return {"kind": "text", "text": f"answered {len(self.prompts)}"}, "dag-session"


@pytest.mark.syngate("ORCHESTRATOR-MATCH-LOG")
def test_the_matched_message_and_the_agents_report_are_messages_of_the_chats_log_and_session(tmp_path, syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root.\n", parents=())
    app = assassin_ui.AssassinApp(root=tmp_path, syngate_dir=syngate_dir)
    app.connectors = {"scripted": (connection := MatchingConnection())}
    app.write_settings("orchestrator", {"agents": {"default": {"connection": "scripted", "model": "model-a"}}})
    app.embed = embed
    setup = {"connector": "scripted", "model": "model-a", "effort": "low", "modes": ["tree"]}  # the test agent's tree calls
    say = lambda text: app.turn_snapshot(app.start_turn({**setup, "uid": "ROOT", "text": text})["turn"], wait=5)

    assert say("hello")["reply"] == "answered 1"
    assert say("run the tests")["reply"] == "3 tests passed"
    log = app.chats["ROOT"].log
    assert [entry["text"] for entry in log] == ["hello", "answered 1", "run the tests", "3 tests passed"]
    assert log[-1].get("matched") == "test" and app.chats["ROOT"].session == "dag-session"
    assert say("what did it say")["reply"] == "answered 2"
    text, session = connection.prompts[-1]
    assert session == "dag-session" and "run the tests" in text and "3 tests passed" in text and text.endswith("what did it say")

    app.chats["ROOT"].session = None  # without a session the kept history carries the matched exchange
    say("and now")
    text, session = connection.prompts[-1]
    assert session is None and "user: run the tests" in text and "assistant: 3 tests passed" in text
