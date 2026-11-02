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
    outcome = turn(base, app, "ROOT", "Run it.", modes=["tree"])
    assert outcome["reply"] == f"- shell pwd -P; exit 3 refused: {assassin_ui.SHELL_REFUSAL}\nCould not."
    assert scripted.heard[0]["modes"] == []
    outcome = turn(base, app, "ROOT", "Run it.", modes=["tree", "bash"])
    ran = f"- shell pwd -P; exit 3:\nexit 3\n{app.root.resolve()}"
    assert scripted.heard[2]["modes"] == ["bash"]  # the mode reaches the connection that lists it
    assert scripted.heard[3]["text"] == synthetic.RESULTS_PREAMBLE + ran  # exit status and output come back as the next prompt
    assert outcome["reply"] == ran + "\nRan."
    outcome = turn(base, app, "ROOT", "List the items.", modes=["tree", "bash"])
    assert outcome["reply"] == f"- shell ls syngate refused: {assassin_ui.SHELL_TREE}\nClosed."
    assert [mode["id"] for mode in app.build_model()["connectors"]["echo"]["modes"]] == ["tree", "patch", "bash"]
