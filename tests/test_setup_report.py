# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Tests for SYNGATE-TEST-SETUP-REPORT: the report discovery of the test setup."""

import json

import pytest

import testreport

JUNIT = """build noise
<?xml version="1.0"?>
<testsuites><testsuite name="s" file="test/vault.t.sol">
  <testcase classname="VaultTest" name="test_Deposit()"/>
  <testcase classname="VaultTest" name="test_Withdraw"><failure message="boom">trace</failure></testcase>
  <testcase classname="OtherTest" name="test_Skipped"><skipped/></testcase>
  <testcase classname="tests.test_a" name="same[1]"/>
  <testcase classname="tests.test_b" name="same"><error message="bad"/></testcase>
</testsuite></testsuites>
trailing noise"""

TAP = """TAP version 13
1..3
ok 1 - mints shares
not ok 2 - burns shares
  ---
  message: expected 1
  ...
ok 3 - waits # SKIP no network
"""

CTRF = "noise " + json.dumps({"results": {"tests": [
    {"name": "mints shares", "status": "passed", "filePath": "test/vault.test.js", "suite": ["vault"]},
    {"name": "burns shares", "status": "failed", "message": "nope"},
    {"name": "waits", "status": "skipped"}]}})


def _binding(uid, name, path, binding=None):
    return {"uid": uid, "binding": binding, "tag": f"[{uid}]", "name": name, "path": path, "line": 1}


@pytest.mark.syngate("SYNGATE-TEST-SETUP-REPORT")
def test_report_discovery_joins_results_by_name():
    """JUnit, TAP and CTRF are told by content, joined by routine name; a skipped test and a binding without a result fail."""
    junit = testreport.parse(JUNIT)
    assert testreport.detect(JUNIT) == "junit" and testreport.detect(TAP) == "tap" and testreport.detect(CTRF) == "ctrf"
    assert [(r["name"], r["passed"]) for r in junit] == [("test_Deposit()", True), ("test_Withdraw", False), ("test_Skipped", False),
                                                       ("same[1]", True), ("same", False)]
    assert junit[1]["log"].startswith("failure: boom") and junit[0]["classname"] == "VaultTest" and junit[0]["file"] == "test/vault.t.sol"
    tap = testreport.parse(TAP)
    assert [(r["name"], r["passed"]) for r in tap] == [("mints shares", True), ("burns shares", False), ("waits", False)]
    assert "expected 1" in tap[1]["log"] and "skip" in tap[2]["log"]
    ctrf = testreport.parse(CTRF)
    assert [(r["name"], r["passed"]) for r in ctrf] == [("mints shares", True), ("burns shares", False), ("waits", False)]
    assert ctrf[0]["file"] == "test/vault.test.js" and ctrf[0]["classname"] == "vault" and "nope" in ctrf[1]["log"]
    assert testreport.parse("nothing here") == [] and testreport.parse(JUNIT, format="tap") == [] and testreport.parse(TAP, "tap") == tap

    bindings = [_binding("VAULT-DEPOSIT", "test_Deposit", "test/vault.t.sol"), _binding("VAULT-WITHDRAW", "test_Withdraw", "test/vault.t.sol"),
                _binding("VAULT-WITHDRAW", "test_Withdraw", "test/vault.t.sol", "again"), _binding("VAULT-SKIP", "test_Skipped", "test/o.t.sol"),
                _binding("VAULT-LOST", "test_Lost", "test/vault.t.sol")]
    joined = testreport.join(junit, bindings)
    assert [r["name"] for r in joined[("VAULT-DEPOSIT", None)]] == ["test_Deposit()"]  # a (…) signature follows the name
    assert joined[("VAULT-WITHDRAW", None)] == joined[("VAULT-WITHDRAW", "again")] == [junit[1]]  # one head bound twice
    assert testreport.verdict(joined[("VAULT-DEPOSIT", None)])[0] and not testreport.verdict(joined[("VAULT-WITHDRAW", None)])[0]
    assert not testreport.verdict(joined[("VAULT-SKIP", None)])[0]  # a skipped test did not run
    assert joined[("VAULT-LOST", None)] == [] and testreport.verdict([], "tail of the output") == (False, "no result\ntail of the output")

    twins = [_binding("A-ONE", "same", "tests/test_a.py"), _binding("B-ONE", "same", "tests/test_b.py")]
    shared = testreport.join(junit, twins)  # two routines of one name: the class names the file stem
    assert shared[("A-ONE", None)] == [junit[3]] and shared[("B-ONE", None)] == [junit[4]]
    assert testreport.join(junit, [_binding("X-ONE", "test_Depos", "test/vault.t.sol")])[("X-ONE", None)] == []  # no prefix match
    assert testreport.join([{"name": "other", "classname": "", "file": "", "passed": True, "log": ""}], bindings[:1])[("VAULT-DEPOSIT", None)] == []
    several = [_result for _result in junit if _result["name"] == "test_Withdraw"] * 2
    assert not testreport.verdict(testreport.join(several + [dict(several[0], passed=True)], bindings[1:2])[("VAULT-WITHDRAW", None)])[0]
