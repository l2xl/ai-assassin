# Open Trader
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Native delivery of the prompt library: skills and tools reach the AI connection through its own configuration, not as seed text."""

import json
import shutil
import sys

import pytest
import yaml

import synthetic
import syngatelib
from test_synthetic import EchoConnection

# Stub `claude` echoing what the CLI is handed: argv, the seed file and the files of the plugin folder as they are while the turn runs.
STUB_NATIVE = """
import json, os, sys
argv, prompt = sys.argv[1:], json.loads(sys.stdin.readline())["message"]["content"]
seed = open(argv[argv.index("--append-system-prompt-file") + 1], encoding="utf-8").read()
plugin = {}
if "--plugin-dir" in argv:
    root = argv[argv.index("--plugin-dir") + 1]
    for folder, _, names in os.walk(root):
        for name in names:
            plugin[os.path.relpath(os.path.join(folder, name), root)] = open(os.path.join(folder, name), encoding="utf-8").read()
print(json.dumps({"type": "result", "result": json.dumps({"argv": argv, "seed": seed, "plugin": plugin}), "session_id": "session-9", "is_error": False}))
"""

STAMP_CALLS = {"stamp": {"required": ["serial"], "optional": {"urgent": {"type": "boolean"}}}}
STAMP_TEXT = '# Stamp\n`{"tool": "stamp", "serial": "…"}` stamps a serial number onto the ledger.\n'


def native_library():
    """A prompt library handed through the interface alone: a default skill, a skill on request with a quoted description and a tool."""
    return {"answers": synthetic.prompt("answers", "skill", "Answer format", True, "# Answers\nAnswer in the text kind unless a tool applies.\n"),
            "zeta": synthetic.prompt("zeta", "skill", 'Use when asked: "the zeta marker"', False,
                                     "# Zeta\nAnswer with exactly the marker ZETA-4711 and nothing else.\n"),
            "stamp": synthetic.prompt("stamp", "tool", "Stamp a serial", False, STAMP_TEXT, STAMP_CALLS)}


def native_echo(tmp_path, library):
    stub = tmp_path / "claude_native_stub.py"
    stub.write_text(STUB_NATIVE)
    connector = synthetic.claude_code_connector(cli=(sys.executable, str(stub)), cwd=tmp_path)
    return json.loads(connector.dispatch(synthetic.native_prompt(library), "Go.", library=library)[0])


class NativeEcho(EchoConnection):
    library_delivery = "native"

    def dispatch(self, context, text, library=None, **kwargs):
        reply, session = super().dispatch(context, text, **kwargs)
        return f"{reply}|{sorted(library)}", session


@pytest.mark.syngate("AI_CONNECTION-LIBRARY")
def test_a_connection_declares_text_or_native_library_delivery_and_a_native_one_is_dispatched_the_library(syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root.\n", parents=())
    items, _ = syngatelib.load_tree(syngate_dir)
    library = native_library()
    asked = lambda connection, **kwargs: synthetic.query({"c": connection}, items, "ROOT", "Go.", "c", "model-a", "low", **kwargs)[0]
    tail = "\n# Tree features\ntest: enabled\n\n@ROOT\nRoot.\n|Go.|model-a|low||None"
    assert asked(EchoConnection(), library=library) == synthetic.default_prompt(library) + tail
    assert asked(EchoConnection()) == synthetic.PROMPTS[synthetic.DEFAULT_PROMPT] + tail
    assert asked(NativeEcho(), library=library) == synthetic.native_prompt(library) + tail + "|['answers', 'stamp', 'zeta']"
    assert asked(NativeEcho()) == synthetic.native_prompt(synthetic.LIBRARY) + tail + f"|{sorted(synthetic.LIBRARY)}"
    assert synthetic.claude_code_connector().settings()["library"] == "native"


@pytest.mark.syngate("CLAUDE_CODE-LIBRARY-NATIVE")
def test_the_claude_connector_takes_the_library_natively_so_its_seed_prompt_holds_the_default_skills_only(tmp_path, syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root.\n", parents=())
    items, _ = syngatelib.load_tree(syngate_dir)
    assert synthetic.claude_code_connector.library_delivery == "native"
    stub = tmp_path / "claude_native_stub.py"
    stub.write_text(STUB_NATIVE)
    connectors = {"claude_code": synthetic.claude_code_connector(cli=(sys.executable, str(stub)), cwd=tmp_path)}
    ask = lambda **kwargs: json.loads(synthetic.query(connectors, items, "ROOT", "Go.", "claude_code", "sonnet", "low", **kwargs)[0])
    assert ask(library=native_library())["seed"] == "# Answers\nAnswer in the text kind unless a tool applies.\n\n# Tree features\ntest: enabled\n\n@ROOT\nRoot.\n"
    seed = ask()["seed"]
    assert seed == synthetic.native_prompt(synthetic.LIBRARY) + "\n# Tree features\ntest: enabled\n\n@ROOT\nRoot.\n"
    assert "Skills on request" not in seed and not [entry for entry in synthetic.LIBRARY.values() if entry.kind == "tool" and entry.text in seed]
    assert all(entry.text in seed for entry in synthetic.LIBRARY.values() if entry.kind == "skill" and entry.default)


@pytest.mark.syngate("CLAUDE_CODE-SKILL-NATIVE")
def test_a_skill_on_request_reaches_the_cli_as_a_skill_of_a_plugin_folder_and_stays_out_of_the_seed(tmp_path):
    library = native_library()
    echoed = native_echo(tmp_path, library)
    assert sorted(echoed["plugin"]) == [".claude-plugin/plugin.json", "skills/zeta/SKILL.md"]
    assert json.loads(echoed["plugin"][".claude-plugin/plugin.json"])["name"] == synthetic.PLUGIN_NAME
    skill = echoed["plugin"]["skills/zeta/SKILL.md"]
    front = yaml.safe_load(synthetic.FRONT_MATTER_RE.match(skill).group(1))
    assert front == {"name": "zeta", "description": 'Use when asked: "the zeta marker"'} and skill.endswith("---\n" + library["zeta"].text)
    assert "ZETA-4711" not in echoed["seed"]
    argv = echoed["argv"]
    assert argv[argv.index("--plugin-dir") + 1] and "Skill" in argv[argv.index("--allowedTools") + 1].split(",")
    for plain in ({name: entry for name, entry in library.items() if name != "zeta"}, synthetic.LIBRARY):
        argv = native_echo(tmp_path, plain)["argv"]
        assert "--plugin-dir" not in argv and "Skill" not in argv[argv.index("--allowedTools") + 1].split(",")


@pytest.mark.syngate("CLAUDE_CODE-TOOL-NATIVE")
def test_the_answer_schema_is_built_from_the_call_definitions_of_the_library_tools_and_their_texts_stay_out_of_the_seed(tmp_path):
    library = native_library()
    echoed = native_echo(tmp_path, library)
    argv = echoed["argv"]
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    assert schema == synthetic.answer_schema(library) and schema["description"] == STAMP_TEXT
    assert schema["properties"]["calls"]["items"]["anyOf"] == [
        {"type": "object", "properties": {"tool": {"const": "stamp"}, "serial": {"type": "string"}, "urgent": {"type": "boolean"}},
         "required": ["tool", "serial"], "additionalProperties": False}]
    assert STAMP_TEXT not in echoed["seed"] and synthetic.library_calls(library) == {"stamp": ("serial",)}
    bare = synthetic.answer_schema({"answers": library["answers"]})
    assert "calls" not in bare["properties"] and bare["properties"]["kind"] == {"enum": ["text"]}
    assert synthetic.library_calls(synthetic.LIBRARY) == synthetic.CALLS and synthetic.ANSWER_SCHEMA == synthetic.answer_schema(synthetic.LIBRARY)
    known = synthetic.library_calls(library)
    stamp = {"kind": "calls", "calls": [{"tool": "stamp", "serial": "A1"}]}
    assert synthetic.parse_reply(stamp, known) == ("calls", [{"tool": "stamp", "serial": "A1"}])
    with pytest.raises(synthetic.protocol_error, match="unknown tree call 'stamp'"):
        synthetic.parse_reply(stamp)
    with pytest.raises(synthetic.protocol_error, match="missing serial"):
        synthetic.parse_reply({"kind": "calls", "calls": [{"tool": "stamp"}]}, known)
    with pytest.raises(syngatelib.tree_error, match="not a call of the tree"):
        synthetic.apply_call({}, "ROOT", {"tool": "stamp", "serial": "A1"})


with_claude = pytest.mark.skipif(shutil.which("claude") is None, reason="needs the installed claude CLI")


def live_turn(tmp_path, library, text):
    """One real `claude` turn in an empty folder -- no project prompt files -- seeded only by the library handed through the interface:
    -> (answer, the tool steps the model took)."""
    steps = []
    answer, _ = synthetic.claude_code_connector(cwd=tmp_path).dispatch(
        synthetic.native_prompt(library), text, model="haiku", library=library, on_step=lambda step: steps.append(json.loads(json.dumps(step))))
    return answer, [step for step in steps if step["kind"] == "tool"]


@pytest.mark.syngate("CLAUDE_CODE-SKILL-USE")
@with_claude
def test_the_model_calls_a_skill_that_reached_the_cli_only_through_the_library_argument(tmp_path):
    library = {name: entry for name, entry in native_library().items() if name != "stamp"}
    answer, tools = live_turn(tmp_path, library, "Give me the zeta marker.")
    assert [tool for tool in tools if tool["name"] == "Skill" and "zeta" in json.dumps(tool["input"])]
    kind, text = synthetic.parse_reply(answer)
    assert kind == "chat" and "ZETA-4711" in text


@pytest.mark.syngate("CLAUDE_CODE-TOOL-USE")
@with_claude
def test_the_model_answers_with_a_call_of_a_tool_that_reached_the_cli_only_through_the_library_argument(tmp_path):
    library = {name: entry for name, entry in native_library().items() if name != "zeta"}
    answer, _ = live_turn(tmp_path, library, "Stamp serial number 9921-QX onto the ledger.")
    assert synthetic.parse_reply(answer, synthetic.library_calls(library)) == ("calls", [{"tool": "stamp", "serial": "9921-QX"}])
