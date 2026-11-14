# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The files tool of the AI (SYNTHETIC-TOOL-FILES): the guard keeping a read inside the project and off the tree, the listing of a folder,
the reading of a file by line range, and both as calls of a turn that are always allowed and keep it going."""

import pytest

import assassin_ui
import synthetic
from ai_scratcher import filelib
from test_assassin_ui import app, server  # noqa: F401 -- the server fixtures of the page tests
from test_assassin_ui_api import Scripted, calls, turn


@pytest.fixture
def project(tmp_path):
    """A project of a source folder with two files, a tree folder, a `.git` folder and a settings file."""
    for rel, text in (("src/queue.py", "".join(f"line {n}\n" for n in range(1, 11))), ("src/deep/leaf.txt", "leaf\n"), ("README.md", "# Read\n"),
                      ("syngate/ROOT.yml", "---\n---\nRoot\n"), (".git/config", "[core]\n"), ("settings.json", '{"key": "s3cret"}\n'),
                      ("src/__pycache__/queue.pyc", "x")):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    (tmp_path / "blob.bin").write_bytes(b"\xff\xfe\x00")
    return tmp_path


@pytest.mark.syngate("SYNTHETIC-TOOL-FILES-GUARD")
def test_the_guard_keeps_a_read_inside_the_project_and_off_the_tree_git_and_the_secret_files(project):
    assert filelib.guard(project, "src/queue.py") == (project / "src" / "queue.py").resolve() and filelib.guard(project, "") == project.resolve()
    (project / "out").symlink_to(project.parent)
    for rel, word in (("/etc/passwd", "outside the project"), ("src/../../x", "outside the project"), ("out/x", "outside the project"),
                      ("syngate/ROOT.yml", "through the tree calls"), (".git/config", "not readable"), ("settings.json", "not readable")):
        with pytest.raises(filelib.refused, match=word):
            filelib.read(project, rel, secret=("settings.json",))
    with pytest.raises(filelib.refused, match="through the tree calls"):
        filelib.listing(project, "syngate")


@pytest.mark.syngate("SYNTHETIC-TOOL-FILES-LIST")
def test_list_names_the_folders_and_files_of_a_folder_to_the_depth_asked(project):
    assert filelib.listing(project, secret=("settings.json",)) == "src/\nsyngate/\nREADME.md  7\nblob.bin  3"
    assert filelib.listing(project, "src", depth=2) == "src/deep/\nsrc/deep/leaf.txt  5\nsrc/queue.py  " + str((project / "src/queue.py").stat().st_size)
    assert "syngate/ROOT.yml" not in filelib.listing(project, depth=5)  # the tree is named and not entered
    for rel, depth, word in (("README.md", None, "no folder"), ("src", 0, "depth must be a whole number"), ("src", "two", "depth must be")):
        with pytest.raises(filelib.refused, match=word):
            filelib.listing(project, rel, depth)


@pytest.mark.syngate("SYNTHETIC-TOOL-FILES-READ")
def test_read_returns_the_numbered_lines_of_a_range_and_tells_where_a_cut_read_goes_on(project, monkeypatch):
    assert filelib.read(project, "src/queue.py", 3, 2) == "src/queue.py lines 3-4 of 10\n3\tline 3\n4\tline 4"
    assert filelib.read(project, "README.md") == "README.md lines 1-1 of 1\n1\t# Read"
    assert filelib.read(project, "src/queue.py", "9") == "src/queue.py lines 9-10 of 10\n9\tline 9\n10\tline 10"
    monkeypatch.setattr(filelib, "READ_LIMIT", 20)
    assert filelib.read(project, "src/queue.py") == "src/queue.py lines 1-2 of 10\n1\tline 1\n2\tline 2\n… cut at 20 characters: go on with from 3"
    for rel, start, word in (("src", None, "list it instead"), ("absent.py", None, "no file"), ("blob.bin", None, "not a text file"),
                             ("src/queue.py", 11, "past its end"), ("src/queue.py", 0, "from must be a whole number")):
        with pytest.raises(filelib.refused, match=word):
            filelib.read(project, rel, start)


@pytest.mark.syngate("SYNTHETIC-TOOL-FILES")
def test_list_and_read_calls_of_a_turn_are_always_allowed_and_come_back_as_the_next_prompt(server):
    base, app = server
    app.root.joinpath("GUIDE.md").write_text("# Guide\nRead it.\n")
    app.root.joinpath(assassin_ui.SETTINGS_FILE).write_text('{"key": "s3cret"}')
    asked = [{"tool": "list"}, {"tool": "read", "path": "GUIDE.md", "from": 2}]
    app.connectors = {"echo": (scripted := Scripted(calls(*asked), {"kind": "text", "text": "Read."},
                                                    calls({"tool": "read", "path": assassin_ui.SETTINGS_FILE}), {"kind": "text", "text": "Closed."}))}
    outcome = turn(base, app, "ROOT", "Look around.", modes=[])  # every permission off
    heard = scripted.heard[1]["text"]
    assert heard.startswith(synthetic.RESULTS_PREAMBLE + "- list .:\n") and "GUIDE.md  17" in heard and assassin_ui.SETTINGS_FILE not in heard
    assert heard.endswith("- read GUIDE.md lines 2-2 of 2\n2\tRead it.")
    assert (outcome["reply"], outcome.get("applied", [])) == ("Read.", [])  # a read is no change the chat reports
    outcome = turn(base, app, "ROOT", "Read the key.", modes=[])
    assert outcome["applied"] == [f"- read {assassin_ui.SETTINGS_FILE} refused: {assassin_ui.SETTINGS_FILE} is not readable"] and "s3cret" not in str(scripted.heard)
    assert set(assassin_ui.UNREADABLE) == {assassin_ui.SETTINGS_FILE, assassin_ui.CHATS_FILE, assassin_ui.LEGACY_CHATS_FILE}
    app.root.joinpath(assassin_ui.CHATS_FILE).write_text("{}")
    with pytest.raises(assassin_ui.ApiError, match="is not readable"):  # the stored chats hold what a chat was told to forget
        app._file({"tool": "read", "path": assassin_ui.CHATS_FILE})
    assert assassin_ui.CHATS_FILE not in app._file({"tool": "list"})
