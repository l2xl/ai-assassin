# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Live engine: the prompt library read from its files for every turn -- [SYNTHETIC-PROMPTS-LIVE] -- and the `assassin` server updated on
the fly: a changed page reloading its tabs -- [ASSASSIN-UI-PAGE-RELOAD] -- and the server re-executed in place on a change of its Python
sources -- [ASSASSIN-UI-ENGINE-WAIT], [ASSASSIN-UI-ENGINE-PREFLIGHT], [ASSASSIN-UI-ENGINE-HANDOFF]."""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import parse_qs, urlsplit

import pytest

import assassin_ui
import syngatelib
import synthetic
from test_assassin_ui import app, call, chrome, enter_reply, page, server  # noqa: F401 -- the server and page fixtures
from test_assassin_ui_api import SETUP, Scripted, held
from test_synthetic import EchoAnswer
from test_synthetic_library import NativeEcho

FRESH = "---\nkind: skill\ndescription: Fresh\ndefault: true\n---\n# Fresh\n%s\n"
STAMP = '---\nkind: tool\ndescription: Stamp\ncalls:\n  stamp:\n    required: [serial]\n---\n# Stamp\n`{"tool": "stamp"}` stamps a serial.\n'


@pytest.mark.syngate("SYNTHETIC-PROMPTS-LIVE")
def test_the_prompt_library_is_read_from_its_files_for_every_turn_and_every_read_of_a_prompt(tmp_path, monkeypatch, syngate_tree):
    prompts = tmp_path / "prompts"
    shutil.copytree(synthetic.PROMPTS_DIR, prompts)
    monkeypatch.setattr(synthetic, "PROMPTS_DIR", prompts)
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root.\n", parents=())
    items, _ = syngatelib.load_tree(syngate_dir)
    served = assassin_ui.AssassinApp(root=tmp_path, syngate_dir=syngate_dir)
    served.connectors = {"echo": EchoAnswer()}
    seed = lambda: served.chat({"connector": "echo", "model": "model-a", "effort": "low", "uid": "ROOT", "text": "Go.", "modes": ["tree"]})["reply"]
    native = lambda: synthetic.query({"native": NativeEcho()}, items, "ROOT", "Go.", "native", "model-a", "low")[0]
    assert "MARK-ONE" not in seed() and "fresh" not in synthetic.LIBRARY

    (prompts / "fresh.md").write_text(FRESH % "MARK-ONE")  # a new prompt file: the next turn of the same server carries it
    assert "MARK-ONE" in seed() and "MARK-ONE" in synthetic.PROMPTS[synthetic.DEFAULT_PROMPT] and synthetic.SKILLS["fresh"].text == "# Fresh\nMARK-ONE\n"
    assert synthetic.apply_call({}, "ROOT", {"tool": "skill", "name": "fresh"}) == "- skill fresh:\n# Fresh\nMARK-ONE\n"
    assert "MARK-ONE" in native() and "'fresh'" in native()

    (prompts / "fresh.md").write_text(FRESH % "MARK-TWO")  # an edited one: nothing of the earlier text is kept
    assert "MARK-TWO" in seed() and "MARK-ONE" not in seed() and synthetic.LIBRARY["fresh"].text == "# Fresh\nMARK-TWO\n"

    (prompts / "stamp.md").write_text(STAMP)  # a new tool: its call joins the answer schema, its text the seed
    tools = [shape["properties"]["tool"]["const"] for shape in synthetic.ANSWER_SCHEMA["properties"]["calls"]["items"]["anyOf"]]
    assert "stamp" in tools and synthetic.library_calls(synthetic.LIBRARY)["stamp"] == ("serial",) and "stamps a serial." in seed()

    (prompts / "fresh.md").unlink()  # a removed one is gone from the next read
    assert "MARK-TWO" not in seed() and "fresh" not in synthetic.LIBRARY and "fresh" not in synthetic.SKILLS and "'fresh'" not in native()
    with pytest.raises(syngatelib.tree_error, match="unknown skill 'fresh'"):
        synthetic.apply_call({}, "ROOT", {"tool": "skill", "name": "fresh"})


def settle(page, predicate, timeout=20):
    """Await `predicate` across a reload of the page, whose evaluation fails while the new document loads."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            if page.eval(f"Boolean({predicate})"):
                return
        except (RuntimeError, AssertionError, TimeoutError):
            pass
        assert time.monotonic() < deadline, f"page never reached: {predicate}"
        time.sleep(0.1)


REPLY = "document.querySelector('#doc .block[data-uid=\"LEAF-001\"] .chat-input')"


@pytest.mark.syngate("ASSASSIN-UI-PAGE-RELOAD")
def test_a_changed_page_reloads_an_idle_tab_with_its_state_kept_and_waits_on_a_busy_one(page, server, tmp_path, monkeypatch):
    changed = tmp_path / "assassin_ui.html"
    changed.write_bytes(assassin_ui.PAGE_FILE.read_bytes() + b"\n<!-- changed -->\n")
    enter_reply(page, "LEAF-001")
    page.eval(f"(() => {{ const input = {REPLY}; input.focus(); input.value = 'half a thought'; window.marker = 1; }})()")
    page.eval("(() => { const filter = document.getElementById('filter'); filter.value = 'leaf'; filter.dispatchEvent(new Event('input')); })()")
    assert page.eval("[document.getElementById('page-update').hidden, document.documentElement.dataset.page]") == [True, assassin_ui.page_sha()]

    monkeypatch.setattr(assassin_ui, "PAGE_FILE", changed)
    page.wait("!document.getElementById('page-update').hidden")  # busy -- text in the field holding the focus: the pill, no reload
    time.sleep(2.5)
    assert page.eval("window.marker") == 1

    page.eval("document.activeElement.blur()")  # idle: the next poll reloads the tab
    settle(page, "window.marker === undefined && state.model && document.querySelector('#tree [data-uid=\"LEAF-001\"]')")
    kept = "[state.filter, document.getElementById('filter').value, state.selected, state.replies.get('LEAF-001'), document.getElementById('page-update').hidden, document.documentElement.dataset.page]"
    assert page.eval(kept) == ["leaf", "leaf", "LEAF-001", "half a thought", True, assassin_ui.page_sha()]
    enter_reply(page, "LEAF-001")
    page.wait(f"{REPLY}.value === 'half a thought'")  # the reply text is back in the line with the chat


@pytest.fixture
def engine(tmp_path, monkeypatch, app):
    """The app watching a folder of stand-in engine sources, its restart recorded instead of executed."""
    folder = tmp_path / "engine"
    folder.mkdir()
    (folder / "core.py").write_text("ANSWER = 1\n")
    monkeypatch.setattr(assassin_ui, "ENGINE_DIR", folder)
    app.engine_loaded, app.restarts = assassin_ui.engine_stamp(), []
    app.relaunch = [sys.executable, "-m", "ai_scratcher.assassin_ui", "--no-browser"]
    app.execv = lambda path, argv, env: app.restarts.append((path, argv, env))
    return app, folder


IDLE = {"changed": [], "error": None, "requested": False, "restarting": False, "running": 0, "watch": True}


@pytest.mark.syngate("ASSASSIN-UI-ENGINE-WAIT")
def test_the_restart_waits_for_every_running_turn_and_run_and_restart_now_stops_them_first(engine):
    app, folder = engine
    assert not app.check_engine() and app.engine_state() == IDLE and app.restarts == []  # nothing changed, nothing to do

    job = app.jobs.start([sys.executable, "-c", "import time; time.sleep(30)"], cwd=app.root)
    (folder / "core.py").write_text("ANSWER = 42\n")
    assert not app.check_engine() and app.engine_state() == {**IDLE, "changed": ["core.py"], "running": 1} and app.restarts == []
    app.jobs.cancel(job)

    gate = threading.Event()
    app.connectors = {"echo": Scripted(held(gate))}
    started = app.start_turn({**SETUP, "uid": "LEAF-001", "text": "Hold on."})["turn"]
    assert not app.check_engine() and app.engine_state()["running"] == 1 and app.restarts == []
    assert app.request_restart(stop=True)["requested"] is True and app._turn(started).stopped  # restart now: the turn is stopped first
    assert not app.check_engine() and app.restarts == []  # ... and still waited for until it ends
    gate.set()
    assert app.turn_snapshot(started, wait=10)["running"] is False

    assert app.check_engine() and app.engine_state()["restarting"] is True
    [(path, argv, env)] = app.restarts
    assert (path, argv) == (sys.executable, app.relaunch) and env[assassin_ui.TOKEN_ENV] == app.token
    for start in (lambda: app.start_turn({**SETUP, "uid": "ROOT", "text": "Now?"}), lambda: app.start_run({"action": "test", "uids": ["LEAF-001"]})):
        with pytest.raises(assassin_ui.ApiError) as refused:
            start()
        assert refused.value.status == 503 and str(refused.value) == assassin_ui.RESTARTING


@pytest.mark.syngate("ASSASSIN-UI-ENGINE-PREFLIGHT")
def test_an_engine_update_that_does_not_compile_keeps_the_running_engine_and_names_the_error(engine):
    app, folder = engine
    (folder / "core.py").write_text("def broken(:\n")
    assert not app.check_engine() and app.restarts == []
    state = app.engine_state()
    assert state["changed"] == ["core.py"] and "SyntaxError" in state["error"] and "core.py" in state["error"] and not state["restarting"]
    (folder / "core.py").write_text("ANSWER = 22\n")  # fixed: the fresh interpreter compiles it and imports the server
    assert app.check_engine() and app.engine_state()["error"] is None and len(app.restarts) == 1
    app.relaunch = None
    with pytest.raises(assassin_ui.ApiError) as refused:
        app.request_restart()
    assert refused.value.status == 409  # a server started with --no-reload never restarts itself


def request(base, token, path, payload=None):
    sent = urllib.request.Request(base + path, data=json.dumps(payload).encode() if payload is not None else None,
                                  method="POST" if payload is not None else "GET", headers={"X-Assassin-Token": token})
    with urllib.request.urlopen(sent, timeout=30) as response:
        return json.loads(response.read())


@pytest.mark.syngate("ASSASSIN-UI-ENGINE-HANDOFF", "socket")
def test_the_restarted_engine_serves_on_the_same_socket_with_the_same_token_and_the_chats_kept(tmp_path, syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root.\n", parents=())
    env = {key: value for key, value in os.environ.items() if key not in (assassin_ui.TOKEN_ENV, assassin_ui.LISTEN_ENV)}
    proc = subprocess.Popen([sys.executable, "-m", "ai_scratcher.assassin_ui", "--root", str(tmp_path), "--port", "0", "--no-browser"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    lines = queue.Queue()
    threading.Thread(target=lambda: [lines.put(line) for line in proc.stdout], daemon=True).start()

    def served():
        while True:
            line = lines.get(timeout=30)
            if " at http://" in line:
                return line.rsplit(" at ", 1)[1].strip()

    try:
        url = served()
        base, token = f"http://{urlsplit(url).netloc}", parse_qs(urlsplit(url).query)["token"][0]
        before = request(base, token, "/api/fingerprint")
        assert before["engine"] == IDLE and before["page"] == assassin_ui.page_sha()
        request(base, token, "/api/chat/ROOT", {"model": "kept"})
        assert request(base, token, "/api/engine", {})["requested"] is True
        assert served() == url  # the same port and token
        after = request(base, token, "/api/fingerprint")
        assert after["boot"] != before["boot"] and after["engine"] == IDLE and after["chats"] == 0
        assert request(base, token, "/api/chats")["chats"]["ROOT"]["model"] == "kept" and proc.poll() is None
    finally:
        proc.kill()
        proc.wait()


@pytest.mark.syngate("ASSASSIN-UI-ENGINE-HANDOFF", "page")
def test_an_open_page_reads_the_chats_of_a_restarted_engine_anew(page, server):
    base, app = server
    for model in ("one", "two", "three"):
        call(base, app, "/api/chat/ROOT", {"model": model})
    page.wait("state.chats.get('ROOT')?.model === 'three' && state.chatsVersion >= 3")
    with app._chat_lock:  # what a restart leaves the page: another boot, its chats counted from zero
        app.boot, app.chats_version = "restarted", 0
        app.chats["ROOT"].setup["model"] = "fresh"
        app._bump(settled=False)
    page.wait("state.boot === 'restarted' && state.chatsVersion === 1 && state.chats.get('ROOT').model === 'fresh'")
