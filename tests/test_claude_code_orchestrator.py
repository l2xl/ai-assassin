# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The Orchestrator exceptions of the Claude Code connector (CLAUDE_CODE-ORCHESTRATOR-*): its session is one the harness cannot write, and its
own `Bash` is no call the security scan holds while its web results mark the session."""

import pytest

import api_connection
import synthetic
from ai_scratcher import security


@pytest.mark.syngate("CLAUDE_CODE-ORCHESTRATOR-PRUNE")
def test_the_claude_code_session_is_owned_by_its_cli_and_offers_the_harness_no_rewrite_an_api_session_does():
    assert not callable(getattr(synthetic.claude_code_connector(), "rewrite_session", None))
    assert callable(getattr(api_connection.api_connection("local", config=lambda: {}), "rewrite_session", None))


@pytest.mark.syngate("CLAUDE_CODE-ORCHESTRATOR-BASH")
def test_the_clis_own_bash_is_not_held_by_the_scan_and_its_web_tools_results_mark_the_session():
    assert not security.is_altering({"tool": "Bash", "command": "rm -rf build"})
    assert all(security.is_external(tool) for tool in synthetic.claude_code_connector.modes["internet"][5])
    assert not security.is_external("Bash") and not security.is_external("Read")
