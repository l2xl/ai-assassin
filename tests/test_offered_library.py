# Open Trader
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Offered library (SYNTHETIC-PROMPTS-OFFER): the prompts a chat is offered by their requirements, the alternatives of one feature and
the probes kept for a server's run."""

import json
import shutil
import sys

import pytest

import assassin_ui
import syngatelib
import synthetic
from test_synthetic import EchoAnswer

PY = sys.executable
MET, UNMET = [{"command": [PY, "-c", "print('ok')"]}], [{"command": [PY, "-c", "print('no')"], "output": "yes"}]


def _says(text):
    return [PY, "-c", f"print({text!r})"]


def _prompt(folder, name, kind="tool", requires=None, feature=None, rank=None, extra=""):
    """Write one prompt of `kind` named `name`, its front matter carrying what is given, its text `The <name> text.`"""
    lines = [f"kind: {kind}", f"description: The {name}", *([f"feature: {feature}"] if feature else []), *([f"rank: {rank}"] if rank is not None else []),
             *([f"requires: {json.dumps(requires)}"] if requires is not None else []), *([extra] if extra else [])]
    (folder / f"{name}.md").write_text("---\n" + "\n".join(lines) + f"\n---\n# {name}\nThe {name} text.\n", encoding="utf-8")


@pytest.mark.syngate("SYNTHETIC-PROMPTS-OFFER-REQUIRES")
def test_a_prompt_is_offered_only_while_every_command_it_requires_exits_0_in_the_project_root_printing_the_output_it_names(tmp_path, monkeypatch):
    monkeypatch.setattr(synthetic, "PROBE_TIMEOUT", 1)
    prompts, project = tmp_path / "prompts", tmp_path / "project"
    prompts.mkdir()
    project.mkdir()
    here = {"command": [PY, "-c", "import os; print(os.getcwd())"], "output": str(project.resolve())}
    _prompt(prompts, "free")
    _prompt(prompts, "rooted", requires=[here])
    _prompt(prompts, "exits", requires=[{"command": _says("anything")}])
    _prompt(prompts, "stderr", requires=[{"command": [PY, "-c", "import sys; sys.stderr.write('ready')"], "output": "ready"}])
    _prompt(prompts, "deaf", requires=[{"command": [PY, "-c", "import sys; print(sys.stdin.read() == '')"], "output": "True"}])  # no stdin to wait on
    _prompt(prompts, "silent", requires=[{"command": _says("other"), "output": "ready"}])
    _prompt(prompts, "failing", requires=[{"command": [PY, "-c", "import sys; print('ready'); sys.exit(3)"], "output": "ready"}])
    _prompt(prompts, "missing", requires=[{"command": ["no-such-program-anywhere", "--version"]}])
    _prompt(prompts, "shell", requires=[{"command": ["echo ready"], "output": "ready"}])  # no shell: a command line is no program
    _prompt(prompts, "slow", requires=[{"command": [PY, "-c", "import time; time.sleep(5)"]}])
    _prompt(prompts, "malformed", requires=["rg --version"])
    _prompt(prompts, "unnamed", requires=[{"output": "ready"}])
    _prompt(prompts, "both", requires=[*MET, *UNMET])
    library = synthetic.load_prompts(prompts)
    offered = synthetic.offered_library(project, library)
    assert sorted(offered) == ["deaf", "exits", "free", "rooted", "stderr"]
    assert offered["rooted"] == library["rooted"] and library["rooted"].requires == (here,) and len(library) == 13  # the library itself stays whole


@pytest.mark.syngate("SYNTHETIC-PROMPTS-OFFER-FEATURE")
def test_of_the_prompts_of_one_feature_only_the_first_by_rank_whose_requirements_are_met_is_offered(tmp_path):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    _prompt(prompts, "search_a", feature="search", rank=1, requires=UNMET)
    _prompt(prompts, "search_b", feature="search", rank=2, requires=MET)
    _prompt(prompts, "search_c", feature="search", rank=3)
    _prompt(prompts, "order_a", feature="order")
    _prompt(prompts, "order_z", feature="order", rank=9)  # a ranked one before every unranked
    _prompt(prompts, "view_b", feature="view")
    _prompt(prompts, "view_a", feature="view")  # unranked ones by name
    _prompt(prompts, "tie_z", feature="tie", rank=5)
    _prompt(prompts, "tie_y", feature="tie", rank=5)  # rank ties by name
    _prompt(prompts, "gone_a", feature="gone", rank=1, requires=UNMET)
    _prompt(prompts, "gone_b", feature="gone", requires=UNMET)  # none met: the feature is absent
    _prompt(prompts, "own", requires=MET)
    _prompt(prompts, "alone")
    library = synthetic.load_prompts(prompts)
    assert (library["search_b"].feature, library["search_b"].rank, library["view_a"].rank) == ("search", 2, None)
    assert sorted(synthetic.offered_library(tmp_path, library)) == ["alone", "order_z", "own", "search_b", "tie_y", "view_a"]


@pytest.mark.syngate("SYNTHETIC-PROMPTS-OFFER-PROBE")
def test_each_requirement_is_probed_once_in_a_servers_run_at_its_first_need_while_the_prompt_files_stay_live(tmp_path):
    prompts, counter, flag = tmp_path / "prompts", tmp_path / "probed.txt", tmp_path / "installed"
    prompts.mkdir()
    flag.touch()
    counting = [PY, "-c", f"import os; open({str(counter)!r}, 'a').write('x'); print('ok' if os.path.exists({str(flag)!r}) else 'no')"]
    _prompt(prompts, "first", requires=[{"command": counting, "output": "ok"}])
    _prompt(prompts, "twin", requires=[{"command": counting, "output": "ok"}])  # the same command and output: one probe
    _prompt(prompts, "other", requires=[{"command": counting}])  # the same command without output: a requirement of its own
    library = synthetic.live_mapping(lambda: synthetic.load_prompts(prompts))
    offered = synthetic.offered_library(tmp_path, library)
    assert not counter.exists()  # nothing probed ahead of its need
    assert sorted(offered) == ["first", "other", "twin"] and counter.read_text() == "xx"
    flag.unlink()  # the program gone while the server runs: its kept outcome stands
    _prompt(prompts, "added")
    (prompts / "twin.md").unlink()
    assert sorted(offered) == ["added", "first", "other"] and "first" in offered and counter.read_text() == "xx"
    assert sorted(synthetic.offered_library(tmp_path, library)) == ["added", "other"] and counter.read_text() == "xxxx"  # a new run probes anew


@pytest.mark.syngate("SYNTHETIC-PROMPTS-OFFER-CHAT")
def test_a_chat_is_built_from_the_offered_library_while_the_shipped_library_stays_whole(tmp_path, syngate_tree, monkeypatch):
    prompts = tmp_path / "prompts"
    shutil.copytree(synthetic.PROMPTS_DIR, prompts)
    _prompt(prompts, "rules", kind="skill", extra="default: true")
    _prompt(prompts, "hidden_rules", kind="skill", requires=UNMET, extra="default: true")
    _prompt(prompts, "brief", kind="skill")
    _prompt(prompts, "secret", kind="skill", requires=UNMET)
    _prompt(prompts, "echo", extra="calls: {echo: {required: [text]}}")
    _prompt(prompts, "blocked", requires=UNMET, extra="calls: {blocked: {required: [text]}}")
    _prompt(prompts, "helper", kind="agent", extra="tools: [echo, blocked]\nskills: [brief, secret]")
    _prompt(prompts, "stranger", kind="agent", requires=UNMET, extra="tools: [echo]")
    monkeypatch.setattr(synthetic, "PROMPTS_DIR", prompts)
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root.\n", parents=())
    app = assassin_ui.AssassinApp(root=tmp_path, syngate_dir=syngate_dir)
    left_out = {"hidden_rules", "secret", "blocked", "stranger"}
    assert left_out <= set(synthetic.LIBRARY) and not left_out & set(app.library) and {"rules", "brief", "echo", "helper"} <= set(app.library)
    app.connectors = {"echo": EchoAnswer()}
    reply = app.chat({"uid": "ROOT", "connector": "echo", "model": "model-a", "effort": "low", "modes": ["tree"], "text": "Go."})["reply"]
    assert "The rules text." in reply and "`brief`: The brief" in reply and "The echo text." in reply
    assert not any(text in reply for text in ("The hidden_rules text.", "`secret`", "The blocked text."))
    tools = [shape["properties"]["tool"]["const"] for shape in synthetic.answer_schema(app.library)["properties"]["calls"]["items"]["anyOf"]]
    assert "echo" in tools and "blocked" not in tools
    assert synthetic.apply_call({}, "ROOT", {"tool": "skill", "name": "brief"}, library=app.library) == "- skill brief:\n# brief\nThe brief text.\n"
    with pytest.raises(syngatelib.tree_error, match="unknown skill 'secret'"):
        synthetic.apply_call({}, "ROOT", {"tool": "skill", "name": "secret"}, library=app.library)
    agents = synthetic.load_agents(app.library)
    defaults = lambda library: [name for name, entry in library.items() if entry.kind == "tool" and entry.default]  # the default tools every agent has
    assert "stranger" not in agents and list(synthetic.agent_library(agents["helper"], app.library)) == ["brief", "echo", *defaults(app.library)]
    assert list(synthetic.agent_library(synthetic.load_agents()["helper"])) == ["brief", "secret", "echo", "blocked", *defaults(synthetic.LIBRARY)]


@pytest.mark.syngate("SYNTHETIC-PROMPTS-OFFER-DEFAULT")
def test_a_default_tool_enters_every_chat_and_every_agent_but_a_verdict_one_while_its_requirements_are_met_and_none_while_not(tmp_path):
    shipped = synthetic.LIBRARY
    assert {name for name, entry in shipped.items() if entry.kind == "tool" and entry.default} == {"grep_rg", "grep_gnu", "grep_git"}
    assert all(shipped[name].feature == "grep" and shipped[name].requires for name in ("grep_rg", "grep_gnu", "grep_git"))
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    _prompt(prompts, "look", requires=MET, extra="default: true\ncalls: {look: {required: [text]}}")
    _prompt(prompts, "peek", requires=UNMET, extra="default: true\ncalls: {peek: {required: [text]}}")
    _prompt(prompts, "worker", kind="agent")
    _prompt(prompts, "lister", kind="agent", extra="tools: [peek]")
    _prompt(prompts, "judge", kind="agent", extra="schema: {type: object, properties: {fair: {type: boolean}}, required: [fair]}")
    offered = synthetic.offered_library(tmp_path, synthetic.load_prompts(prompts))
    chat = synthetic.default_prompt(offered)
    assert "The look text." in chat and "The peek text." not in chat and set(synthetic.library_calls(offered)) == {"look"}
    agents = synthetic.load_agents(offered)
    for name in ("worker", "lister"):  # listed or not, the met one enters and the unmet one does not
        prompt = synthetic.agent_prompt(agents[name], offered)
        assert synthetic.agent_calls(agents[name], offered) == {"look": ("text",)} and "The look text." in prompt and "The peek text." not in prompt
    assert synthetic.agent_prompt(agents["judge"], offered) == agents["judge"].text and synthetic.agent_library(agents["judge"], offered) == {}
