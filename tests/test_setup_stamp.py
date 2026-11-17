# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""SYNGATE-TEST-SETUP-STAMP: the setup enters the canonical JSON only on an item carrying one."""

import pytest

import syngatelib


def make(setup=None):
    return syngatelib.Item(uid="VAULT-DEPOSIT", path=None, description="Deposit\n", parents=["VAULT"], tests={None: None}, setup=setup)


@pytest.mark.syngate("SYNGATE-TEST-SETUP-STAMP")
def test_setup_enters_the_stamp_only_on_an_item_carrying_one():
    plain = make()
    assert "setup" not in syngatelib.stamp_payload(plain)
    setup = {"run": "forge test", "files": ["test/**/*.t.sol"]}
    carrying = make(setup)
    assert syngatelib.stamp_payload(carrying)["setup"] == setup
    assert syngatelib.compute_stamp(carrying) != syngatelib.compute_stamp(plain)
    changed = make({"run": "forge test -vv", "files": ["test/**/*.t.sol"]})
    assert syngatelib.compute_stamp(changed) != syngatelib.compute_stamp(carrying)
    assert syngatelib.compute_stamp(make(dict(setup))) == syngatelib.compute_stamp(carrying)
