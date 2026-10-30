# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The patch tool of the AI and the Edit files switch that gates it: the guard of a unified diff, its all-or-nothing `git apply`, the
switch of a turn refusing the calls with the text headed by its notice, and the connectors' own edit tools denied to Claude Code."""

import json
import shutil
import sys

import pytest

import assassin_ui
import synthetic
from ai_scratcher import patchlib
from test_git import git, repo, repo_server  # noqa: F401 -- the git project fixtures
from test_assassin_ui_api import Scripted, calls, turn

GUIDE = "--- a/GUIDE.md\n+++ b/GUIDE.md\n@@ -1 +1,2 @@\n # Guide\n+Read it.\n"
NEW = "--- /dev/null\n+++ b/notes/new.md\n@@ -0,0 +1 @@\n+New.\n"


@pytest.fixture
def project(tmp_path):
    """A git work tree holding one file, `notes.md`, of three lines."""
    if shutil.which("git") is None:
        pytest.skip("no git")
    (tmp_path / "notes.md").write_text("# Notes\nOne line.\nEnd.\n")
    git(tmp_path, "init", "-q")
    return tmp_path


@pytest.mark.syngate("SYNTHETIC-TOOL-PATCH-APPLY")
def test_a_patch_applies_its_whole_diff_with_git_apply_or_none_of_it(project):
    diff = "--- a/notes.md\n+++ b/notes.md\n@@ -1,3 +1,4 @@\n # Notes\n-One line.\n+Two lines.\n+Read on.\n End.\n"
    assert patchlib.apply(project, diff) == ["notes.md"]
    assert (project / "notes.md").read_text() == "# Notes\nTwo lines.\nRead on.\nEnd.\n"
    assert patchlib.apply(project, NEW) == ["notes/new.md"] and (project / "notes" / "new.md").read_text() == "New.\n"
    broken = "--- /dev/null\n+++ b/other.md\n@@ -0,0 +1 @@\n+Made.\n" + "--- a/notes.md\n+++ b/notes.md\n@@ -1 +1 @@\n-Gone.\n+Here.\n"
    with pytest.raises(patchlib.refused, match="notes.md"):
        patchlib.apply(project, broken)
    assert not (project / "other.md").exists()
    assert (project / "notes.md").read_text() == "# Notes\nTwo lines.\nRead on.\nEnd.\n"


@pytest.mark.syngate("SYNTHETIC-TOOL-PATCH-GUARD")
def test_the_guard_passes_the_paths_of_a_diff_and_refuses_one_reaching_the_tree_or_past_the_project():
    assert patchlib.guard(GUIDE + NEW) == ["GUIDE.md", "notes/new.md"]
    refused = ("--- a/syngate/synthetic/LEAF.yml\n+++ b/syngate/synthetic/LEAF.yml\n@@ -1 +1 @@\n-a\n+b\n",
               "--- a/src/../../etc/passwd\n+++ b/src/../../etc/passwd\n@@ -1 +1 @@\n-a\n+b\n",
               "--- a/.git/config\n+++ b/.git/config\n@@ -1 +1 @@\n-a\n+b\n",
               "--- /etc/passwd\n+++ b/etc/passwd\n@@ -1 +1 @@\n-a\n+b\n",
               "new file mode 120000\n--- /dev/null\n+++ b/link\n@@ -0,0 +1 @@\n+/etc\n",
               "diff --git a/GUIDE.md b/GUIDE.md\nrename from GUIDE.md\nrename to syngate/GUIDE.md\n",
               GUIDE + "--- a/syngate/LEAF.yml\n+++ b/syngate/LEAF.yml\n@@ -1 +1 @@\n-a\n+b\n",
               "Just prose, no diff.\n")
    for diff in refused:
        with pytest.raises(patchlib.refused):
            patchlib.guard(diff)


@pytest.mark.syngate("SYNTHETIC-TOOL-PATCH-MODE")
def test_the_edit_files_switch_gates_the_patch_calls_of_a_turn(repo_server):
    base, app = repo_server
    app.connectors = {"echo": (scripted := Scripted(calls({"tool": "patch", "diff": GUIDE}), {"kind": "text", "text": "Could not."},
                                                    calls({"tool": "patch", "diff": GUIDE})))}
    outcome = turn(base, app, "ROOT", "Edit the guide.", modes=["tree"])
    assert outcome["reply"].startswith("- patch refused: ") and outcome["reply"].endswith("\nCould not.")
    assert app.root.joinpath("GUIDE.md").read_text() == "# Guide\n"
    outcome = turn(base, app, "ROOT", "Edit the guide.", modes=["patch"])
    assert outcome["reply"] == "- patch changed GUIDE.md"
    assert app.root.joinpath("GUIDE.md").read_text() == "# Guide\nRead it.\n"
    assert [mode["id"] for mode in app.build_model()["connectors"]["echo"]["modes"]][:2] == ["tree", "patch"]


@pytest.mark.syngate("CLAUDE_CODE-NO-EDIT")
def test_claude_code_is_denied_its_own_edit_tools_in_every_mode(tmp_path):
    stub = tmp_path / "claude_stub.py"
    stub.write_text('import json, sys\nsys.stdin.readline()\nprint(json.dumps({"type": "result", "result": json.dumps(sys.argv[1:]), '
                    '"session_id": "s", "is_error": False}))\n')
    connector = synthetic.claude_code_connector(cli=(sys.executable, str(stub)), cwd=tmp_path)
    for modes in ((), ("internet", "bash")):
        argv = json.loads(connector.dispatch("", "Go.", modes=modes)[0])
        denied = argv[argv.index("--disallowedTools") + 1].split(",")
        assert {"Edit", "MultiEdit", "Write", "NotebookEdit"} <= set(denied) and "Edit(syngate/**)" in denied
        assert "acceptEdits" not in argv
