# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""File measuring in the session (ORCHESTRATOR-TIER-KEEP, -UPDATE, -CHANGED, -FOR, -MISS): the kept system prompt, the context update heading
a later turn, a file changed by someone else, the `for` of a context call and the miss records of the server's memory."""

import json

import pytest

import assassin_ui
import syngatelib
import synthetic
from test_assassin_ui import app, call, server  # noqa: F401 -- the server fixtures of the page tests
from test_assassin_ui_api import Scripted, calls, turn

SMALL, BIG = "s" * 40, "b" * 400  # 10 and 100 tokens


class Hearing(Scripted):
    """A scripted connector keeping the system prompt of every dispatch too."""

    def __init__(self, *answers):
        super().__init__(*answers)
        self.contexts = []

    def dispatch(self, context, text, **kw):
        self.contexts.append(context)
        return super().dispatch(context, text, **kw)


def lay(app, budget, files):
    (app.root / "src").mkdir(exist_ok=True)
    for name, text in files.items():
        (app.root / "src" / name).write_text(text)
    app.settings_file.write_text(json.dumps({"orchestrator": {"budget": budget}}))


def leaf(app, uid, sources, text="It shall leaf.\n", parent="ROOT"):
    (app.syngate_dir / f"{uid}.yml").write_text(f"---\nparents: [{parent}]\nsources: [{', '.join(sources)}]\ntest: ~\n---\n{text}")


@pytest.mark.syngate("ORCHESTRATOR-TIER-KEEP")
def test_the_system_prompt_of_a_session_is_composed_once_with_its_files_as_measured_and_sent_unchanged(server):
    base, app = server
    lay(app, 50, {"small.py": SMALL, "big.py": BIG})
    leaf(app, "LEAF-001", ["src/small.py", "src/big.py"])
    app.connectors = {"echo": (echo := Hearing())}
    turn(base, app, "LEAF-001", "First", modes=["tree"])
    first = echo.contexts[0]
    assert f"# Source src/small.py\n````\n{SMALL}\n````" in first
    assert BIG not in first and "# Source src/big.py" not in first and "src/big.py (1 lines)" in first
    (app.root / "src" / "small.py").write_text("changed\n")
    leaf(app, "LEAF-001", ["src/small.py", "src/big.py"], text="It shall leaf otherwise.\n")
    leaf(app, "LEAF-002", ["src/small.py"], parent="LEAF-001")
    lay(app, 1000, {})
    turn(base, app, "LEAF-001", "Second", modes=["tree"])
    turn(base, app, "LEAF-001", "Third", modes=["tree"])
    assert echo.contexts == [first] * 3  # byte for byte, whatever changed on disk
    assert assassin_ui.Chat.restore("LEAF-001", app.chats["LEAF-001"].record()).keep["context"] == first
    call(base, app, "/api/chat/LEAF-001", {"reset": True})
    turn(base, app, "LEAF-001", "Fourth", modes=["tree"])
    assert echo.contexts[3] != first and "changed" in echo.contexts[3] and BIG in echo.contexts[3]  # a new session composes anew


@pytest.mark.syngate("ORCHESTRATOR-TIER-UPDATE")
def test_the_context_update_heads_the_next_prompt_with_what_changed_and_takes_no_file_back(server):
    base, app = server
    lay(app, 50, {"small.py": SMALL, "big.py": BIG})
    leaf(app, "LEAF-001", ["src/small.py", "src/big.py"])
    app.connectors = {"echo": (echo := Hearing())}
    turn(base, app, "LEAF-001", "First", modes=["tree"])
    root = app.syngate_dir / "ROOT.yml"
    root.write_text(root.read_text().replace("Root branch", "Root branch reworded"))
    leaf(app, "LEAF-002", [], text="Second leaf\nfollows.\n", parent="LEAF-001")
    lay(app, 1000, {})
    turn(base, app, "LEAF-001", "Second", modes=["tree"])
    heard = echo.heard[1]["text"]
    assert heard.startswith(synthetic.CONTEXT_UPDATE) and heard.endswith("\n\nSecond")
    assert "Item added:\n@LEAF-002\nSecond leaf" in heard and "Statement edited, it now reads:\n@ROOT\n" in heard and "reworded" in heard
    assert f"File brought in whole:\n# Source src/big.py\n````\n{BIG}" in heard
    assert echo.contexts[1] == echo.contexts[0]
    turn(base, app, "LEAF-001", "Third", modes=["tree"])
    assert echo.heard[2]["text"] == "Third"  # nothing changed since, nothing taken back


@pytest.mark.syngate("ORCHESTRATOR-TIER-CHANGED")
def test_a_file_changed_by_someone_else_is_named_in_the_update_and_not_resent(server):
    base, app = server
    lay(app, 1000, {"a.py": "a-old\n", "b.py": "b-old\n"})
    leaf(app, "LEAF-001", ["src/a.py", "src/b.py"])
    replace = {"tool": "replace", "path": "src/b.py", "old": "b-old", "new": "b-mine"}
    app.connectors = {"echo": (echo := Hearing({"kind": "text", "text": "ok"}, calls(replace)))}  # a batch without a query ends its turn
    turn(base, app, "LEAF-001", "First", modes=["tree"])
    (app.root / "src" / "a.py").write_text("a-theirs-NEW\n")
    turn(base, app, "LEAF-001", "Second", modes=["tree", "patch"])
    heard = echo.heard[1]["text"]
    assert heard.startswith(synthetic.CONTEXT_UPDATE) and "File changed by someone else" in heard and "src/a.py" in heard
    assert "a-theirs-NEW" not in heard and "src/b.py" not in heard
    assert (app.root / "src" / "b.py").read_text() == "b-mine\n"
    turn(base, app, "LEAF-001", "Third", modes=["tree"])
    assert echo.heard[2]["text"] == "Third"  # the session's own patch is no news, the other change was told once


def two_leaves(app, budget=120):
    lay(app, budget, {"a.py": "a" * 400, "b.py": "b" * 400})
    leaf(app, "LEAF-001", ["src/a.py"])
    leaf(app, "LEAF-002", ["src/b.py"])


@pytest.mark.syngate("ORCHESTRATOR-TIER-FOR")
def test_a_context_call_measures_its_files_against_its_for_text_else_the_message_and_the_cli_stays_unmeasured(server):
    base, app = server
    two_leaves(app)
    batch = calls({"tool": "context", "uid": "ROOT"}, {"tool": "context", "uid": "ROOT", "for": "look at a.py"})
    app.connectors = {"echo": (echo := Hearing(batch, {"kind": "text", "text": "read"}))}
    turn(base, app, "ROOT", "Fix b.py", modes=["tree"])
    by_message, by_for = echo.heard[1]["text"].split("- context of ROOT:\n")[1:]
    assert "# Source src/b.py" in by_message and "# Source src/a.py" not in by_message and "src/a.py (1 lines)" in by_message
    assert "# Source src/a.py" in by_for and "# Source src/b.py" not in by_for and "src/b.py (1 lines)" in by_for
    items, _ = syngatelib.load_tree(app.syngate_dir)
    unmeasured = synthetic.apply_call(items, "ROOT", {"tool": "context", "uid": "ROOT"}, syngate_dir=app.syngate_dir)
    assert "# Source src/a.py" in unmeasured and "# Source src/b.py" in unmeasured
    assert synthetic.seed_context(items, "ROOT", root=app.root).count("a" * 400) == 1  # what `syngate context` prints
    with pytest.raises(synthetic.protocol_error):
        synthetic.parse_reply(calls({"tool": "context", "uid": "ROOT", "for": " "}))


@pytest.mark.syngate("ORCHESTRATOR-TIER-MISS")
def test_a_heavy_file_the_session_reads_is_noted_in_memory_with_its_message_and_feeds_later_measurements(server):
    base, app = server
    two_leaves(app)
    read = lambda rel: {"tool": "read", "path": rel}
    app.connectors = {"echo": (echo := Hearing(calls(read("src/a.py"), read("src/b.py")), {"kind": "text", "text": "one"}))}
    turn(base, app, "ROOT", "Fix a.py", modes=["tree"])
    assert app.misses == [{"uid": "ROOT", "file": "src/b.py", "message": "Fix a.py"}]  # the whole a.py is no miss
    chat = app.chats["ROOT"]
    saved = app.chats_file.read_text() if app.chats_file.exists() else ""
    assert "misses" not in saved and "misses" not in json.dumps(chat.record())
    for message in chat.log:
        message.pop("steps", None)  # the miss note alone now tells of the read
    items, _ = syngatelib.load_tree(app.syngate_dir)
    assert synthetic.measure_seed(items, "ROOT", "Second", app.root, 120).whole == ["src/a.py"]  # without the note
    turn(base, app, "ROOT", "Second", modes=["tree"])
    assert f"File brought in whole:\n# Source src/b.py\n````\n{'b' * 400}" in echo.heard[2]["text"]
    assert assassin_ui.AssassinApp(root=app.root, syngate_dir=app.syngate_dir).misses == []  # a new run estimates from scratch
