# Open Trader
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Synthetic agent library: item seed context and AI connectors."""

import json
import os
import subprocess
import sys
import threading
import time

import pytest

import synthetic
import syngate_ui
import syngatelib

# Stub `claude`: answers the result event a non-interactive stream-json turn closes with, echoing its argv, the prompt read from its
# stdin and the seed file it was handed.
STUB_CLAUDE = """
import json, sys
argv, prompt = sys.argv[1:], json.loads(sys.stdin.readline())["message"]["content"]
if "rc-1" in prompt:
    print(json.dumps({"type": "result", "is_error": True, "result": "model overloaded"})); sys.exit(1)
seed = open(argv[argv.index("--append-system-prompt-file") + 1], encoding="utf-8").read()
print(json.dumps({"type": "result", "result": json.dumps({"argv": argv, "prompt": prompt, "seed": seed}), "session_id": "session-7", "is_error": False}))
"""


@pytest.mark.syngate("SYNTHETIC-010")
def test_seed_context_opens_with_the_default_prompt_then_the_ancestry_the_item_and_its_descendants_each_once(syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root.\n", parents=())
    make_item(syngate_dir, "SIDE-A", "Side A.\n", parents=("ROOT",), order=10)
    make_item(syngate_dir, "SIDE-B", "Side B.\n", parents=("ROOT",), order=20)
    make_item(syngate_dir, "LEAF-001", "It shall leaf.\n", parents=("SIDE-A", "SIDE-B"), order=20, tests=None)
    make_item(syngate_dir, "NOTE-001", "A note.\n", parents=("SIDE-B",), order=10)
    make_item(syngate_dir, "DEEP-001", "It shall go deep.\n", parents=("NOTE-001",), tests=None)
    items, errors = syngatelib.load_tree(syngate_dir)
    assert not errors
    prompt = synthetic.PROMPTS["default"] + "\n"
    assert synthetic.seed_context(items, "ROOT") == prompt + "Root.\nSide A.\nIt shall leaf.\nSide B.\nA note.\nIt shall go deep.\n"
    assert synthetic.seed_context(items, "SIDE-B") == prompt + "Root.\nSide B.\nA note.\nIt shall go deep.\nIt shall leaf.\n"
    assert synthetic.seed_context(items, "NOTE-001") == prompt + "Root.\nSide B.\nA note.\nIt shall go deep.\n"
    assert synthetic.seed_context(items, "LEAF-001") == prompt + "Root.\nSide A.\nSide B.\nIt shall leaf.\n"


def test_the_seed_context_ends_with_the_key_sources_of_the_selection_each_once(tmp_path, syngate_tree):
    syngate_dir, _ = syngate_tree
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "root.py").write_text("ROOT = 1\n")
    (tmp_path / "src" / "leaf.py").write_text("```\nLEAF = 2")
    (syngate_dir / "ROOT.yml").write_text("---\nparents: []\nsources: [src/root.py]\ntest: enabled\nreview: enabled\n---\nRoot.\n")
    (syngate_dir / "SIDE-A.yml").write_text("---\nparents: [ROOT]\nsources: [src/leaf.py, src/root.py]\n---\nSide A.\n")
    (syngate_dir / "LEAF-001.yml").write_text("---\nparents: [SIDE-A]\nsources: [src/leaf.py, docs/GONE.md]\ntest: ~\n---\nIt shall leaf.\n")
    items, errors = syngatelib.load_tree(syngate_dir)
    assert not errors and synthetic.item_view(items, "SIDE-A")["sources"] == ["src/leaf.py", "src/root.py"]
    prompt = synthetic.PROMPTS["default"] + "\n"
    root_source = "\n# Source src/root.py\n````\nROOT = 1\n````\n"
    leaf_sources = "\n# Source src/leaf.py\n````\n```\nLEAF = 2\n````\n" + "\n# Source docs/GONE.md\n(file not found)\n"
    assert synthetic.seed_context(items, "ROOT", root=tmp_path) == prompt + "Root.\nSide A.\nIt shall leaf.\n" + root_source + leaf_sources
    assert synthetic.seed_context(items, "SIDE-A", root=tmp_path) == synthetic.seed_context(items, "ROOT", root=tmp_path)
    seed = synthetic.seed_context(items, "LEAF-001", root=tmp_path)
    assert seed == prompt + "Root.\nSide A.\nIt shall leaf.\n" + root_source + leaf_sources
    assert synthetic.apply_call(items, "ROOT", {"tool": "context", "uid": "LEAF-001"}, syngate_dir=syngate_dir) == f"- context of LEAF-001:\n{seed}"
    app = syngate_ui.SyngateUIApp(root=tmp_path, syngate_dir=syngate_dir)
    app.connectors = {"echo": EchoAnswer()}
    reply = app.chat({"uid": "LEAF-001", "connector": "echo", "model": "model-a", "effort": "low", "text": "Go."})["reply"]
    assert reply == f"{seed}|Go.|model-a|low||None"
    synthetic.apply_call(items, "ROOT", {"tool": "add", "uid": "LEAF-002", "description": "Second\n\nIt shall follow.", "sources": ["src/leaf.py"]}, syngate_dir=syngate_dir)
    assert items["LEAF-002"].sources == ["src/leaf.py"] and synthetic.seed_context(items, "LEAF-002", root=tmp_path).endswith(root_source + "\n# Source src/leaf.py\n````\n```\nLEAF = 2\n````\n")
    synthetic.apply_call(items, "ROOT", {"tool": "edit", "uid": "LEAF-002", "sources": []}, syngate_dir=syngate_dir)
    assert items["LEAF-002"].sources == [] and synthetic.seed_context(items, "LEAF-002", root=tmp_path).endswith("It shall follow.\n" + root_source)


def _library(folder):
    """A prompt library of two skills -- `rules` default, `brief` on request -- and one tool, written as front-matter markdown."""
    folder.mkdir(exist_ok=True)
    (folder / "rules.md").write_text("---\nkind: skill\ndescription: The rules\ndefault: true\n---\n# Rules\nFollow them.\n")
    (folder / "brief.md").write_text("---\nkind: skill\ndescription: Be brief\n---\n\nSay less.\n\n")
    (folder / "echo.md").write_text("---\nkind: tool\ndescription: Echo back\n---\n# Echo\n`{\"tool\": \"echo\"}` echoes.\n")
    (folder / "notes.txt").write_text("not a prompt")
    return synthetic.load_prompts(folder)


@pytest.mark.syngate("AI_CHAT-PROMPTS")
def test_the_prompt_library_is_read_from_front_matter_markdown_files_by_name_as_skills_and_tools(tmp_path, syngate_tree):
    library = _library(tmp_path / "prompts")
    assert library == {
        "brief": synthetic.prompt("brief", "skill", "Be brief", False, "Say less.\n"),
        "echo": synthetic.prompt("echo", "tool", "Echo back", False, "# Echo\n`{\"tool\": \"echo\"}` echoes.\n"),
        "rules": synthetic.prompt("rules", "skill", "The rules", True, "# Rules\nFollow them.\n")}
    (tmp_path / "prompts" / "bare.md").write_text("No front matter.\n")
    assert synthetic.load_prompts(tmp_path / "prompts")["bare"] == synthetic.prompt("bare", "skill", "", False, "No front matter.\n")
    assert synthetic.LIBRARY == synthetic.load_prompts() and set(synthetic.PROMPTS) == set(synthetic.LIBRARY) | {synthetic.DEFAULT_PROMPT}
    assert all(synthetic.PROMPTS[name] == entry.text for name, entry in synthetic.LIBRARY.items())
    assert synthetic.SKILLS == {name: entry for name, entry in synthetic.LIBRARY.items() if entry.kind == "skill"}
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root.\n", parents=())
    items, _ = syngatelib.load_tree(syngate_dir)
    assert synthetic.seed_context(items, "ROOT") == synthetic.PROMPTS[synthetic.DEFAULT_PROMPT] + "\nRoot.\n"


@pytest.mark.syngate("AI_CHAT-PROMPTS-DEFAULT")
def test_the_default_prompt_is_composed_of_the_default_skills_the_skills_on_request_and_every_tool(tmp_path):
    library = _library(tmp_path / "prompts")
    assert synthetic.default_prompt(library) == ("# Rules\nFollow them.\n\n# Skills on request\nLoad one with the `skill` tool:\n- `brief`: Be brief\n\n"
                                                 "# Echo\n`{\"tool\": \"echo\"}` echoes.\n")
    assert synthetic.default_prompt({"rules": library["rules"]}) == "# Rules\nFollow them.\n\n# Skills on request\nLoad one with the `skill` tool:\nnone\n"
    shipped = synthetic.PROMPTS[synthetic.DEFAULT_PROMPT]
    assert shipped == synthetic.default_prompt(synthetic.LIBRARY) and not list(synthetic.PROMPTS_DIR.glob("CLAUDE.md"))
    assert all(entry.text in shipped for entry in synthetic.LIBRARY.values() if entry.kind == "tool" or entry.default)
    assert all(f'"tool": "{tool}"' in shipped for tool in synthetic.CALLS)


@pytest.mark.syngate("AI_CHAT-SKILL-CALL-TOOL")
def test_the_tool_call_skill_is_a_default_skill_stating_the_answer_format_and_the_result_round_trip():
    skill = synthetic.SKILLS["call_tool"]
    assert skill.default and skill.text.startswith("# Tool calls\n")
    for phrase in ('{"kind": "text", "text": "…"}', '{"kind": "calls", "calls": [...]}', "```syngate", "never both",
                   "applied in order", "first refused one stops the batch", "next prompt"):
        assert phrase in skill.text


@pytest.mark.syngate("AI_CHAT-SKILL-SYNGATE")
def test_the_syngate_rules_skill_is_a_default_skill_stating_the_dag_rules():
    skill = synthetic.SKILLS["syngate"]
    assert skill.default and skill.text.startswith("# Syngate DAG rules\n")
    for phrase in ("directed acyclic graph", "testable statement", "split into children", "markdown files", "root-relative link",
                   "tags equal to the item UID", "numbered suffix"):
        assert phrase in skill.text


@pytest.mark.syngate("AI_CHAT-SKILL-DELEGATE")
def test_the_delegation_skill_is_a_default_skill_stating_how_separable_children_are_delegated_and_subagents_anchored():
    skill = synthetic.SKILLS["delegate"]
    assert skill.default and skill.text.startswith("# Delegation\n")
    for phrase in ("with children", "`query`", "separable", '{"tool": "agent"', "next prompt", "first line", "`@UID`"):
        assert phrase in skill.text
    shipped = synthetic.PROMPTS[synthetic.DEFAULT_PROMPT]
    assert skill.text in shipped and synthetic.LIBRARY["agent"].kind == "tool" and synthetic.LIBRARY["agent"].text in shipped


@pytest.mark.syngate("AI_CHAT-TOOL-SKILL")
def test_the_skill_call_brings_the_named_skill_back_as_the_next_prompt_and_an_unknown_name_is_refused(tmp_path, syngate_tree):
    assert synthetic.parse_reply({"kind": "calls", "calls": [{"tool": "skill", "name": "syngate"}]}) == ("calls", [{"tool": "skill", "name": "syngate"}])
    with pytest.raises(synthetic.protocol_error, match="missing name"):
        synthetic.parse_reply({"kind": "calls", "calls": [{"tool": "skill"}]})
    shape = next(shape for shape in synthetic.ANSWER_SCHEMA["properties"]["calls"]["items"]["anyOf"] if shape["properties"]["tool"]["const"] == "skill")
    assert shape["required"] == ["tool", "name"] and "uid" not in shape["properties"]
    assert synthetic.apply_call({}, "ROOT", {"tool": "skill", "name": "syngate"}) == "- skill syngate:\n" + synthetic.SKILLS["syngate"].text
    with pytest.raises(syngatelib.tree_error, match="unknown skill 'fly'"):
        synthetic.apply_call({}, "ROOT", {"tool": "skill", "name": "fly"})
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root.\n", parents=())
    app = syngate_ui.SyngateUIApp(root=tmp_path, syngate_dir=syngate_dir)
    calls = lambda *batch: {"kind": "calls", "calls": list(batch)}
    ask = lambda: app.chat({"uid": "ROOT", "connector": "scripted", "model": "model-a", "effort": "low", "text": "Which rules?"})
    app.connectors = {"scripted": (scripted := ScriptedConnection(calls({"tool": "skill", "name": "call_tool"}), {"kind": "text", "text": "Got it."}))}
    result = ask()
    assert scripted.prompts[1] == (synthetic.RESULTS_PREAMBLE + "- skill call_tool:\n" + synthetic.SKILLS["call_tool"].text, "session-1")
    assert result["reply"].endswith(synthetic.SKILLS["call_tool"].text + "\nGot it.") and result["session"] == "session-2"
    app.connectors = {"scripted": ScriptedConnection(calls({"tool": "skill", "name": "fly"}))}
    with pytest.raises(syngate_ui.ApiError, match="skill fly refused: unknown skill 'fly'") as refused:
        ask()
    assert refused.value.status == 400


class EchoConnection:
    label, models, efforts, modes = "Echo", ("model-a", "model-b"), ("low", "high"), ("edit",)

    def dispatch(self, context, text, model=None, effort=None, modes=(), session=None, on_step=None):
        return f"{context}|{text}|{model}|{effort}|{','.join(modes)}|{session}", "session-1"


class EchoAnswer(EchoConnection):
    """The echo as a structured answer: the seed context it quotes carries the ```syngate example of the tool definitions."""

    def dispatch(self, context, text, **kwargs):
        reply, session = super().dispatch(context, text, **kwargs)
        return {"kind": "text", "text": reply}, session


@pytest.mark.syngate("SYNTHETIC-011")
def test_query_goes_through_the_selected_connection_model_and_effort(syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root.\n", parents=())
    make_item(syngate_dir, "LEAF-001", "It shall leaf.\n", parents=("ROOT",), tests=None)
    items, _ = syngatelib.load_tree(syngate_dir)
    connectors = {"echo": EchoConnection(), "other": None}
    reply, session = synthetic.query(connectors, items, "LEAF-001", "What is missing?", "echo", "model-b", "high", modes=["edit"], session="session-0")
    assert (reply, session) == (synthetic.PROMPTS[synthetic.DEFAULT_PROMPT] + "\nRoot.\nIt shall leaf.\n|What is missing?|model-b|high|edit|session-0", "session-1")
    with pytest.raises(synthetic.query_error):
        synthetic.query(connectors, items, "LEAF-001", "hi", "echo", "model-a", "low", modes=["fly"])
    for uid, text, connector, model, effort in (("NOPE", "hi", "echo", "model-a", "low"), ("LEAF-001", "hi", "absent", "model-a", "low"),
                                                ("LEAF-001", "hi", "echo", "model-c", "low"), ("LEAF-001", "hi", "echo", "model-a", "max"),
                                                ("LEAF-001", "  ", "echo", "model-a", "low")):
        with pytest.raises(synthetic.query_error):
            synthetic.query(connectors, items, uid, text, connector, model, effort)


@pytest.mark.syngate("CLAUDE_CODE")
def test_claude_code_connector_dispatches_a_non_interactive_turn(tmp_path):
    stub = tmp_path / "claude_stub.py"
    stub.write_text(STUB_CLAUDE)
    connector = synthetic.claude_code_connector(cli=(sys.executable, str(stub)), cwd=tmp_path)
    reply, session = connector.dispatch("Root.\nIt shall leaf.\n", "What is missing?", model="claude-sonnet-5", effort="low", session="session-6")
    echoed = json.loads(reply)
    assert session == "session-7" and echoed["seed"] == "Root.\nIt shall leaf.\n"
    argv = echoed["argv"]
    assert argv[:5] == ["-p", "--input-format", "stream-json", "--output-format", "stream-json"] and echoed["prompt"] == "What is missing?"
    for flag, value in (("--model", "claude-sonnet-5"), ("--effort", "low"), ("--resume", "session-6")):
        assert argv[argv.index(flag) + 1] == value
    assert "--model" not in json.loads(connector.dispatch("", "Defaults?")[0])["argv"]
    with pytest.raises(synthetic.connection_error, match="model overloaded"):
        connector.dispatch("", "rc-1")


@pytest.mark.syngate("CLAUDE_CODE-010")
def test_claude_code_settings_list_models_by_display_name_efforts_and_modes():
    settings = synthetic.claude_code_connector().settings()
    assert settings["label"] == "Claude Code"
    assert {"id": "claude-opus-5-5", "name": "opus-5-5", "efforts": ["low", "medium", "high", "xhigh", "max"]} in settings["models"]
    assert {"id": "claude-haiku-4-5-20251001", "name": "haiku-4-5-20251001", "efforts": []} in settings["models"]
    assert [model["id"] for model in settings["models"]] == list(synthetic.CLAUDE_MODELS)
    assert all(model["efforts"] == list(synthetic.CLAUDE_MODEL_EFFORTS[model["id"]]) for model in settings["models"])
    assert not [model for model in settings["models"] if model["name"].startswith("claude")]
    assert [(mode["id"], mode["label"], mode["hint"], mode["default"]) for mode in settings["modes"]] == [
        ("edit", "Edit", "project files", True), ("internet", "Internet", "access", True), ("workflows", "Workflows", "run subagents", False)]


def _mode_argv(tmp_path, modes):
    stub = tmp_path / "claude_stub.py"
    stub.write_text(STUB_CLAUDE)
    connector = synthetic.claude_code_connector(cli=(sys.executable, str(stub)), cwd=tmp_path)
    return json.loads(connector.dispatch("", "Go.", modes=modes)[0])["argv"]


@pytest.mark.syngate("CLAUDE_CODE-020")
def test_edit_mode_accepts_project_file_edits(tmp_path):
    argv = _mode_argv(tmp_path, ["edit"])
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits" and argv[argv.index("--allowedTools") + 1] == "Agent"
    assert "--permission-mode" not in _mode_argv(tmp_path, [])


@pytest.mark.syngate("CLAUDE_CODE-030")
def test_internet_mode_allows_the_web_tools(tmp_path):
    argv = _mode_argv(tmp_path, ["internet"])
    assert argv[argv.index("--allowedTools") + 1] == "Agent,WebSearch,WebFetch" and "--permission-mode" not in argv
    bare = _mode_argv(tmp_path, [])
    assert bare[bare.index("--allowedTools") + 1] == "Agent"


@pytest.mark.syngate("CLAUDE_CODE-040")
def test_workflows_mode_allows_the_workflow_tool(tmp_path):
    argv = _mode_argv(tmp_path, ["workflows"])
    assert argv[argv.index("--allowedTools") + 1] == "Agent,Workflow"
    combined = _mode_argv(tmp_path, ["edit", "internet", "workflows"])
    assert combined[combined.index("--allowedTools") + 1] == "Agent,WebSearch,WebFetch,Workflow"
    assert combined[combined.index("--permission-mode") + 1] == "acceptEdits"


@pytest.mark.syngate("CLAUDE_CODE-050")
def test_the_seed_context_is_the_appended_system_prompt(tmp_path, syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root.\n", parents=())
    items, _ = syngatelib.load_tree(syngate_dir)
    stub = tmp_path / "claude_stub.py"
    stub.write_text(STUB_CLAUDE)
    connector = synthetic.claude_code_connector(cli=(sys.executable, str(stub)), cwd=tmp_path)
    echoed = json.loads(connector.dispatch(synthetic.seed_context(items, "ROOT"), "Go.")[0])
    assert echoed["seed"] == synthetic.PROMPTS[synthetic.DEFAULT_PROMPT] + "\nRoot.\n" and "--append-system-prompt" not in echoed["argv"]
    assert synthetic.LIBRARY["syngate_api"].text in synthetic.PROMPTS[synthetic.DEFAULT_PROMPT]


@pytest.mark.syngate("CLAUDE_CODE-TREE-GUARD")
def test_tree_file_edits_are_denied_in_every_mode(tmp_path):
    for modes in ([], ["edit"], ["edit", "internet", "workflows"]):
        argv = _mode_argv(tmp_path, modes)
        assert argv[argv.index("--disallowedTools") + 1] == "Edit(syngate/**),Write(syngate/**)"


@pytest.mark.syngate("SYNTHETIC-020")
def test_an_answer_is_text_or_one_block_of_tree_calls_never_both():
    calls = [{"tool": "add", "uid": "AREA-030", "parent": "@", "description": "D"}, {"tool": "remove", "uid": "AREA-020"},
             {"tool": "move", "uid": "AREA-010", "to": "AREA", "before": "AREA-030"}]
    block = "```syngate\n" + json.dumps(calls) + "\n```"
    prose = "Plain prose, even with ```json\n[]\n``` inside."
    assert synthetic.parse_reply(prose) == ("chat", prose)
    assert synthetic.parse_reply(f"\n{block}\n\n") == ("calls", calls)
    for mixed in (f"Here you go:\n{block}", f"{block}\nDone.", f"{block}\n{block}"):
        with pytest.raises(synthetic.protocol_error, match="never both"):
            synthetic.parse_reply(mixed)
    for malformed in ("[{", "[]", '{"tool": "add"}', '[{"tool": "rename", "uid": "X"}]', '[{"tool": "add", "uid": "X", "sources": ["a"]}]', '[{"tool": "move", "uid": "X"}]'):
        with pytest.raises(synthetic.protocol_error):
            synthetic.parse_reply(f"```syngate\n{malformed}\n```")


# Stub `claude` answering through structured output, the reply text being something else entirely.
STUB_STRUCTURED = """
import json
print(json.dumps({"type": "result", "result": "the text the model also printed", "structured_output": {"kind": "calls", "calls": [{"tool": "query", "uid": "@"}]},
                  "session_id": "session-8", "is_error": False}))
"""


@pytest.mark.syngate("CLAUDE_CODE-060")
def test_the_answer_schema_carries_every_tool_call_and_the_structured_output_is_the_answer(tmp_path):
    stub = tmp_path / "claude_stub.py"
    stub.write_text(STUB_CLAUDE)
    argv = json.loads(synthetic.claude_code_connector(cli=(sys.executable, str(stub)), cwd=tmp_path).dispatch("", "Go.")[0])["argv"]
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    assert schema == synthetic.ANSWER_SCHEMA and schema["properties"]["kind"]["enum"] == ["text", "calls"]
    shapes = {shape["properties"]["tool"]["const"]: shape["required"] for shape in schema["properties"]["calls"]["items"]["anyOf"]}
    assert shapes == {tool: ["tool", *fields] for tool, fields in synthetic.CALLS.items()}
    assert set(synthetic.QUERIES) == {"query", "context", "skill"} and set(synthetic.RUNS) == {"test"} and set(synthetic.DELEGATIONS) == {"agent"}
    assert set(synthetic.CALLS) == set(synthetic.TOOLS) | set(synthetic.QUERIES) | set(synthetic.RUNS) | set(synthetic.DELEGATIONS)
    structured = tmp_path / "structured_stub.py"
    structured.write_text(STUB_STRUCTURED)
    answer, session = synthetic.claude_code_connector(cli=(sys.executable, str(structured)), cwd=tmp_path).dispatch("", "Go.")
    assert (answer, session) == ({"kind": "calls", "calls": [{"tool": "query", "uid": "@"}]}, "session-8")
    assert synthetic.parse_reply(answer) == ("calls", [{"tool": "query", "uid": "@"}])
    assert synthetic.parse_reply({"kind": "text", "text": "Talk."}) == ("chat", "Talk.")
    for mixed in ({"kind": "text", "text": "Both.", "calls": [{"tool": "remove", "uid": "X"}]}, {"kind": "calls", "text": "Both.", "calls": [{"tool": "remove", "uid": "X"}]}):
        with pytest.raises(synthetic.protocol_error, match="never both"):
            synthetic.parse_reply(mixed)
    with pytest.raises(synthetic.protocol_error, match="missing"):
        synthetic.parse_reply({"kind": "calls", "calls": [{"tool": "context"}]})


class ScriptedConnection:
    """Answers the scripted structured answers in turn, keeping every prompt it was handed."""
    label, models, efforts, modes = "Scripted", ("model-a",), ("low",), ()

    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    def dispatch(self, context, text, model=None, effort=None, modes=(), session=None, on_step=None, stopped=None):
        self.prompts.append((text, session))
        return self.answers[min(len(self.prompts), len(self.answers)) - 1], f"session-{len(self.prompts)}"


@pytest.mark.syngate("SYNTHETIC-021")
def test_what_a_batch_queried_goes_back_into_the_session_until_an_answer_carries_no_query(tmp_path, syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root.\n", parents=())
    make_item(syngate_dir, "LEAF-001", "It shall leaf.\n", parents=("ROOT",), tests=None)
    app = syngate_ui.SyngateUIApp(root=tmp_path, syngate_dir=syngate_dir)
    calls = lambda *batch: {"kind": "calls", "calls": list(batch)}
    query, add = {"tool": "query", "uid": "@"}, {"tool": "add", "uid": "LEAF-002", "description": "Second\n\nIt shall follow."}
    agent = {"tool": "agent", "uid": "LEAF-002", "prompt": "Check it."}
    ask = lambda connection: app.chat({"uid": "ROOT", "connector": "scripted", "model": "model-a", "effort": "low", "text": "Add a second leaf."})

    app.connectors = {"scripted": (scripted := ScriptedConnection(calls(query), calls(add, query), calls(agent), {"kind": "text", "text": "Checked."},
                                                                  {"kind": "text", "text": "Done."}))}
    result = ask(scripted)
    assert [session for _, session in scripted.prompts] == [None, "session-1", "session-2", None, "session-3"]
    assert scripted.prompts[3][0] == "Check it." and scripted.prompts[4][0] == synthetic.RESULTS_PREAMBLE + "- agent LEAF-002: Checked."
    assert scripted.prompts[0][0] == "Add a second leaf."
    for prompt, children in ((scripted.prompts[1][0], ["LEAF-001"]), (scripted.prompts[2][0], ["LEAF-001", "LEAF-002"])):
        assert prompt.startswith(synthetic.RESULTS_PREAMBLE) and json.loads(prompt.split("- ROOT: ", 1)[1])["children"] == children
    assert scripted.prompts[2][0].split("\n")[1] == "- added LEAF-002 under ROOT"
    assert result["session"] == "session-5" and result["calls"] == [query, add, query, agent] and result["reply"].endswith(
        "- added LEAF-002 under ROOT\n- ROOT: " + json.dumps(synthetic.item_view(app._load(), "ROOT"), ensure_ascii=False) + "\n- agent LEAF-002: Checked.\nDone.")

    app.connectors = {"scripted": (looping := ScriptedConnection(calls(query)))}
    with pytest.raises(syngate_ui.ApiError, match="kept querying") as refused:
        ask(looping)
    assert len(looping.prompts) == synthetic.QUERY_ROUNDS and refused.value.extra["session"] == f"session-{synthetic.QUERY_ROUNDS}"

    app.connectors = {"scripted": (unknown := ScriptedConnection(calls(query, {"tool": "query", "uid": "LEAF-009"})))}
    with pytest.raises(syngate_ui.ApiError, match="query LEAF-009 refused") as refused:
        ask(unknown)
    assert refused.value.status == 404 and str(refused.value).startswith("- ROOT: ") and len(unknown.prompts) == 1


# Stub `syngate test`: records one coverage line per addressed binding -- `two` failing with a log -- and keeps the argv it was run with.
STUB_RUNNER = """
import json, sys
argv = sys.argv[1:]
open(sys.argv[0] + ".argv", "a").write(" ".join(argv) + "\\n")
with open(argv[argv.index("--coverage-out") + 1], "a") as out:
    for leaf in argv[1:argv.index("--build-dir")]:
        uid, _, name = leaf.partition(":")
        for binding in ([name] if name else {"LEAF-001": ["one", "two"], "LEAF-002": [""]}[uid]):
            failed = binding == "two"
            out.write(json.dumps({"tags": [uid] + ([binding] if binding else []), "passed": not failed, "name": "", "log": "boom" if failed else ""}) + "\\n")
"""


@pytest.mark.syngate("SYNGATE-API-AI")
def test_a_test_call_runs_the_bound_routines_through_the_page_runner_and_reports_the_outcome(tmp_path, syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root.\n", parents=())
    make_item(syngate_dir, "LEAF-001", "It shall leaf.\n", parents=("ROOT",), tests={"one": None, "two": None})
    make_item(syngate_dir, "LEAF-002", "It shall follow.\n", parents=("ROOT",), order=10, tests=None)
    stub = tmp_path / "runner_stub.py"
    stub.write_text(STUB_RUNNER)
    app = syngate_ui.SyngateUIApp(root=tmp_path, syngate_dir=syngate_dir, cli_prefix=[sys.executable, str(stub)])
    calls = lambda *batch: {"kind": "calls", "calls": list(batch)}
    everything, narrowed = {"tool": "test", "uid": "@"}, {"tool": "test", "uid": "LEAF-001", "name": "two"}
    ask = lambda: app.chat({"uid": "ROOT", "connector": "scripted", "model": "model-a", "effort": "low", "text": "Run the tests."})

    app.connectors = {"scripted": (scripted := ScriptedConnection(calls(everything), calls(narrowed), {"kind": "text", "text": "Done."}))}
    result = ask()
    runs = (tmp_path / "runner_stub.py.argv").read_text().splitlines()
    assert [run.split(" --build-dir")[0] for run in runs] == ["test LEAF-001 LEAF-002", "test LEAF-001:two"]
    assert all(run.endswith(f"--coverage-out {app.run_coverage}") for run in runs)
    outcome, again = scripted.prompts[1][0], scripted.prompts[2][0]
    assert outcome == synthetic.RESULTS_PREAMBLE + "- LEAF-001:one: pass\n- LEAF-001:two: fail\n- LEAF-002: pass\nLEAF-001:two output:\nboom"
    assert again == synthetic.RESULTS_PREAMBLE + "- LEAF-001:two: fail\nLEAF-001:two output:\nboom"
    assert result["calls"] == [everything, narrowed] and result["reply"].endswith("boom\nDone.") and result["session"] == "session-3"
    axes = syngatelib.compute_axes(app._load(), syngatelib.load_coverage([app.run_coverage])[0])
    assert (axes["LEAF-001"]["test"], axes["LEAF-002"]["test"], axes["ROOT"]["test"]) == (syngatelib.TEST_FAILED, syngatelib.TEST_PASSED, syngatelib.TEST_FAILED)

    app.connectors = {"scripted": ScriptedConnection(calls(everything))}
    app.jobs.start([sys.executable, "-c", "import time; time.sleep(60)"], cwd=tmp_path)
    try:
        with pytest.raises(syngate_ui.ApiError, match="test ROOT refused: a run is already in progress") as refused:
            ask()
        assert refused.value.status == 409 and len((tmp_path / "runner_stub.py.argv").read_text().splitlines()) == 2
    finally:
        app.jobs.cancel()


class DelegatedConnection(ScriptedConnection):
    """The parent's scripted answers; a delegated `Do …` prompt is answered only once two of them are out at the same time, `Hold`
    once released."""
    models = ("model-a", "model-b")

    def __init__(self, *answers):
        super().__init__(*answers)
        self.gate, self.release = threading.Barrier(2, timeout=5), threading.Event()

    def dispatch(self, context, text, model=None, effort=None, modes=(), session=None, on_step=None, stopped=None):
        if text == "Hold":
            self.release.wait(5)
            return {"kind": "text", "text": "Held."}, None
        if not text.startswith("Do "):
            return super().dispatch(context, text, model, effort, modes, session, on_step)
        on_step({"kind": "reasoning", "text": f"On it: {text}", "at": 0.0})
        try:
            self.gate.wait()
        except threading.BrokenBarrierError:
            return {"kind": "text", "text": "alone"}, None
        return {"kind": "text", "text": f"did: {text}"}, f"session-{model}"


def _awaited(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.02)
    return predicate()


class HaltedConnection(ScriptedConnection):
    """Answers the `held` prompt once released, telling whether the turn was stopped by then."""

    def __init__(self, held, *answers):
        super().__init__(*answers)
        self.held, self.release, self.halted = held, threading.Event(), None

    def dispatch(self, context, text, stopped=lambda: False, **kwargs):
        if text == self.held:
            self.release.wait(5)
            self.halted = stopped()
        return super().dispatch(context, text, **kwargs)


@pytest.mark.syngate("CLAUDE_CODE-080", "gate")
def test_a_stop_closes_the_turns_gate_so_no_call_run_or_delegation_is_applied_past_it(tmp_path, syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root.\n", parents=())
    make_item(syngate_dir, "LEAF-001", "It shall leaf.\n", parents=("ROOT",), tests=None)
    app = syngate_ui.SyngateUIApp(root=tmp_path, syngate_dir=syngate_dir)
    setup = {"connector": "scripted", "model": "model-a", "effort": "low"}
    batch = {"kind": "calls", "calls": [{"tool": "add", "uid": "LEAF-002", "description": "Late.\n"}, {"tool": "test", "uid": "LEAF-001"},
                                        {"tool": "agent", "uid": "LEAF-001", "prompt": "Do the leaf"}]}

    app.connectors = {"scripted": (connection := HaltedConnection("Go.", batch, {"kind": "text", "text": "Never."}))}
    turn = app.start_turn({**setup, "uid": "ROOT", "text": "Go."})["turn"]
    app.stop_turn(turn)
    connection.release.set()
    outcome = app.turn_snapshot(turn, wait=5)
    assert connection.halted is True and (outcome["status"], outcome["error"]) == (409, "turn stopped")
    assert "LEAF-002" not in app._load() and app.jobs.current is None and "LEAF-001" not in app.chats
    assert len(connection.prompts) == 1 and app.chats_snapshot()["chats"]["ROOT"]["log"][-1] == {"role": "error", "text": "turn stopped"}

    connection = HaltedConnection("Hold", {"kind": "calls", "calls": [{"tool": "agent", "uid": "LEAF-001", "prompt": "Hold"}]}, {"kind": "text", "text": "Never."})
    app.connectors = {"scripted": connection}
    parent = app.start_turn({**setup, "uid": "ROOT", "text": "Delegate."})["turn"]
    assert _awaited(lambda: "LEAF-001" in app.chats and app.chats["LEAF-001"].running)
    app.stop_turn(parent)
    assert app.chats["LEAF-001"].turn.stopped
    connection.release.set()
    stopped = app.turn_snapshot(parent, wait=5)
    assert (stopped["status"], stopped["error"]) == (409, "- agent LEAF-001: turn stopped\nturn stopped")


@pytest.mark.syngate("AI_CHAT-TOOL-AGENT")
def test_the_agent_calls_of_a_batch_run_as_parallel_turns_of_their_items_chats_and_report_back_as_the_next_prompt(tmp_path, syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root.\n", parents=())
    make_item(syngate_dir, "LEAF-001", "It shall leaf.\n", parents=("ROOT",), tests=None)
    make_item(syngate_dir, "LEAF-002", "It shall follow.\n", parents=("ROOT",), order=10, tests=None)
    app = syngate_ui.SyngateUIApp(root=tmp_path, syngate_dir=syngate_dir)
    calls = lambda *batch: {"kind": "calls", "calls": list(batch)}
    leaf = {"tool": "agent", "uid": "LEAF-001", "prompt": "Do the leaf", "model": "model-b"}
    other = {"tool": "agent", "uid": "LEAF-002", "prompt": "Do the other"}
    setup = {"connector": "scripted", "model": "model-a", "effort": "low"}

    app.connectors = {"scripted": (connection := DelegatedConnection(calls(leaf, other), {"kind": "text", "text": "All done."}))}
    started = app.start_turn({**setup, "uid": "ROOT", "text": "Split the work."})
    outcome = app.turn_snapshot(started["turn"], wait=10)
    chats = app.chats_snapshot()["chats"]
    assert started["turn"] == "ROOT:1" and outcome["reply"].endswith("- agent LEAF-001: did: Do the leaf\n- agent LEAF-002: did: Do the other\nAll done.")
    assert connection.prompts[1][0] == synthetic.RESULTS_PREAMBLE + "- agent LEAF-001: did: Do the leaf\n- agent LEAF-002: did: Do the other"
    for child, prompt, model in (("LEAF-001", "Do the leaf", "model-b"), ("LEAF-002", "Do the other", "model-a")):
        assert chats[child]["log"][0] == {"role": "user", "text": prompt, "agent": "ROOT:1"}
        assert (chats[child]["log"][1]["text"], chats[child]["model"], chats[child]["session"]) == (f"did: {prompt}", model, f"session-{model}")
    agents = [step for step in outcome["steps"] if step["kind"] == "agent"]
    assert _without_at(agents) == [{"kind": "agent", "uid": child, "prompt": prompt, "report": f"did: {prompt}", "steps": [{"kind": "reasoning", "text": f"On it: {prompt}"}]}
                                   for child, prompt in (("LEAF-001", "Do the leaf"), ("LEAF-002", "Do the other"))]

    held = app.start_turn({**setup, "uid": "LEAF-001", "text": "Hold"})["turn"]
    app.connectors["scripted"].answers = [calls(dict(other, prompt="Hold"), leaf, {"tool": "agent", "uid": "@", "prompt": "Me"})]
    with pytest.raises(syngate_ui.ApiError, match=f"agent LEAF-001 refused: a turn of LEAF-001 is running \\({held}\\)") as refused:
        threading.Timer(0.3, connection.release.set).start()
        app.chat({**setup, "uid": "ROOT", "text": "Again."})
    assert refused.value.status == 409 and str(refused.value).startswith("- agent LEAF-002: Held.\n")
    assert app.turn_snapshot(held, wait=5)["reply"] == "Held."

    connection.release.clear()
    app.connectors["scripted"].answers = [calls(dict(other, prompt="Hold"))]
    parent = app.start_turn({**setup, "uid": "ROOT", "text": "Once more."})["turn"]
    assert _awaited(lambda: app.chats["LEAF-002"].running)
    app.stop_turn(parent)
    assert _awaited(lambda: app.chats["LEAF-002"].turn.stopped)
    connection.release.set()
    stopped = app.turn_snapshot(parent, wait=5)
    assert (stopped["status"], stopped["error"]) == (409, "- agent LEAF-002: turn stopped\nturn stopped")

    app.connectors["scripted"].answers = [calls({"tool": "agent", "uid": "@", "prompt": "Me"})]
    itself = app.turn_snapshot(app.start_turn({**setup, "uid": "ROOT", "text": "Delegate to yourself."})["turn"], wait=5)
    assert (itself["status"], itself["error"]) == (409, "agent ROOT refused: a turn of ROOT is running (ROOT:3)")


STUB_AWAITED = """
import json, sys, time
open("started", "w").write("the first answer, given before the subagent reported")
time.sleep(0.3)
print(json.dumps({"type": "result", "result": "the agent reported", "structured_output": {"kind": "text", "text": "the agent reported"}, "session_id": "session-9", "is_error": False}))
"""


@pytest.mark.syngate("CLAUDE_CODE-070")
def test_a_turn_lasts_until_the_process_exits_and_its_answer_is_the_last_one(tmp_path):
    stub = tmp_path / "awaited_stub.py"
    stub.write_text(STUB_AWAITED)
    connector = synthetic.claude_code_connector(cli=(sys.executable, str(stub)), cwd=tmp_path)
    started = time.monotonic()
    answer, session = connector.dispatch("", "Launch an agent.")
    assert time.monotonic() - started >= 0.3 and (tmp_path / "started").exists()
    assert (answer, session) == ({"kind": "text", "text": "the agent reported"}, "session-9") and connector.live == {}


# Stub `claude` that honours the interrupt control request the way the CLI does: it records the request, answers it, closes the turn
# with an error result and exits once its stdin is closed. The deaf one ignores its stdin and sleeps with a child of its own.
STUB_COOPERATIVE = """
import json, os, sys
here = os.path.dirname(os.path.abspath(sys.argv[0]))
for line in sys.stdin:
    event = json.loads(line)
    if event["type"] == "control_request" and event["request"]["subtype"] == "interrupt":
        open(os.path.join(here, "interrupted"), "w").write(event["request_id"])
        print(json.dumps({"type": "control_response", "response": {"subtype": "success", "request_id": event["request_id"]}}), flush=True)
        print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": None, "session_id": "session-cut"}), flush=True)
sys.exit(1)
"""
STUB_DEAF = """
import os, subprocess, sys, time
here = os.path.dirname(os.path.abspath(sys.argv[0]))
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
open(os.path.join(here, "child"), "w").write(str(child.pid))
time.sleep(30)
"""


def _stopped_dispatch(connector, **kwargs):
    """The failure of a dispatch of `connector` run on its own thread and interrupted once its process is live."""
    failures = []

    def turn():
        try:
            connector.dispatch("", "Never answers.", **kwargs)
        except synthetic.connection_error as err:
            failures.append(str(err))

    thread = threading.Thread(target=turn)
    thread.start()
    assert _awaited(lambda: thread.ident in connector.live)
    connector.interrupt(thread.ident)
    thread.join(5)
    assert not thread.is_alive() and connector.live == {}
    return failures


@pytest.mark.syngate("CLAUDE_CODE-080", "interrupt")
def test_an_interrupted_turn_asks_its_process_to_interrupt_kills_a_deaf_one_with_its_group_and_fails_as_a_connection_error(tmp_path):
    cooperative = tmp_path / "cooperative_stub.py"
    cooperative.write_text(STUB_COOPERATIVE)
    connector = synthetic.claude_code_connector(cli=(sys.executable, str(cooperative)), cwd=tmp_path)
    assert _stopped_dispatch(connector) == ["claude exited with 1"]
    assert (tmp_path / "interrupted").read_text().startswith("stop-")

    deaf = tmp_path / "deaf_stub.py"
    deaf.write_text(STUB_DEAF)
    connector = synthetic.claude_code_connector(cli=(sys.executable, str(deaf)), cwd=tmp_path)
    connector.grace = 0.3
    started = time.monotonic()
    assert _stopped_dispatch(connector) == ["claude exited with -9"] and time.monotonic() - started >= 0.3
    child = int((tmp_path / "child").read_text())

    def gone():
        try:
            os.kill(child, 0)
            return False
        except ProcessLookupError:
            return True
    assert _awaited(gone)

    connector = synthetic.claude_code_connector(cli=(sys.executable, str(tmp_path / "no_such_stub.py")), cwd=tmp_path)
    with pytest.raises(synthetic.connection_error, match="turn stopped"):
        connector.dispatch("", "Stopped before I start.", stopped=lambda: True)


# Stub `claude` streaming the events of `events.json` next to it, one NDJSON line each: "await" holds the stream until a `go` file
# appears there, {"write"|"remove": path} changes a project file, then the result event closes the turn; its argv lands in `argv.json`.
STUB_STREAM = """
import json, os, sys, time
here = os.path.dirname(os.path.abspath(sys.argv[0]))
json.dump(sys.argv[1:], open(os.path.join(here, "argv.json"), "w"))
for event in json.load(open(os.path.join(here, "events.json"))):
    if event == "await":
        deadline = time.time() + 10
        while not os.path.exists(os.path.join(here, "go")) and time.time() < deadline:
            time.sleep(0.02)
        if not os.path.exists(os.path.join(here, "go")):
            sys.exit(3)
    elif "write" in event:
        os.makedirs(os.path.dirname(event["write"]) or ".", exist_ok=True)
        open(event["write"], "wb").write(event["text"].encode("latin-1"))
    elif "remove" in event:
        os.remove(event["remove"])
    else:
        print(json.dumps(event), flush=True)
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "Done.",
                  "structured_output": {"kind": "text", "text": "Done."}, "session_id": "session-s"}), flush=True)
"""


def _streaming(tmp_path, events, **kwargs):
    """A connector whose `claude` streams `events` in the project folder `tmp_path/project`."""
    (tmp_path / "events.json").write_text(json.dumps(events))
    (tmp_path / "claude_stub.py").write_text(STUB_STREAM)
    (tmp_path / "project").mkdir(exist_ok=True)
    return synthetic.claude_code_connector(cli=(sys.executable, str(tmp_path / "claude_stub.py")), cwd=tmp_path / "project",
                                           transcripts_dir=tmp_path / "transcripts", **kwargs)


def _said(*content, parent=None, role="assistant"):
    return {"type": role, "message": {"role": role, "content": list(content)}, "parent_tool_use_id": parent}


def _use(ident, name, **given):
    return {"type": "tool_use", "id": ident, "name": name, "input": given}


def _result(ident, content, parent=None):
    return _said({"type": "tool_result", "tool_use_id": ident, "content": content}, parent=parent, role="user")


def _without_at(steps):
    return [{**{key: value for key, value in step.items() if key not in ("at", "seconds")},
             **({"steps": _without_at(step["steps"])} if "steps" in step else {})} for step in steps]


def _announced(connector, text, go=None, **kwargs):
    """(answer, the top-level steps in order, a copy of every announcement) of one dispatch, every announcement touching `go`."""
    announced, steps = [], []

    def on_step(step):
        if go:
            go.touch()
        announced.append(json.loads(json.dumps(step)))
        if not any(step is known for known in steps):
            steps.append(step)
    answer, _ = connector.dispatch("", text, on_step=on_step, **kwargs)
    return answer, steps, announced


@pytest.mark.syngate("CLAUDE_CODE-090")
def test_a_turn_streams_its_messages_tool_calls_results_and_subagents_as_steps_when_they_happen(tmp_path):
    events = [_said({"type": "thinking", "thinking": "Let me look."}), "await",
              _said(_use("t1", "Read", file_path="README.md")), _result("t1", "readme text"),
              _said(_use("a1", "Agent", description="Check", prompt="@LEAF-001 check it\nthoroughly")),
              _said(_use("t2", "Grep", pattern="x"), parent="a1"), _result("t2", [{"type": "text", "text": "found"}], parent="a1"),
              _said({"type": "text", "text": "Found it."}, parent="a1"), _said({"type": "text", "text": "leaf checked"}, parent="a1"),
              _result("a1", [{"type": "text", "text": "leaf checked"}]),
              _said(_use("w1", "Workflow", script="run()")), _said(_use("t3", "Bash", command="ls"), parent="w1"), _result("t3", "inside", parent="w1"),
              _result("w1", "workflow done"),
              _said({"type": "text", "text": "Answering."}, _use("s1", "StructuredOutput", kind="text", text="Done.")), "not json"]
    answer, steps, announced = _announced(_streaming(tmp_path, events), "Go.", go=tmp_path / "go")
    assert answer == {"kind": "text", "text": "Done."}
    assert announced[0] == {"kind": "reasoning", "text": "Let me look.", "at": announced[0]["at"]}
    assert _without_at(steps) == [
        {"kind": "reasoning", "text": "Let me look."},
        {"kind": "tool", "name": "Read", "input": {"file_path": "README.md"}, "result": "readme text"},
        {"kind": "agent", "uid": "LEAF-001", "prompt": "@LEAF-001 check it\nthoroughly", "report": "leaf checked",
         "steps": [{"kind": "tool", "name": "Grep", "input": {"pattern": "x"}, "result": "found"}, {"kind": "message", "text": "Found it."}]},
        {"kind": "workflow", "input": {"script": "run()"}, "result": "workflow done"},
        {"kind": "message", "text": "Answering."}]
    assert all(isinstance(step["seconds"], float) and step["seconds"] >= 0 for step in (steps[1], steps[2]["steps"][0]))
    ats = [step["at"] for step in steps]
    assert ats == sorted(ats) and all(isinstance(at, float) for at in ats)
    launches = [step for step in announced if step["kind"] == "agent"]
    assert (launches[0]["prompt"], launches[0]["report"], launches[0]["steps"]) == ("@LEAF-001 check it\nthoroughly", None, [])
    assert launches[-1]["report"] == "leaf checked" and [step["kind"] for step in launches[-1]["steps"]] == ["tool", "message"]
    assert "leaf checked" in [step["text"] for launch in launches for step in launch["steps"] if step["kind"] == "message"]
    assert [step["result"] for step in announced if step["kind"] == "tool" and step["name"] == "Read"] == [None, "readme text"]
    _, steps, _ = _announced(_streaming(tmp_path, [_said(_use("a2", "Task", prompt="No anchor here\n@LATE-001 below"))]), "Go.")
    assert _without_at(steps) == [{"kind": "agent", "uid": None, "prompt": "No anchor here\n@LATE-001 below", "report": None, "steps": []}]



@pytest.mark.syngate("CLAUDE_CODE-100")
def test_reasoning_is_requested_through_the_effort_of_a_model_that_has_one_and_recorded_only_when_it_comes(tmp_path):
    connector = _streaming(tmp_path, [_said({"type": "thinking", "thinking": "Pondering."}), _said({"type": "thinking", "thinking": "", "signature": "x"})])
    _, steps, _ = _announced(connector, "Go.", model="claude-opus-5-5", effort="high")
    assert _without_at(steps) == [{"kind": "reasoning", "text": "Pondering."}]
    argv = lambda: json.loads((tmp_path / "argv.json").read_text())
    assert argv()[argv().index("--effort") + 1] == "high" and "--verbose" in argv()
    assert synthetic.CLAUDE_MODEL_EFFORTS["claude-haiku-4-5-20251001"] == ()
    connector.dispatch("", "Go.", model="claude-haiku-4-5-20251001", effort="high")
    assert "--effort" not in argv() and argv()[argv().index("--model") + 1] == "claude-haiku-4-5-20251001"
    connector.dispatch("", "Go.", effort="low")
    assert argv()[argv().index("--effort") + 1] == "low"
    _, steps, _ = _announced(_streaming(tmp_path, [_said({"type": "text", "text": "No thinking."})]), "Go.", model="claude-sonnet-5", effort="max")
    assert [step["kind"] for step in steps] == ["message"] and argv()[argv().index("--effort") + 1] == "max"


def _jsonl(path, *entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join((entry if isinstance(entry, str) else json.dumps(entry)) + "\n" for entry in entries))


@pytest.mark.syngate("CLAUDE_CODE-110")
def test_the_subagents_own_turns_are_read_from_the_session_transcript_once_the_turn_ends(tmp_path, monkeypatch):
    events = [_said(_use("a1", "Agent", prompt="@LEAF-002 Dig\ndeep")), _said({"type": "thinking", "thinking": "Digging."}, parent="a1"),
              _result("a1", "dug"), _said(_use("a2", "Task", prompt="Read the guide")), _result("a2", "read"),
              _said(_use("a3", "Agent", prompt="Untold")), _result("a3", "nothing kept")]
    connector = _streaming(tmp_path, events)
    stamp = "2026-10-10T10:00:00.000Z"
    sidechain = lambda agent, entry: {**entry, "isSidechain": True, "agentId": agent, "parentUuid": None, "timestamp": stamp}
    session = tmp_path / "transcripts" / "session-s"
    _jsonl(session / "subagents" / "agent-x1.jsonl",
           sidechain("x1", {"type": "user", "message": {"role": "user", "content": "@LEAF-002 Dig\ndeep"}}),
           sidechain("x1", {"type": "attachment", "attachment": {}}), "not json",
           sidechain("x1", _said({"type": "thinking", "thinking": "Digging."})), sidechain("x1", _said(_use("g1", "Grep", pattern="dig"))),
           sidechain("x1", _result("g1", "hit")), sidechain("x1", _said({"type": "text", "text": "dug"})))
    (session / "subagents" / "agent-x1.meta.json").write_text(json.dumps({"agentType": "general-purpose", "toolUseId": "a1"}))
    _jsonl(session.with_suffix(".jsonl"), {"type": "user", "message": {"role": "user", "content": "Go."}},
           sidechain("y2", {"type": "user", "message": {"role": "user", "content": "Read the guide"}}),
           sidechain("y2", _said(_use("r1", "Read", file_path="docs/GUIDE.md"))), sidechain("y2", _result("r1", "guide text")),
           sidechain("z9", {"type": "user", "message": {"role": "user", "content": "Somebody else's prompt"}}),
           sidechain("z9", _said(_use("r9", "Read", file_path="elsewhere"))))
    _, steps, announced = _announced(connector, "Go.")
    assert _without_at(steps) == [
        {"kind": "agent", "uid": "LEAF-002", "prompt": "@LEAF-002 Dig\ndeep", "report": "dug", "steps": [
            {"kind": "reasoning", "text": "Digging."}, {"kind": "tool", "name": "Grep", "input": {"pattern": "dig"}, "result": "hit"}]},
        {"kind": "agent", "uid": None, "prompt": "Read the guide", "report": "read", "steps": [
            {"kind": "tool", "name": "Read", "input": {"file_path": "docs/GUIDE.md"}, "result": "guide text"}]},
        {"kind": "agent", "uid": None, "prompt": "Untold", "report": "nothing kept", "steps": []}]
    assert all(isinstance(step["at"], float) for agent in steps for step in agent["steps"])
    assert _without_at(list({step["prompt"]: step for step in announced}.values())) == _without_at(steps)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert synthetic.claude_transcripts_dir("/home/me/my_project.d") == synthetic.Path.home() / ".claude" / "projects" / "-home-me-my-project-d"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
    assert synthetic.claude_transcripts_dir("/srv/app") == tmp_path / "config" / "projects" / "-srv-app"
    assert synthetic.claude_code_connector(cwd=tmp_path).transcripts_dir is None


@pytest.mark.syngate("CLAUDE_CODE-120")
def test_the_project_files_a_turn_changed_are_its_diff_step_from_snapshots_before_and_after(tmp_path):
    project = tmp_path / "project"
    for rel, text in (("keep.txt", "same\n"), ("edit.txt", "a\nb\nc\n"), ("gone.txt", "bye\n"), ("image.bin", "\0\1"),
                      (".cache/x", "hidden"), ("__pycache__/m.pyc", "old"), ("node_modules/z.js", "old")):
        (project / rel).parent.mkdir(parents=True, exist_ok=True)
        (project / rel).write_text(text)
    events = [{"write": "edit.txt", "text": "a\nB\nc\n"}, {"write": "src/new.txt", "text": "hello"}, {"remove": "gone.txt"},
              {"write": "image.bin", "text": "\0\2"}, {"write": ".cache/x", "text": "changed"}, {"write": "__pycache__/m.pyc", "text": "new"},
              {"write": "node_modules/z.js", "text": "new"}, _said(_use("e1", "Edit", file_path="edit.txt")), _result("e1", "ok")]
    _, steps, announced = _announced(_streaming(tmp_path, events), "Go.")
    assert [step["kind"] for step in steps] == ["tool", "diff"] and announced[-1] == steps[-1]
    assert steps[-1]["files"] == [{"path": "edit.txt", "status": "M", "hunks": "@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n"},
                                  {"path": "gone.txt", "status": "D", "hunks": "@@ -1 +0,0 @@\n-bye\n"},
                                  {"path": "image.bin", "status": "M", "hunks": ""},
                                  {"path": "src/new.txt", "status": "A", "hunks": "@@ -0,0 +1 @@\n+hello\n"}]
    _, steps, _ = _announced(_streaming(tmp_path, [_said({"type": "thinking", "thinking": "Nothing to change."})]), "Go.")
    assert [step["kind"] for step in steps] == ["reasoning"]
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    (project / ".gitignore").write_text("build/\n")
    _, steps, _ = _announced(_streaming(tmp_path, [{"write": "build/out.o", "text": "binary"}, {"write": "keep.txt", "text": "kept\n"}]), "Go.")
    assert [(file["path"], file["status"]) for file in steps[-1]["files"]] == [("keep.txt", "M")]
