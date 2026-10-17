# Open Trader
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The syngate tree calls in the core library, their command line spelling and
the AI wrapper that dispatches a structured answer into them.

Each call's semantics are covered once, against the core function; the command
line and the AI wrapper are covered once each, for the translation into a core
call alone -- not by replaying every call through all three surfaces.
"""

import argparse
import sys

import pytest
import yaml

import syngate
import syngatelib
import synthetic


def _tree(syngate_dir, make_item, features=("test", "review")):
    make_item(syngate_dir, "ROOT", "Root branch\n", parents=(), features=features)
    make_item(syngate_dir, "BRANCH", "It shall group.\n", parents=("ROOT",), order=10)
    make_item(syngate_dir, "LEAF-001", "It shall leaf.\n", parents=("ROOT",), order=20, tests=None)
    items, errors = syngatelib.load_tree(syngate_dir)
    assert errors == []
    return items


def _stamped(items, uid):
    items[uid].reviewed = syngatelib.item_stamp(items, uid)
    syngatelib.write_item(items[uid])
    return items[uid]


def _violated(items, uid):
    """Whether `uid`'s stamp is standing over content that has since moved."""
    return any(uid == flagged for flagged, _ in syngatelib.review_problems(items))


def _stored(syngate_dir, uid):
    return syngatelib.parse_item((syngate_dir / f"{uid}.yml").read_text())


@pytest.mark.syngate("SYNGATE-API-ADD")
def test_add_scaffolds_an_item_where_it_is_placed_and_refuses_an_unplaceable_one(syngate_tree):
    syngate_dir, make_item = syngate_tree
    items = _tree(syngate_dir, make_item)
    leaf = syngatelib.add_item(items, "LEAF-002", ["BRANCH"], description="Second\n\nIt shall follow.", sources=["src/leaf.py"],
                               folder="syngate/sub", syngate_dir=syngate_dir)
    assert leaf.path == syngate_dir / "sub" / "LEAF-002.yml" and leaf.title == "Second"
    assert syngatelib.parse_item(leaf.path.read_text()) == {"description": "Second\n\nIt shall follow.\n", "parents": ["BRANCH"],
                                                           "sources": ["src/leaf.py"], "test": None}
    assert items["LEAF-002"] is leaf  # a later call of the same batch sees it
    branch = syngatelib.add_item(items, "BRANCH-2", ["ROOT"], kind="branch", syngate_dir=syngate_dir)
    assert branch.tests is None and "test" not in _stored(syngate_dir, "BRANCH-2")
    for uid, parents, folder, sources in (("LEAF-002", ["ROOT"], None, None), ("not a uid", ["ROOT"], None, None), ("LEAF-003", [], None, None),
                                          ("LEAF-003", ["NOPE"], None, None), ("LEAF-003", ["ROOT"], "src", None),
                                          ("LEAF-003", ["ROOT"], None, ["../secret"]), ("LEAF-003", ["ROOT"], None, "src/leaf.py")):
        with pytest.raises(syngatelib.tree_error):
            syngatelib.add_item(items, uid, parents, folder=folder, sources=sources, syngate_dir=syngate_dir)
    assert sorted(p.stem for p in syngate_dir.rglob("*.yml")) == ["BRANCH", "BRANCH-2", "LEAF-001", "LEAF-002", "ROOT"]
    off = _tree(syngate_dir, make_item, features=("review",))  # the switch withholds the binding, not the item
    assert syngatelib.add_item(off, "LEAF-004", ["ROOT"], syngate_dir=syngate_dir).tests is None


@pytest.mark.syngate("SYNGATE-API-EDIT")
def test_edit_moves_the_named_fields_only_drops_the_stamp_and_never_clobbers_a_disk_edit(syngate_tree):
    syngate_dir, make_item = syngate_tree
    items = _tree(syngate_dir, make_item)
    item = _stamped(items, "LEAF-001")
    assert syngatelib.edit_item(items, "LEAF-001", {"order": 30}, clear=True)["order"] == 30
    assert item.reviewed and item.description == "It shall leaf.\n"  # order sits outside the stamp
    stored = syngatelib.edit_item(items, "LEAF-001", {"description": "Leafier\n\nIt shall leaf harder."}, clear=True)
    assert stored["description"] == "Leafier\n\nIt shall leaf harder.\n" and item.title == "Leafier"
    assert item.reviewed is None and item.tests == {None: None}
    assert _stored(syngate_dir, "LEAF-001") == {"description": "Leafier\n\nIt shall leaf harder.\n", "parents": ["ROOT"], "order": 30, "test": None}
    with pytest.raises(syngatelib.unknown_uid):
        syngatelib.edit_item(items, "NOPE-001", {"description": "x"})

    base = {"description": "Leafier\n\nIt shall leaf harder.\n"}
    items = syngatelib.load_tree(syngate_dir)[0]
    assert syngatelib.edit_item(items, "LEAF-001", {"sources": ["src/leaf.py", "src/leaf.py"]}, base=base)["sources"] == ["src/leaf.py"]  # another field moved: rebases silently
    assert _stored(syngate_dir, "LEAF-001")["sources"] == ["src/leaf.py"]
    items = syngatelib.load_tree(syngate_dir)[0]
    syngatelib.edit_item(items, "LEAF-001", {"description": "It shall leaf twice."}, base=base)
    items = syngatelib.load_tree(syngate_dir)[0]
    with pytest.raises(syngatelib.stale_edit) as clash:
        syngatelib.edit_item(items, "LEAF-001", {"description": "It shall leaf thrice."}, base=base)
    assert clash.value.current == {"description": "It shall leaf twice.\n"}
    assert _stored(syngate_dir, "LEAF-001")["description"] == "It shall leaf twice.\n"


@pytest.mark.syngate("SYNGATE-API-MOVE")
def test_move_adds_and_removes_parent_links_places_the_item_and_guards_the_dag(syngate_tree):
    syngate_dir, make_item = syngate_tree
    items = _tree(syngate_dir, make_item)
    item = _stamped(items, "LEAF-001")
    assert syngatelib.move_item(items, "LEAF-001", "BRANCH", source="ROOT", clear=True) == ["LEAF-001"]
    assert item.parents == ["BRANCH"] and item.reviewed is None  # a relink is an edit under the stamp
    syngatelib.move_item(items, "LEAF-001", "ROOT", link=True)
    assert item.parents == ["BRANCH", "ROOT"]  # link adds one more parent instead of re-pointing
    syngatelib.move_item(items, "LEAF-001", "ROOT", source="BRANCH")
    assert item.parents == ["ROOT"]  # naming a parent while another is the target drops the named one
    assert _stored(syngate_dir, "LEAF-001")["parents"] == ["ROOT"]
    for uid, to in (("ROOT", "BRANCH"), ("LEAF-001", "NOPE")):  # under its own descendant; under nothing
        with pytest.raises(syngatelib.tree_error):
            syngatelib.move_item(items, uid, to)
    with pytest.raises(syngatelib.unknown_uid):
        syngatelib.move_item(items, "NOPE-001", "ROOT")

    for uid, order in (("KID-A", 30), ("KID-B", 31), ("KID-C", 50)):
        make_item(syngate_dir, uid, "It shall sort.\n", parents=("ROOT",), order=order, tests=None)
    items = syngatelib.load_tree(syngate_dir)[0]
    assert syngatelib.move_item(items, "LEAF-001", "ROOT", before="KID-C") == ["LEAF-001"]
    assert items["LEAF-001"].order == 40  # a free key between the neighbours: one file written
    assert syngatelib.move_item(items, "LEAF-001", "ROOT", before="KID-C") == []  # already placed
    assert syngatelib.move_item(items, "KID-C", "ROOT", before="KID-B") == ["KID-A", "KID-B", "KID-C", "LEAF-001"]
    assert [items[uid].order for uid in ("KID-A", "KID-C", "KID-B", "LEAF-001")] == [20, 30, 40, 50]
    with pytest.raises(syngatelib.tree_error):
        syngatelib.move_item(items, "LEAF-001", "ROOT", before="KID-Z")


@pytest.mark.syngate("SYNGATE-API-DELETE")
def test_delete_removes_a_childless_item_only_and_unsettles_the_parent_it_left(syngate_tree):
    syngate_dir, make_item = syngate_tree
    items = _tree(syngate_dir, make_item)
    with pytest.raises(syngatelib.tree_error) as populated:
        syngatelib.delete_item(items, "ROOT")
    assert "still has children" in str(populated.value)

    make_item(syngate_dir, "BRANCH-001", "It shall be borne.\n", parents=("BRANCH",), tests=None)
    items = syngatelib.load_tree(syngate_dir)[0]
    branch = _stamped(items, "BRANCH")  # a test-bearing branch carries a stamp of its own
    assert not _violated(items, "BRANCH") and syngatelib.compute_stamp(branch) != branch.reviewed
    syngatelib.delete_item(items, "BRANCH-001")
    assert _violated(items, "BRANCH")  # it cannot stay approved over a subtree it has lost
    branch.reviewed = syngatelib.item_stamp(items, "BRANCH")
    syngatelib.add_item(items, "BRANCH-002", ["BRANCH"], syngate_dir=syngate_dir)
    assert _violated(items, "BRANCH")  # nor over one it has gained
    branch.reviewed = syngatelib.item_stamp(items, "BRANCH")
    syngatelib.delete_item(items, "BRANCH-002", clear=True)
    assert branch.reviewed is None and not _violated(items, "BRANCH")  # the user's own delete clears instead

    assert syngatelib.delete_item(items, "LEAF-001") == syngate_dir / "LEAF-001.yml"
    assert not (syngate_dir / "LEAF-001.yml").exists() and "LEAF-001" not in items
    with pytest.raises(syngatelib.unknown_uid):
        syngatelib.delete_item(items, "LEAF-001")


@pytest.mark.syngate("SYNGATE-API-TEST")
def test_a_run_addresses_the_test_bearing_items_below_and_runs_whichever_way_the_switch_sits(monkeypatch, tmp_path, syngate_tree):
    syngate_dir, make_item = syngate_tree
    items = _tree(syngate_dir, make_item)
    make_item(syngate_dir, "LEAF-002", "It shall nest.\n", parents=("BRANCH",), tests=None)
    items = syngatelib.load_tree(syngate_dir)[0]
    assert syngatelib.leaves_under(items, "ROOT") == ["LEAF-002", "LEAF-001"]
    assert syngatelib.leaves_under(items, "LEAF-001") == ["LEAF-001"]
    assert syngatelib.leaves_under(items, "NOPE-001") == ["NOPE-001"]  # the addressed command judges a typo

    make_item(syngate_dir, "ROOT", "Root branch\n", parents=(), features=("review",))
    make_item(syngate_dir, "LEAF-001", "It shall leaf.\n", parents=("ROOT",), order=20)
    make_item(syngate_dir, "LEAF-002", "It shall not be awaited.\n", parents=("BRANCH",))
    items = syngatelib.load_tree(syngate_dir)[0]
    assert syngatelib.leaves_under(items, "ROOT") == ["LEAF-002", "LEAF-001"]  # with the switch off, the childless ones

    located = {("LEAF-001", None): [syngatelib.Location("tests/test_leaf.py", 1, "tests/test_leaf.py::test_one", "")]}
    runs = []
    monkeypatch.setattr(syngatelib, "load_tree", lambda: (items, []))
    monkeypatch.setattr(syngatelib, "discover_bindings", lambda: located)
    monkeypatch.setattr(syngate.subprocess, "run", lambda argv, **kwargs: runs.append(argv) or argparse.Namespace(returncode=0))
    assert syngate.cmd_test(argparse.Namespace(uid=["LEAF-001"], build_dir=str(tmp_path), coverage_out=None)) == 0
    assert runs == [[sys.executable, "-m", "pytest", "tests/test_leaf.py::test_one"]]  # the switch withholds enforcement, never the run
    assert syngate.cmd_test(argparse.Namespace(uid=["LEAF-002"], build_dir=str(tmp_path), coverage_out=None)) == 0
    assert len(runs) == 1  # nothing tagged for it, and with the switch off nothing was awaited


@pytest.mark.syngate("SYNGATE-API-REVIEW")
def test_review_is_closed_by_its_own_switch_and_stamps_where_the_test_switch_is_off(monkeypatch, capsys, tmp_path, syngate_tree):
    syngate_dir, make_item = syngate_tree
    load_tree = syngatelib.load_tree
    make_item(syngate_dir, "ROOT", "Root branch\n", parents=(), features=())
    make_item(syngate_dir, "LEAF-001", "It shall leaf.\n", parents=("ROOT",))
    items = load_tree(syngate_dir)[0]
    monkeypatch.setattr(syngatelib, "load_tree", lambda: (items, []))
    monkeypatch.setattr(syngatelib, "discover_bindings", lambda: {})
    args = argparse.Namespace(uid=["LEAF-001"], build_dir=str(tmp_path), coverage_out=None)
    assert syngate.cmd_review(args) == 1 and syngate.cmd_clear(argparse.Namespace(uid=["LEAF-001"])) == 1
    assert capsys.readouterr().err.count("the tree's review feature is off") == 2

    make_item(syngate_dir, "ROOT", "Root branch\n", parents=(), features=("review",))
    items = load_tree(syngate_dir)[0]
    monkeypatch.setattr(syngatelib, "load_tree", lambda: (items, []))
    written = []
    monkeypatch.setattr(syngatelib, "write_item", written.append)
    assert syngate.cmd_review(args) == 0  # the test switch withholds routine stamping alone
    assert [(item.uid, item.tests, item.reviewed == syngatelib.compute_stamp(item)) for item in written] == [("LEAF-001", None, True)]




@pytest.fixture
def cli(tmp_path, syngate_tree, monkeypatch):
    """Drive the CLI against a scratch tree, restoring the module's bound root."""
    syngate_dir, make_item = syngate_tree
    _tree(syngate_dir, make_item)
    bound = (syngatelib.ROOT, syngatelib.SYNGATE_DIR)

    def run(*argv):
        monkeypatch.setattr(sys, "argv", ["syngate", "--root", str(tmp_path), *argv])
        return syngate.main()

    yield run, syngate_dir
    syngatelib.ROOT, syngatelib.SYNGATE_DIR = bound


@pytest.mark.syngate("SYNGATE-API")
def test_every_tree_call_is_reachable_from_the_command_line(cli, capsys):
    run, syngate_dir = cli
    assert run("add", "LEAF-002", "--parent", "BRANCH", "--description", "Second\n\nIt shall follow.", "--source", "src/leaf.py") == 0
    assert _stored(syngate_dir, "LEAF-002") == {"description": "Second\n\nIt shall follow.\n", "parents": ["BRANCH"],
                                                "sources": ["src/leaf.py"], "test": None}
    assert run("edit", "LEAF-002", "--description", "Second thoughts\n\nIt shall follow.", "--source", "src/leaf.py", "--source", "docs/LEAF.md") == 0
    assert _stored(syngate_dir, "LEAF-002")["description"] == "Second thoughts\n\nIt shall follow.\n"
    assert _stored(syngate_dir, "LEAF-002")["sources"] == ["src/leaf.py", "docs/LEAF.md"]
    assert run("move", "LEAF-002", "--to", "ROOT", "--link") == 0
    assert _stored(syngate_dir, "LEAF-002")["parents"] == ["BRANCH", "ROOT"]
    assert run("move", "LEAF-002", "--to", "ROOT", "--from", "BRANCH") == 0
    assert _stored(syngate_dir, "LEAF-002")["parents"] == ["ROOT"]
    assert run("delete", "LEAF-002") == 0 and not (syngate_dir / "LEAF-002.yml").exists()
    capsys.readouterr()
    assert run("delete", "ROOT") == 1  # a refusal is reported, not raised
    assert run("edit", "LEAF-001") == 1
    err = capsys.readouterr().err
    assert "still has children" in err and "nothing to edit" in err


@pytest.mark.syngate("SYNGATE-API-QUERY")
def test_query_reads_an_item_with_its_children_in_sibling_order_and_its_kind(cli, capsys):
    run, syngate_dir = cli
    items, _ = syngatelib.load_tree(syngate_dir)
    root = synthetic.item_view(items, "ROOT")
    assert (root["uid"], root["description"], root["parents"], root["children"]) == ("ROOT", "Root branch\n", [], ["BRANCH", "LEAF-001"])
    assert synthetic.item_view(items, "BRANCH") == {"uid": "BRANCH", "description": "It shall group.\n", "parents": ["ROOT"], "sources": [], "children": [], "kind": "branch"}
    assert (synthetic.item_view(items, "LEAF-001")["kind"], synthetic.item_view(items, "LEAF-001")["tests"]) == ("leaf", [""])  # the default binding
    items["LEAF-001"].tests = {"api": None, "page": None}
    assert synthetic.item_view(items, "LEAF-001")["tests"] == ["api", "page"]
    with pytest.raises(syngatelib.unknown_uid):
        synthetic.item_view(items, "LEAF-009")
    line = synthetic.apply_call(items, "ROOT", {"tool": "query", "uid": "@"})
    assert line.startswith("- ROOT: ") and yaml.safe_load(line.removeprefix("- ROOT: ")) == root
    capsys.readouterr()
    assert run("query", "ROOT") == 0 and yaml.safe_load(capsys.readouterr().out) == root
    assert run("query", "LEAF-009") == 1


@pytest.mark.syngate("SYNGATE-API-CONTEXT")
def test_context_reads_the_seed_an_exchange_anchored_at_the_item_is_formed_from(cli, capsys):
    run, syngate_dir = cli
    items, _ = syngatelib.load_tree(syngate_dir)
    seed = synthetic.seed_context(items, "LEAF-001")
    assert seed.startswith(synthetic.PROMPTS[synthetic.DEFAULT_PROMPT]) and seed.endswith("Root branch\nIt shall leaf.\n")
    assert synthetic.apply_call(items, "ROOT", {"tool": "context", "uid": "LEAF-001"}) == f"- context of LEAF-001:\n{seed}"
    with pytest.raises(syngatelib.unknown_uid):
        synthetic.seed_context(items, "LEAF-009")
    capsys.readouterr()
    assert run("context", "LEAF-001") == 0 and capsys.readouterr().out == seed
    assert run("context", "LEAF-009") == 1
