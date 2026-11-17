# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""SYNGATE-TEST-SETUP-APPROVAL: the self-approval check reads a setup's `stamp` and watches the files of the setups."""

import subprocess

import pytest
import yaml

from check_self_approval import run as approval_run

SHA_A, SHA_B = "a" * 64, "b" * 64


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd, check=True, capture_output=True)


def commit(repo, message):
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message, "--no-verify")


def write(repo, sha, run="forge test", routine="// deposit\n", built_in="x\n", plain=False):
    """One reviewed item under a setup of `contracts/**/*.t.sol` holding its routine sha under `stamp` -- or a plain key."""
    (repo / "syngate").mkdir(exist_ok=True)
    test = sha if plain else {"stamp": {"deposit": sha}, "run": run, "files": ["contracts/**/*.t.sol"]}
    data = {"parents": ["VAULT"], "test": test, "review": sha}
    (repo / "syngate" / "VAULT-DEPOSIT.yml").write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nDeposit\n\nMints shares.\n")
    for rel, text in (("contracts/sub/Vault.t.sol", routine), ("scripts/tests/test_probe.py", built_in)):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)


def verdict(repo):
    return approval_run("HEAD^..HEAD", cwd=repo)


@pytest.mark.syngate("SYNGATE-TEST-SETUP-APPROVAL")
def test_stamp_of_a_setup_is_read_and_its_files_are_watched(tmp_path):
    def fresh(name):
        repo = tmp_path / name
        repo.mkdir()
        git(repo, "init", "-q")
        write(repo, SHA_A)
        commit(repo, "freeze")
        return repo

    repo = fresh("routine")  # a routine of the setup's files edited with the restamp
    write(repo, SHA_B, routine="// deposit edited\n")
    commit(repo, "self-approving edit")
    assert verdict(repo) == 1

    repo = fresh("setup")  # the setup changed with the restamp
    write(repo, SHA_B, run="forge test -vv")
    commit(repo, "restamp and rerun command")
    assert verdict(repo) == 1

    repo = fresh("builtin")  # the built-in test trees stay watched
    write(repo, SHA_B, built_in="y\n")
    commit(repo, "restamp and built-in test edit")
    assert verdict(repo) == 1

    repo = fresh("split")  # edit, then restamp alone: the shas under `stamp` are what changed, nothing else
    write(repo, SHA_A, routine="// deposit edited\n")
    commit(repo, "edit")
    write(repo, SHA_B, routine="// deposit edited\n")
    commit(repo, "restamp")
    assert verdict(repo) == 0

    repo = fresh("plain")  # a plain key is read as before: a restamp alone passes
    write(repo, SHA_A, plain=True)
    commit(repo, "plain key")
    write(repo, SHA_B, plain=True)
    commit(repo, "restamp plain")
    assert verdict(repo) == 0
