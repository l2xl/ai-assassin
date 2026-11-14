# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""SYNTHETIC-AGENTS: the agents of the prompt library -- their tool and skill lists, the starting chat's cover of them, the shipped ones, the
verdict agents, the CLI call of an agent and the route the settings give it."""

import json
import sys
import threading

import pytest

import assassin_ui
import syngatelib
import synthetic
from ai_scratcher import recommend
from test_assassin_ui import app, call, server  # noqa: F401 -- the app and server fixtures of the page tests
from test_recommend_turn import held_turn

# Stub `claude`: answers the result event of a stream-json turn, echoing its argv and the system prompt file it was handed.
STUB_CLAUDE = """
import json, sys
argv = sys.argv[1:]
sys.stdin.readline()
flag = "--system-prompt-file" if "--system-prompt-file" in argv else "--append-system-prompt-file"
seed = open(argv[argv.index(flag) + 1], encoding="utf-8").read()
print(json.dumps({"type": "result", "result": json.dumps({"argv": argv, "seed": seed}), "session_id": "session-a", "is_error": False}))
"""


def _library(folder):
    """Two skills -- `rules` default, `brief` on request -- two tools, an agent white-listing `brief` and `echo`, and a verdict agent."""
    folder.mkdir(exist_ok=True)
    (folder / "rules.md").write_text("---\nkind: skill\ndescription: The rules\ndefault: true\n---\n# Rules\nFollow them.\n")
    (folder / "brief.md").write_text("---\nkind: skill\ndescription: Be brief\n---\nSay less.\n")
    (folder / "echo.md").write_text("---\nkind: tool\ndescription: Echo back\ncalls:\n  echo:\n    required: [text]\n---\n# Echo\nIt echoes.\n")
    (folder / "shout.md").write_text("---\nkind: tool\ndescription: Shout\ncalls:\n  shout:\n    required: [text]\n---\n# Shout\nIt shouts.\n")
    (folder / "echoer.md").write_text("---\nkind: agent\ndescription: Echo it\nexamples: [echo it]\ntools: [echo]\nskills: [brief]\n---\n# Echoer\nEcho the message.\n")
    (folder / "judge.md").write_text("---\nkind: agent\ndescription: Judge it\nschema:\n  type: object\n  properties:\n    fair: {type: boolean}\n"
                                     "  required: [fair]\n---\n# Judge\nJudge the data.\n")
    return synthetic.load_prompts(folder)


class Heard:
    """A connection answering the scripted answers in order, then plain text, keeping what every dispatch was handed."""
    label, models, efforts, modes = "Heard", ("model-a", "model-b"), ("low",), ()

    def __init__(self, *answers):
        self.answers, self.heard = list(answers), []

    def settings(self):
        return {"label": self.label, "models": [{"id": model, "name": model} for model in self.models], "efforts": list(self.efforts), "modes": []}

    def dispatch(self, context, text, model=None, effort=None, modes=(), session=None, on_step=None, stopped=None, agent=None):
        self.heard.append({"context": context, "text": text, "model": model, "agent": agent.name if agent else None})
        return (self.answers.pop(0) if self.answers else {"kind": "text", "text": "done"}), "session-h"


class Routed(Heard):
    """A connection an agent is routed to: the verdict agents the harness runs on the same route never take from its script."""

    def dispatch(self, context, text, *args, agent=None, **kwargs):
        if agent is not None and synthetic.is_verdict(agent):
            self.heard.append({"context": context, "text": text, "model": kwargs.get("model"), "agent": agent.name})
            return {"texts": [], "findings": [], "agent": None}, "session-v"
        return super().dispatch(context, text, *args, agent=agent, **kwargs)


def _calls(*batch):
    return {"kind": "calls", "calls": list(batch)}


def _routed(app, agents, **connectors):
    app.connectors = connectors
    app.settings_file.write_text(json.dumps({"orchestrator": {"agents": agents}}))


def _library_agent(app, name, front, text="# Agent\nDo it.\n"):
    """Offer the app a library of the shipped prompts and one more agent `name`."""
    folder = app.root.parent / "fixture_prompts"
    folder.mkdir(exist_ok=True)
    (folder / f"{name}.md").write_text(f"---\nkind: agent\n{front}---\n{text}")
    app.library = {**synthetic.read_library(app.library), name: synthetic.read_prompt(folder / f"{name}.md")}


def _shipped(name):
    return synthetic.load_agents()[name]


def _worker(kind, *names):
    """An agent listing `names` under the key of `kind` -- `tool` or `skill` -- and nothing under the other."""
    return synthetic.prompt("worker", "agent", "", False, "# Worker\n", **{f"{kind}s": names})


def _listed(kind, library, *names):
    """The names of the list of the `kind` an agent listing `names` under its key builds over `library`."""
    return [name for name, entry in synthetic.agent_library(_worker(kind, *names), library).items() if entry.kind == kind]


def _check_listed(kind, tmp_path):
    library = _library(tmp_path / "prompts")
    names = ("shout", "echo", "shout") if kind == "tool" else ("rules", "brief", "rules")
    assert _listed(kind, library, *names) == [names[0], names[1]]  # the order of the list, each name once
    assert _listed(kind, library) == [] and synthetic.agent_calls(_worker(kind), library) == {}  # without the key, none


def _check_entry(kind, tmp_path):
    library = _library(tmp_path / "prompts")
    listed, other_text, text = ("echo", "It shouts.", "# Echo\nIt echoes.\n") if kind == "tool" else ("brief", "Follow them.", "Say less.\n")
    prompt = synthetic.agent_prompt(_worker(kind, listed), library)
    assert prompt == f"# Worker\n\n{text}" and other_text not in prompt  # after the agent's text, the listed prompt alone
    assert synthetic.agent_prompt(_worker(kind), library) == "# Worker\n"  # nothing listed, nothing entering, a default skill included


@pytest.mark.syngate("SYNTHETIC-AGENT-TOOLS-LIST")
def test_the_tool_list_is_the_names_of_the_tools_key_in_order_each_once_none_without_the_key(tmp_path):
    _check_listed("tool", tmp_path)


@pytest.mark.syngate("SYNTHETIC-AGENT-TOOLS-ENTRY")
def test_the_tool_prompts_of_the_list_alone_enter_the_system_prompt_after_the_agents_text(tmp_path):
    _check_entry("tool", tmp_path)


@pytest.mark.syngate("SYNTHETIC-AGENT-TOOLS-REFUSED")
def test_a_call_of_a_tool_outside_the_list_is_refused(tmp_path, app):
    library = _library(tmp_path / "prompts")
    known = synthetic.agent_calls(library["echoer"], library)
    assert known == {"echo": ("text",)} and synthetic.parse_reply(_calls({"tool": "echo", "text": "hi"}), known)[0] == "calls"
    with pytest.raises(synthetic.protocol_error, match="shout"):
        synthetic.parse_reply(_calls({"tool": "shout", "text": "hi"}), known)
    _library_agent(app, "reader", "tools: [files]\n")
    (app.root / "notes.txt").write_text("one\n")
    _routed(app, {"default": {"connection": "heard", "model": "model-a"}},
            heard=(heard := Heard(_calls({"tool": "shell", "command": "ls"}), _calls({"tool": "read", "path": "notes.txt"}), {"kind": "text", "text": "Read."})))
    outcome = app.run_agent("reader", {"uid": "ROOT", "text": "Read the notes.", "modes": ["tree", "bash"]})
    assert outcome["reply"] == "Read." and "unknown tree call 'shell'" in heard.heard[1]["text"]  # the shell call refused, nothing of it run
    assert "one" in heard.heard[2]["text"]


@pytest.mark.syngate("SYNTHETIC-AGENT-SKILLS-LIST")
def test_the_skill_list_is_the_names_of_the_skills_key_in_order_each_once_none_without_the_key(tmp_path):
    _check_listed("skill", tmp_path)


@pytest.mark.syngate("SYNTHETIC-AGENT-SKILLS-ENTRY")
def test_the_skill_prompts_of_the_list_alone_enter_the_system_prompt_after_the_agents_text(tmp_path):
    _check_entry("skill", tmp_path)


def _delegation(base, app, name, modes=(), behaviour="ask", uid="ROOT", parent=None, child=None):
    """Start a turn of `uid`, its model calling the agent `name` once; the agent route is the `child` connection. -> (parent, child, the turn key)."""
    parent = parent or Heard(_calls({"tool": "agent", "name": name, "prompt": "Do it."}), {"kind": "text", "text": "Parent done."})
    child = child or Routed({"kind": "text", "text": "Child done."})
    _routed(app, {"default": {"connection": "child", "model": "model-b"}}, parent=parent, child=child)
    setup = {"connector": "parent", "model": "model-a", "effort": "low", "uid": uid, "text": "Go.", "modes": list(modes), "recommendations": behaviour}
    return parent, child, call(base, app, "/api/turn", setup)[1]["turn"]


def _ran(child, name):
    """The turns the connection `child` served for the agent `name`: the verdict agents the harness runs on the same route are not its."""
    return [entry for entry in child.heard if entry["agent"] == name]


def _finished(base, app, key):
    return call(base, app, f"/api/turn/{key}?wait=10")[1]


@pytest.mark.syngate("SYNTHETIC-AGENT-COVER-OFFER")
def test_an_agent_listing_what_the_chat_does_not_offer_is_forbidden_to_run_no_turn_of_it_starting(server):
    base, app = server
    assert not app.git  # no work tree at hand: the git tool is not offered
    _library_agent(app, "needy", "tools: [files]\nskills: [ghost]\n")
    _library_agent(app, "shelly", "tools: [shell]\n")  # needs `bash`, which the route's connection does not list
    for name, lacking in (("commit", "git"), ("needy", "ghost"), ("shelly", "bash")):
        parent, child, key = _delegation(base, app, name)
        outcome = _finished(base, app, key)
        assert outcome["reply"] == "Parent done." and _ran(child, name) == []  # the agent never ran
        assert f"the agent {name} is forbidden here" in parent.heard[1]["text"] and lacking in parent.heard[1]["text"], parent.heard[1]["text"]


@pytest.mark.syngate("SYNTHETIC-AGENT-COVER-ASK")
def test_a_permission_the_agents_tools_need_that_the_chat_has_off_is_asked_as_a_recommendation_the_run_waiting_and_a_granted_one_staying_on(server):
    base, app = server
    _library_agent(app, "editor", "tools: [syngate_api]\n")
    parent, child, key = _delegation(base, app, "editor")
    asked = recommend.asked_text(recommend.permission_recommendation("tree", "the agent editor needs it"))
    held = held_turn(app, "ROOT")
    assert held is not None and held.held == asked and _ran(child, "editor") == []  # the run waits for the answer, the agent not started
    app.release(held.id, "accept")
    outcome = _finished(base, app, key)
    assert outcome["reply"] == "Parent done." and "- agent editor: Child done." in parent.heard[1]["text"] and len(_ran(child, "editor")) == 1
    assert app.chats["ROOT"].setup["modes"] == ["tree"]  # on for the chat from then on
    assert asked == "recommendation permission → tree: the agent editor needs it"
    parent, child, key = _delegation(base, app, "editor", uid="LEAF-001", behaviour="auto")  # applied at once, nothing asked: the turn is never held
    outcome = _finished(base, app, key)
    assert "- agent editor: Child done." in parent.heard[1]["text"] and app.chats["LEAF-001"].setup["modes"] == ["tree"]
    assert any(step.get("text") == recommend.applied_line(recommend.permission_recommendation("tree", "the agent editor needs it")) for step in outcome["steps"])


@pytest.mark.syngate("SYNTHETIC-AGENT-COVER-DENIED")
def test_a_denied_permission_forbids_the_whole_run_of_the_agent_and_is_not_asked_again_in_the_conversation(server):
    base, app = server
    _library_agent(app, "editor", "tools: [syngate_api]\n")
    parent = Heard(*[answer for _ in range(2) for answer in (_calls({"tool": "agent", "name": "editor", "prompt": "Do it."}), {"kind": "text", "text": "Not run."})])
    threading.Thread(target=lambda: (held := held_turn(app, "ROOT")) and app.release(held.id, "deny"), daemon=True).start()
    for _ in range(2):  # the second time nothing is asked: no one answers it, and the turn is not held
        _, child, key = _delegation(base, app, "editor", parent=parent)
        outcome = _finished(base, app, key)
        assert outcome["reply"] == "Not run." and _ran(child, "editor") == []
    assert app.chats["ROOT"].denied == ["permission:tree"] and "tree" not in (app.chats["ROOT"].setup.get("modes") or ())
    assert parent.heard[1]["text"].count("the agent editor is forbidden here") == 1 and "the agent editor is forbidden here" in parent.heard[3]["text"]


@pytest.mark.syngate("SYNTHETIC-AGENT-EXPLORE")
def test_the_explore_agent_has_the_reading_tools_alone_and_reports_the_places_found():
    agent = _shipped("explore")
    assert agent.tools == ("files",) and agent.schema is None and set(synthetic.agent_calls(agent)) == {"list", "read"}
    assert "report the places found" in agent.text and "change nothing" in agent.text


@pytest.mark.syngate("SYNTHETIC-AGENT-COMMIT")
def test_the_commit_agent_has_the_git_tool_alone_and_commits_from_the_diff_under_a_one_line_subject_without_a_body():
    agent = _shipped("commit")
    assert agent.tools == ("git",) and set(synthetic.agent_calls(agent)) == {"git"} and agent.examples
    assert all(words in agent.text for words in ("git diff", "from its diff", "one-line subject", "without a body"))


@pytest.mark.syngate("SYNTHETIC-AGENT-TEST")
def test_the_test_agent_has_the_tree_calls_alone_and_runs_the_routines_under_the_named_items_reporting_the_failed_ones():
    agent = _shipped("test")
    calls = synthetic.agent_calls(agent)
    assert agent.tools == ("syngate_api",) and "test" in calls and not {"patch", "replace", "shell", "git"} & set(calls)
    assert all(words in agent.text for words in ("item UIDs", "`test` call", "failed bindings"))


@pytest.mark.syngate("SYNTHETIC-AGENT-VERDICT")
def test_a_verdict_agent_declares_a_schema_and_no_tools_and_its_answer_is_the_json_the_harness_reads(tmp_path):
    library = _library(tmp_path / "prompts")
    judge = library["judge"]
    assert synthetic.is_verdict(judge) and not synthetic.is_verdict(library["echoer"])
    assert synthetic.agent_prompt(judge, library) == judge.text and synthetic.agent_schema(judge, library) == judge.schema
    assert all(not entry.tools and not entry.skills for entry in synthetic.load_agents().values() if synthetic.is_verdict(entry))
    heard = Heard({"fair": True}, "not json")
    assert synthetic.verdict({"heard": heard}, judge, "Is it fair?", "heard", "model-a", library=library) == {"fair": True}
    assert heard.heard[0] == {"context": judge.text, "text": "````\nIs it fair?\n````", "model": "model-a", "agent": "judge"}
    with pytest.raises(synthetic.protocol_error):
        synthetic.verdict({"heard": heard}, judge, "Again?", "heard", "model-a", library=library)


@pytest.mark.syngate("SYNTHETIC-AGENT-MATCH")
def test_the_match_agent_answers_one_shortlisted_agent_or_none():
    agent = _shipped("match")
    assert synthetic.is_verdict(agent) and agent.schema["required"] == ["agent"]
    assert agent.schema["properties"]["agent"]["type"] == ["string", "null"] and "shortlisted" in agent.text


@pytest.mark.syngate("SYNTHETIC-AGENT-SCAN")
def test_the_scan_agent_answers_a_list_of_findings_each_a_span_a_category_and_a_reason():
    agent = _shipped("scan")
    findings = agent.schema["properties"]["findings"]
    assert synthetic.is_verdict(agent) and findings["type"] == "array" and findings["items"]["required"] == ["span", "category", "reason"]


@pytest.mark.syngate("SYNTHETIC-AGENT-PRUNE")
def test_the_prune_agent_answers_for_every_ai_text_whether_it_states_something_new():
    agent = _shipped("prune")
    texts = agent.schema["properties"]["texts"]
    assert synthetic.is_verdict(agent) and texts["items"]["required"] == ["index", "new"]
    assert texts["items"]["properties"]["new"]["type"] == "boolean"


def _subagent_tree(syngate_dir, make_item):
    make_item(syngate_dir, "ROOT", "Root\nis the root.\n", parents=())
    make_item(syngate_dir, "LEAF-001", "Tagged release\ncarries a tag.\n", parents=("ROOT",), tests=None)
    items, errors = syngatelib.load_tree(syngate_dir)
    assert not errors
    return items


@pytest.mark.syngate("SYNTHETIC-SUBAGENT-BOUND")
def test_a_dag_bound_subagent_runs_above_its_items_seed_context_its_start_message_holding_only_what_the_tree_does_not(tmp_path, syngate_tree):
    items = _subagent_tree(*syngate_tree)
    brief = synthetic.DELEGATION_TEXT.format(uid="LEAF-001")
    synthetic.query({"heard": (heard := Heard())}, items, "LEAF-001", brief, "heard", "model-a", "low", root=tmp_path)
    seed = synthetic.seed_context(items, "LEAF-001", root=tmp_path, head=synthetic.default_prompt(synthetic.read_library()))
    assert heard.heard[0]["context"] == seed and "carries a tag" in seed and heard.heard[0]["agent"] is None
    assert heard.heard[0]["text"] == brief and "@LEAF-001" in brief and "carries a tag" not in brief  # the statement stays in the seed


@pytest.mark.syngate("SYNTHETIC-SUBAGENT-OFF-CONTEXT")
def test_an_off_context_subagent_runs_above_its_agents_prompt_alone_without_seed_context(tmp_path, syngate_tree):
    items = _subagent_tree(*syngate_tree)
    agent = _shipped("explore")
    synthetic.query({"heard": (heard := Heard())}, items, "LEAF-001", "Where is @ROOT?", "heard", "model-a", "low", root=tmp_path, agent=agent)
    context = heard.heard[0]["context"]
    assert context == synthetic.agent_prompt(agent) and heard.heard[0]["agent"] == "explore"
    assert not any(part in context for part in ("is the root", "carries a tag", "# Tree features", "@LEAF-001"))


def _stub(tmp_path):
    stub = tmp_path / "claude_stub.py"
    stub.write_text(STUB_CLAUDE)
    return synthetic.claude_code_connector(cli=(sys.executable, str(stub)), cwd=tmp_path)


@pytest.mark.syngate("CLAUDE_CODE-AGENT-CALL")
def test_an_agent_runs_as_a_fresh_cli_call_with_its_prompt_as_the_system_prompt_and_every_tool_of_the_cli_denied(tmp_path):
    agent = _shipped("explore")
    prompt = synthetic.agent_prompt(agent)
    echoed = json.loads(_stub(tmp_path).dispatch(prompt, "Where is it?", model="haiku", modes=("internet", "bash"), agent=agent)[0])
    argv = echoed["argv"]
    assert echoed["seed"] == prompt and "--append-system-prompt-file" not in argv and "--system-prompt-file" in argv
    assert argv[argv.index("--tools") + 1] == "" and not {"--plugin-dir", "--allowedTools", "--resume", "--permission-mode"} & set(argv)
    assert json.loads(argv[argv.index("--json-schema") + 1]) == synthetic.agent_schema(agent, text=False)


@pytest.mark.syngate("CLAUDE_CODE-AGENT-SCHEMA")
def test_a_verdict_agents_schema_is_the_answer_schema_of_its_cli_call(tmp_path):
    agent = _shipped("scan")
    argv = json.loads(_stub(tmp_path).dispatch(synthetic.agent_prompt(agent), "text", agent=agent)[0])["argv"]
    assert json.loads(argv[argv.index("--json-schema") + 1]) == agent.schema


@pytest.mark.syngate("SYNTHETIC-AGENT-LOCATOR")
def test_an_agent_runs_on_the_model_locator_of_its_name_else_on_the_default_one(app):
    route = {"default": {"connection": "first", "model": "model-a"}, "explore": [{"connection": "second", "model": "model-b", "effort": "low"}]}
    assert synthetic.agent_locator({"agents": route}, "explore") == {"connection": "second", "model": "model-b", "effort": "low"}
    assert synthetic.agent_locator({"agents": route}, "commit") == {"connection": "first", "model": "model-a", "effort": None}
    assert synthetic.agent_locator({}, "commit") is None
    _routed(app, route, first=(first := Heard()), second=(second := Heard()))
    app.run_agent("explore", {"uid": "ROOT", "text": "Where?", "connector": "first", "model": "model-a"})
    app.run_agent("commit", {"uid": "ROOT", "text": "Commit."})
    assert [(entry["agent"], entry["model"]) for entry in second.heard] == [("explore", "model-b")]
    assert [(entry["agent"], entry["model"]) for entry in first.heard] == [("commit", "model-a")]
    app.settings_file.write_text("{}")
    with pytest.raises(assassin_ui.ApiError, match="no model locator"):
        app.run_agent("explore", {"uid": "ROOT", "text": "Where?"})


@pytest.mark.syngate("SYNTHETIC-TOOL-AGENT-NAMED")
def test_a_named_agent_call_runs_the_off_context_agent_of_the_library_and_its_report_comes_back_as_the_next_prompt(app):
    with pytest.raises(synthetic.protocol_error, match="uid or name"):
        synthetic.parse_reply(_calls({"tool": "agent", "prompt": "Who?"}))
    assert synthetic.parse_reply(_calls({"tool": "agent", "name": "explore", "prompt": "Where?"}))[0] == "calls"
    _library_agent(app, "reader", "tools: [files]\n")
    (app.root / "notes.txt").write_text("one\n")
    parent = Heard(_calls({"tool": "agent", "name": "reader", "prompt": "Read the notes."}), {"kind": "text", "text": "Reported."})
    child = Heard(_calls({"tool": "read", "path": "notes.txt"}), {"kind": "text", "text": "The notes say one."})
    _routed(app, {"default": {"connection": "child", "model": "model-b"}}, parent=parent, child=child)
    outcome = app.chat({"uid": "ROOT", "text": "What do the notes say?", "connector": "parent", "model": "model-a", "modes": ["tree"]})
    assert outcome["reply"] == "Reported." and "- agent reader: The notes say one." in parent.heard[1]["text"]
    assert child.heard[0]["context"] == synthetic.agent_prompt(synthetic.load_agents(app.library)["reader"], app.library)
    assert (child.heard[0]["agent"], child.heard[0]["model"], child.heard[0]["text"]) == ("reader", "model-b", "Read the notes.") and "one" in child.heard[1]["text"]


@pytest.mark.syngate("SYNTHETIC-TOOL-AGENT-SETUP")
def test_an_agent_call_may_name_a_connection_and_model_of_the_listing_for_its_subagent_the_delegating_setup_standing_without_it(app):
    add = {"tool": "add", "uid": "NEW-001", "parent": "ROOT", "description": "New leaf\nis new."}
    first = Heard(_calls(add, {"tool": "agent", "uid": "NEW-001", "connection": "second", "model": "model-b"}),
                  _calls({"tool": "agent", "uid": "NEW-001", "connection": "nowhere", "model": "model-x"}),
                  _calls({"tool": "agent", "uid": "NEW-001"}), {"kind": "text", "text": "child done"}, {"kind": "text", "text": "ok"})
    second = Heard()
    app.connectors = {"first": first, "second": second}
    outcome = app.chat({"uid": "ROOT", "text": "Go.", "connector": "first", "model": "model-a", "modes": ["tree"]})
    brief = synthetic.DELEGATION_TEXT.format(uid="NEW-001")
    assert outcome["reply"] == "ok" and [(entry["text"], entry["model"]) for entry in second.heard] == [(brief, "model-b")]
    assert "not in the models listing" in first.heard[2]["text"]
    assert [entry["model"] for entry in first.heard if entry["text"].endswith(brief)] == ["model-a"]
