# Open Trader
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The `bin/assassin` launcher, run against a stand-in `uv` that records its calls and provisions a fake environment."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "bin" / "assassin"
FAKE_UV = """#!{python}
import os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["LAUNCH_LOG"], "a") as log:
    log.write(" ".join(["uv", *args]) + "\\n")
def script(path, body):
    path.write_text("#!/bin/sh\\n" + body + "\\n")
    path.chmod(0o755)
if args[0] == "venv":
    (Path(args[-1]) / "bin").mkdir(parents=True)
    script(Path(args[-1]) / "bin" / "python", "exit 1")
if args[0] == "pip":
    script(Path(args[args.index("--python") + 1]).parent / "assassin", 'echo "assassin $*"')
"""


@pytest.mark.syngate("ASSASSIN-UI-LAUNCHER")
def test_the_launcher_provisions_the_environment_once_and_runs_assassin_with_the_arguments_given(tmp_path):
    assert os.access(LAUNCHER, os.X_OK), f"{LAUNCHER.relative_to(ROOT)} is not executable"
    tools, venv, log = tmp_path / "tools", tmp_path / "venv", tmp_path / "launch.log"
    tools.mkdir()
    (tools / "uv").write_text(FAKE_UV.format(python=sys.executable))
    (tools / "uv").chmod(0o755)
    env = {**{key: value for key, value in os.environ.items() if key != "PYTHON"}, "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
           "ASSASSIN_VENV": str(venv), "LAUNCH_LOG": str(log)}
    launch = lambda: subprocess.run([str(LAUNCHER), "--port", "0", "--no-browser"], env=env, capture_output=True, text=True, check=True).stdout
    calls = lambda: [line.split(" -e ")[0] + (f" -e {Path(line.split(' -e ')[1]).resolve()}" if " -e " in line else "") for line in log.read_text().splitlines()]
    install = f"uv pip install --quiet --python {venv}/bin/python -e {ROOT}"
    assert launch() == "assassin --port 0 --no-browser\n"
    assert calls() == [f"uv venv --quiet {venv}", install]  # the first use creates and fills the environment
    assert launch() == "assassin --port 0 --no-browser\n" and calls() == [f"uv venv --quiet {venv}", install]  # provisioned: straight to the command
    os.utime(venv / ".assassin-installed", (0, 0))
    assert launch() == "assassin --port 0 --no-browser\n" and calls() == [f"uv venv --quiet {venv}", install, install]  # pyproject.toml newer: installed again
