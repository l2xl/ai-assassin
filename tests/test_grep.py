# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Grep tool (SYNTHETIC-TOOL-GREP): the run of a grep call by the program the offered library selects, its guard, its absence and its read-only run."""

import os
import shutil
import subprocess

import pytest

import assassin_ui
import synthetic
from ai_scratcher import greplib
from test_assassin_ui_api import SETUP, Scripted, calls

GIT = shutil.which("git")


def git(root, *args):
    return subprocess.run([GIT, *args], cwd=root, check=True, capture_output=True, text=True).stdout


def at_hand(program):
    """Whether the machine runs `program` -- rg, GNU grep, git -- for the run of a real search."""
    return {"rg": shutil.which("rg") is not None, "gnu": synthetic.probe(".", ["grep", "--version"], "GNU grep"), "git": GIT is not None}[program]


def make_project(root, syngate_tree, repo=True):
    """A project of one item whose `src/a.py` holds `needle one`, committed in a git work tree when `repo`."""
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root.\n", parents=())
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("needle one\n")
    (root / "notes.md").write_text("nothing here\n")
    if repo:
        if GIT is None:
            pytest.skip("no git")
        for args in (("init", "-q", "-b", "main"), ("config", "user.email", "tester@example.com"), ("config", "user.name", "Tester"),
                     ("config", "commit.gpgsign", "false"), ("add", "-A"), ("commit", "-q", "-m", "Add the project")):
            git(root, *args)
    return root, syngate_dir


@pytest.fixture
def project(tmp_path, syngate_tree):
    return make_project(tmp_path, syngate_tree)


def offered_on(project, program):
    """An app of `project` whose library offers the grep prompt of `program` alone, as a machine having only it would."""
    if not at_hand(program):
        pytest.skip(f"no {program} on this machine")
    app = assassin_ui.AssassinApp(root=project[0], syngate_dir=project[1])
    app.library = {name: entry for name, entry in synthetic.LIBRARY.items() if greplib.PROMPTS.get(name, program) == program}
    return app


def ask(app, *answers):
    """(outcome, connector) of one chat turn of ROOT answered by the scripted `answers`."""
    app.connectors = {"echo": (scripted := Scripted(*answers))}
    return app.chat({**SETUP, "uid": "ROOT", "text": "Find it.", "modes": ["tree"]}), scripted


def grep_prompts(library):
    return [name for name in greplib.PROMPTS if name in library]


@pytest.mark.syngate("SYNTHETIC-TOOL-GREP-RUN")
@pytest.mark.parametrize("program", list(greplib.PROGRAMS))
def test_a_grep_call_runs_the_offered_program_in_the_project_root_without_a_shell_or_stdin_reporting_its_exit_status_over_every_match(project, program):
    app = offered_on(project, program)
    found = {"tool": "grep", "command": "-i 'NEEDLE one' src"}
    quiet = {"tool": "grep", "command": "-F '$(touch pwned)'"}  # no match, and no shell to run the line
    whole = {"tool": "grep", "command": "-F 'needle one'"}  # no path: the project root, never the stdin
    outcome, scripted = ask(app, calls(found, quiet, whole), {"kind": "text", "text": "Found."})
    assert greplib.program(app.library) == program
    assert scripted.heard[1]["text"] == (synthetic.RESULTS_PREAMBLE + "- grep -i 'NEEDLE one' src:\nexit 0\nsrc/a.py:1:needle one\n"
                                         "- grep -F '$(touch pwned)':\nexit 1\n- grep -F 'needle one':\nexit 0\nsrc/a.py:1:needle one")
    assert (outcome.get("applied", []), outcome["reply"]) == ([], "Found.") and not (project[0] / "pwned").exists()  # exit 1 is a result, not a refusal


@pytest.mark.syngate("SYNTHETIC-TOOL-GREP-GUARD")
def test_the_guard_refuses_unlisted_options_and_paths_off_the_project_and_keeps_every_search_out_of_the_tree_git_and_the_server_files(project):
    root, secret = project[0], assassin_ui.UNREADABLE
    for program, command, option in (("rg", "--pre cat x", "--pre"), ("rg", "--follow x", "--follow"), ("rg", "--ignore-c x", "--ignore-c"),
                                     ("rg", "-iz x", "-z"), ("rg", "--search-zip x", "--search-zip"), ("gnu", "-R x", "-R"),
                                     ("gnu", "--devices=read x", "--devices"), ("gnu", "-5 x", "-5"), ("git", "--no-index x", "--no-index"),
                                     ("git", "-inO x", "-O"), ("git", "--recurse-submodules x", "--recurse-submodules")):
        with pytest.raises(greplib.refused, match=f"'{option}' is no option"):
            greplib.guard(root, command, program, secret)
    words = "-in -A3 --max-count=5 -m 5 needle src"
    assert greplib.guard(root, words, "gnu", secret) == [*greplib.PROGRAMS["gnu"].head, *greplib.PROGRAMS["gnu"].fixed, "-in", "-A3", "--max-count=5",
                                                         "-m", "5", *greplib.excludes("gnu", secret), "--", "needle", "src"]  # its excludes last
    (root / "link").symlink_to(root)
    (root / "out").symlink_to("/etc")
    for program in greplib.PROGRAMS:
        for command in ("needle /etc/passwd", "needle ../x", "needle .git/config", "needle syngate", "needle ./syngate/ROOT.yml", "needle out",
                        "needle assassin_settings.json", "needle link", "-f syngate/ROOT.yml", "-f/etc/passwd", "-f ../p", "-i"):
            with pytest.raises(greplib.refused):
                greplib.guard(root, command, program, secret)
    with pytest.raises(greplib.refused, match="magic"):
        greplib.guard(root, "needle ':(top)syngate'", "git", secret)
    (root / "link").unlink()
    (root / "out").unlink()
    (root / "syngate" / "needle.txt").write_text("needle\n")
    (root / ".git" / "needle").write_text("needle\n")
    (root / assassin_ui.SETTINGS_FILE).write_text('{"note": "needle"}\n')
    widened = {"rg": "--hidden --no-ignore -uuu -g '*' -g 'syngate/**' -g '.git/**' needle", "gnu": "--include=* -a needle", "git": "--untracked needle"}
    for program, command in widened.items():
        if not at_hand(program):
            continue
        refusal = {"tool": "grep", "command": "-f syngate/needle.txt src"}
        outcome, scripted = ask(offered_on(project, program), calls({"tool": "grep", "command": command}), calls(refusal), {"kind": "text", "text": "Kept out."})
        assert scripted.heard[1]["text"] == synthetic.RESULTS_PREAMBLE + f"- grep {command}:\nexit 0\nsrc/a.py:1:needle one"  # the chats file kept out too
        assert outcome["applied"] == ["- grep -f syngate/needle.txt src refused: syngate/needle.txt is in the tree: the items are read only through the tree calls"]


@pytest.mark.syngate("SYNTHETIC-TOOL-GREP-ABSENT")
def test_without_ripgrep_gnu_grep_or_git_at_hand_no_grep_tool_is_offered_and_a_grep_call_is_refused_naming_why(tmp_path, tmp_path_factory, syngate_tree, monkeypatch):
    if GIT is None:
        pytest.skip("no git")
    root, syngate_dir = make_project(tmp_path, syngate_tree, repo=False)
    tools = tmp_path_factory.mktemp("bin")

    def program(name, says):
        (tools / name).write_text(f"#!/bin/sh\necho '{says}'\n")
        (tools / name).chmod(0o755)

    program("grep", "grep (BSD grep, GNU compatible) 2.6.0-FreeBSD")  # a grep, but no GNU one
    (tools / "git").symlink_to(GIT)  # git found, the project no work tree
    monkeypatch.setenv("PATH", str(tools))
    app = assassin_ui.AssassinApp(root=root, syngate_dir=syngate_dir)
    shapes = synthetic.answer_schema(app.library)["properties"]["calls"]["items"]["anyOf"]
    assert set(greplib.PROMPTS) <= set(synthetic.LIBRARY) and grep_prompts(app.library) == [] and greplib.program(app.library) is None
    assert "grep" not in [shape["properties"]["tool"]["const"] for shape in shapes] and "git" not in app.library
    outcome, _ = ask(app, calls({"tool": "grep", "command": "needle"}), {"kind": "text", "text": "No search here."})
    assert (outcome["applied"], outcome["reply"]) == ([f"- grep needle refused: {assassin_ui.GREP_ABSENT}"], "No search here.")
    program("rg", "ripgrep 15.1.0")
    assert grep_prompts(synthetic.offered_library(root)) == ["grep_rg"]  # each of the three alone brings the tool back
    (tools / "rg").unlink()
    program("grep", "grep (GNU grep) 3.12")
    assert grep_prompts(synthetic.offered_library(root)) == ["grep_gnu"]
    program("grep", "grep (BSD grep, GNU compatible) 2.6.0-FreeBSD")
    git(root, "init", "-q")
    assert grep_prompts(synthetic.offered_library(root)) == ["grep_git"]


def snapshot(root):
    """Every folder and file under `root`, `.git` included, with the content and modification time of each file."""
    seen = {}
    for folder, dirs, names in os.walk(root):
        seen[os.path.relpath(folder, root)] = None
        for name in names:
            path = os.path.join(folder, name)
            seen[os.path.relpath(path, root)] = (open(path, "rb").read(), os.stat(path).st_mtime_ns) if os.path.isfile(path) else os.readlink(path)
    return seen


# What runs a program, writes or reads past the project among the programs' own options: none of them is listed.
UNSAFE = {"rg": "--pre --pre-glob -z --search-zip -L --follow --ignore-file --config --no-config -f- --debug --trace",
          "gnu": "-R --dereference-recursive -D --devices -d --directories -r --recursive",
          "git": "-O --open-files-in-pager --no-index --recurse-submodules --textconv --ext-grep --exclude-standard --no-exclude-standard"}
COMBINED = {"rg": ("-i -S -w -n --column --vimgrep -r X -C2 --sort path -g '*.py' needle", "-U --multiline-dotall -P 'needle\\s+one' -o -c --count-matches",
                   "-f pats.txt --hidden --no-ignore -uuu -l", "-M 5 -d 3 -t py -T md -m 1 -A1 -B1 --iglob '*' -s -x -F -H -I -N 'needle one'",
                   "--files-without-match -v --replace=Y --max-count=2 needle src"),
            "gnu": ("-i -E -o -c -H -n -s -a -I --include=*.py --exclude=*.md --exclude-dir=x -m 1 -A1 -B1 -C1 needle", "-P -x -v -L -l needle",
                    "-f pats.txt -w -h -G --no-ignore-case", "-F --max-count=3 --after-context=1 -e needle src"),
            "git": ("--untracked --all-match -e needle -e one -o --column -H -n -i -w -E -C1 --max-depth 2", "--cached -l -c -F -h needle",
                    "-P -v -m 1 -f pats.txt", "-L -G --name-only --after-context=1 needle src")}


@pytest.mark.syngate("SYNTHETIC-TOOL-GREP-READONLY")
@pytest.mark.parametrize("program", list(greplib.PROGRAMS))
def test_no_combination_of_the_listed_options_writes_a_file_of_the_project_or_of_git_or_runs_another_program(project, program):
    spec, root = greplib.PROGRAMS[program], project[0]
    assert not (spec.flags | spec.values) & set(UNSAFE[program].split())
    if not at_hand(program):
        pytest.skip(f"no {program} on this machine")
    (root / "pats.txt").write_text("needle\n")
    before = snapshot(root)
    for command in COMBINED[program]:
        assert greplib.run(root, greplib.guard(root, command, program, assassin_ui.UNREADABLE)).split("\n", 1)[0] in ("exit 0", "exit 1"), command
    assert snapshot(root) == before
