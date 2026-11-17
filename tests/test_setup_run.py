# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""SYNGATE-TEST-SETUP-RUN: `syngate test` and `review` find the routines over the files of all setups and run each by its setup's command."""

import argparse
import json
import shlex
import subprocess
import sys

import pytest

import syngate
import syngatelib

RUNNER = '''import json, os, sys
mode, args = sys.argv[1], sys.argv[2:]
select = [json.loads(line) for line in open(os.environ["SYNGATE_SELECT_FILE"])]
with open("runs.jsonl", "a") as log:  # a relative path: the command runs in the project root
    log.write(json.dumps({"mode": mode, "args": args, "token": os.environ.get("TOKEN"), "report": os.environ["SYNGATE_REPORT_FILE"],
                          "select": [[s["uid"], s["binding"], s["name"]] for s in select]}) + "\\n")
if mode == "junit":
    open(args[0], "w").write('<testsuite><testcase name="test_Deposit()"/><testcase name="test_Withdraw"><failure message="short"/></testcase>'
                              '<testcase name="test_Nobody"><failure message="stray"/></testcase></testsuite>')
    print("ok 1 - test_Lost")  # never read: the report file holds results
elif mode == "tap":
    print("ok 1 - mints shares\\nnot ok 2 - burns shares")
elif mode == "coverage":
    with open(os.environ["SYNGATE_COVERAGE_FILE"], "a") as out:
        out.writelines(json.dumps({"tags": [uid], "passed": uid != "RUN-NOBODY", "name": "emitted"}) + "\\n" for uid in args + ["RUN-NOBODY"])
    sys.exit(1)  # the records tell the outcome, not the exit status
else:
    print("checked", args[0])
    sys.exit(0 if args[0] == "check_ok" else 3)
'''

FILES = {
    "tools/run.py": RUNNER,
    "contracts/Vault.t.sol": "contract VaultTest {\n    // syngate: RUN-VAULT-DEPOSIT\n    function test_Deposit() public {}\n\n"
                             "    // syngate: RUN-VAULT-WITHDRAW overdraw\n    function test_Withdraw() public {}\n\n"
                             "    // syngate: RUN-VAULT-LOST\n    function test_Lost() public {}\n\n"
                             "    // syngate: RUN-NOBODY\n    function test_Nobody() public {}\n}\n// syngate: RUN-NOBODY stray\n",
    "contracts/events.txt": "# syngate: RUN-VAULT-EVENTS\ncheck_events()\n",
    "contracts/gone.txt": "# syngate: RUN-GONE\ncheck_gone()\n",
    "checks/checks.py": '@pytest.mark.syngate("RUN-CHECK-OK")\ndef check_ok():\n    pass\n\n\n@pytest.mark.syngate("RUN-CHECK-BAD")\ndef check_bad():\n    pass\n',
    "tests/test_plain.py": '@pytest.mark.syngate("RUN-PLAIN")\ndef test_plain():\n    pass\n',
    "native/vault.cpp": 'TEST_CASE("mints shares", "[RUN-NATIVE-MINTS]") {}\nTEST_CASE("burns shares", "[RUN-NATIVE-BURNS]") {}\n',
}


def _project(root, make_item):
    """A project of five setups around a built-in leaf: a report file, coverage records (nested), the exit status one by one, a whole suite in TAP, a command that cannot start;
    a leaf no routine is tagged for, and tags, records and results naming RUN-NOBODY, no item of the tree."""
    for rel, text in FILES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    run, tree = f"{shlex.quote(sys.executable)} tools/run.py", root / "syngate"
    make_item(tree, "RUN", "root\n", header="Run")
    make_item(tree, "RUN-PLAIN", "plain\n", parents=("RUN",), tests=None)
    make_item(tree, "RUN-VAULT", "vault\n", parents=("RUN",), tests={"run": run + " junit {report} ^({names:|})$", "files": ["contracts/*.sol"], "env": {"TOKEN": "$RUN_SECRET"}})
    make_item(tree, "RUN-VAULT-DEPOSIT", "deposit\n", parents=("RUN-VAULT",), tests=None)
    make_item(tree, "RUN-VAULT-WITHDRAW", "withdraw\n", parents=("RUN-VAULT",), tests={"overdraw": None})
    make_item(tree, "RUN-VAULT-LOST", "lost\n", parents=("RUN-VAULT",), tests=None)
    make_item(tree, "RUN-VAULT-UNTAGGED", "untagged\n", parents=("RUN-VAULT",), tests=None)
    make_item(tree, "RUN-VAULT-EVENTS", "events\n", parents=("RUN-VAULT",), tests={"stamp": None, "run": run + " coverage {uids}", "files": ["contracts/events.txt"]})
    make_item(tree, "RUN-CHECK", "check\n", parents=("RUN",), tests={"run": run + " exit {name} '$HOME;*'", "files": ["checks/*.py", "tests/*.py"]})
    make_item(tree, "RUN-CHECK-OK", "ok\n", parents=("RUN-CHECK",), tests=None)
    make_item(tree, "RUN-CHECK-BAD", "bad\n", parents=("RUN-CHECK",), tests=None)
    make_item(tree, "RUN-NATIVE", "native\n", parents=("RUN",), tests={"run": run + " tap", "files": ["native/*.cpp"]})
    make_item(tree, "RUN-NATIVE-MINTS", "mints\n", parents=("RUN-NATIVE",), tests=None)
    make_item(tree, "RUN-NATIVE-BURNS", "burns\n", parents=("RUN-NATIVE",), tests=None)
    make_item(tree, "RUN-GONE", "gone\n", parents=("RUN",), tests={"stamp": None, "run": "no-such-runner-of-syngate {names}", "files": ["contracts/gone.txt"]})


@pytest.mark.syngate("SYNGATE-TEST-SETUP-RUN")
def test_bindings_run_by_the_command_of_the_setup_holding_for_their_item(monkeypatch, tmp_path, syngate_tree):
    syngate_dir, make_item = syngate_tree
    _project(tmp_path, make_item)
    monkeypatch.setattr(syngatelib, "ROOT", tmp_path)
    monkeypatch.setattr(syngatelib, "SYNGATE_DIR", syngate_dir)
    monkeypatch.setenv("RUN_SECRET", "s3")
    monkeypatch.delenv("TOKEN", raising=False)
    calls, run = [], subprocess.run

    def recorded(argv, **kwargs):
        calls.append((argv, kwargs))
        return argparse.Namespace(returncode=0) if argv[1:3] == ["-m", "pytest"] else run(argv, **kwargs)

    monkeypatch.setattr(syngate.subprocess, "run", recorded)
    coverage = tmp_path / "coverage.jsonl"
    addressed = ["RUN-PLAIN", "RUN-VAULT-*", "RUN-CHECK-*", "RUN-NATIVE-MINTS", "RUN-GONE"]
    assert syngate.cmd_test(argparse.Namespace(uid=addressed, build_dir="build", coverage_out=str(coverage))) == 1

    # every command is an argument list run in the project root, never a shell line; without a setup the built-in pytest run holds
    assert all(isinstance(argv, list) and not kwargs.get("shell") and kwargs["cwd"] == tmp_path for argv, kwargs in calls)
    assert [sys.executable, "-m", "pytest", "tests/test_plain.py::test_plain"] in [argv for argv, _ in calls]

    runs = {}
    for line in (tmp_path / "runs.jsonl").read_text(encoding="utf-8").splitlines():
        runs.setdefault(json.loads(line)["mode"], []).append(json.loads(line))
    (junit,), (events,), (tap,) = runs["junit"], runs["coverage"], runs["tap"]
    # plural placeholders join the addressed bindings of one setup into one command, the report and the select file going with it
    assert junit["args"] == [junit["report"], "^(test_Deposit|test_Lost|test_Withdraw)$"]
    assert junit["select"] == [["RUN-VAULT-DEPOSIT", None, "test_Deposit"], ["RUN-VAULT-LOST", None, "test_Lost"], ["RUN-VAULT-WITHDRAW", "overdraw", "test_Withdraw"]]
    assert junit["token"] == "s3"  # an `env` value `$NAME` passes a variable of the server through
    assert events["args"] == ["RUN-VAULT-EVENTS"] and events["token"] is None  # the nearest setup holds whole, its parent's `env` not merged
    assert sorted(entry["args"] for entry in runs["exit"]) == [["check_bad", "$HOME;*"], ["check_ok", "$HOME;*"]]  # one by one, no shell expanding a word
    assert tap["args"] == [] and tap["select"] == [["RUN-NATIVE-MINTS", None, "mints shares"]]  # no placeholder: the whole suite, once

    records, errors = syngatelib.load_coverage([coverage])
    assert errors == [] and {binding: [record["passed"] for record in found] for binding, found in records.items()} == {
        ("RUN-VAULT-DEPOSIT", None): [True], ("RUN-VAULT-WITHDRAW", "overdraw"): [False], ("RUN-VAULT-LOST", None): [False],  # the report file
        ("RUN-VAULT-UNTAGGED", None): [False],  # a binding no routine is tagged for
        ("RUN-VAULT-EVENTS", None): [True],  # the coverage records, ahead of the exit status
        ("RUN-CHECK-OK", None): [True], ("RUN-CHECK-BAD", None): [False],  # the exit status of a command run one by one
        ("RUN-NATIVE-MINTS", None): [True],  # the standard output, the results of bindings not addressed dropped
        ("RUN-GONE", None): [False]}  # nothing of RUN-NOBODY: its report result and its emitted record are passed over
    log = lambda uid, name=None: records[(uid, name)][0]["log"]
    assert "short" in log("RUN-VAULT-WITHDRAW", "overdraw") and log("RUN-VAULT-LOST").startswith("no result")
    assert "must match exactly one routine" in log("RUN-VAULT-UNTAGGED")
    assert records[("RUN-VAULT-EVENTS", None)][0]["name"] == "emitted" and "checked check_bad" in log("RUN-CHECK-BAD")
    assert "cannot start" in log("RUN-GONE") and "no-such-runner-of-syngate" in log("RUN-GONE")  # fails every binding it was to run

    passing = ["RUN-VAULT-DEPOSIT", "RUN-VAULT-EVENTS", "RUN-CHECK-OK", "RUN-NATIVE-MINTS"]
    assert syngate.cmd_test(argparse.Namespace(uid=passing, build_dir="build", coverage_out=None)) == 0  # a failed result of no addressed binding reddens nothing

    # review freezes the routine as its setup's command ran it, red or green, and stamps nothing the command could not run
    monkeypatch.setattr(syngate.subprocess, "run", run)
    assert syngate.cmd_review(argparse.Namespace(uid=["RUN-CHECK-BAD", "RUN-GONE"], build_dir="build", coverage_out=None)) == 1
    items = syngatelib.load_tree()[0]
    (routine,) = syngatelib.discover_setups(items)[0][("RUN-CHECK-BAD", None)]
    assert (routine.path, routine.routine) == ("checks/checks.py", "check_bad") and items["RUN-CHECK-BAD"].tests == {None: syngatelib.routine_sha(routine)}
    assert items["RUN-CHECK-BAD"].reviewed == syngatelib.item_stamp(items, "RUN-CHECK-BAD")
    assert items["RUN-GONE"].reviewed is None and items["RUN-GONE"].tests == {None: None} and items["RUN-GONE"].setup["run"].startswith("no-such-runner")

    # tags naming no item of the tree -- one over a routine, one over none -- are passed over by discovery, validate and the report
    assert syngatelib.discover_setups(items)[1] == []
    assert syngate.cmd_validate(argparse.Namespace(coverage=[], strict=False)) == 0
    with open(coverage, "a", encoding="utf-8") as out:
        out.write(json.dumps({"tags": ["RUN-NOBODY"], "passed": False, "name": "stray"}) + "\n")
    status = tmp_path / "status.json"
    assert syngate.cmd_report(argparse.Namespace(coverage=[str(coverage)], out=str(status), html=None)) == 0
    report = json.loads(status.read_text(encoding="utf-8"))
    assert "RUN-NOBODY" not in report and not any("RUN-NOBODY" in problem for entry in report.values() for problem in entry["problems"])
    assert report["RUN-VAULT-UNTAGGED"]["status"] == syngatelib.TEST_FAILED  # the binding no routine is tagged for, red on its item
