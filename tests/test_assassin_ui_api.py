# Open Trader
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""AI Assassin UI: the chat API of the loopback server.

The harness's own Tree permission, the chats kept across server runs, subagent reports mirrored into their items' chats, the
session and chat resets, the retry of a failed turn, the connector's closing usage step and the cancel of a run with its process group."""

import json
import os
import sys
import threading
import time
import urllib.error

import pytest

import assassin_ui
import synthetic
from test_assassin_ui import app, call, server  # noqa: F401 -- the server fixtures of the page tests

SETUP = {"connector": "echo", "model": "model-a", "effort": "low"}


def calls(*batch):
    return {"kind": "calls", "calls": list(batch)}


class Scripted:
    """Answers the scripted replies in order -- a callable one is given `on_step`, an exception one is raised -- then `done`,
    keeping what every dispatch was handed."""
    label, models, efforts = "Scripted", ("model-a",), ("low",)
    modes = ("edit",)

    def __init__(self, *answers):
        self.answers, self.heard = list(answers), []

    def settings(self):
        return {"label": self.label, "models": [{"id": model, "name": model} for model in self.models], "efforts": list(self.efforts),
                "modes": [{"id": "edit", "label": "Edit files", "hint": "change project files", "default": True}]}

    def dispatch(self, context, text, model=None, effort=None, modes=(), session=None, on_step=None, stopped=None):
        self.heard.append({"text": text, "modes": list(modes), "session": session})
        answer = self.answers.pop(0) if self.answers else {"kind": "text", "text": "done"}
        if isinstance(answer, Exception):
            raise answer
        return (answer(on_step) if callable(answer) else answer), f"session-{len(self.heard)}"


def held(gate):
    """A reply given once `gate` is set."""
    return lambda on_step: (gate.wait(10), {"kind": "text", "text": "late"})[1]


def turn(base, app, uid, text, **data):
    """The outcome of one turn of `uid`, awaited."""
    started = call(base, app, "/api/turn", {**SETUP, "uid": uid, "text": text, **data})[1]
    return call(base, app, f"/api/turn/{started['turn']}?wait=10")[1]


def refused(base, app, path, payload):
    with pytest.raises(urllib.error.HTTPError) as denied:
        call(base, app, path, payload)
    return denied.value.code, json.loads(denied.value.read())


def without_at(steps):
    return [{**{key: value for key, value in step.items() if key not in ("at", "seconds")}, **({"steps": without_at(step["steps"])} if "steps" in step else {})}
            for step in steps]


@pytest.mark.syngate("AI_CHAT-PERMISSION-TREE")
def test_tree_edits_are_refused_while_the_tree_edit_permission_is_off_and_a_child_cannot_switch_it_on(server, syngate_tree):
    base, app = server
    add = {"tool": "add", "uid": "NEW-001", "description": "New leaf\n\nIt shall be new."}
    app.connectors = {"echo": (scripted := Scripted(calls({"tool": "query", "uid": "@"}, add), {"kind": "text", "text": "I would add it."}))}
    modes = call(base, app, "/api/tree")[1]["connectors"]["echo"]["modes"]
    assert modes[0] == assassin_ui.TREE_MODE and modes[0]["default"] is True and [mode["id"] for mode in modes] == ["tree", "edit"]
    outcome = call(base, app, "/api/chat", {**SETUP, "uid": "ROOT", "modes": ["edit"], "text": "Add it."})[1]
    assert outcome["reply"] == f"- add NEW-001 refused: {assassin_ui.TREE_REFUSAL}\nI would add it."  # the query was read but stays out of the reply
    assert scripted.heard[0] == {"text": assassin_ui.TREE_OFF + "\nAdd it.", "modes": ["edit"], "session": None}  # the mode is never sent
    assert scripted.heard[1]["text"].startswith(synthetic.RESULTS_PREAMBLE + "- ROOT: {") and scripted.heard[1]["text"].endswith(f"\n- add NEW-001 refused: {assassin_ui.TREE_REFUSAL}")
    assert "NEW-001" not in app._load() and len(scripted.heard) == 2

    app.connectors = {"echo": (scripted := Scripted(calls(add)))}
    outcome = turn(base, app, "ROOT", "Add it.", modes=["edit", "tree"])
    assert outcome["reply"] == "- added NEW-001 under ROOT" and "NEW-001" in app._load()
    assert scripted.heard == [{"text": "Add it.", "modes": ["edit"], "session": None}]
    assert outcome["steps"][-1]["kind"] == "calls" and outcome["steps"][-1]["tools"] == ["add"] and outcome["steps"][-1]["lines"] == ["- added NEW-001 under ROOT"]

    child = {"tool": "agent", "uid": "LEAF-001", "prompt": "Add one more", "modes": ["edit", "tree"]}
    denied = f"- add NEW-002 refused: {assassin_ui.TREE_REFUSAL}"
    app.connectors = {"echo": (scripted := Scripted(calls(child), calls(dict(add, uid="NEW-002")), {"kind": "text", "text": "Could not."}, {"kind": "text", "text": "Reported."}))}
    outcome = turn(base, app, "ROOT", "Delegate.", modes=["edit"])
    assert outcome["reply"] == f"- agent LEAF-001: {denied}\nCould not.\nReported."
    assert scripted.heard[1]["text"] == assassin_ui.TREE_OFF + "\nAdd one more" and scripted.heard[1]["modes"] == ["edit"] and "NEW-002" not in app._load()
    assert scripted.heard[2]["text"] == synthetic.RESULTS_PREAMBLE + denied  # the child hears its refusal and answers in text
    assert scripted.heard[3]["text"] == synthetic.RESULTS_PREAMBLE + f"- agent LEAF-001: {denied}\nCould not."

    call(base, app, "/api/chat/LEAF-001", {"modes": ["edit", "tree"]})  # the child's own panel has Tree edit on
    app.connectors = {"echo": (scripted := Scripted(calls({"tool": "agent", "uid": "LEAF-001", "prompt": "Add one more"}), calls(dict(add, uid="NEW-003")), {"kind": "text", "text": "Could not."}, {"kind": "text", "text": "Reported."}))}
    started = call(base, app, "/api/turn", {**SETUP, "uid": "ROOT", "text": "Delegate."})[1]  # no modes key at all: Tree edit is off
    outcome = call(base, app, f"/api/turn/{started['turn']}?wait=10")[1]
    assert outcome["reply"] == f"- agent LEAF-001: - add NEW-003 refused: {assassin_ui.TREE_REFUSAL}\nCould not.\nReported."
    assert scripted.heard[1]["modes"] == ["edit"] and "NEW-003" not in app._load()

    status, body = refused(base, app, "/api/chat", {**SETUP, "uid": "ROOT", "modes": ["edit"], "text": "  "})
    assert status == 400 and "empty input" in body["error"] and not scripted.heard[4:]  # the read-only notice never stands in for the text


@pytest.mark.syngate("AI_CHAT-PERSIST")
def test_chats_are_kept_in_a_file_next_to_the_tree_across_server_runs_and_dropped_with_their_items(server, syngate_tree):
    base, app = server
    syngate_dir, _ = syngate_tree
    stored = lambda: json.loads(app.chats_file.read_text())
    app.connectors = {"echo": Scripted({"kind": "text", "text": "First reply"})}
    turn(base, app, "LEAF-001", "First")
    call(base, app, "/api/chat/LEAF-001", {"effort": "low", "message": {"index": 1, "cuts": [[6, 11]]}})
    deadline = time.monotonic() + 3
    while not (app.chats_file.is_file() and len(stored().get("LEAF-001", {}).get("log", [])) == 2 and stored()["LEAF-001"]["log"][1].get("cuts")) and time.monotonic() < deadline:
        time.sleep(0.05)
    record = stored()["LEAF-001"]
    assert isinstance(record.pop("started"), float) and app.chats_file.parent == app.root
    assert record == {"turns": 1, "log": [{"role": "user", "text": "First"}, {"role": "ai", "text": "First reply", "cuts": [[6, 11]]}], "session": None,
                      "setup": {**SETUP}, "archive": []}
    record["session"] = "session-1"
    app.chats_file.write_text(json.dumps({**stored(), "LEAF-001": record}))

    again = assassin_ui.AssassinApp(root=app.root, syngate_dir=syngate_dir, cli_prefix=app.cli_prefix)
    again.connectors = {"echo": (scripted := Scripted({"kind": "text", "text": "Second reply"}))}
    restored = again.chats_snapshot()["chats"]["LEAF-001"]
    assert (restored["log"], restored["session"], restored["effort"], restored["turn"]) == (record["log"], "session-1", "low", None)
    assert again.start_turn({"uid": "LEAF-001", "text": "Second", **SETUP})["turn"] == "LEAF-001:2"  # the numbering goes on
    assert again.turn_snapshot("LEAF-001:2", wait=5)["reply"] == "Second reply" and scripted.heard[0]["session"] == "session-1"
    again.save_chats()

    app.chats_file.write_text(json.dumps({**stored(), "GONE-001": {"log": [{"role": "user", "text": "Orphan"}]}}))
    assert sorted(assassin_ui.AssassinApp(root=app.root, syngate_dir=syngate_dir).chats) == ["LEAF-001"]  # an item no longer in the tree

    gate = threading.Event()
    app.connectors = {"echo": Scripted(held(gate))}
    running = call(base, app, "/api/turn", {**SETUP, "uid": "ROOT", "text": "Slow"})[1]["turn"]
    app.save_chats()
    root = stored()["ROOT"]
    assert isinstance(root.pop("started"), float)
    assert root == {"turns": 1, "log": [{"role": "user", "text": "Slow"}], "session": None, "setup": {**SETUP}, "archive": []}  # never a running turn
    gate.set()
    assert call(base, app, f"/api/turn/{running}?wait=5")[1]["reply"] == "late"

    call(base, app, "/api/delete/LEAF-001", {})
    assert "LEAF-001" not in call(base, app, "/api/chats")[1]["chats"]
    app.save_chats()
    assert sorted(stored()) == ["ROOT"]


@pytest.mark.syngate("AI_CHAT-AGENT-MIRROR")
def test_a_subagents_report_is_mirrored_into_its_items_chat_but_not_the_anchors_nor_a_delegated_childs(server, syngate_tree):
    base, app = server
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "LEAF-002", "It shall follow.\n", parents=("ROOT",), order=10, tests=None)
    grep = {"kind": "tool", "name": "Grep", "input": {"pattern": "leaf"}, "result": "1 match", "seconds": 0.3, "at": 0.5}
    agents = [{"kind": "agent", "uid": "LEAF-002", "prompt": "@LEAF-002 check it", "report": "LEAF-002 checked", "at": 0.4, "steps": [grep]},
              {"kind": "agent", "uid": None, "prompt": "no anchor", "report": "looked", "at": 0.6,
               "steps": [{"kind": "agent", "uid": "LEAF-002", "prompt": "@LEAF-002 again", "report": "checked again", "at": 0.7, "steps": []}]},
              {"kind": "agent", "uid": "ROOT", "prompt": "@ROOT itself", "report": "the anchor", "at": 0.8, "steps": []},
              {"kind": "agent", "uid": "NOPE", "prompt": "@NOPE unknown", "report": "nothing", "at": 0.9, "steps": []},
              {"kind": "agent", "uid": "LEAF-002", "prompt": "@LEAF-002 silent", "report": None, "at": 1.0, "steps": []}]

    def narrate(on_step):
        for step in agents:
            on_step(step)
        return {"kind": "text", "text": "All checked."}

    app.connectors = {"echo": Scripted(calls({"tool": "agent", "uid": "LEAF-001", "prompt": "Do the leaf"}), {"kind": "text", "text": "did it"}, narrate)}
    outcome = turn(base, app, "ROOT", "Check everything.")
    chats = call(base, app, "/api/chats")[1]["chats"]
    assert outcome["reply"] == "- agent LEAF-001: did it\nAll checked." and sorted(chats) == ["LEAF-001", "LEAF-002", "ROOT"]
    assert [m["role"] for m in chats["ROOT"]["log"]] == ["user", "ai"]
    assert [(m["role"], m["text"], m.get("agent")) for m in chats["LEAF-001"]["log"]] == [("user", "Do the leaf", "ROOT:1"), ("ai", "did it", None)]  # delegated: its own chat, not mirrored twice
    assert [{**m, "steps": without_at(m["steps"])} for m in chats["LEAF-002"]["log"]] == [
        {"role": "ai", "agent": "ROOT:1", "prompt": "@LEAF-002 check it", "text": "LEAF-002 checked", "steps": without_at([grep])},
        {"role": "ai", "agent": "ROOT:1", "prompt": "@LEAF-002 again", "text": "checked again", "steps": []}]
    assert chats["LEAF-002"]["turn"] is None and chats["LEAF-002"]["log"] == app.chats_snapshot()["chats"]["LEAF-002"]["log"]


@pytest.mark.syngate("AI_CHAT-RESET", "api")
def test_a_reset_keeps_the_log_and_drops_the_session_an_erase_drops_both_and_a_running_turn_refuses_either(server):
    base, app = server
    app.connectors = {"echo": (scripted := Scripted())}
    turn(base, app, "LEAF-001", "First")
    status, reset = call(base, app, "/api/chat/LEAF-001", {"reset": True})
    assert status == 200 and reset["session"] is None and [m["text"] for m in reset["log"]] == ["First", "done"] and reset["version"] == app.chats_version
    turn(base, app, "LEAF-001", "Second")
    assert scripted.heard[1] == {"session": None, "modes": [], "text": synthetic.HISTORY_PREAMBLE + "user: First\nassistant: done\n\n" + assassin_ui.TREE_OFF + "\nSecond"}
    assert call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]["session"] == "session-2"  # the next turn opened a new one

    gate = threading.Event()
    app.connectors = {"echo": Scripted(held(gate))}
    running = call(base, app, "/api/turn", {**SETUP, "uid": "LEAF-001", "text": "Slow"})[1]["turn"]
    for change in ({"reset": True}, {"erase": True}, {"message": {"index": 0, "cuts": [[0, 2]]}}):
        status, body = refused(base, app, "/api/chat/LEAF-001", change)
        assert status == 409 and body["error"] == "a turn of LEAF-001 is running; change the exchange once it ends", change
    assert call(base, app, "/api/chat/LEAF-001", {"effort": "low"})[1]["effort"] == "low"  # the setup is not the exchange
    gate.set()
    assert call(base, app, f"/api/turn/{running}?wait=5")[1]["reply"] == "late"
    assert call(base, app, "/api/chat/LEAF-001", {"message": {"index": 0, "cuts": [[0, 2]]}})[1]["session"] is None
    erased = call(base, app, "/api/chat/LEAF-001", {"erase": True})[1]
    assert (erased["log"], erased["session"]) == ([], None)


@pytest.mark.syngate("AI_CHAT-CONVERSATIONS", "api")
def test_a_new_conversation_files_the_live_one_and_a_filed_one_resumes_with_its_session_and_setup(server, syngate_tree):
    base, app = server
    syngate_dir, _ = syngate_tree
    app.connectors = {"echo": (scripted := Scripted())}
    turn(base, app, "LEAF-001", "First")
    begun = call(base, app, "/api/chat/LEAF-001", {"begin": True})[1]
    assert (begun["log"], begun["session"], begun["started"], begun["effort"]) == ([], None, None, "low")  # the setup stays with the live one
    assert [(c["title"], c["messages"]) for c in begun["archive"]] == [("First", 2)] and isinstance(begun["archive"][0]["started"], float)
    assert call(base, app, "/api/chat/LEAF-001", {"begin": True})[1]["archive"] == begun["archive"]  # an empty live conversation is not filed
    turn(base, app, "LEAF-001", "Second", modes=["edit"])
    assert scripted.heard[1]["session"] is None  # a new conversation, a new session
    status, body = refused(base, app, "/api/chat/LEAF-001", {"resume": 5})
    assert status == 404 and body["error"] == "no conversation 5 of LEAF-001"
    resumed = call(base, app, "/api/chat/LEAF-001", {"resume": 0})[1]
    assert ([m["text"] for m in resumed["log"]], resumed["session"], resumed.get("modes")) == (["First", "done"], "session-1", None)  # the first conversation, its session and setup
    assert [(c["title"], c["messages"]) for c in resumed["archive"]] == [("Second", 2)]  # the live one filed in its place
    turn(base, app, "LEAF-001", "Third")
    assert scripted.heard[2]["session"] == "session-1"  # the resumed conversation goes on
    assert call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]["log"][-1]["text"] == "done"

    gate = threading.Event()
    app.connectors = {"echo": Scripted(held(gate))}
    running = call(base, app, "/api/turn", {**SETUP, "uid": "LEAF-001", "text": "Slow"})[1]["turn"]
    for change in ({"begin": True}, {"resume": 0}):
        status, body = refused(base, app, "/api/chat/LEAF-001", change)
        assert status == 409 and body["error"] == "a turn of LEAF-001 is running; change the exchange once it ends", change
    gate.set()
    assert call(base, app, f"/api/turn/{running}?wait=5")[1]["reply"] == "late"

    app.save_chats()
    again = assassin_ui.AssassinApp(root=app.root, syngate_dir=syngate_dir, cli_prefix=app.cli_prefix)
    kept = again.chats_snapshot()["chats"]["LEAF-001"]
    assert [c["title"] for c in kept["archive"]] == ["Second"] and [m["text"] for m in kept["log"]][:2] == ["First", "done"]  # the filed conversations survive a restart
    assert again.chats["LEAF-001"].archive[0]["session"] == "session-2" and again.chats["LEAF-001"].archive[0]["setup"]["modes"] == ["edit"]
    erased = call(base, app, "/api/chat/LEAF-001", {"erase": True})[1]
    assert erased["log"] == [] and [c["title"] for c in erased["archive"]] == ["Second"]  # deleting the live conversation leaves the filed ones


@pytest.mark.syngate("AI_CHAT-RETRY", "api")
def test_a_retry_resends_the_last_user_text_without_logging_it_again_and_a_failed_turns_message_can_be_removed(server):
    base, app = server
    app.connectors = {"echo": (scripted := Scripted({"kind": "text", "text": "fine"}, synthetic.connection_error("claude exited with 1"), {"kind": "text", "text": "better"}))}
    turn(base, app, "LEAF-001", "First")
    failed = turn(base, app, "LEAF-001", "Second")
    roles = lambda: [(m["role"], m["text"]) for m in call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]["log"]]
    assert failed["status"] == 502 and roles() == [("user", "First"), ("ai", "fine"), ("user", "Second"), ("error", "claude exited with 1")]
    retried = turn(base, app, "LEAF-001", "Second", retry=True)
    assert retried["reply"] == "better" and roles() == [("user", "First"), ("ai", "fine"), ("user", "Second"), ("error", "claude exited with 1"), ("ai", "better")]
    assert [(h["text"].rpartition("\n")[2], h["session"]) for h in scripted.heard[1:]] == [("Second", "session-1"), ("Second", "session-1")]  # the same session, once more
    assert call(base, app, "/api/chat/LEAF-001", {"message": {"index": 3, "remove": True}})[1]["log"][3] == {"role": "ai", "text": "better"}
    status, body = refused(base, app, "/api/chat/LEAF-001", {"message": {"index": 3, "remove": True}})
    assert status == 400 and "failed or stopped" in body["error"] and len(roles()) == 4
    status, body = refused(base, app, "/api/chat/LEAF-001", {"message": {"index": "x", "cuts": []}})
    assert (status, body["error"]) == (400, "'index' must be a number")


@pytest.mark.syngate("AI_CHAT-CONTROLS-FOLD-KEEP", "cuts")
def test_cuts_are_merged_and_clipped_the_kept_text_travels_and_a_stored_dropped_mark_reads_as_a_whole_cut(server, syngate_tree):
    base, app = server
    syngate_dir, _ = syngate_tree
    app.connectors = {"echo": (scripted := Scripted({"kind": "text", "text": "one two three four five"}, {"kind": "text", "text": "again"}))}
    turn(base, app, "LEAF-001", "First")
    log = call(base, app, "/api/chat/LEAF-001", {"message": {"index": 1, "cuts": [[14, 30], [8, 14], [-2, 3], [5, 5], ["x", 1], [1, 2]]}})[1]["log"]
    assert log[1]["cuts"] == [[0, 3], [8, 23]] and app.chats["LEAF-001"].kept()[1] == {"role": "ai", "text": " two "}  # sorted, merged where they touch, clipped, the malformed left out
    turn(base, app, "LEAF-001", "Second")
    assert scripted.heard[1] == {"session": None, "modes": [], "text": synthetic.HISTORY_PREAMBLE + "user: First\nassistant:  two \n\n" + assassin_ui.TREE_OFF + "\nSecond"}  # the kept text heads the new session
    status, body = refused(base, app, "/api/chat/LEAF-001", {"message": {"index": 1, "cuts": "all"}})
    assert status == 400 and body["error"] == "'cuts' must be a list of [from, to] spans"
    legacy = app.root / "legacy"
    legacy.mkdir()
    (legacy / assassin_ui.CHATS_FILE).write_text(json.dumps({"LEAF-001": {"turns": 1, "setup": {}, "session": None, "log": [
        {"role": "user", "text": "Old", "folded": True}, {"role": "ai", "text": "Reply", "dropped": True}, {"role": "ai", "text": "Kept", "cuts": [[9, 2], [0, 1]]}]}}))
    restored = assassin_ui.AssassinApp(root=legacy, syngate_dir=syngate_dir, cli_prefix=app.cli_prefix).chats["LEAF-001"]
    assert restored.log == [{"role": "user", "text": "Old"}, {"role": "ai", "text": "Reply", "cuts": [[0, 5]]}, {"role": "ai", "text": "Kept", "cuts": [[0, 1]]}]  # a record from before cuts
    assert restored.kept() == [{"role": "user", "text": "Old"}, {"role": "ai", "text": "ept"}]


# Stub `claude` closing its turn with a result event carrying the cost fields when told to, else bare.
STUB_COSTED = """
import json, sys
prompt = json.loads(sys.stdin.readline())["message"]["content"]
result = {"type": "result", "subtype": "success", "is_error": False, "result": "Done.", "session_id": "session-c",
          "structured_output": {"kind": "text", "text": "Done."}}
if "costed" in prompt:
    result.update(duration_ms=1530, total_cost_usd=0.0123, usage={"input_tokens": 12, "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 218, "output_tokens": 45})
print(json.dumps(result))
"""


@pytest.mark.syngate("AI_CHAT-TURN-COST", "api")
def test_the_claude_code_connector_closes_a_turn_with_a_usage_step_from_the_result_event(tmp_path):
    stub = tmp_path / "claude_stub.py"
    stub.write_text(STUB_COSTED)
    connector = synthetic.claude_code_connector(cli=(sys.executable, str(stub)), cwd=tmp_path)
    steps = []
    answer, session = connector.dispatch("", "costed", on_step=steps.append)
    assert (answer, session) == ({"kind": "text", "text": "Done."}, "session-c")
    assert steps[-1] == {"kind": "usage", "seconds": 1.53, "cost_usd": 0.0123, "input_tokens": 1230, "output_tokens": 45, "at": steps[-1]["at"]}
    assert isinstance(steps[-1]["at"], float) and [step["kind"] for step in steps] == ["usage"]
    steps.clear()
    assert connector.dispatch("", "bare", on_step=steps.append)[0] == {"kind": "text", "text": "Done."} and steps == []


# Stub run holding a child of its own, printing the child's pid, so a cancel is seen to take the whole process group.
STUB_FAMILY = [sys.executable, "-c", "import subprocess, sys, time; child = subprocess.Popen(['sleep', '30']); print('child', child.pid); sys.stdout.flush(); time.sleep(30)"]


def _alive(pid):
    try:
        return "State:\tZ" not in (open(f"/proc/{pid}/status").read() if os.path.exists(f"/proc/{pid}/status") else "State:\tZ")
    except OSError:
        return False


@pytest.mark.syngate("ASSASSIN-UI-STATUS-POPUP-RUN", "cancel")
def test_a_cancelled_run_ends_with_its_whole_process_group_and_the_api_answers_bad_input_and_failures_as_json(server, monkeypatch):
    base, app = server
    app.cli_prefix = STUB_FAMILY
    job = call(base, app, "/api/run", {"action": "clear", "uids": ["LEAF-001"]})[1]["job"]
    snapshot = lambda: call(base, app, f"/api/job/{job}")[1]
    deadline = time.monotonic() + 5
    while not snapshot()["lines"] and time.monotonic() < deadline:
        time.sleep(0.05)
    child = int(snapshot()["lines"][0].split()[1])
    assert _alive(child) and refused(base, app, "/api/job/999/cancel", {})[0] == 404
    assert call(base, app, f"/api/job/{job}/cancel", {})[1] == {"ok": True}
    deadline = time.monotonic() + 6
    while (snapshot()["running"] or _alive(child)) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert snapshot()["running"] is False and snapshot()["returncode"] != 0 and not _alive(child)

    with pytest.raises(urllib.error.HTTPError) as bad:
        call(base, app, "/api/chats?since=x")
    assert bad.value.code == 400 and json.loads(bad.value.read()) == {"error": "'since' must be a number"}
    with pytest.raises(urllib.error.HTTPError) as bad:
        call(base, app, "/api/turn/LEAF-001:1?wait=soon")
    assert bad.value.code == 400 and json.loads(bad.value.read()) == {"error": "'wait' must be a number"}
    monkeypatch.setattr(app, "build_model", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(urllib.error.HTTPError) as crashed:
        call(base, app, "/api/tree")
    assert crashed.value.code == 500 and json.loads(crashed.value.read()) == {"error": "RuntimeError: boom"}
