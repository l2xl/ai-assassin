# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The shell tool of the AI and the Raw command switch that gates it: a shell call of a turn refused while the switch is off, run in the
project root with it on, its exit status and output coming back as the next prompt, and a command naming the tree refused."""

import pytest

import assassin_ui
import synthetic
from test_assassin_ui import app, server  # noqa: F401 -- the server fixtures of the page tests
from test_assassin_ui_api import Scripted, calls, turn


class Shelled(Scripted):
    """A scripted connection listing the Raw command mode, as an API connection does."""
    modes = ("bash",)

    def settings(self):
        return {**super().settings(), "modes": [dict(synthetic.BASH_MODE)]}


@pytest.mark.syngate("OPEN-AI-API-BASH-MODE")
def test_the_raw_command_switch_gates_the_shell_calls_of_a_turn_run_in_the_project_root(server):
    base, app = server
    shell = {"tool": "shell", "command": "pwd -P; exit 3"}
    app.connectors = {"echo": (scripted := Shelled(calls(shell), {"kind": "text", "text": "Could not."}, calls(shell), {"kind": "text", "text": "Ran."},
                                                    calls({"tool": "shell", "command": "ls syngate"}), {"kind": "text", "text": "Closed."}))}
    from test_recommend_turn import answering
    answering(app, "ROOT", "deny")  # the held call is denied by the user
    outcome = turn(base, app, "ROOT", "Run it.", modes=["tree"])
    assert (outcome["applied"], outcome["reply"]) == ([f"- shell pwd -P; exit 3 refused: {assassin_ui.SHELL_REFUSAL}"], "Could not.")
    assert scripted.heard[0]["modes"] == []
    outcome = turn(base, app, "ROOT", "Run it.", modes=["tree", "bash"])
    ran = f"- shell pwd -P; exit 3:\nexit 3\n{app.root.resolve()}"
    assert scripted.heard[2]["modes"] == ["bash"]  # the mode reaches the connection that lists it
    assert scripted.heard[3]["text"] == synthetic.RESULTS_PREAMBLE + ran  # exit status and output come back as the next prompt
    assert (outcome["applied"], outcome["reply"]) == ([ran], "Ran.")
    outcome = turn(base, app, "ROOT", "List the items.", modes=["tree", "bash"])
    assert (outcome["applied"], outcome["reply"]) == ([f"- shell ls syngate refused: {assassin_ui.SHELL_TREE}"], "Closed.")
    assert [mode["id"] for mode in app.build_model()["connectors"]["echo"]["modes"]] == ["tree", "patch", "bash"]


@pytest.mark.syngate("SYNTHETIC-TOOL-SHELL-RUN")
def test_a_shell_run_has_no_stdin_a_time_limit_and_its_output_cut(server, monkeypatch):
    _, app = server
    assert app._shell({"tool": "shell", "command": "cat; echo done"}) == "- shell cat; echo done:\nexit 0\ndone"  # stdin is empty, nothing waits
    monkeypatch.setattr(assassin_ui, "SHELL_LIMIT", 5)
    assert app._shell({"tool": "shell", "command": "echo 123456789"}) == "- shell echo 123456789:\nexit 0\n12345\n… cut at 5 characters"
    monkeypatch.setattr(assassin_ui, "SHELL_TIMEOUT", 0.2)
    assert app._shell({"tool": "shell", "command": "sleep 5"}) == "- shell sleep 5:\ntimed out after 0.2 s"


@pytest.mark.syngate("SYNTHETIC-TOOL-SHELL-TREE")
def test_a_shell_command_naming_the_tree_is_refused(server):
    _, app = server
    for command in ("cat syngate/ROOT.yml", "ls ./syngate", "syngate query ROOT"):
        with pytest.raises(assassin_ui.ApiError, match="naming syngate is refused"):
            app._shell({"tool": "shell", "command": command})
    assert app._shell({"tool": "shell", "command": "echo syngate_ui.py"}).endswith("exit 0\nsyngate_ui.py")
