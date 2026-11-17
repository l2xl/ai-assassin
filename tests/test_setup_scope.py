# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""SYNGATE-TEST-SETUP-SCOPE: a setup holds for its item and everything below up to the next setup, switches the test feature on
where the parents hand it off, and an item its parents hand different setups, carrying none itself, is a layout problem."""

import pytest

import syngatelib

FORGE = {"run": "forge test --match-test ^({names:|})$", "files": ["test/**/*.t.sol"]}
JEST = {"run": "npx jest -t {name}", "files": ["web/**/*.js"]}


@pytest.mark.syngate("SYNGATE-TEST-SETUP-SCOPE")
def test_setup_scope(syngate_tree):
    syngate_dir, make_item = syngate_tree
    syngate_dir = syngate_dir / "scope"
    make_item(syngate_dir, "ROOT", "root")
    make_item(syngate_dir, "FORGE", "contracts", parents=["ROOT"], tests=FORGE)
    make_item(syngate_dir, "FORGE-VAULT", "vault", parents=["FORGE"], tests=None)
    make_item(syngate_dir, "FORGE-WEB", "web", parents=["FORGE-VAULT"], tests=dict(JEST, stamp={"page": None}))
    make_item(syngate_dir, "FORGE-WEB-PAGE", "page", parents=["FORGE-WEB"], tests=None)
    make_item(syngate_dir, "PLAIN", "plain", parents=["ROOT"])
    make_item(syngate_dir, "TWICE", "one setup through two parents", parents=["FORGE-VAULT", "FORGE"], tests=None)
    make_item(syngate_dir, "MIXED", "two setups, the first parent's taken", parents=["FORGE", "PLAIN"], tests=None)
    make_item(syngate_dir, "MIXED-UNDER", "below the mixed one", parents=["MIXED"], tests=None)
    make_item(syngate_dir, "MIXED-PLAIN", "two setups, the built-in one first", parents=["PLAIN", "FORGE"], tests=None)
    make_item(syngate_dir, "OWNED", "two setups, its own over both", parents=["FORGE", "PLAIN"], tests=JEST)
    items, errors = syngatelib.load_tree(syngate_dir)
    assert errors == []

    scopes = syngatelib.setup_scopes(items)
    assert scopes == {"ROOT": None, "PLAIN": None, "FORGE": "FORGE", "FORGE-VAULT": "FORGE", "TWICE": "FORGE",
                      "FORGE-WEB": "FORGE-WEB", "FORGE-WEB-PAGE": "FORGE-WEB", "OWNED": "OWNED",
                      "MIXED": "FORGE", "MIXED-UNDER": "FORGE", "MIXED-PLAIN": None}
    assert syngatelib.layout_problems(items) == []  # different setups through the parents are no layout problem

    # a setup switches the test feature on where the parents hand it off
    syngate_dir = syngate_dir.parent / "switch"
    make_item(syngate_dir, "ROOT", "root", features=("review",))
    make_item(syngate_dir, "DOCS", "untested", parents=["ROOT"])
    make_item(syngate_dir, "FORGE", "contracts", parents=["ROOT"], tests=FORGE)
    make_item(syngate_dir, "FORGE-VAULT", "vault", parents=["FORGE"], tests=None)
    items, errors = syngatelib.load_tree(syngate_dir)
    assert errors == []
    scopes, problems = syngatelib.feature_scopes(items)
    assert problems == [] and syngatelib.layout_problems(items) == []
    assert [scopes[uid]["test"] for uid in ("ROOT", "DOCS", "FORGE", "FORGE-VAULT")] == [False, False, True, True]

    # under an item that already switches the feature it is the override nested in an override
    syngate_dir = syngate_dir.parent / "nested"
    make_item(syngate_dir, "ROOT", "root")
    make_item(syngate_dir, "OFF", "switched off", parents=["ROOT"], tests="disabled")
    make_item(syngate_dir, "OFF-FORGE", "contracts", parents=["OFF"], tests=FORGE)
    items, errors = syngatelib.load_tree(syngate_dir)
    assert errors == []
    problems = syngatelib.layout_problems(items)
    assert [uid for uid, _ in problems] == ["OFF-FORGE"]
    assert "test setup" in problems[0][1] and "one override per path" in problems[0][1]
