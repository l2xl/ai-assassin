# Open Trader
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""SYNGATE-TEST-SETUP-KEY: the `test` key read as a setup with its bindings under `stamp`, told from bindings, written back as read."""

import pytest
import syngatelib

SHA = "ab" * 32


@pytest.mark.syngate("SYNGATE-TEST-SETUP-KEY")
def test_setup_mapping_key(syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root\n")
    setup = {"stamp": {"deposit": None, "overdraw": SHA}, "run": "forge test --match-test ^({names:|})$",
             "files": ["test/**/*.t.sol"], "report": "junit", "env": {"SEED": "0x01"}}
    make_item(syngate_dir, "WITH-SETUP", "With setup\n", parents=["ROOT"], tests=setup)
    make_item(syngate_dir, "ONLY-SETUP", "Only setup\n", parents=["ROOT"], tests={"run": "go test"})
    make_item(syngate_dir, "RUN-BINDING", "A binding named run\n", parents=["ROOT"], tests={"run": SHA, "other": None})
    make_item(syngate_dir, "PLAIN", "Plain\n", parents=["ROOT"], tests=None)
    make_item(syngate_dir, "UNKNOWN-KEY", "Unknown key\n", parents=["ROOT"], tests={"stamp": None, "bogus": 1})
    make_item(syngate_dir, "STAMP-NAME", "stamp as binding name\n", parents=["ROOT"], tests={"stamp": {"stamp": SHA}})
    items, errors = syngatelib.load_tree(syngate_dir)

    item = items["WITH-SETUP"]
    assert item.setup == {"run": setup["run"], "files": setup["files"], "report": "junit", "env": {"SEED": "0x01"}}
    assert item.tests == {"deposit": None, "overdraw": SHA}
    assert items["ONLY-SETUP"].setup == {"run": "go test"} and items["ONLY-SETUP"].tests is None
    assert items["RUN-BINDING"].setup is None and items["RUN-BINDING"].tests == {"run": SHA, "other": None}
    assert items["PLAIN"].setup is None
    assert any("invalid binding name 'stamp'" in error for error in errors)

    problems = [message for uid, message in syngatelib.layout_problems(items) if uid == "UNKNOWN-KEY"]
    assert any("bogus" in message for message in problems)
    assert items["UNKNOWN-KEY"].tests == {None: None}

    # written back as read: dump, reload, same fields
    for uid in ("WITH-SETUP", "ONLY-SETUP", "RUN-BINDING"):
        before = items[uid]
        syngatelib.write_item(before)
    again, _ = syngatelib.load_tree(syngate_dir)
    for uid in ("WITH-SETUP", "ONLY-SETUP", "RUN-BINDING"):
        assert (again[uid].setup, again[uid].tests) == (items[uid].setup, items[uid].tests)
    assert (syngate_dir / "WITH-SETUP.yml").read_text().count("stamp:") == 1
    assert "stamp" not in (syngate_dir / "RUN-BINDING.yml").read_text()
    assert again["UNKNOWN-KEY"].setup_extra == {"bogus": 1}
