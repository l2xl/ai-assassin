# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""SYNGATE-TEST-SETUP-EDIT: `syngate edit` and the edit call write the item's setup, its bindings moving under `stamp`."""

import sys

import pytest

import syngate
import syngatelib
import synthetic


@pytest.mark.syngate("SYNGATE-TEST-SETUP-EDIT")
def test_cli_flags_and_edit_call_write_the_setup_with_bindings_under_stamp(tmp_path, syngate_tree, monkeypatch, capsys):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root\n")
    make_item(syngate_dir, "LEAF", "Leaf\n", parents=["ROOT"], tests=None)
    monkeypatch.setattr(syngatelib, "ROOT", syngatelib.ROOT)
    monkeypatch.setattr(syngatelib, "SYNGATE_DIR", syngatelib.SYNGATE_DIR)

    def cli(*argv):
        monkeypatch.setattr(sys, "argv", ["syngate", "--root", str(tmp_path), "edit", "LEAF", *argv])
        code = syngate.main()
        capsys.readouterr()
        items, errors = syngatelib.load_tree(syngate_dir)
        assert not errors
        return code, items["LEAF"]

    # the flags write the whole setup; the binding the item had moves under `stamp` in its file
    code, leaf = cli("--run", "forge test --match-test ^({names:|})$", "--files", "test/**/*.t.sol", "--files", "more/**",
                     "--report", "junit", "--env", "A=1", "--env", "B=x=y")
    assert code == 0
    assert leaf.setup == {"run": "forge test --match-test ^({names:|})$", "files": ["test/**/*.t.sol", "more/**"], "report": "junit",
                          "env": {"A": "1", "B": "x=y"}}
    assert leaf.tests == {None: None}
    text = (syngate_dir / "LEAF.yml").read_text(encoding="utf-8")
    assert "stamp:" in text and "run:" in text

    # a setup given again replaces the item's whole
    code, leaf = cli("--run", "go test")
    assert code == 0 and leaf.setup == {"run": "go test"} and leaf.tests == {None: None}

    # refused combinations change nothing
    for refused in (["--files", "a/**"], ["--report", "tap"], ["--env", "A=1"], ["--no-setup", "--run", "x"], ["--run", "x", "--env", "nokey"]):
        code, leaf = cli(*refused)
        assert code == 1 and leaf.setup == {"run": "go test"}

    # --no-setup removes it, the bindings kept
    code, leaf = cli("--no-setup")
    assert code == 0 and leaf.setup is None and leaf.tests == {None: None}
    assert "stamp:" not in (syngate_dir / "LEAF.yml").read_text(encoding="utf-8")

    # the edit call: a setup alone is a whole edit, query reads it back, null removes it
    items, _ = syngatelib.load_tree(syngate_dir)
    setup = {"run": "cargo test {names}", "files": ["src/**/*.rs"], "report": "tap", "env": {"K": "$KEY"}}
    call = {"tool": "edit", "uid": "LEAF", "setup": setup}
    assert synthetic.parse_reply({"kind": "calls", "calls": [call]}) == ("calls", [call])
    before = syngatelib.item_stamp(items, "LEAF")
    assert synthetic.apply_call(items, "ROOT", call, syngate_dir=syngate_dir) == "- edited LEAF"
    assert items["LEAF"].setup == setup and items["LEAF"].tests == {None: None}
    assert synthetic.item_view(items, "LEAF")["setup"] == setup and "setup" not in synthetic.item_view(items, "ROOT")
    assert syngatelib.item_stamp(items, "LEAF") != before
    reloaded, errors = syngatelib.load_tree(syngate_dir)
    assert not errors and reloaded["LEAF"].setup == setup and reloaded["LEAF"].tests == {None: None}
    for bad in ({"run": "x", "shell": True}, {"files": ["a"]}, {"run": "x", "report": "xml"}, {"run": "x", "env": {"K": 1}}):
        with pytest.raises(syngatelib.tree_error):
            synthetic.apply_call(items, "ROOT", {"tool": "edit", "uid": "LEAF", "setup": bad}, syngate_dir=syngate_dir)
    assert items["LEAF"].setup == setup
    removal = {"tool": "edit", "uid": "LEAF", "setup": None}
    assert synthetic.parse_reply({"kind": "calls", "calls": [removal]}) == ("calls", [removal])
    assert synthetic.apply_call(items, "ROOT", removal, syngate_dir=syngate_dir) == "- edited LEAF"
    assert items["LEAF"].setup is None and "setup" not in synthetic.item_view(items, "LEAF")
    assert syngatelib.item_stamp(items, "LEAF") == before
