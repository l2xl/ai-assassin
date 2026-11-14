# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""ORCHESTRATOR-SETUP: the `assassin-setup` command writing the model services a project starts with into the server settings --
the card, docker, the servers, the claude CLI and the connections' model listings all scripted, none of them run."""

import json
from pathlib import Path

import pytest

from ai_scratcher import assassin_setup, assassin_ui, local_models, services

CLAUDE = {"connection": "claude_code", "model": "haiku"}
CUDA = {"embed": {"connection": "cuda-4gb-embed", "model": "bge-m3"}, "rerank": {"connection": "cuda-4gb-rerank", "model": "bge-reranker-v2-m3"}}


class Machine:
    """A scripted workstation: the card's memory (None for no card), the claude CLI at hand or not, how `compose up` ends, the calls made."""

    def __init__(self, memory=4096, claude=True, up=(0, "")):
        self.memory, self.claude, self.up_result, self.calls, self.said = memory, claude, up, [], []

    def sh(self, argv):
        self.calls.append(argv)
        if argv[0] == "nvidia-smi":
            return (0, str(self.memory)) if self.memory else (127, "nvidia-smi: command not found")
        words = argv[argv.index("compose"):] if "compose" in argv else argv
        if "version" in words:
            return 0, "29.0"
        if "up" in words:
            return self.up_result
        if "logs" in words:
            return 0, "embed-1  | error: model file is corrupt"
        raise AssertionError(argv)

    def fetch(self, url, body=None, timeout=5):
        return {"data": [{"embedding": [0.1]}], "results": [{"index": 0}], "choices": [{}]}

    def which(self, command):
        return "/usr/bin/claude" if self.claude and command == "claude" else None

    def served(self):
        return [argv for argv in self.calls if "compose" in argv and "up" in argv]

    def run(self, root, **given):
        return assassin_setup.run(root, say=self.said.append, sh=self.sh, fetch=self.fetch, which=self.which, **given)


def settings_of(root, held=None):
    """The server settings file of `root`, written with `held` first when one is given; its content as read."""
    file = Path(root) / assassin_setup.SETTINGS_FILE
    if held is not None:
        file.write_text(json.dumps(held))
    return json.loads(file.read_text())


def folder(root, name):
    """A new empty project folder `name` under `root`."""
    (root / name).mkdir()
    return root / name


@pytest.mark.syngate("ORCHESTRATOR-SETUP-CLAUDE")
def test_agents_go_to_the_claude_code_connection_haiku_while_the_cli_is_installed(tmp_path):
    settings_of(tmp_path, {"connections": {"mix": {"base_url": "http://x/v1", "models": ["big"]}}, "orchestrator": CUDA})
    machine = Machine()
    report = machine.run(tmp_path)
    assert settings_of(tmp_path)["orchestrator"]["agents"] == {"default": CLAUDE, "scan": CLAUDE}  # the API connection is there and ignored
    assert report["wrote"] == ["orchestrator.agents.default", "orchestrator.agents.scan"] and report["unrouted"] == []
    assert not machine.served()  # both roles already routed: no preset is served for them


@pytest.mark.syngate("ORCHESTRATOR-SETUP-API")
def test_agents_go_to_the_first_connection_offering_a_chat_model_without_the_cli(tmp_path):
    settings_of(tmp_path, {"orchestrator": CUDA, "connections": {
        "emb": {"base_url": "http://x/v1", "models": ["bge-m3"], "serves": "embedding"}, "empty": {"models": []},
        "mix": {"base_url": "http://x/v1", "models": [{"id": "big", "name": "Big"}, "small"]}, "other": {"models": ["later"]}}})
    report = Machine(claude=False).run(tmp_path)
    assert settings_of(tmp_path)["orchestrator"]["agents"] == {"default": {"connection": "mix", "model": "big"}}
    assert report["wrote"] == ["orchestrator.agents.default"] and report["unrouted"] == []

    queried = folder(tmp_path, "queried")  # a connection listing its models by query is asked, its first listed model taken
    settings_of(queried, {"orchestrator": CUDA, "connections": {"local": {"base_url": "http://x/v1", "models": "query"}}})
    Machine(claude=False).run(queried, listing=lambda name, entry: ["first-served", "second"] if name == "local" else [])
    assert settings_of(queried)["orchestrator"]["agents"]["default"] == {"connection": "local", "model": "first-served"}


@pytest.mark.syngate("ORCHESTRATOR-SETUP-HARDWARE")
def test_the_preset_fitting_the_card_is_served_and_routes_embed_and_rerank(tmp_path):
    machine = Machine(memory=4096)
    report = machine.run(tmp_path)
    assert len(machine.served()) == 1 and "assassin-cuda-4gb" in machine.served()[0]
    written = settings_of(tmp_path)
    assert written["orchestrator"]["embed"] == CUDA["embed"] and written["orchestrator"]["rerank"] == CUDA["rerank"]
    assert written["connections"]["cuda-4gb-embed"]["serves"] == "embedding" and written["connections"]["cuda-4gb-rerank"]["serves"] == "reranking"
    assert report["unrouted"] == [] and "orchestrator.embed" in report["wrote"] and "connections.cuda-4gb-rerank" in report["wrote"]
    assert any("cuda-4gb/embed" in line for line in machine.said)

    small, machine = folder(tmp_path, "small"), Machine(memory=1024)  # no shipped preset fits a card this small
    report = machine.run(small)
    assert not machine.served() and "no shipped preset fits a card of 1024 MiB" in dict(report["unrouted"])["embed"]

    assert "nvidia-smi" in dict(Machine(memory=None).run(folder(tmp_path, "bare"))["unrouted"])["rerank"]  # no card: reported, nothing served

    broken = folder(tmp_path, "broken")
    report = Machine(up=(1, "container assassin-cuda-4gb-embed-1 is unhealthy")).run(broken)
    assert "did not come up" in dict(report["unrouted"])["embed"] and "embed" not in settings_of(broken)["orchestrator"]
    assert settings_of(broken)["orchestrator"]["agents"]["default"] == CLAUDE  # a failed preset does not stop the agents' routes


@pytest.mark.syngate("ORCHESTRATOR-SETUP-KEEP")
def test_held_settings_are_never_overwritten_and_unrouted_roles_are_reported(tmp_path, monkeypatch, capsys):
    held = {"theme": "dark", "connections": {"mine": {"base_url": "http://mine/v1", "models": ["m"]}},
            "orchestrator": {"embed": {"connection": "mine", "model": "own-embed"}, "agents": {"default": {"connection": "mine", "model": "m", "effort": "low"}}}}
    settings_of(tmp_path, held)
    machine = Machine(memory=None)
    report = machine.run(tmp_path)
    written = settings_of(tmp_path)
    assert written["theme"] == "dark" and written["connections"] == held["connections"]
    assert written["orchestrator"]["embed"] == held["orchestrator"]["embed"] and written["orchestrator"]["agents"]["default"] == held["orchestrator"]["agents"]["default"]
    assert written["orchestrator"]["agents"]["scan"] == CLAUDE  # what was missing is added beside what is held
    assert report["wrote"] == ["orchestrator.agents.scan"] and [role for role, _ in report["unrouted"]] == ["rerank"]

    again = machine.run(tmp_path)  # a second run changes nothing
    assert again["wrote"] == [] and settings_of(tmp_path) == written

    # no CLI and no chat connection: the agents are reported too, and nothing is written
    nothing = folder(tmp_path, "nothing")
    report = Machine(memory=None, claude=False).run(nothing)
    assert [role for role, _ in report["unrouted"]] == ["embed", "rerank", "agents.default"] and report["wrote"] == []
    assert not (nothing / assassin_setup.SETTINGS_FILE).exists()

    hand = nothing / assassin_setup.SETTINGS_FILE  # a file that is no JSON object is left as the user wrote it
    hand.write_text("[1, 2]")
    with pytest.raises(local_models.setup_error, match="not a JSON object"):
        Machine().run(nothing)
    assert hand.read_text() == "[1, 2]"

    # the command itself: its entry point, the settings file the server reads, and the report of what it wrote and could not route
    assert 'assassin-setup = "ai_scratcher.assassin_setup:main"' in (Path(__file__).parent.parent / "pyproject.toml").read_text()
    assert assassin_setup.SETTINGS_FILE == assassin_ui.SETTINGS_FILE
    fresh, real = folder(tmp_path, "fresh"), assassin_setup.run
    monkeypatch.setattr(assassin_setup, "run", lambda root, **given: real(root, say=machine.said.append, sh=machine.sh, fetch=machine.fetch, which=machine.which, **given))
    assert assassin_setup.main(["--root", str(fresh)]) == 1  # the embedding and rerank roles stay unrouted: no card
    out = capsys.readouterr().out
    assert "wrote: orchestrator.agents.default, orchestrator.agents.scan" in out and "could not route embed: " in out and "could not route rerank: " in out
    assert services.locator_of(settings_of(fresh)["orchestrator"]["agents"]["default"]) == CLAUDE
