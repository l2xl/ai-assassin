# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""`websurf-extension/` loads unpacked in Chrome and as a temporary add-on in Firefox -- [BROWSER-EXTENSION], [CHROME-EXTENSION], [FIREFOX-EXTENSION]."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "websurf-extension"


def _manifest():
    """Return the extension's parsed manifest."""
    return json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))


@pytest.mark.syngate("BROWSER-EXTENSION")
def test_the_extension_folder_is_installable_as_is_with_every_referenced_file_and_module_present():
    manifest = _manifest()
    assert manifest["manifest_version"] == 3
    assert {"tabs", "scripting", "storage", "alarms", "webNavigation", "webRequest"} <= set(manifest["permissions"])
    assert manifest["host_permissions"] == ["<all_urls>"]
    background = manifest["background"]
    pages = [background["service_worker"], *background["scripts"], manifest["options_ui"]["page"]]
    for page in pages:
        assert (EXTENSION / page).is_file(), page
    for html in EXTENSION.glob("*.html"):
        for src in re.findall(r'<script[^>]*\bsrc="([^"]+)"', html.read_text(encoding="utf-8")):
            assert (EXTENSION / src).is_file(), f"{html.name}: {src}"
    scripts = sorted(EXTENSION.glob("*.js"))
    for script in scripts:
        for target in re.findall(r"""^import\b[^'"]*['"](\./[^'"]+)['"]""", script.read_text(encoding="utf-8"), re.M):
            assert (EXTENSION / target).is_file(), f"{script.name}: {target}"
    node = shutil.which("node")
    if node is not None:
        for script in scripts:
            subprocess.run([node, "--check", str(script)], check=True, capture_output=True, timeout=30)
    readme = (EXTENSION / "README.md").read_text(encoding="utf-8")
    assert "chrome://extensions" in readme and "about:debugging" in readme


@pytest.mark.syngate("CHROME-EXTENSION")
def test_the_chrome_build_runs_the_background_as_a_module_service_worker_from_chrome_121():
    manifest = _manifest()
    assert manifest["background"]["service_worker"] == "background.js"
    assert manifest["background"]["type"] == "module"
    assert int(manifest["minimum_chrome_version"]) >= 121


@pytest.mark.syngate("FIREFOX-EXTENSION")
def test_the_firefox_build_runs_the_background_as_a_module_event_page_with_loopback_ws_left_unupgraded():
    manifest = _manifest()
    assert manifest["background"]["scripts"] == ["background.js"]
    assert manifest["background"]["type"] == "module"
    gecko = manifest["browser_specific_settings"]["gecko"]
    assert gecko["id"] and int(gecko["strict_min_version"].split(".")[0]) >= 121
    policy = manifest["content_security_policy"]["extension_pages"]
    assert "script-src 'self'" in policy and "upgrade-insecure-requests" not in policy
