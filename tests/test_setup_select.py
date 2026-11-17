# Open Trader
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""SYNGATE-TEST-SETUP-SELECT: a setup's `run` line expands into the commands of the addressed bindings."""

import pytest

import testselect


def _binding(uid, binding, name, path, line):
    tag = f"[{uid}][{binding}]" if binding else f"[{uid}]"
    return {"uid": uid, "binding": binding, "tag": tag, "name": name, "path": path, "line": line}


@pytest.mark.syngate("SYNGATE-TEST-SETUP-SELECT")
def test_run_line_expands_into_commands_of_addressed_bindings():
    a = _binding("VAULT-DEPOSIT", "", "test_Deposit", "test/Vault.t.sol", 10)
    b = _binding("VAULT-WITHDRAW", "overdraw", "test_Overdraw", "test/Vault.t.sol", 30)
    c = _binding("VAULT-FEES", "", "test_Fees", "test/Fees.t.sol", 5)
    both, three = [a, b], [a, b, c]
    # plural placeholders: one command, a bare one becoming a word per value, a joined one a single word
    assert testselect.commands("pytest {ids}", both, "/p") == [(["pytest", "test/Vault.t.sol::test_Deposit", "test/Vault.t.sol::test_Overdraw"], both)]
    assert testselect.commands("forge test --match-test ^({names:|})$", both, "/p") == [(["forge", "test", "--match-test", "^(test_Deposit|test_Overdraw)$"], both)]
    assert testselect.commands('bin "{tags:,}"', both, "/p")[0][0] == ["bin", "[VAULT-DEPOSIT],[VAULT-WITHDRAW][overdraw]"]
    assert testselect.commands("run {uids}", both, "/p")[0][0] == ["run", "VAULT-DEPOSIT", "VAULT-WITHDRAW"]
    assert testselect.commands("jest {paths}", three, "/p")[0][0] == ["jest", "test/Vault.t.sol", "test/Fees.t.sol"]
    # singular placeholders: one command per binding
    one_by_one = testselect.commands("go test -run ^{name}$ -tags {binding} {path}:{line} {uid} {tag} {id}", both, "/p")
    assert one_by_one == [(["go", "test", "-run", "^test_Deposit$", "-tags", "", "test/Vault.t.sol:10", "VAULT-DEPOSIT", "[VAULT-DEPOSIT]",
                           "test/Vault.t.sol::test_Deposit"], [a]),
                          (["go", "test", "-run", "^test_Overdraw$", "-tags", "overdraw", "test/Vault.t.sol:30", "VAULT-WITHDRAW",
                            "[VAULT-WITHDRAW][overdraw]", "test/Vault.t.sol::test_Overdraw"], [b])]
    # no selection placeholder: the whole suite once, the addressed bindings still named
    assert testselect.commands("cargo test --quiet", both, "/p") == [(["cargo", "test", "--quiet"], both)]
    # {root} and {report} are plain substitutions, in any form of line
    assert testselect.commands("t --out {report} --cwd {root} {ids}", [a], "/p", "/tmp/r.xml")[0][0] == [
        "t", "--out", "/tmp/r.xml", "--cwd", "/p", "test/Vault.t.sol::test_Deposit"]
    assert testselect.commands("t {name} {report}", both, "/p", "/tmp/r.xml")[1][0] == ["t", "test_Overdraw", "/tmp/r.xml"]
    assert testselect.commands("t {report}", [a], "/p", "/tmp/r.xml") == [(["t", "/tmp/r.xml"], [a])]
    # words are split as a shell splits them
    assert testselect.commands("sh -c 'echo {names:+}'", both, "/p")[0][0] == ["sh", "-c", "echo test_Deposit+test_Overdraw"]
    # nothing addressed, nothing run
    assert testselect.commands("pytest {ids}", [], "/p") == []
    # refused lines
    for line in ("t {ids} {name}", "t {names:|} {uid}", "t {ids}x", "t {nonsense}", "t {name:,}", "   "):
        with pytest.raises(ValueError):
            testselect.commands(line, both, "/p")
    with pytest.raises(ValueError):
        testselect.commands("t {report}", both, "/p")
