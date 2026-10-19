# Open Trader
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Git integration: the AI's git tool and its guards, the review refused over uncommitted content and committed itself, and the
commit made with the AI from the status popup."""

import shutil
import subprocess
import sys
import threading

import pytest

import assassin_ui
import syngate
import syngatelib
import synthetic
from ai_scratcher import gitlib
from test_assassin_ui import Page, call, chrome  # noqa: F401 -- the page fixtures
from test_assassin_ui_api import SETUP, Scripted, calls, refused, turn


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path, syngate_tree):
    """A project in a git work tree, its tree -- review on, tests off -- committed as `Add the tree`."""
    if shutil.which("git") is None:
        pytest.skip("no git")
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root branch\n\n[GUIDE.md](GUIDE.md)\n", parents=(), features=("review",))
    make_item(syngate_dir, "LEAF-001", "It shall leaf.\n", parents=("ROOT",))
    (tmp_path / "GUIDE.md").write_text("# Guide\n")
    (tmp_path / ".gitignore").write_text("assassin_chats.json*\nsyngate_coverage.jsonl\n")
    for args in (("init", "-q", "-b", "main"), ("config", "user.email", "tester@example.com"), ("config", "user.name", "Tester"),
                 ("config", "commit.gpgsign", "false"), ("add", "-A"), ("commit", "-q", "-m", "Add the tree")):
        git(tmp_path, *args)
    return tmp_path, syngate_dir, make_item


@pytest.fixture
def repo_server(repo):
    root, syngate_dir, _ = repo
    app = assassin_ui.AssassinApp(root=root, syngate_dir=syngate_dir)
    httpd = assassin_ui.make_server(app, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", app
    httpd.shutdown()
    thread.join()


def run_review(base, app, uid):
    """The console output of a review run of `uid`, awaited to its end."""
    _, job = call(base, app, "/api/run", {"action": "review", "uids": [uid]})
    return call(base, app, f"/api/job/{job['job']}/events?token={app.token}", token=False, raw=True)[1].decode()


@pytest.mark.syngate("SYNTHETIC-TOOL-GIT", "run")
def test_a_git_call_runs_in_the_project_root_without_a_shell_and_its_outcome_comes_back_as_the_next_prompt(repo_server):
    base, app = repo_server
    (app.root / "notes.md").write_text("# Notes\n")
    commit = {"tool": "git", "command": "commit -m 'Add the notes; $(touch pwned)'"}
    app.connectors = {"echo": (scripted := Scripted(calls({"tool": "git", "command": "status --short"}), calls({"tool": "git", "command": "add notes.md"}, commit),
                                                    {"kind": "text", "text": "Committed."}))}
    outcome = turn(base, app, "ROOT", "Commit the notes.", modes=[])  # no switch gates git: its records run with every permission off
    assert scripted.heard[1]["text"] == synthetic.RESULTS_PREAMBLE + "- git status --short:\nexit 0\n?? notes.md"  # the read came back, out of the reply
    assert outcome["reply"].startswith("- git add notes.md:\nexit 0\n- git commit -m 'Add the notes; $(touch pwned)':\nexit 0\n[main ")
    assert outcome["reply"].endswith("\nCommitted.") and scripted.heard[2]["text"].startswith(synthetic.RESULTS_PREAMBLE + "- git add notes.md:\nexit 0")
    assert git(app.root, "log", "-1", "--format=%s") == "Add the notes; $(touch pwned)\n" and not (app.root / "pwned").exists()  # no shell saw the line


@pytest.mark.syngate("SYNTHETIC-TOOL-GIT", "offer")
def test_the_git_tool_is_offered_only_while_git_finds_a_work_tree_around_the_project_root(repo):
    root, syngate_dir, _ = repo
    assert "git" in synthetic.LIBRARY and synthetic.offered_library(True) is synthetic.LIBRARY and "git" not in synthetic.offered_library(False)
    offered = assassin_ui.AssassinApp(root=root, syngate_dir=syngate_dir)
    offered.connectors = {"echo": Scripted()}
    assert offered.git and offered.library is synthetic.LIBRARY and offered.build_model()["git"] is True
    assert [mode["id"] for mode in offered.build_model()["connectors"]["echo"]["modes"]] == ["tree", "edit"]  # always offered, no switch of its own
    shutil.rmtree(root / ".git")
    bare = assassin_ui.AssassinApp(root=root, syngate_dir=syngate_dir)
    tools = [shape["properties"]["tool"]["const"] for shape in synthetic.answer_schema(bare.library)["properties"]["calls"]["items"]["anyOf"]]
    assert not bare.git and "git" not in bare.library and "git" not in tools and "query" in tools
    bare.connectors = {"echo": Scripted(calls({"tool": "git", "command": "status"}), {"kind": "text", "text": "No git here."})}
    assert bare.build_model()["git"] is False
    assert bare.chat({**SETUP, "uid": "ROOT", "text": "Status?", "modes": ["tree"]})["reply"] == f"- git status refused: {assassin_ui.GIT_ABSENT}\nNo git here."


@pytest.mark.syngate("SYNTHETIC-TOOL-GIT-GUARD", "command")
def test_the_guard_runs_the_listed_reads_and_records_and_refuses_any_other_command_and_any_option_ahead_of_it():
    assert gitlib.guard("log --oneline -5") == (["log", "--oneline", "-5"], False)
    assert gitlib.guard("commit -m 'Two words'") == (["commit", "-m", "Two words"], True)
    assert all(gitlib.guard(name) == ([name], False) for name in gitlib.READS)
    assert all(gitlib.guard(f"{name} --continue" if name in ("merge", "cherry-pick", "revert") else f"{name} --staged x" if name == "restore" else name)[1]
               for name in gitlib.RECORDS)
    for line in ("reset --hard HEAD~1", "checkout -- notes.md", "clean -fd", "rebase -i main", "stash drop", "gc --prune=now", "reflog expire --all",
                 "update-ref -d refs/heads/main", "filter-branch", "config alias.st status", "push --force", "pull", "fetch", "remote add x y", "st",
                 "-c core.pager=evil log", "-C .. status", "--git-dir=/tmp/x status", "", "commit -m 'unclosed"):
        with pytest.raises(gitlib.refused):
            gitlib.guard(line)


@pytest.mark.syngate("SYNTHETIC-TOOL-GIT-GUARD", "option")
def test_the_guard_refuses_every_option_that_discards_rewrites_or_deletes_in_any_abbreviation_or_bundle():
    for line in ("commit --amend", "commit --amen --no-edit", "commit -an -m x", "commit --no-verify -m x", 'commit -m"no"', "add -f secret.key",
                 "add --force .", "mv -f a b", "rm --force a", "rm -rf docs", "branch -D topic", "branch --delete topic", "branch --del topic",
                 "branch -m old new", "branch -M old new", "branch -f main HEAD~1", "tag -d v1", "tag --force v1", "switch -C main",
                 "switch --discard-changes main", "switch --orphan fresh", "merge --abort", "cherry-pick --abort", "revert --abort", "restore notes.md",
                 "restore --staged --worktree notes.md", "restore -SW notes.md", "log --output=../stolen", "diff --no-index /etc/passwd notes.md", "grep -O vi TODO"):
        with pytest.raises(gitlib.refused):
            gitlib.guard(line)
    for line in ("commit -a -m 'Fix -n handling'", "commit --no-edit", "branch topic", "branch -c topic copy", "tag -a v1 -m 'Version one'", "switch -c topic",
                 "merge --no-ff topic", "cherry-pick --continue", "restore --staged notes.md", "rm --cached notes.md", "log -n 3 --oneline", "diff --stat",
                 "grep -n TODO", "add -A", "commit -m x -- --amend"):
        gitlib.guard(line)


@pytest.mark.syngate("SYNTHETIC-TOOL-GIT-TREE")
def test_mv_and_rm_take_no_path_under_the_tree_nor_holding_it_and_no_glob_or_pathspec_magic():
    for line in ("rm syngate/LEAF-001.yml", "rm --cached syngate/ROOT.yml", "rm -r syngate", "rm -r .", "rm -r ./", "mv notes.md syngate/notes.md",
                 "mv syngate/LEAF-001.yml old.yml", "rm 'docs/*.md'", "rm ':(glob)**/ROOT.yml'", "rm :/notes.md", "rm docs/../syngate/ROOT.yml",
                 "rm ../other/file", "rm /etc/hosts", "rm -- syngate/ROOT.yml", "rm --pathspec-from-file=list.txt"):
        with pytest.raises(gitlib.refused):
            gitlib.guard(line)
    for line in ("rm docs/old.md", "mv notes.md docs/notes.md", "add syngate/LEAF-001.yml", "restore --staged syngate/ROOT.yml", "log -- syngate", "rm -r docs"):
        gitlib.guard(line)


@pytest.mark.syngate("SYNGATE-API-REVIEW-COMMITTED")
def test_review_refuses_an_item_whose_footprint_holds_uncommitted_changes_naming_the_files(repo, monkeypatch, capsys):
    root, syngate_dir, make_item = repo
    bound = (syngatelib.ROOT, syngatelib.SYNGATE_DIR)

    def review(uid):
        monkeypatch.setattr(sys, "argv", ["syngate", "--root", str(root), "review", uid])
        return syngate.main()

    try:
        (root / "GUIDE.md").write_text("# Guide\n\nReworded.\n")  # linked by ROOT, so in the seed context of LEAF-001
        (root / "scratch.txt").write_text("unrelated\n")
        assert review("LEAF-001") == 1 and "LEAF-001: uncommitted changes in its review footprint, commit them first: GUIDE.md" in capsys.readouterr().err
        git(root, "commit", "-qam", "Reword the guide")
        make_item(syngate_dir, "LEAF-002", "It shall follow.\n", parents=("ROOT",))  # untracked: below ROOT, beside LEAF-001
        assert review("LEAF-001") == 0 and syngatelib.load_tree(syngate_dir)[0]["LEAF-001"].reviewed  # scratch.txt is in no footprint
        capsys.readouterr()
        assert review("ROOT") == 1
        assert "ROOT: uncommitted changes in its review footprint, commit them first: syngate/LEAF-001.yml, syngate/LEAF-002.yml" in capsys.readouterr().err
    finally:
        syngatelib.ROOT, syngatelib.SYNGATE_DIR = bound
    items = syngatelib.load_tree(syngate_dir)[0]
    located = {("LEAF-001", None): [syngatelib.Location("tests/test_leaf.py", 1, "tests/test_leaf.py::test_leaf", "")]}
    items["LEAF-001"].tests = {None: None}
    assert syngatelib.review_footprint(items, "ROOT", located, root) == {"syngate/ROOT.yml", "syngate/LEAF-001.yml", "syngate/LEAF-002.yml", "GUIDE.md", "tests/test_leaf.py"}
    assert syngatelib.review_footprint(items, "LEAF-002", located, root) == {"syngate/ROOT.yml", "syngate/LEAF-002.yml", "GUIDE.md"}


@pytest.mark.syngate("ASSASSIN-UI-REVIEW-COMMIT", "single")
def test_a_review_run_commits_the_stamped_item_files_alone_after_the_one_commit_since_the_last_review(repo_server):
    base, app = repo_server
    (app.root / "notes.md").write_text("# Notes\n")
    git(app.root, "add", "notes.md")  # staged, in no footprint: it stays staged and out of the review commit
    events = run_review(base, app, "ROOT")
    assert "review commit: [main " in events and "Review: Add the tree" in events
    assert git(app.root, "log", "--format=%s").splitlines() == ["Review: Add the tree", "Add the tree"]
    assert sorted(git(app.root, "show", "--name-only", "--format=", "HEAD").split()) == ["syngate/LEAF-001.yml", "syngate/ROOT.yml"]
    assert git(app.root, "status", "--porcelain").splitlines() == ["A  notes.md"]


@pytest.mark.syngate("ASSASSIN-UI-REVIEW-COMMIT", "several")
def test_after_several_commits_the_ai_formulates_the_review_message_in_the_reviewed_items_chat(repo_server):
    base, app = repo_server
    (app.root / "GUIDE.md").write_text("# Guide\n\nReworded.\n")
    git(app.root, "commit", "-qam", "Reword the guide")
    app.connectors = {"echo": (scripted := Scripted({"kind": "text", "text": "Review: the tree and its guide"}))}
    call(base, app, "/api/chat/ROOT", SETUP)
    events = run_review(base, app, "ROOT")
    assert "Review: the tree and its guide" in events
    assert git(app.root, "log", "--format=%s").splitlines() == ["Review: the tree and its guide", "Reword the guide", "Add the tree"]
    asked = scripted.heard[0]["text"]
    assert "ROOT" in asked and "LEAF-001" in asked and asked.endswith("- Reword the guide\n- Add the tree")
    assert [(m["role"], m.get("agent")) for m in call(base, app, "/api/chats")[1]["chats"]["ROOT"]["log"]] == [("user", "review"), ("ai", None)]

    leaf = app.root / "syngate" / "LEAF-001.yml"
    leaf.write_text(leaf.read_text().replace("It shall leaf.", "It shall leaf again."))
    git(app.root, "commit", "-qam", "Reword the leaf")
    (app.root / "GUIDE.md").write_text("# Guide\n\nAgain.\n")
    git(app.root, "commit", "-qam", "Reword the guide again")
    app.connectors = {"echo": Scripted(synthetic.connection_error("claude exited with 1"))}
    events = run_review(base, app, "LEAF-001")  # a chat without a setup of its own runs the first connector's default one
    assert "review commit: no message came from the chat of LEAF-001, the stamps of syngate/LEAF-001.yml are left uncommitted" in events
    assert git(app.root, "status", "--porcelain").splitlines() == [" M syngate/LEAF-001.yml"]


@pytest.mark.syngate("ASSASSIN-UI-STATUS-POPUP-COMMIT")
def test_the_popup_offers_the_commit_with_ai_and_holds_the_review_while_its_footprint_is_uncommitted(repo_server, chrome):
    base, app = repo_server
    (app.root / "GUIDE.md").write_text("# Guide\n\nDraft.\n")
    status, body = refused(base, app, "/api/run", {"action": "review", "uids": ["LEAF-001"]})
    assert (status, body["error"], body["files"]) == (409, "commit first: GUIDE.md", ["GUIDE.md"])
    app.connectors = {"echo": (scripted := Scripted({"kind": "text", "text": "Committed."}))}
    page = Page(chrome, f"{base}/?token={app.token}")
    page.wait("document.querySelector('#tree [data-path]')")
    popup = "document.querySelector('#doc .block[data-uid=\"LEAF-001\"] legend .status').click()"
    actions = ("[...document.querySelectorAll('#tests-pop [data-run=\"review\"], #tests-pop [data-commit], #tests-pop .commit-first')]"
               ".map((el) => [el.textContent, el.disabled === true, el.title])")
    page.eval(f"select('LEAF-001', 'ROOT/LEAF-001'); {popup}")
    assert page.eval(actions) == [["👀 Mark reviewed", True, "commit first: GUIDE.md"],
                                  ["⎇ Commit with AI", False, "1 file uncommitted — the AI commits them in this item's chat"], ["commit first: 1 file", False, "GUIDE.md"]]
    page.eval("document.querySelector('#tests-pop [data-commit]').click()")
    page.wait("document.querySelector('#doc .block[data-uid=\"LEAF-001\"] .chat-msg.ai')")
    assert scripted.heard[0]["text"] == "Commit the uncommitted changes of the project." and app.chats["LEAF-001"].log[0]["text"] == scripted.heard[0]["text"]
    git(app.root, "commit", "-qam", "Draft the guide")
    page.wait("state.model.uncommitted.length === 0")  # the page follows the repository
    page.eval(popup)
    assert page.eval(actions) == [["👀 Mark reviewed", False, ""]]
