# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""SYNGATE-TEST-SETUP-TAG: the comment tag binds the routine standing under it in any text file of a setup's `files`."""

import pytest

import syngatelib
import testtags


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.mark.syngate("SYNGATE-TEST-SETUP-TAG")
def test_comment_tag_binds_the_routine_under_it(tmp_path):
    write(tmp_path, "test/Vault.t.sol", """contract VaultTest {
    // syngate: VAULT-DEPOSIT
    function test_Deposit() public {
        vault.deposit(1);
        assertEq(vault.balance(), 1);
    }

    /// @custom:syngate VAULT-WITHDRAW overdraw
    // an ordinary comment between the tag and the head
    function test_Overdraw(
        uint256 a
    ) public {
        vault.withdraw(a);
    }
}
""")
    write(tmp_path, "web/vault.spec.js", """describe("vault", () => {
  // syngate: VAULT-DEPOSIT mints
  // syngate: VAULT-SHARES
  it("mints shares", () => {
    expect(1).toBe(1);
  });
});
/* syngate: VAULT-CLOSED */
func TestClosed(t *testing.T) {
}
""")
    write(tmp_path, "other/skipped.txt", "# syngate: VAULT-SKIPPED\nfn skipped() {}\n")
    found, problems = testtags.comment_locations(tmp_path, ["test/**/*.t.sol", "web/*.js"])
    assert problems == []
    assert set(found) == {("VAULT-DEPOSIT", None), ("VAULT-WITHDRAW", "overdraw"), ("VAULT-DEPOSIT", "mints"), ("VAULT-SHARES", None), ("VAULT-CLOSED", None)}

    (deposit,) = found[("VAULT-DEPOSIT", None)]
    assert (deposit.path, deposit.line, deposit.routine, deposit.name) == ("test/Vault.t.sol", 2, "test_Deposit", "test/Vault.t.sol::test_Deposit")
    # the span runs from the tag to the closing bracket at the head's indent, and no further
    assert deposit.span == "    // syngate: VAULT-DEPOSIT\n    function test_Deposit() public {\n        vault.deposit(1);\n        assertEq(vault.balance(), 1);\n    }\n"

    # a head spread over lines closes at the bracket line of its signature and runs on to its own closing line
    (overdraw,) = found[("VAULT-WITHDRAW", "overdraw")]
    assert overdraw.routine == "test_Overdraw" and overdraw.line == 8
    assert overdraw.span.endswith("        vault.withdraw(a);\n    }\n") and ") public {" in overdraw.span

    # the name is the first string literal of the head when that is its first argument
    (mints,), (shares,) = found[("VAULT-DEPOSIT", "mints")], found[("VAULT-SHARES", None)]
    assert mints.routine == shares.routine == "mints shares"
    assert (mints.line, shares.line) == (2, 3) and mints.span != shares.span  # several tags over one head bind it several times
    assert mints.span.endswith("  });\n") and not mints.span.endswith("});\n});\n")

    # the identifier in front of the first `(`, with a blank-closed body and a tag closed by `*/`
    (closed,) = found[("VAULT-CLOSED", None)]
    assert closed.routine == "TestClosed" and closed.span == "/* syngate: VAULT-CLOSED */\nfunc TestClosed(t *testing.T) {\n}\n"

    # files the globs do not match are not read
    assert not any(uid == "VAULT-SKIPPED" for uid, _ in found)

    # a head with neither a string nor a `(`, and a tag with nothing under it, are problems of their binding
    write(tmp_path, "bad/a.txt", "# syngate: BAD-HEAD\nlet x = 1\n")
    write(tmp_path, "bad/b.txt", "# syngate: BAD-END\n\n# only comments\n")
    found, problems = testtags.comment_locations(tmp_path, ["bad/*.txt"])
    assert found == {}
    assert sorted(uid for uid, _ in problems) == ["BAD-END", "BAD-HEAD"]
    assert all(message.startswith(f"{uid}: bad/") for uid, message in problems)

    # a tag whose binding is no binding name, or whose UID is no UID, binds nothing
    write(tmp_path, "bad/c.txt", "# syngate: lower-case\nfn a() {}\n# syngate: VAULT-X Bad\nfn b() {}\n")
    assert testtags.comment_locations(tmp_path, ["bad/c.txt"]) == ({}, [])
    assert all(isinstance(location, syngatelib.Location) for locations in found.values() for location in locations)
