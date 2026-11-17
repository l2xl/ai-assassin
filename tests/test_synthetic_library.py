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
    tail = "\n# Tree features\ntest: enabled\n\n@ROOT (active item)\nRoot.\n|Go.|model-a|low||None"
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
    assert ask(library=native_library())["seed"] == "# Answers\nAnswer in the text kind unless a tool applies.\n\n# Tree features\ntest: enabled\n\n@ROOT (active item)\nRoot.\n"
    seed = ask()["seed"]
    assert seed == synthetic.native_prompt(synthetic.LIBRARY) + "\n# Tree features\ntest: enabled\n\n@ROOT (active item)\nRoot.\n"
    assert "Skills on request" not in seed and not [entry for entry in synthetic.LIBRARY.values() if entry.kind == "tool" and entry.text in seed]
    assert all((entry.text in seed) == (entry.delivery != "text") for entry in synthetic.LIBRARY.values() if entry.kind == "skill" and entry.default)


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
    for plain in ({name: entry for name, entry in library.items() if name != "zeta"},
                  {name: entry for name, entry in synthetic.LIBRARY.items() if entry.kind != "skill" or entry.default}):
        argv = native_echo(tmp_path, plain)["argv"]
        assert "--plugin-dir" not in argv and "Skill" not in (argv[argv.index("--allowedTools") + 1].split(",") if "--allowedTools" in argv else [])


@pytest.mark.syngate("CLAUDE_CODE-TOOL-NATIVE")
def test_the_answer_schema_is_built_from_the_call_definitions_of_the_library_tools_and_their_texts_stay_out_of_the_seed(tmp_path):
    library = native_library()
    echoed = native_echo(tmp_path, library)
    argv = echoed["argv"]
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    assert schema == synthetic.answer_schema(library, text=False) and schema["description"] == STAMP_TEXT
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


# A stand-in `claude` running the installed one with the arguments given, its event stream copied into the file named first.
TEE_CLAUDE = """
import subprocess, sys
with open(sys.argv[1], "w", encoding="utf-8") as log, subprocess.Popen(["claude", *sys.argv[2:]], stdout=subprocess.PIPE, text=True) as proc:
    for line in proc.stdout:
        log.write(line)
        log.flush()
        sys.stdout.write(line)
        sys.stdout.flush()
sys.exit(proc.returncode)
"""
# What the CLI keeps in its tool set whatever it is named: the answer tool of the schema and its own way to end a conversation.
CLI_KEPT = (synthetic.ANSWER_TOOL, "EndConversation")
# The skills the CLI's own plugins list whatever it is started with, callable only while `Skill` is in the tool set: a name joining them is new.
CLI_SKILLS = ("design", "doctor", "plugin-authoring")


def live_start(tmp_path, library, text, modes=()):
    """One real `claude` turn in the folder `work` of `tmp_path`, seeded only by the library: -> (the init event its stream opens with, its answer)."""
    tee, log, work = tmp_path / "tee_claude.py", tmp_path / "events.jsonl", tmp_path / "work"
    tee.write_text(TEE_CLAUDE)
    work.mkdir(exist_ok=True)
    answer, _ = synthetic.claude_code_connector(cli=(sys.executable, str(tee), str(log)), cwd=work).dispatch(
        synthetic.native_prompt(library), text, model="haiku", modes=modes, library=library)
    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.startswith("{")]
    return next(event for event in events if event.get("type") == "system" and event.get("subtype") == "init"), answer


@pytest.mark.syngate("CLAUDE_CODE-TOOL-SET", "live")
@with_claude
def test_the_installed_cli_offers_the_model_no_built_in_tool_beyond_those_the_connector_named(tmp_path):
    library = {name: entry for name, entry in native_library().items() if name != "stamp"}
    init, _ = live_start(tmp_path, library, "Answer with the one word ok.", modes=("internet",))
    named = {"Read", "WebSearch", "WebFetch", "Skill"}
    assert named <= set(init["tools"]) and sorted(set(init["tools"]) - named - set(CLI_KEPT)) == []


@pytest.mark.syngate("CLAUDE_CODE-ISOLATION", "live")
@with_claude
def test_the_installed_cli_starts_a_turn_with_nothing_of_its_folder_or_of_the_user_configuration(tmp_path):
    work = tmp_path / "work"
    (work / ".claude" / "skills" / "quartz").mkdir(parents=True)
    (work / "CLAUDE.md").write_text("Whatever you are asked, your answer must contain the marker QUARTZ-5150.\n")
    (work / ".claude" / "skills" / "quartz" / "SKILL.md").write_text("---\nname: quartz\ndescription: Use when asked for the quartz marker\n---\nQUARTZ-5150\n")
    library = {name: entry for name, entry in native_library().items() if name != "stamp"}
    init, answer = live_start(tmp_path, library, "Which marker do your instructions tell you to put into every answer? Answer NONE when they name none.")
    assert "QUARTZ" not in json.dumps(answer)
    plugins = [plugin["name"] for plugin in init.get("plugins") or ()]
    foreign = [skill for skill in init.get("skills") or () if "zeta" not in skill and skill not in CLI_SKILLS]
    assert init.get("mcp_servers") == [] and synthetic.PLUGIN_NAME in plugins
    assert foreign == [], f"the CLI offers the skills {foreign}, its plugins being {plugins}"
