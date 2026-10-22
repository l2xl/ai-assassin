# Open Trader
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""AI Assassin UI: loopback HTTP server over syngatelib and the Synthetic harness.

The app serves the tree model as JSON, writes per-field item edits and
drag-and-drop placements through the canonical writer, scaffolds and deletes
items, and drives review/clear through the CLI as a streamed subprocess -- all
gated by a per-session token and a loopback Host check."""

import fcntl
import http.client
import json
import os
import select
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

import assassin_ui
import syngatelib
import synthetic

# Stub CLI: echoes its argv tail and exits with the code named by an rc=N
# argument (charset-valid as a UID pattern), standing in for `syngate.py review/clear` runs.
STUB = [sys.executable, "-c",
        "import sys; print('stub:', *sys.argv[1:]); rc = [a for a in sys.argv if a.startswith('rc-')]; sys.exit(int(rc[0][3:]) if rc else 0)"]


@pytest.fixture
def app(tmp_path, syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root branch\n", parents=())
    make_item(syngate_dir, "LEAF-001", "It shall leaf.\n", parents=("ROOT",), tests=None)
    return assassin_ui.AssassinApp(root=tmp_path, syngate_dir=syngate_dir, cli_prefix=STUB)


@pytest.fixture
def server(app):
    httpd = assassin_ui.make_server(app, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", app
    httpd.shutdown()
    thread.join()


class Cdp:
    """Headless Chrome over --remote-debugging-pipe: NUL-delimited JSON on fds 3 (in) / 4 (out)."""

    def __init__(self, binary, profile):
        to_chrome, from_chrome = os.pipe(), os.pipe()

        def wire():
            source, sink = fcntl.fcntl(to_chrome[0], fcntl.F_DUPFD, 10), fcntl.fcntl(from_chrome[1], fcntl.F_DUPFD, 10)
            os.dup2(source, 3)
            os.dup2(sink, 4)

        # A desktop window with a hovering pointer: headless Chrome otherwise opens 780px wide and reports (hover: none), the page's touch layout.
        argv = [binary, "--headless=new", "--remote-debugging-pipe", f"--user-data-dir={profile}", "--no-first-run", "--disable-gpu", "--window-size=1280,900",
                "--blink-settings=primaryHoverType=2,availableHoverTypes=2,primaryPointerType=4,availablePointerTypes=4"]
        if os.geteuid() == 0:
            argv.append("--no-sandbox")
        self.process = subprocess.Popen(argv, preexec_fn=wire, pass_fds=(3, 4), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(to_chrome[0])
        os.close(from_chrome[1])
        self.sink, self.source, self.buffer, self.serial, self.events = to_chrome[1], from_chrome[0], b"", 0, []

    def call(self, method, params=None, session=None):
        self.serial += 1
        message = {"id": self.serial, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        os.write(self.sink, json.dumps(message).encode() + b"\0")
        while True:
            while b"\0" not in self.buffer:
                if not select.select([self.source], [], [], 20)[0]:
                    raise TimeoutError(f"no CDP reply to {method}")
                self.buffer += os.read(self.source, 1 << 16)
            raw, self.buffer = self.buffer.split(b"\0", 1)
            reply = json.loads(raw)
            if "method" in reply:
                self.events.append(reply)
            elif reply.get("id") == self.serial:
                if "error" in reply:
                    raise RuntimeError(reply["error"])
                return reply["result"]

    def close(self):
        self.process.kill()
        self.process.wait()
        os.close(self.sink)
        os.close(self.source)


class Page:
    def __init__(self, cdp, url):
        self.cdp = cdp
        self.target = cdp.call("Target.createTarget", {"url": url})["targetId"]
        self.session = cdp.call("Target.attachToTarget", {"targetId": self.target, "flatten": True})["sessionId"]

    def activate(self):
        self.cdp.call("Target.activateTarget", {"targetId": self.target})

    def eval(self, script):
        result = self.cdp.call("Runtime.evaluate", {"expression": script, "awaitPromise": True, "returnByValue": True}, self.session)
        assert "exceptionDetails" not in result, result["exceptionDetails"]
        return result["result"].get("value")

    def mouse(self, kind, x, y, clicks=1, buttons=1):
        self.cdp.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "buttons": buttons, "clickCount": clicks}, self.session)

    def wait(self, predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while not self.eval(f"Boolean({predicate})"):
            assert time.monotonic() < deadline, f"page never reached: {predicate}"
            time.sleep(0.05)


@pytest.fixture(scope="session")
def chrome(tmp_path_factory):
    binary = next(filter(None, map(shutil.which, ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"))), None)
    if binary is None:
        pytest.skip("no headless Chrome")
    cdp = Cdp(binary, tmp_path_factory.mktemp("chrome-profile"))
    yield cdp
    cdp.close()


@pytest.fixture
def page(server, chrome):
    base, app = server
    opened = Page(chrome, f"{base}/?token={app.token}")
    opened.wait("document.querySelector('#tree [data-path]')")
    return opened


def call(base, app, path, payload=None, token=True, raw=False):
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method="POST" if payload is not None else "GET",
    )
    if token:
        request.add_header("X-Assassin-Token", app.token if token is True else token)
    with urllib.request.urlopen(request) as response:
        body = response.read()
        return response.status, body if raw else json.loads(body)


@pytest.mark.syngate("ASSASSIN-UI-SERVER")
def test_requests_without_token_or_loopback_host_are_refused(server):
    base, app = server
    with pytest.raises(urllib.error.HTTPError) as missing:
        call(base, app, "/api/tree", token=False)
    assert missing.value.code == 401
    with pytest.raises(urllib.error.HTTPError) as forged:
        call(base, app, "/api/tree", token="forged")
    assert forged.value.code == 401
    port = int(base.rsplit(":", 1)[1])
    conn = http.client.HTTPConnection("127.0.0.1", port)  # DNS-rebinding defense: loopback Host names only
    conn.request("GET", "/api/tree", headers={"Host": "evil.example", "X-Assassin-Token": app.token})
    assert conn.getresponse().status == 403
    conn.close()
    status, _ = call(base, app, f"/api/tree?token={app.token}", token=False)
    assert status == 200  # EventSource cannot set headers; the query token is equivalent


def _hold(port):
    """A listening socket on the loopback `port`, or None when another process already holds it."""
    held = socket.socket()
    try:
        held.bind(("127.0.0.1", port))
    except OSError:
        held.close()
        return None
    held.listen()
    return held


@pytest.mark.syngate("ASSASSIN-UI-PORT")
def test_the_port_is_derived_from_the_project_root_and_an_explicit_port_is_bound_exactly(app, tmp_path, monkeypatch):
    derived = assassin_ui.project_port(tmp_path)
    assert derived == assassin_ui.project_port(tmp_path / "." ) == assassin_ui.project_port(str(tmp_path))
    assert assassin_ui.DEFAULT_PORT < derived <= assassin_ui.DEFAULT_PORT + assassin_ui.PORT_SPAN
    assert {assassin_ui.project_port(tmp_path / f"p{n}") for n in range(20)} != {derived}  # a hash of the root, not one port for all
    ports = list(assassin_ui.project_ports(tmp_path))
    assert ports[0] == derived and sorted(ports) == list(range(assassin_ui.DEFAULT_PORT + 1, assassin_ui.DEFAULT_PORT + assassin_ui.PORT_SPAN + 1))

    holding = [_hold(derived)]
    following = next(port for port in ports[1:] if (probe := _hold(port)) and not probe.close())
    httpd = assassin_ui.make_server(app)  # the derived port held: the next free one of the range
    assert httpd.server_address[1] == following
    httpd.server_close()

    monkeypatch.setattr(assassin_ui, "PORT_SPAN", 3)
    holding += [_hold(port) for port in assassin_ui.project_ports(tmp_path)]
    httpd = assassin_ui.make_server(app)  # the whole range held: an ephemeral port
    assert httpd.server_address[1] not in set(assassin_ui.project_ports(tmp_path))
    httpd.server_close()

    taken = next(held for held in holding if held)
    with pytest.raises(OSError):
        assassin_ui.make_server(app, port=taken.getsockname()[1])  # an explicit port is that port or nothing
    for held in holding:
        if held:
            held.close()
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
    free.close()
    httpd = assassin_ui.make_server(app, port=port)
    assert httpd.server_address[1] == port
    httpd.server_close()

    seen = {}
    monkeypatch.setattr(assassin_ui, "serve", lambda **kwargs: seen.update(kwargs) or 0)
    monkeypatch.setattr(sys, "argv", ["assassin", "--no-browser"])
    assassin_ui.main()
    assert seen["port"] is None  # without --port the root decides
    monkeypatch.setattr(sys, "argv", ["assassin", "--port", "9123"])
    assassin_ui.main()
    assert seen["port"] == 9123


@pytest.mark.syngate("ASSASSIN-UI-SERVER-REUSE")
def test_a_second_assassin_on_a_served_root_opens_the_running_server_and_a_dead_record_is_replaced(app, tmp_path, monkeypatch):
    record, opened, made = tmp_path / assassin_ui.SERVER_FILE, [], []
    monkeypatch.setattr(assassin_ui.webbrowser, "open", opened.append)
    make_server = assassin_ui.make_server
    monkeypatch.setattr(assassin_ui, "make_server", lambda app, port=None, fd=None: made.append(make_server(app, port, fd)) or made[-1])

    def started():
        before = len(made)
        thread = threading.Thread(target=assassin_ui.serve, kwargs={"port": 0, "open_browser": False, "root": tmp_path, "reload": False}, daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while len(made) == before or not record.is_file() or json.loads(record.read_text())["port"] != made[-1].server_address[1]:
            assert time.monotonic() < deadline, "the server never wrote its record"
            time.sleep(0.02)
        return made[-1], thread

    def stopped(httpd, thread):
        httpd.shutdown()
        thread.join(10)
        assert not record.exists()  # removed when the server stops

    httpd, thread = started()
    stored = json.loads(record.read_text())
    assert stored == {"pid": os.getpid(), "port": httpd.server_address[1], "token": httpd.RequestHandlerClass.app.token}
    url = f"http://127.0.0.1:{stored['port']}/?token={stored['token']}"
    assert assassin_ui.serve(port=0, open_browser=True, root=tmp_path, reload=False) == 0
    assert opened == [url] and len(made) == 1  # the running server is opened, no second one is bound
    stopped(httpd, thread)

    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    record.write_text(json.dumps({"pid": gone.pid, "port": stored["port"], "token": stored["token"]}))
    httpd, thread = started()  # a record whose process is gone is ignored and replaced
    assert json.loads(record.read_text())["pid"] == os.getpid() and len(made) == 2
    silent = _hold(0)
    silent_port = silent.getsockname()[1]
    silent.close()
    stopped(httpd, thread)

    record.write_text(json.dumps({"pid": os.getpid(), "port": silent_port, "token": "stale"}))
    httpd, thread = started()  # a live pid whose server does not answer is ignored and replaced
    assert json.loads(record.read_text())["token"] == httpd.RequestHandlerClass.app.token and opened == [url]
    stopped(httpd, thread)


@pytest.mark.syngate("ASSASSIN-UI-BOOTSTRAP")
def test_a_project_without_item_files_is_bootstrapped_with_a_root_item_named_after_it(tmp_path, monkeypatch):
    project = tmp_path / "my-app"
    project.mkdir()
    (project / "README.md").write_text("An app.\n\n# My App\n\n## Usage\n")
    monkeypatch.delenv("SYNGATE_ROOT", raising=False)
    monkeypatch.chdir(project)
    root = assassin_ui.bootstrap()
    items, errors = syngatelib.load_tree(project / "syngate")
    assert root == project.resolve() and errors == [] and list(items) == ["MY-APP"]
    assert items["MY-APP"].parents == [] and items["MY-APP"].description == "My App\n\n[README.md](README.md)\n"
    assert syngatelib.features(items) == {"test": False, "review": False}
    assert assassin_ui.AssassinApp(root=root).build_model()["roots"] == ["MY-APP"]

    bare = tmp_path / "2048"
    (bare / "syngate").mkdir(parents=True)
    assert assassin_ui.bootstrap(bare) == bare.resolve()
    items, errors = syngatelib.load_tree(bare / "syngate")
    assert errors == [] and list(items) == ["PROJECT"] and items["PROJECT"].description == "2048\n"

    kept = tmp_path / "kept"
    (kept / "syngate" / "area").mkdir(parents=True)
    (kept / "syngate" / "area" / "BROKEN.yml").write_text("parents: [unclosed\n")
    before = {path: path.read_bytes() for path in kept.rglob("*") if path.is_file()}
    assert assassin_ui.bootstrap(kept) == kept.resolve()
    assert {path: path.read_bytes() for path in kept.rglob("*") if path.is_file()} == before


@pytest.mark.syngate("ASSASSIN-UI-REVIEW-CLEAR")
def test_edit_of_a_stamped_field_clears_the_review(server, syngate_tree):
    base, app = server
    syngate_dir, make_item = syngate_tree
    frozen = syngatelib.Item(uid="LEAF-002", path=syngate_dir / "LEAF-002.yml", description="Frozen\n\nIt shall freeze.\n", parents=["ROOT"], tests={None: "a" * 64})
    frozen.reviewed = syngatelib.compute_stamp(frozen)
    syngatelib.write_item(frozen)
    status, result = call(base, app, "/api/item/LEAF-002", {"order": 30, "sources": ["src/leaf.py"]})
    assert status == 200 and result["stamp_fresh"] is True  # order and sources sit outside the stamp
    status, result = call(base, app, "/api/item/LEAF-002", {"description": "Frozen v2\n\nIt shall freeze harder."})
    assert status == 200 and result["stamp_fresh"] is None
    expected = syngatelib.Item(uid="LEAF-002", path=frozen.path, description="Frozen v2\n\nIt shall freeze harder.\n",
                           parents=["ROOT"], order=30, sources=["src/leaf.py"], tests={None: None})
    assert (syngate_dir / "LEAF-002.yml").read_text() == syngatelib.dump_item(expected)  # canonical writer, stamp and sha dropped
    make_item(syngate_dir, "BRANCH-A", "Groups.\n", parents=("ROOT",))
    syngatelib.write_item(frozen)
    call(base, app, "/api/move/LEAF-002", {"from": "ROOT", "to": "BRANCH-A", "before": None})
    moved = syngatelib.parse_item((syngate_dir / "LEAF-002.yml").read_text())
    assert moved["parents"] == ["BRANCH-A"] and "review" not in moved and moved["test"] is None


@pytest.mark.syngate("ASSASSIN-UI-FIELD-SAVE", "guard")
def test_save_rejects_unknown_parent_and_cycle(server, syngate_tree):
    base, app = server
    syngate_dir, _ = syngate_tree
    before = (syngate_dir / "ROOT.yml").read_text()
    for parents in (["NOPE"], ["LEAF-001"]):  # unknown parent; child-of-own-child cycle
        with pytest.raises(urllib.error.HTTPError) as denied:
            call(base, app, "/api/item/ROOT", {"description": "Root branch\n", "parents": parents, "order": 0, "tests": None})
        assert denied.value.code == 400
    assert (syngate_dir / "ROOT.yml").read_text() == before


@pytest.mark.syngate("ASSASSIN-UI-FIELD-SAVE", "cas")
def test_partial_save_touches_only_named_fields_and_refuses_to_clobber_disk_edits(server, syngate_tree):
    base, app = server
    syngate_dir, _ = syngate_tree
    path = syngate_dir / "LEAF-001.yml"
    status, result = call(base, app, "/api/item/LEAF-001", {"sources": ["src/leaf.py"], "base": {"sources": []}})
    assert status == 200 and result["stored"]["sources"] == ["src/leaf.py"]
    on_disk = syngatelib.parse_item(path.read_text())
    assert on_disk == {"description": "It shall leaf.\n", "parents": ["ROOT"], "sources": ["src/leaf.py"], "test": None}
    path.write_text(path.read_text().replace("It shall leaf.", "It shall leaf, said the agent."))
    status, _ = call(base, app, "/api/item/LEAF-001", {"sources": ["src/leaf.py", "docs/LEAF.md"], "base": {"sources": ["src/leaf.py"]}})
    assert status == 200  # an on-disk edit of another field rebases silently
    assert syngatelib.parse_item(path.read_text())["description"] == "It shall leaf, said the agent.\n"
    with pytest.raises(urllib.error.HTTPError) as clash:
        call(base, app, "/api/item/LEAF-001", {"description": "It shall leaf, said the user.", "base": {"description": "It shall leaf.\n"}})
    assert clash.value.code == 409
    assert json.loads(clash.value.read())["current"] == {"description": "It shall leaf, said the agent.\n"}
    assert syngatelib.parse_item(path.read_text())["description"] == "It shall leaf, said the agent.\n"


def _orders(syngate_dir, *uids):
    return [syngatelib.parse_item((syngate_dir / f"{uid}.yml").read_text()).get("order", 0) for uid in uids]


@pytest.mark.syngate("ASSASSIN-UI-TREE-ROW-DROP", "reorder")
def test_move_takes_a_free_order_key_else_renumbers_the_family(server, syngate_tree):
    base, app = server
    syngate_dir, make_item = syngate_tree
    for uid, order in (("KID-A", 10), ("KID-B", 11), ("KID-C", 30)):
        make_item(syngate_dir, uid, "It shall sort.\n", parents=("ROOT",), order=order, tests=None)
    _, moved = call(base, app, "/api/move/LEAF-001", {"from": "ROOT", "to": "ROOT", "before": "KID-C"})
    assert moved["written"] == ["LEAF-001"] and _orders(syngate_dir, "LEAF-001") == [20]
    _, tree = call(base, app, "/api/tree")
    assert tree["items"]["ROOT"]["children"] == ["KID-A", "KID-B", "LEAF-001", "KID-C"]
    _, unmoved = call(base, app, "/api/move/LEAF-001", {"from": "ROOT", "to": "ROOT", "before": "KID-C"})
    assert unmoved["written"] == []
    _, moved = call(base, app, "/api/move/KID-C", {"from": "ROOT", "to": "ROOT", "before": "KID-B"})  # no integer between 10 and 11
    assert moved["written"] == ["KID-B", "KID-C", "LEAF-001"]
    assert _orders(syngate_dir, "KID-A", "KID-C", "KID-B", "LEAF-001") == [10, 20, 30, 40]


@pytest.mark.syngate("ASSASSIN-UI-TREE-ROW-DROP", "reparent")
def test_move_repoints_or_adds_the_parent_link_and_guards_the_dag(server, syngate_tree):
    base, app = server
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "BRANCH-A", "Groups.\n", parents=("ROOT",))
    make_item(syngate_dir, "BRANCH-B", "Groups too.\n", parents=("BRANCH-A",))
    call(base, app, "/api/move/LEAF-001", {"from": "ROOT", "to": "BRANCH-A", "before": "BRANCH-B"})
    _, tree = call(base, app, "/api/tree")
    assert tree["items"]["LEAF-001"]["parents"] == ["BRANCH-A"]
    assert tree["items"]["BRANCH-A"]["children"] == ["LEAF-001", "BRANCH-B"]
    call(base, app, "/api/move/LEAF-001", {"from": "BRANCH-A", "to": "BRANCH-B", "before": None, "link": True})
    _, tree = call(base, app, "/api/tree")
    assert tree["items"]["LEAF-001"]["parents"] == ["BRANCH-A", "BRANCH-B"]
    before = (syngate_dir / "BRANCH-A.yml").read_text()
    for target in ("BRANCH-B", "LEAF-001"):  # under its own descendant; under a test-bearing leaf
        with pytest.raises(urllib.error.HTTPError) as denied:
            call(base, app, "/api/move/BRANCH-A", {"from": "ROOT", "to": target, "before": None})
        assert denied.value.code == 400
    assert (syngate_dir / "BRANCH-A.yml").read_text() == before


@pytest.mark.syngate("ASSASSIN-UI-FILE-MANAGE")
def test_new_and_delete_manage_item_files(server, syngate_tree):
    base, app = server
    syngate_dir, _ = syngate_tree
    status, _ = call(base, app, "/api/new", {"uid": "LEAF-003", "parents": ["ROOT"], "dir": "syngate/sub", "kind": "leaf"})
    assert status == 200
    created = syngatelib.parse_item((syngate_dir / "sub" / "LEAF-003.yml").read_text())
    assert created["parents"] == ["ROOT"] and created["test"] is None
    with pytest.raises(urllib.error.HTTPError) as duplicate:
        call(base, app, "/api/new", {"uid": "LEAF-003", "parents": ["ROOT"]})
    assert duplicate.value.code == 400
    with pytest.raises(urllib.error.HTTPError) as populated:
        call(base, app, "/api/delete/ROOT", {})
    assert populated.value.code == 400  # has children
    status, _ = call(base, app, "/api/delete/LEAF-003", {})
    assert status == 200 and not (syngate_dir / "sub" / "LEAF-003.yml").exists()


@pytest.mark.syngate("ASSASSIN-UI-STATUS-POPUP-RUN", "stream")
def test_review_runs_cli_and_streams_output_until_exit(server):
    base, app = server
    status, job = call(base, app, "/api/run", {"action": "review", "uids": ["rc-3", "LEAF-001"]})
    assert status == 200
    status, body = call(base, app, f"/api/job/{job['job']}/events?token={app.token}", token=False, raw=True)
    text = body.decode().replace("\r", "")
    assert "stub: review rc-3 LEAF-001" in text
    assert "event: done\ndata: 3\n" in text
    status, snapshot = call(base, app, f"/api/job/{job['job']}")
    assert snapshot["returncode"] == 3 and snapshot["running"] is False
    assert "--build-dir" in snapshot["argv"]  # review forwards the build dir


@pytest.mark.syngate("ASSASSIN-UI-STATUS-POPUP-RUN", "single_flight")
def test_concurrent_runs_are_refused_while_busy(server):
    base, app = server
    app.cli_prefix = [sys.executable, "-c", "import sys, time; print('held'); sys.stdout.flush(); time.sleep(30)"]
    _, job = call(base, app, "/api/run", {"action": "clear", "uids": ["LEAF-001"]})
    try:
        with pytest.raises(urllib.error.HTTPError) as busy:
            call(base, app, "/api/run", {"action": "clear", "uids": ["LEAF-001"]})
        assert busy.value.code == 409
    finally:
        app.jobs.cancel()
    status, snapshot = call(base, app, f"/api/job/{job['job']}")
    assert snapshot["running"] is False


@pytest.mark.syngate("ASSASSIN-UI-STATUS-POPUP-RUN", "branch")
def test_a_branch_run_addresses_every_leaf_below_it(server, syngate_tree):
    base, app = server
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "BRANCH-A", "Groups.\n", parents=("ROOT",))
    make_item(syngate_dir, "BRANCH-B", "Groups nothing yet.\n", parents=("ROOT",))
    make_item(syngate_dir, "LEAF-002", "It shall nest.\n", parents=("BRANCH-A",), tests=None)
    _, job = call(base, app, "/api/run", {"action": "test", "uids": ["ROOT"]})
    _, body = call(base, app, f"/api/job/{job['job']}/events?token={app.token}", token=False, raw=True)
    assert f"stub: test LEAF-002 LEAF-001 --build-dir {app.build_dir} --coverage-out {app.run_coverage}" in body.decode()
    _, job = call(base, app, "/api/run", {"action": "review", "uids": ["BRANCH-A"]})
    _, body = call(base, app, f"/api/job/{job['job']}/events?token={app.token}", token=False, raw=True)
    assert "stub: review LEAF-002 BRANCH-A --build-dir" in body.decode()  # the branch stamps after its children
    with pytest.raises(urllib.error.HTTPError) as barren:
        call(base, app, "/api/run", {"action": "test", "uids": ["BRANCH-B"]})
    assert barren.value.code == 400


@pytest.mark.syngate("ASSASSIN-UI-CONTENT-FILE-VIEW", "read")
def test_linked_files_are_served_only_from_inside_the_project(server, tmp_path_factory):
    base, app = server
    (app.root / "docs").mkdir()
    (app.root / "docs" / "GUIDE.md").write_text("# Guide\n")
    (app.root / "key.txt").write_text("secret\n")
    outside = tmp_path_factory.mktemp("outside") / "LEAK.md"
    outside.write_text("# Leak\n")
    (app.root / "docs" / "LINK.md").symlink_to(outside)
    status, served = call(base, app, "/api/file?path=docs/GUIDE.md")
    assert status == 200 and served["text"] == "# Guide\n" and served["writable"] is True
    _, state = call(base, app, "/api/fingerprint?file=docs/GUIDE.md&file=docs/GONE.md")
    assert state["files"] == {"docs/GUIDE.md": served["sha"], "docs/GONE.md": None}
    for path, code in (("key.txt", 403), ("../GUIDE.md", 400), ("docs/../key.txt", 400), ("docs/LINK.md", 404), ("docs/GONE.md", 404)):  # untracked non-markdown; traversal; symlink escape; missing
        with pytest.raises(urllib.error.HTTPError) as denied:
            call(base, app, f"/api/file?path={path}")
        assert denied.value.code == code, path


@pytest.mark.syngate("ASSASSIN-UI-CONTENT-FILE-VIEW", "save")
def test_file_save_is_a_compare_and_swap_limited_to_markdown(server):
    base, app = server
    guide = app.root / "GUIDE.md"
    guide.write_text("# Guide\n")
    (app.root / "notes.txt").write_text("plain\n")
    status, saved = call(base, app, "/api/file", {"path": "GUIDE.md", "text": "# Guide\n\nTyped.\n", "base": "# Guide\n"})
    assert status == 200 and saved["stored"] == {"file": "# Guide\n\nTyped.\n"} and guide.read_text() == "# Guide\n\nTyped.\n"
    guide.write_text("# Guide\n\nSaid the agent.\n")
    with pytest.raises(urllib.error.HTTPError) as clash:
        call(base, app, "/api/file", {"path": "GUIDE.md", "text": "# Guide\n\nTyped more.\n", "base": "# Guide\n\nTyped.\n"})
    assert clash.value.code == 409 and json.loads(clash.value.read())["current"] == {"file": "# Guide\n\nSaid the agent.\n"}
    assert guide.read_text() == "# Guide\n\nSaid the agent.\n"
    with pytest.raises(urllib.error.HTTPError) as foreign:
        call(base, app, "/api/file", {"path": "notes.txt", "text": "edited\n", "base": "plain\n"})
    assert foreign.value.code == 403 and (app.root / "notes.txt").read_text() == "plain\n"


@pytest.mark.syngate("ASSASSIN-UI-RENDER", "csp")
def test_the_page_runs_only_its_own_nonced_script(server):
    base, app = server
    request = urllib.request.Request(base + "/", headers={"X-Assassin-Token": app.token})
    with urllib.request.urlopen(request) as response:
        policy, page = response.headers["Content-Security-Policy"], response.read().decode()
    nonce = policy.split("script-src 'nonce-")[1].split("'")[0]
    assert "default-src 'none'" in policy and f'<script nonce="{nonce}">' in page and "<script>" not in page


def test_the_page_script_loads_and_renders_without_an_uncaught_error(server, chrome):
    base, app = server
    opened = Page(chrome, f"{base}/?token={app.token}")
    chrome.call("Runtime.enable", session=opened.session)
    thrown = lambda: [event["params"]["exceptionDetails"] for event in chrome.events if event["method"] == "Runtime.exceptionThrown" and event.get("sessionId") == opened.session]
    errors = lambda: [f"{d.get('exception', {}).get('description', d['text'])} (assassin_ui.html:{d['lineNumber'] + 1})" for d in thrown()]
    deadline = time.monotonic() + 10
    while not errors() and not opened.eval("Boolean(document.querySelector('#tree [data-path]') && document.querySelector('#doc [data-path]'))"):
        assert time.monotonic() < deadline, "the page rendered neither tree nor content"
        time.sleep(0.05)
    assert errors() == []


PATHS = "[...document.querySelectorAll('%s [data-path]')].map((el) => el.dataset.path)"


@pytest.mark.syngate("ASSASSIN-UI-RENDER", "render")
def test_the_page_renders_every_tree_item_from_the_served_model(page):
    assert page.eval(PATHS % "#tree") == ["ROOT", "ROOT/LEAF-001"]
    assert page.eval(PATHS % "#doc") == ["ROOT", "ROOT/LEAF-001"]
    assert page.eval("[document.title, document.querySelector('header h1').textContent]") == ["Root branch · AI Assassin", "Root branch"]  # the tree names the page


@pytest.mark.syngate("ASSASSIN-UI-TREE-ROW-TITLE")
def test_a_row_title_is_cut_with_an_ellipsis_exactly_where_the_row_runs_out_of_room(page, syngate_tree):
    syngate_dir, make_item = syngate_tree
    first = "A title that runs past the edge of a narrow outline"
    make_item(syngate_dir, "LEAF-002", f"{first}\n\nIt shall fit where there is room.\n", parents=("ROOT",), tests=None)
    page.wait("document.querySelector('#tree [data-uid=\"LEAF-002\"] .title')")
    look = "(() => { const el = document.querySelector('#tree [data-uid=\"LEAF-002\"] .title');" \
           " return [el.textContent, el.title, getComputedStyle(el).textOverflow, el.scrollWidth > el.clientWidth]; })()"
    page.eval("setTreeWidth(600)")
    assert page.eval(look) == [first, first, "ellipsis", False]  # room enough: the whole line
    page.eval("setTreeWidth(300)")
    assert page.eval(look) == [first, first, "ellipsis", True]  # no room: cut, the whole line in the tooltip
    page.eval("setTreeWidth(600)")
    assert page.eval(look)[3] is False


@pytest.fixture
def violated_page(page, syngate_tree):
    """The page with LEAF-002 selected: reviewed, but its stamped routine is gone -- test unknown, review violated."""
    syngate_dir, _ = syngate_tree
    frozen = syngatelib.Item(uid="LEAF-002", path=syngate_dir / "LEAF-002.yml", description="Frozen\n\nIt shall freeze.\n", parents=["ROOT"], tests={None: "a" * 64})
    frozen.reviewed = syngatelib.compute_stamp(frozen)
    syngatelib.write_item(frozen)
    page.wait("document.querySelector('#tree [data-uid=\"LEAF-002\"]')")
    page.eval("select('LEAF-002', 'ROOT/LEAF-002')")
    return page


LABEL = "(() => { const el = document.querySelector('%s'), mark = el.querySelector('.status');" \
        " return [mark.className, mark.nextElementSibling.textContent, [...mark.children].map((c) => c.className + ':' + c.textContent)]; })()"


@pytest.mark.syngate("ASSASSIN-UI-LABEL")
def test_row_and_panel_label_an_item_by_one_status_icon_and_id(violated_page, server, syngate_tree):
    page, (_, app), (syngate_dir, _) = violated_page, server, syngate_tree
    routines = app.root / "scripts" / "tests"
    routines.mkdir(parents=True)
    (routines / "test_leaf.py").write_text('import pytest\n\n\n@pytest.mark.syngate("LEAF-003")\ndef test_leaf():\n    pass\n')
    sha = syngatelib.routine_sha(syngatelib.discover_bindings(app.root)[("LEAF-003", None)][0])
    approved = syngatelib.Item(uid="LEAF-003", path=syngate_dir / "LEAF-003.yml", description="Approved\n\nIt shall pass.\n", parents=["ROOT"], tests={None: sha})
    approved.reviewed = syngatelib.compute_stamp(approved)
    syngatelib.write_item(approved)
    for uid in ("LEAF-001", "LEAF-003"):
        with open(app.run_coverage, "a") as coverage:
            coverage.write(json.dumps({"tags": [uid], "passed": True, "name": "", "log": ""}) + "\n")
    page.wait("document.querySelector('#tree [data-uid=\"LEAF-003\"] .status.green')")
    for place in ("#tree [data-uid=\"%s\"]", "#doc .block[data-uid=\"%s\"] legend"):
        assert page.eval(LABEL % (place % "LEAF-002")) == ["status gray review_violated", "LEAF-002", ["eyes:👀", "seal:❗"]]  # test unknown, review violated
        assert page.eval(LABEL % (place % "LEAF-001")) == ["status green not_reviewed", "LEAF-001", []]  # passed but not reviewed: empty square
        assert page.eval(LABEL % (place % "LEAF-003")) == ["status green reviewed", "LEAF-003", ["eyes:👀"]]  # passed and reviewed
    assert page.eval("document.querySelector('#tree [data-uid=\"LEAF-001\"] .status').title") == "test passed · not reviewed"
    circle = "(() => { const s = getComputedStyle(document.querySelector('%s .status')); return [s.borderRadius, s.width === s.height, Math.abs(parseFloat(s.width) - (1.15 * parseFloat(s.fontSize) + 2)) < 0.1]; })()"
    for place in ("#tree [data-uid=\"LEAF-001\"]", "#doc .block[data-uid=\"LEAF-001\"] legend"):
        assert page.eval(circle % place) == ["50%", True, True]  # a circle 1.15 times the glyph size plus 2px, in either pane


ROW_PARTS = "[...document.querySelector('#tree [data-uid=\"LEAF-002\"]').querySelectorAll('.twist, .status, .node-uid, .chat-state, .dupmark, .title, .tools button:not([hidden])')]" \
            ".map((el) => el.dataset.act || el.className.split(' ')[0])"
MENU_ENTRIES = "[document.getElementById('status-menu').matches(':popover-open'), [...document.querySelectorAll('#status-menu [data-row-act]')].map((el) => el.dataset.rowAct)]"
MENU_OPEN = "document.getElementById('status-menu').matches(':popover-open')"


def open_row_menu(page, uid):
    page.eval(f"document.querySelector('#tree [data-uid=\"{uid}\"] [data-act=\"menu\"]').click()")


@pytest.mark.syngate("ASSASSIN-UI-TREE-ROW-COMPOSITION")
def test_a_tree_row_shows_collapse_mark_label_chat_state_title_and_menu_button_only(violated_page):
    page = violated_page
    assert page.eval(ROW_PARTS) == ["twist", "status", "node-uid", "chat-state", "title", "menu"]
    assert page.eval("Boolean(document.querySelector('#tree .row-problems'))") is False


@pytest.mark.syngate("ASSASSIN-UI-TREE-ROW-MENU")
def test_the_row_menu_button_opens_a_drop_down_of_the_item_actions_fit_for_the_row(violated_page):
    page = violated_page
    edge = "(() => { const row = document.querySelector('#tree [data-uid=\"LEAF-002\"]'), menu = row.querySelector('[data-act=\"menu\"]');" \
           " return [row.lastElementChild.contains(menu), row.getBoundingClientRect().right - menu.getBoundingClientRect().right]; })()"
    last, gap = page.eval(edge)
    assert last and 0 <= gap < 8  # the last thing on the row, flush with its right end
    open_row_menu(page, "LEAF-002")
    open_row_menu(page, "LEAF-002")
    assert page.eval(MENU_ENTRIES) == [True, ["add-parent", "add", "delete"]]  # structure edits only behind the explicit menu
    assert page.eval("[document.querySelectorAll(':popover-open').length, document.activeElement.textContent]") == [1, "⇑ Add parent"]  # opened twice: one menu, its first entry focused
    page.eval(KEY % ("document.activeElement", "ArrowDown"))
    assert page.eval("document.activeElement.textContent") == "+ Add child"
    page.eval(KEY % ("document.activeElement", "Escape"))
    assert page.eval(f"[{MENU_OPEN}, document.activeElement.dataset.act]") == [False, "menu"]  # closed, the focus back on the ⋯ it came from
    open_row_menu(page, "ROOT")
    assert page.eval(MENU_ENTRIES) == [True, ["add"]]  # the root has no parent to add and an item with children cannot be deleted
    page.eval("new Promise((done) => requestAnimationFrame(() => setTimeout(done, 0)))")  # the frame of the selection's own scroll passes
    page.eval("document.getElementById('doc-pane').dispatchEvent(new Event('scroll'))")
    assert page.eval(MENU_OPEN) is False  # a scroll of either pane closes it


@pytest.mark.syngate("ASSASSIN-UI-TREE-MENU-ADD-CHILD")
def test_add_child_opens_the_new_uid_row_under_the_item(violated_page):
    page = violated_page
    open_row_menu(page, "ROOT")
    page.eval("document.querySelector('#status-menu [data-row-act=\"add\"]').click()")
    assert page.eval("Boolean(document.querySelector('#tree .row.adding .new-uid'))")


@pytest.mark.syngate("ASSASSIN-UI-TREE-MENU-ADD-PARENT")
def test_add_parent_links_one_more_parent_keeping_the_old_one(violated_page):
    page = violated_page
    open_row_menu(page, "LEAF-001")
    page.eval("document.querySelector('#status-menu [data-row-act=\"add-parent\"]').click()")
    search = "(() => { const rows = [...document.querySelectorAll('#tree .row')], i = rows.findIndex((r) => r.dataset.uid === 'LEAF-001');" \
             " return [rows[i + 1].classList.contains('adding'), [...rows[i + 1].querySelectorAll('datalist option')].map((o) => o.value)]; })()"
    assert page.eval(search) == [True, ["LEAF-002"]]  # the search row sits right under the item and offers the items it may hang from
    page.eval("(() => { const input = document.querySelector('#tree .row.adding .new-uid'); input.value = 'LEAF-002'; input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); })()")
    page.wait("state.model.items['LEAF-001'].parents.length === 2")
    assert page.eval("[state.model.items['LEAF-001'].parents, state.model.items['LEAF-002'].children]") == [["ROOT", "LEAF-002"], ["LEAF-001"]]  # linked, the old parent kept


ASK = "window.asked = []; window.confirm = (text) => { window.asked.push(text); return %s; }"


@pytest.mark.syngate("ASSASSIN-UI-TREE-MENU-DELETE")
def test_delete_is_offered_for_a_childless_item_only_and_removes_its_file_after_a_confirmation_naming_it(violated_page, syngate_tree):
    page, (syngate_dir, _) = violated_page, syngate_tree
    open_row_menu(page, "ROOT")
    assert "delete" not in page.eval(MENU_ENTRIES)[1]  # an item with children keeps its file
    open_row_menu(page, "LEAF-002")
    page.eval(ASK % "false")
    page.eval("document.querySelector('#status-menu [data-row-act=\"delete\"]').click()")
    assert page.eval("window.asked") == ["Delete LEAF-002 and its file syngate/LEAF-002.yml? This cannot be undone."]
    assert (syngate_dir / "LEAF-002.yml").exists() and page.eval(f"[{MENU_OPEN}, state.selected]") == [False, "LEAF-002"]  # declined: nothing happens
    open_row_menu(page, "LEAF-002")
    page.eval(ASK % "true")
    page.eval("document.querySelector('#status-menu [data-row-act=\"delete\"]').click()")
    page.wait("!document.querySelector('#tree [data-uid=\"LEAF-002\"]')")
    assert not (syngate_dir / "LEAF-002.yml").exists() and page.eval(PATHS % "#tree") == ["ROOT", "ROOT/LEAF-001"] and page.eval("state.selected") is None


@pytest.mark.syngate("ASSASSIN-UI-TREE-MENU-UNLINK")
def test_unlink_is_offered_under_each_parent_of_a_multi_parent_item_and_drops_that_one_link(violated_page, syngate_tree):
    page, (syngate_dir, make_item) = violated_page, syngate_tree
    make_item(syngate_dir, "BR-001", "Branch\n", parents=("ROOT",), header="Branch")
    make_item(syngate_dir, "LEAF-001", "It shall leaf.\n", parents=("ROOT", "BR-001"), header="First leaf", tests=None)
    page.wait("document.querySelector('#tree [data-uid=\"BR-001\"]')")
    page.eval("state.expanded.add('BR-001'); persistExpanded(); render()")
    menu_at = lambda path: page.eval(f"document.querySelector('#tree [data-path=\"{path}\"] [data-act=\"menu\"]').click()")
    entries = "[...document.querySelectorAll('#status-menu [data-row-act]')].map((el) => el.dataset.rowAct + ':' + el.textContent)"
    menu_at("ROOT/BR-001/LEAF-001")
    assert page.eval(entries) == ["add-parent:⇑ Add parent", "add:+ Add child", "unlink:⊖ Unlink from BR-001", "delete:✕ Delete item"]  # the parent the row sits under
    menu_at("ROOT/LEAF-001")
    assert page.eval(entries)[2] == "unlink:⊖ Unlink from ROOT"
    menu_at("ROOT/BR-001/LEAF-001")
    page.eval("document.querySelector('#status-menu [data-row-act=\"unlink\"]').click()")
    page.wait("!document.querySelector('#tree [data-path=\"ROOT/BR-001/LEAF-001\"]')")
    assert page.eval("[state.model.items['LEAF-001'].parents, state.model.items['BR-001'].children]") == [["ROOT"], []] and (syngate_dir / "LEAF-001.yml").exists()
    assert page.eval(PATHS % "#tree") == ["ROOT", "ROOT/BR-001", "ROOT/LEAF-001", "ROOT/LEAF-002"]  # the item stays under its other parent
    menu_at("ROOT/LEAF-001")
    assert page.eval(MENU_ENTRIES) == [True, ["add-parent", "add", "delete"]]  # one parent left: nothing to unlink


SCROLL_SPY ="window.scrolled = []; Element.prototype.scrollIntoView = function () { window.scrolled.push(this.className.split(' ')[0]); }"


@pytest.mark.syngate("ASSASSIN-UI-TREE-ROW-CLICK")
def test_a_single_click_selects_the_row_without_activating_or_scrolling_to_its_panel(violated_page):
    page = violated_page
    page.eval(SCROLL_SPY)
    page.eval("document.querySelector('#tree [data-uid=\"LEAF-001\"] .cell-title').click()")
    selection = "[state.selected, document.querySelector('#tree .row.selected').dataset.uid, [...document.querySelectorAll('#doc .block.selected')].map((b) => b.dataset.uid), window.scrolled.includes('block')]"
    assert page.eval(selection) == ["LEAF-001", "LEAF-001", [], False]


@pytest.mark.syngate("ASSASSIN-UI-TREE-ROW-DOUBLE-CLICK")
def test_a_double_click_activates_the_panel_and_scrolls_to_it_only_when_out_of_view(violated_page):
    page = violated_page
    page.eval(SCROLL_SPY)
    dblclick = "document.querySelector('#tree [data-uid=\"%s\"] .cell-title').dispatchEvent(new MouseEvent('dblclick', { bubbles: true }))"
    page.eval(dblclick % "LEAF-001")
    assert page.eval("[state.selected, document.querySelector('#doc .block.selected').dataset.uid, window.scrolled.includes('block')]") == ["LEAF-001", "LEAF-001", False]  # the panel is in view: activated, not scrolled
    page.eval("document.getElementById('doc-pane').style.height = '40px'; window.scrolled = []")
    page.eval(dblclick % "LEAF-002")
    assert page.eval("[state.selected, window.scrolled.includes('block')]") == ["LEAF-002", True]  # the panel is out of view: scrolled to


@pytest.mark.syngate("ASSASSIN-UI-CONTENT-LABEL")
def test_a_block_carries_the_status_label_without_title_or_menu_on_its_top_border(violated_page):
    page = violated_page
    label = "(() => { const block = document.querySelector('#doc .block[data-uid=\"LEAF-002\"]'), tag = block.querySelector('legend .tag'), at = tag.getBoundingClientRect(), box = block.getBoundingClientRect();" \
            " return [[...tag.children].filter((e) => !e.classList.contains('status')).map((e) => e.textContent).join(''), tag.querySelectorAll('button:not(.status)').length, Math.abs(at.top + at.height / 2 - box.top) < at.height]; })()"
    assert page.eval(label) == ["LEAF-002", 0, True]


POPUP = "(() => { const pop = document.getElementById('tests-pop'); return [pop.matches(':popover-open'), pop.dataset.uid, pop.getAttribute('aria-label')," \
        " [...pop.querySelectorAll('.status-lines > div')].map((el) => [el.className, el.textContent]), [...pop.querySelectorAll('[data-run]')].map((el) => el.dataset.run + ':' + el.textContent + ':' + el.disabled)," \
        " [...pop.querySelectorAll('.section-label')].map((el) => el.textContent), [...pop.querySelectorAll('.binding-row .name')].map((el) => el.textContent)]; })()"


@pytest.mark.syngate("ASSASSIN-UI-STATUS-POPUP", "label")
def test_the_status_icon_on_the_block_label_opens_the_popup_listing_status_bindings_runs_and_run_actions(violated_page):
    page = violated_page
    assert page.eval("document.querySelectorAll('#doc .block-status, #doc .tip, #tree [data-act=\"tests\"]').length") == 0  # nothing else shows the status
    icon = "document.querySelector('#doc .block[data-uid=\"%s\"] legend .status')"
    page.eval(f"{icon % 'LEAF-002'}.click()")
    opened, uid, label, lines, runs, sections, bindings = page.eval(POPUP)
    assert (opened, uid, label, sections, bindings) == (True, "LEAF-002", "status, tests and review of LEAF-002", ["LEAF-002 tests", "run"], ["(default)"])
    assert lines[0] == ["tip-unknown", "not run"] and lines[1][0] == "tip-unknown" and lines[1][1].startswith("(default) · not run · no test bound yet — tag one with LEAF-002")
    assert lines[2] == ["tip-review_violated", "⚠ review violated"] and lines[-1][0] == "tip-review_violated" and "no test routine tagged [LEAF-002] found" in lines[-1][1]
    assert runs == ["test:▶ Run test:false", "review:👀 Mark reviewed:false", "clear:✕ Clear review:false"]
    place = f"(() => {{ const at = {icon % 'LEAF-002'}.getBoundingClientRect(), el = document.getElementById('tests-pop'), pop = el.getBoundingClientRect(); return [pop.top >= at.bottom, Math.abs(pop.left - at.left) < 2, el.scrollWidth <= el.clientWidth]; }})()"
    assert page.eval(place) == [True, True, True] and page.eval("[state.selected, state.panel, Boolean(document.querySelector('#doc .block.editing'))]") == ["LEAF-002", True, False]
    assert page.eval("[document.querySelector('#tests-pop #f-isleaf').checked, Boolean(document.querySelector('#tests-pop #f-add-binding')), document.querySelector('#tests-pop .binding-row .sha').textContent]") == [True, True, "frozen by review"]
    page.eval(f"{icon % 'ROOT'}.click()")
    opened, uid, label, lines, runs, sections, bindings = page.eval(POPUP)
    assert (opened, uid, sections, bindings) == (True, "ROOT", ["run"], [])  # a branch: its tally, no binding editor
    assert lines[:2] == [["tip-unknown", "not run"], ["tip-unknown", "2 items below not run"]] and runs[0] == "test:▶ Run tests of 2 leaf items:false" and runs[1] == "review:👀 Mark reviewed with 2 items below:false"
    assert page.eval("document.querySelectorAll(':popover-open').length") == 1
    page.eval("window.asked = []; window.confirm = (text) => { window.asked.push(text); return false; }")
    page.eval("document.querySelector('#tests-pop [data-run=\"review\"]').click()")
    assert page.eval("window.asked") == ["Run the tests of the 2 leaf items under ROOT and mark ROOT and every item below it reviewed?"] and page.eval(POPUP)[0] is False


@pytest.mark.syngate("ASSASSIN-UI-STATUS-POPUP", "row")
def test_the_status_icon_in_the_tree_row_opens_the_same_popup_selecting_the_row_only(violated_page):
    page = violated_page
    page.eval(SCROLL_SPY)
    page.eval("document.querySelector('#tree [data-uid=\"LEAF-001\"] .status').click()")
    opened, uid, label, lines, runs, sections, bindings = page.eval(POPUP)
    assert (opened, uid, label, lines[0], runs[0], bindings) == (True, "LEAF-001", "status, tests and review of LEAF-001", ["tip-unknown", "not run"], "test:▶ Run test:false", ["(default)"])
    assert page.eval("[state.selected, state.panel, document.querySelectorAll('#doc .block.selected').length, window.scrolled.includes('block')]") == ["LEAF-001", False, 0, False]  # a row selection, the document left alone
    page.eval("document.querySelector('#tree [data-uid=\"LEAF-002\"] .status .eyes').click()")
    assert page.eval(POPUP)[1] == "LEAF-002" and page.eval("document.querySelectorAll(':popover-open').length") == 1
    page.eval("new Promise((done) => requestAnimationFrame(() => setTimeout(done, 0)))")  # the frame of the selection's own scroll passes
    page.eval("document.getElementById('tree-pane').dispatchEvent(new Event('scroll'))")
    assert page.eval(POPUP)[0] is False


def heard(text):
    """The user's text as the fake connectors read it: the harness's tree-off line, heading it while the Tree permission is off, stripped."""
    return text.removeprefix(assassin_ui.TREE_OFF + "\n")


class EchoConnector:
    models, efforts, modes = ("model-a", "model-b"), ("low", "high"), {"edit": True, "internet": True, "workflows": False}

    def __init__(self, label="Echo"):
        self.label = label

    def settings(self):
        return {"label": self.label, "models": [{"id": model, "name": model.removeprefix("model-")} for model in self.models], "efforts": list(self.efforts),
                "modes": [{"id": mode, "label": mode.capitalize(), "hint": mode + " hint", "default": default, "advanced": mode == "workflows"}
                          for mode, default in self.modes.items()]}

    def dispatch(self, context, text, model=None, effort=None, modes=(), session=None, on_step=None, stopped=None):
        return {"kind": "text", "text": f"{context}|{heard(text)}|{model}|{effort}|{','.join(modes)}|{session}"}, "session-1"


SETUP = "document.querySelector('.chat-setup').textContent"


def item_page(server, chrome, **connectors):
    base, app = server
    app.connectors = connectors or {"echo": EchoConnector()}
    page = Page(chrome, f"{base}/?token={app.token}")
    page.wait("document.querySelector('#tree [data-uid=\"LEAF-001\"]')")
    page.wait("document.querySelector('#doc .block[data-uid=\"LEAF-001\"] .chat-input')")
    return page


def enter_reply(page, uid):
    page.eval(f"document.querySelector('#doc .block[data-uid=\"{uid}\"] .chat-input').click()")


def open_chat(server, chrome, **connectors):
    page = item_page(server, chrome, **connectors)
    enter_reply(page, "LEAF-001")
    return page


def edit_leaf(page, text):
    page.eval("(() => { select('LEAF-001', 'ROOT/LEAF-001'); startEditing('ROOT/LEAF-001'); })()")
    page.eval(f"(() => {{ const text = document.querySelector('#doc .block.editing textarea'); text.value = '{text}'; text.dispatchEvent(new Event('input', {{ bubbles: true }})); }})()")


LEAF_BLOCK = "document.querySelector('#doc .block[data-uid=\"LEAF-001\"]')"


def tree_item(server, uid):
    base, app = server
    return call(base, app, "/api/tree")[1]["items"][uid]


KEY = "%s.dispatchEvent(new KeyboardEvent('keydown', { key: '%s', bubbles: true }))"
FOCUS = "(() => { const el = document.activeElement; return (el.dataset.uid ? el.dataset.uid + ' ' : '') + (el.dataset.act || el.id || el.className.split(' ')[0] || el.tagName.toLowerCase()); })()"


def press(page, key, code=None, vk=0, modifiers=0):
    """A real key through CDP, so the browser's own Tab traversal and button activation run."""
    for kind in ("keyDown", "keyUp"):
        params = {"type": kind, "key": key, "code": code or key, "windowsVirtualKeyCode": vk, "modifiers": modifiers}
        if kind == "keyDown" and (len(key) == 1 or key == "Enter"):
            params["text"] = "\r" if key == "Enter" else key
        page.cdp.call("Input.dispatchKeyEvent", params, page.session)


def tab(page, back=False):
    press(page, "Tab", "Tab", 9, 8 if back else 0)
    return page.eval(FOCUS)
CTRL_ENTER = "%s.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, bubbles: true }))"
TOASTS = "[...document.querySelectorAll('#toasts .toast')].map((el) => el.className + ':' + el.textContent)"


@pytest.mark.syngate("ASSASSIN-UI-CONTENT-BLOCK-CLICK", "click")
def test_a_single_click_on_a_block_opens_its_editor_but_a_click_ending_a_text_selection_does_not(server, chrome):
    page = item_page(server, chrome)
    page.eval(f"{LEAF_BLOCK}.querySelector('.block-body .md').click()")
    editing = f"[state.editing, {LEAF_BLOCK}.classList.contains('editing'), document.activeElement === {LEAF_BLOCK}.querySelector('.block-body textarea')]"
    assert page.eval(editing) == ["ROOT/LEAF-001", True, True]
    page.eval(KEY % (f"{LEAF_BLOCK}.querySelector('.block-body textarea')", "Escape"))
    assert page.eval(editing) == [None, False, False]
    page.eval(f"(() => {{ const text = {LEAF_BLOCK}.querySelector('.block-body .md'), range = document.createRange(); range.selectNodeContents(text);"
              " getSelection().removeAllRanges(); getSelection().addRange(range); text.click(); })()")
    assert page.eval(editing) == [None, False, False]


@pytest.mark.syngate("ASSASSIN-UI-CONTENT-BLOCK-CLICK", "enter")
def test_enter_on_a_row_only_selection_activates_the_block_and_opens_the_editor(violated_page):
    page = violated_page
    page.eval("document.querySelector('#tree [data-uid=\"LEAF-001\"] .cell-title').click()")
    page.eval("document.querySelector('#tree .row.selected').focus()")
    assert page.eval("[state.panel, document.querySelectorAll('#doc .block.selected').length, document.activeElement.dataset.uid]") == [False, 0, "LEAF-001"]
    page.eval(KEY % ("document.activeElement", "Enter"))
    opened = "[state.panel, state.editing, document.querySelector('#doc .block.selected')?.dataset.uid, document.activeElement === document.querySelector('#doc .block.editing textarea')]"
    assert page.eval(opened) == [True, "ROOT/LEAF-001", "LEAF-001", True]
    page.eval("document.querySelector('#tree [data-uid=\"LEAF-002\"] .cell-title').click()")  # a row's own click leaves the editor standing
    assert page.eval("[state.selected, state.editing, Boolean(document.querySelector('#doc .block.editing textarea'))]") == ["LEAF-002", "ROOT/LEAF-001", True]
    page.eval("document.querySelector('#tree [data-uid=\"LEAF-002\"] .cell-title').dispatchEvent(new MouseEvent('dblclick', { bubbles: true }))")  # activating another block ends it
    assert page.eval("[state.selected, state.editing, Boolean(document.querySelector('#doc .block.editing'))]") == ["LEAF-002", None, False]


REST_HINT = "Type a message to start new chat"
OPEN_HINT = "Type message · Ctrl/⌘+Enter sends"
WAIT_HINT = "Waiting AI response"


@pytest.mark.syngate("AI_CHAT-070")
def test_the_reply_line_waits_under_every_item_outside_the_tab_order_with_its_hint_revealed_by_the_border(server, chrome):
    page = item_page(server, chrome)
    rest = "[...document.querySelectorAll('#doc .block')].map((el) => [Boolean(el.querySelector('.block-body ~ .block-chat > textarea.chat-input')), el.querySelector('.chat-input').placeholder, el.querySelector('.chat-input').tabIndex, el.querySelector('.block-ai').children.length])"
    assert page.eval(rest) == [[True, REST_HINT, -1, 0], [True, REST_HINT, -1, 0]]
    hint = f"getComputedStyle({LEAF_BLOCK}.querySelector('.chat-input'), '::placeholder').color"
    assert page.eval(hint) == "rgba(0, 0, 0, 0)"  # the hint is there for the hover, invisible at rest
    page.eval(f"{LEAF_BLOCK}.querySelector('.chat-input').focus()")
    assert page.eval(rest) == [[True, REST_HINT, -1, 0], [True, OPEN_HINT, 0, 6]]  # send with setup, three permissions, the advanced list, hide
    page.wait(f"{hint} === {json.dumps(css_color(page, '--dim'))}")
    page.eval(f"{LEAF_BLOCK}.querySelector('.chat-hide').click()")
    assert page.eval(rest) == [[True, REST_HINT, -1, 0], [True, REST_HINT, -1, 0]]
    edit_leaf(page, "It shall leaf, edited.")
    assert page.eval(rest)[1] == [True, OPEN_HINT, 0, 7]  # the save mark joins the strip while editing


@pytest.mark.syngate("AI_CHAT-REPLY-HINT")
@pytest.mark.syngate("AI_CHAT-REPLY-DRAFT")
def test_while_a_turn_runs_the_reply_line_shows_a_spinner_at_its_left_and_keeps_the_next_message_unsent(server, chrome):
    base, app = server
    gated = GatedConnector()
    page = open_chat(server, chrome, echo=gated)
    send(page, "LEAF-001", "Slow one")
    page.wait(f"{LEAF}.querySelector('.block-ai .chat-stop')")
    spinner = f"(() => {{ const spin = {LEAF}.querySelector('.reply-wait .spinner'), line = {LEAF}.querySelector('.chat-input'), box = spin.getBoundingClientRect();" \
              " return [line.placeholder, box.width > 0, box.right <= line.getBoundingClientRect().left]; })()"
    assert page.eval(spinner) == [WAIT_HINT, True, True]  # beside the field, never over its text
    page.eval(f"{LEAF}.querySelector('.chat-input').value = 'Next one'")
    page.eval(f"{LEAF}.querySelector('.block-ai .chat-send').click()")
    assert page.eval(TOASTS) == ["toast info:a turn of LEAF-001 is running — wait for it or stop it"] and page.eval(f"{LEAF}.querySelector('.chat-input').value") == "Next one"
    assert [m["role"] for m in call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]["log"]] == ["user"]
    gated.release.set()
    page.wait(f"{LEAF}.querySelector('.chat-msg.ai')")
    assert page.eval(spinner)[:2] == [OPEN_HINT, False]
    page.eval(f"{LEAF}.querySelector('.block-ai .chat-send').click()")
    page.wait(f"{LEAF}.querySelectorAll('.chat-msg.user').length === 2")


@pytest.mark.syngate("AI_CHAT-REPLY-NEW")
def test_entering_the_reply_line_of_a_hidden_chat_joins_a_running_turn_else_shows_a_new_conversation_filing_the_old_one_on_the_first_send(server, chrome):
    gated = GatedConnector()
    page = open_chat(server, chrome, echo=gated)
    send(page, "LEAF-001", "Slow one")
    page.wait(f"{LEAF}.querySelector('.block-ai .chat-stop')")
    page.eval("hideChat('ROOT/LEAF-001')")
    assert page.eval(f"[{LEAF}.querySelectorAll('.chat-msg').length, {LEAF}.querySelector('.chat-input').placeholder]") == [0, WAIT_HINT]
    enter_reply(page, "LEAF-001")
    assert page.eval(f"[...{LEAF}.querySelectorAll('.chat-msg.user')].map((el) => el.textContent)") == ["Slow one"]
    gated.release.set()
    page.wait(f"{LEAF}.querySelector('.chat-msg.ai')")
    assert page.eval("state.chats.get('LEAF-001').archive.length") == 0
    page.eval(f"{LEAF}.querySelector('.block-ai .chat-hide').click()")
    assert page.eval(f"{LEAF}.querySelector('.chat-input').placeholder") == REST_HINT
    enter_reply(page, "LEAF-001")
    assert page.eval(f"{LEAF}.querySelectorAll('.chat-msg').length") == 0
    page.eval(f"{LEAF}.querySelector('.block-ai .chat-hide').click()")  # shown, not sent: the conversations stay as they were
    enter_reply(page, "LEAF-001")
    assert page.eval(f"{LEAF}.querySelectorAll('.chat-msg').length") == 0 and page.eval("state.chats.get('LEAF-001').archive.length") == 0
    base, app = server
    assert [m["text"] for m in call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]["log"] if m["role"] == "user"] == ["Slow one"]
    send(page, "LEAF-001", "Fresh one")
    page.wait(f"{LEAF}.querySelector('.chat-msg.ai')")
    assert page.eval(f"[...{LEAF}.querySelectorAll('.chat-msg.user')].map((el) => el.textContent)") == ["Fresh one"]
    assert page.eval("state.chats.get('LEAF-001').archive.map((c) => c.title)") == ["Slow one"]  # filed by the first send


@pytest.mark.syngate("AI_CHAT-022", "send")
def test_editing_the_description_offers_the_ai_controls_and_sends_the_saved_statement_first_or_into_the_shown_conversation(server, chrome):
    page = item_page(server, chrome)
    edit_leaf(page, "It shall leaf better.")
    controls = f"[...{LEAF_BLOCK}.querySelectorAll('.block-ai .chat-send, .block-ai .chat-setup, .block-ai .chat-mode, .block-ai .chat-advanced')].length"
    assert page.eval(controls) == 6  # send, setup, the three permission switches and the advanced list, before anything is sent
    pick(page, "model", "model-b")
    page.eval(f"{LEAF_BLOCK}.querySelector('.block-ai .chat-send').click()")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    assert tree_item(server, "LEAF-001")["description_raw"].strip() == "It shall leaf better."
    assert page.eval(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai').textContent").endswith("It shall leaf better.|It shall leaf better.|model-b|low|edit,internet|None")
    assert page.eval(f"{LEAF_BLOCK}.querySelectorAll('.chat-msg.user').length") == 0  # the first message is the content itself
    edit_leaf(page, "It shall leaf by keyboard.")
    page.eval(CTRL_ENTER % "document.querySelector('#doc .block.editing textarea')")
    page.wait(f"{LEAF_BLOCK}.querySelectorAll('.chat-msg.ai').length === 2")
    assert tree_item(server, "LEAF-001")["description_raw"].strip() == "It shall leaf by keyboard."
    announced = assassin_ui.STATEMENT_NOTE.format(uid="LEAF-001", statement="It shall leaf by keyboard.")
    assert page.eval(f"[...{LEAF_BLOCK}.querySelectorAll('.chat-msg.user .msg-part')].map((el) => el.textContent)") == [announced]
    base, app = server
    assert call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]["log"][-1]["text"].endswith(f"|{announced}|model-b|low|edit,internet|session-1")  # into the shown conversation
    assert page.eval("state.chats.get('LEAF-001').archive.length") == 0
    page.eval(f"{LEAF_BLOCK}.querySelector('.block-ai .chat-hide').click()")
    edit_leaf(page, "It shall leaf by keyboard.")  # unchanged, and the chat hidden: Ctrl+Enter begins a new conversation all the same
    page.eval(CTRL_ENTER % "document.querySelector('#doc .block.editing textarea')")
    page.wait(f"{LEAF_BLOCK}.querySelectorAll('.chat-msg.ai').length === 1 && state.chats.get('LEAF-001').archive.length === 1")
    assert page.eval(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai').textContent").endswith("|It shall leaf by keyboard.|model-b|low|edit,internet|None")


@pytest.mark.syngate("AI_CHAT-022", "done")
def test_done_ends_the_edit_with_the_text_saved_closing_the_chat_and_beginning_no_conversation(server, chrome):
    base, app = server
    page = item_page(server, chrome)
    strip = f"[...{LEAF_BLOCK}.querySelectorAll('.block-ai .pill')].map((el) => el.className.split(' ').pop() + ':' + el.textContent.trim())"
    after = f"[state.editing, {LEAF_BLOCK}.classList.contains('editing'), {LEAF_BLOCK}.classList.contains('chatting'), document.activeElement === {LEAF_BLOCK}]"
    edit_leaf(page, "It shall leaf, done.")
    assert page.eval(strip)[0] == "chat-hide:▴ done" and page.eval(f"{LEAF_BLOCK}.classList.contains('chatting')")
    assert page.eval(f"{LEAF_BLOCK}.querySelectorAll('.block-ai .chat-hide, .block-ai .chat-stop').length") == 1  # one done, whatever is open
    corner = f"(() => {{ const done = {LEAF_BLOCK}.querySelector('.block-ai .chat-hide').getBoundingClientRect(), strip = {LEAF_BLOCK}.querySelector('.block-ai').getBoundingClientRect(), block = {LEAF_BLOCK}.getBoundingClientRect();" \
             " return [done.left - strip.left < 2, Math.abs(done.top + done.height / 2 - block.bottom) < done.height]; })()"
    assert page.eval(corner) == [True, True]  # the state pill leads the strip, straddling the bottom-left border
    page.eval(f"{LEAF_BLOCK}.querySelector('.block-ai .chat-hide').click()")
    page.wait("drafts.size === 0")
    assert page.eval(after) == [None, False, False, True] and tree_item(server, "LEAF-001")["description_raw"].strip() == "It shall leaf, done."
    assert call(base, app, "/api/chats")[1]["chats"].get("LEAF-001", {"log": []})["log"] == []  # nothing sent
    enter_reply(page, "LEAF-001")
    send(page, "LEAF-001", "Kept")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    edit_leaf(page, "It shall leaf, done twice.")
    assert page.eval(f"[...{LEAF_BLOCK}.querySelectorAll('.chat-msg.user')].map((el) => el.textContent)") == ["Kept"]  # the shown conversation goes on
    page.eval(f"{LEAF_BLOCK}.querySelector('.block-ai .chat-hide').click()")
    page.wait("drafts.size === 0")
    assert page.eval(after) == [None, False, False, True]  # the editor and the chat close together
    edit_leaf(page, "It shall leaf, done thrice.")
    assert page.eval(f"{LEAF_BLOCK}.querySelectorAll('.chat-msg').length") == 0  # a hidden chat is no chat: the editor shows a new conversation
    page.eval(KEY % (f"{LEAF_BLOCK}.querySelector('.block-body textarea')", "Escape"))
    page.wait("drafts.size === 0")
    chat = call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]
    assert page.eval(after) == [None, False, False, True] and chat["archive"] == [] and [m["text"] for m in chat["log"]][0] == "Kept"  # none begun, none sent


@pytest.mark.syngate("AI_CHAT-030", "esc")
def test_escape_is_the_done_mark_from_the_keyboard_and_keeps_a_typed_message_for_the_chat_shown_again(server, chrome):
    page = item_page(server, chrome)
    state = f"[state.editing, {LEAF_BLOCK}.classList.contains('chatting'), document.activeElement === {LEAF_BLOCK}, {LEAF_BLOCK}.querySelector('.chat-input').value]"
    edit_leaf(page, "It shall leaf by key.")
    page.eval(KEY % (f"{LEAF_BLOCK}.querySelector('.block-body textarea')", "Escape"))
    assert page.eval(state) == [None, False, True, ""]
    enter_reply(page, "LEAF-001")
    page.eval(f"{LEAF_BLOCK}.querySelector('.chat-input').value = 'a draft'")
    page.eval(KEY % (f"{LEAF_BLOCK}.querySelector('.chat-input')", "Escape"))
    assert page.eval(state) == [None, False, True, ""]  # hidden, the line at rest empty
    enter_reply(page, "LEAF-001")
    assert page.eval(state) == [None, True, False, "a draft"]  # the kept text is back
    page.eval(f"{LEAF_BLOCK}.querySelector('.block-ai .chat-hide').click()")
    assert page.eval(state) == [None, False, True, ""] and page.eval(TOASTS) == []
    page.eval(f"{LEAF_BLOCK}.querySelector('.chat-input').focus()")
    assert page.eval(state)[1:] == [True, False, "a draft"]
    page.eval(f"{LEAF_BLOCK}.querySelector('.chat-input').value = ''")
    page.eval(f"{LEAF_BLOCK}.focus()")
    page.eval(KEY % ("document.activeElement", "Escape"))
    assert page.eval(state) == [None, False, True, ""]  # on the focused block Esc hides its chat


@pytest.mark.syngate("AI_CHAT-REPLY-CLEAR")
def test_the_clear_mark_stands_on_the_right_border_level_with_a_reply_line_holding_text_and_empties_it_and_its_kept_text(server, chrome):
    base, app = server
    page = open_chat(server, chrome)
    send(page, "LEAF-001", "Kept")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    before = call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]
    line, mark = f"{LEAF_BLOCK}.querySelector('.chat-input')", f"{LEAF_BLOCK}.querySelector('.reply-clear')"
    shown = f"{mark}.getBoundingClientRect().width > 0"
    page.eval(f"{line}.focus()")
    assert page.eval(shown) is False and tab(page, back=True) != "reply-clear"  # an empty line has nothing to clear, and no mark in the Tab order
    page.eval(f"{line}.focus()")
    set_text(page, line, "a draft @lea")
    assert page.eval(shown) is True and page.eval(MENTION)[0] is True
    assert page.eval(f"[{mark}.tagName, {mark}.title, {mark}.tabIndex, Boolean({mark}.querySelector('svg path'))]") == ["BUTTON", "clear the message", 0, True]
    place = f"(() => {{ const m = {mark}.getBoundingClientRect(), l = {line}.getBoundingClientRect(), b = {LEAF_BLOCK}.getBoundingClientRect(), s = getComputedStyle({line});" \
            " const first = l.top + parseFloat(s.borderTopWidth) + parseFloat(s.paddingTop) + parseFloat(s.lineHeight) / 2;" \
            " return [Math.abs(m.left + m.width / 2 - (b.right - 0.5)) < 1.5, Math.abs(m.top + m.height / 2 - first) < 3, m.left >= l.right]; })()"
    assert page.eval(place) == [True, True, True]  # on the right border line, level with the line's first line, off the typed text
    looks = "(() => { const seen = new Set(); for (const el of document.querySelectorAll('%s')) { const s = getComputedStyle(el);" \
            " seen.add([s.width, s.height, s.borderTopStyle, s.borderTopWidth, s.borderTopLeftRadius, s.backgroundColor].join()); } return [...seen]; })()"
    assert len(page.eval(looks % f"#doc .msg-tools button, #doc .reply-clear")) == 1  # the one border-mark shape
    page.eval(f"{mark}.click()")
    cleared = f"[{line}.value, document.activeElement === {line}, {shown}, state.replies.has('LEAF-001'), {LEAF_BLOCK}.classList.contains('chatting')]"
    assert page.eval(cleared) == ["", True, False, False, True] and page.eval(MENTION)[0] is False
    set_text(page, line, "a second draft")
    page.eval(f"{LEAF_BLOCK}.querySelector('.block-ai .chat-hide').click()")
    assert page.eval("state.replies.get('LEAF-001')") == "a second draft" and page.eval(shown) is False  # kept by the tab, no mark on a hidden chat
    enter_reply(page, "LEAF-001")
    assert page.eval(f"[{line}.value, {shown}]") == ["a second draft", True]  # the kept text is back, and its mark with it
    page.eval(f"{line}.focus()")
    assert tab(page, back=True) == "reply-clear"  # reached by keyboard
    press(page, " ", "Space", 32)
    assert page.eval(cleared) == ["", True, False, False, True]
    page.eval(f"{LEAF_BLOCK}.querySelector('.block-ai .chat-hide').click()")
    enter_reply(page, "LEAF-001")
    assert page.eval(f"{line}.value") == ""  # nothing kept to come back
    after = call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]
    assert [after["log"], after["session"]] == [before["log"], before["session"]] and tree_item(server, "LEAF-001")["description_raw"].strip() == "It shall leaf."


MENTION = "(() => { const pop = document.getElementById('mention-hint'); return [pop.matches(':popover-open'), [...pop.querySelectorAll('.mention-entry')].map((e) => e.dataset.kind + ':' + e.dataset.value + (e.getAttribute('aria-selected') === 'true' ? '*' : ''))]; })()"


def type_keys(page, text):
    for char in text:
        press(page, char)


def set_text(page, target, text):
    page.eval(f"(() => {{ const el = {target}; el.value = {json.dumps(text)}; el.setSelectionRange(el.value.length, el.value.length); el.dispatchEvent(new Event('input', {{ bubbles: true }})); }})()")


@pytest.mark.syngate("AI_CHAT-MENTION-HINT", "page")
def test_typing_at_in_a_reply_line_or_an_editor_hints_items_and_files_and_a_pick_writes_the_mention(server, chrome):
    base, app = server
    for name in ("guide.md", "docs/leaf-notes.md"):
        (app.root / name).parent.mkdir(parents=True, exist_ok=True)
        (app.root / name).write_text("# Guide\n")
    page = item_page(server, chrome)
    page.activate()
    reply = f"{LEAF_BLOCK}.querySelector('.chat-input')"
    enter_reply(page, "LEAF-001")
    page.wait(f"document.activeElement === {reply}")
    assert page.eval(MENTION) == [False, []]
    type_keys(page, "@lea")
    page.wait("document.querySelectorAll('#mention-hint .mention-entry').length === 3")  # the items at once, the files once the listing arrives
    assert page.eval(MENTION) == [True, ["item:@LEAF-001*", "file:docs/leaf-notes.md", "file:syngate/LEAF-001.yml"]]
    assert page.eval("document.getElementById('mention-hint').style.length") == 2  # only the computed position is inline
    press(page, "Escape", "Escape", 27)
    assert page.eval(MENTION)[0] is False and page.eval(f"[{reply}.value, {LEAF_BLOCK}.classList.contains('chatting'), document.activeElement === {reply}]") == ["@lea", True, True]
    type_keys(page, "f")
    assert page.eval(MENTION)[0] is False  # dismissed for this word
    set_text(page, reply, "")
    type_keys(page, "@oo")
    page.wait("document.querySelectorAll('#mention-hint .mention-entry').length === 2")
    assert page.eval(MENTION) == [True, ["item:@ROOT*", "file:syngate/ROOT.yml"]]
    press(page, "ArrowDown", "ArrowDown", 40)
    assert page.eval(MENTION)[1] == ["item:@ROOT", "file:syngate/ROOT.yml*"]
    press(page, "ArrowUp", "ArrowUp", 38)
    assert page.eval(MENTION)[1][0] == "item:@ROOT*"
    press(page, "Enter", "Enter", 13)
    assert page.eval(MENTION)[0] is False and page.eval(f"[{reply}.value, {LEAF_BLOCK}.querySelectorAll('.chat-msg').length]") == ["@ROOT", 0]  # picked, not sent, no newline
    type_keys(page, " @zzz")
    assert page.eval(MENTION) == [False, []]  # nothing matches
    set_text(page, reply, "")
    type_keys(page, "@lea")
    page.wait("document.querySelectorAll('#mention-hint .mention-entry').length === 3")
    page.eval(f"{reply}.setSelectionRange(0, 0)")
    page.wait("!document.getElementById('mention-hint').matches(':popover-open')")  # the caret left the word
    set_text(page, reply, "")
    type_keys(page, "@lea")
    page.wait("document.getElementById('mention-hint').matches(':popover-open')")
    page.eval(f"{reply}.blur()")
    assert page.eval(MENTION)[0] is False

    page.eval(f"{reply}.value = ''")
    page.eval(f"{LEAF_BLOCK}.querySelector('.block-ai .chat-hide').click()")
    page.wait(f"!{LEAF_BLOCK}.classList.contains('chatting')")
    page.eval("(() => { select('LEAF-001', 'ROOT/LEAF-001'); startEditing('ROOT/LEAF-001'); })()")
    editor = "document.querySelector('#doc .block.editing textarea.block-text')"
    page.wait(f"document.activeElement === {editor}")
    type_keys(page, " see @oo")
    page.wait("document.querySelectorAll('#mention-hint .mention-entry').length === 2")
    press(page, "Tab", "Tab", 9)
    assert page.eval(MENTION)[0] is False and page.eval(f"{editor}.value") == "It shall leaf. see @ROOT"
    type_keys(page, " @guide")
    page.wait("document.querySelectorAll('#mention-hint .mention-entry').length === 1")
    assert page.eval(MENTION) == [True, ["file:guide.md*"]]
    press(page, "Enter", "Enter", 13)
    assert page.eval(f"{editor}.value") == "It shall leaf. see @ROOT guide.md"  # a file is written as its project-relative path
    type_keys(page, " @oo")
    page.wait("document.getElementById('mention-hint').matches(':popover-open')")
    press(page, "Escape", "Escape", 27)
    assert page.eval(MENTION)[0] is False and page.eval(f"[state.editing, {editor}.value]") == ["ROOT/LEAF-001", "It shall leaf. see @ROOT guide.md @oo"]  # Esc closed the hint only
    press(page, "Escape", "Escape", 27)
    assert page.eval("state.editing") is None
    page.wait("drafts.size === 0")
    assert tree_item(server, "LEAF-001")["description_raw"].strip() == "It shall leaf. see @ROOT guide.md @oo"  # every pick reached the autosave


@pytest.mark.syngate("AI_CHAT-025")
def test_user_messages_look_like_the_description_and_ai_replies_sit_right_highlighted(server, chrome):
    page = open_chat(server, chrome)
    send(page, "LEAF-001", "Styled?")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    look = f"(() => {{ const body = {LEAF_BLOCK}.querySelector('.block-body .block-text'), user = {LEAF_BLOCK}.querySelector('.chat-msg.user .msg-body'), ai = {LEAF_BLOCK}.querySelector('.chat-msg.ai .msg-body');" \
           " const css = (el) => getComputedStyle(el), at = (el) => el.getBoundingClientRect(); return [css(user).backgroundColor === css(body).backgroundColor, Math.abs(at(user).left - at(body).left) < 2," \
           " at(ai).left > at(user).left + 20 && Math.abs(at(ai).right - at(ai.parentElement).right) < 2, css(ai).backgroundColor !== css(body).backgroundColor]; })()"
    assert page.eval(look) == [True, True, True, True]  # the user's text flush with the description, the reply shifted right and highlighted


@pytest.mark.syngate("AI_CHAT-CONTROLS-FOLD-KEEP", "marks")
def test_the_fold_mark_folds_a_message_to_its_first_line_grey_and_out_of_the_exchange_and_back(server, chrome):
    base, app = server
    page = open_chat(server, chrome)
    send(page, "LEAF-001", "First")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    tools = f"[...{LEAF_BLOCK}.querySelectorAll('.chat-msg')].map((el) => [[...el.querySelectorAll('.msg-fold')].map((b) => b.getAttribute('aria-expanded')), el.querySelectorAll('.msg-keep').length])"
    assert page.eval(tools) == [[["true"], 0], [["true"], 0]]  # one fold mark per message and no keep mark: folded text is out of the exchange
    place = f"(() => {{ const msg = {LEAF_BLOCK}.querySelector('.chat-msg.ai'), mark = msg.querySelector('.msg-fold').getBoundingClientRect(), block = {LEAF_BLOCK}.getBoundingClientRect(), part = msg.querySelector('.msg-part').getBoundingClientRect();" \
            " return [Math.abs(mark.left + mark.width / 2 - block.left) < 2, Math.abs(mark.top + mark.height / 2 - (part.top + parseFloat(getComputedStyle(msg).lineHeight) / 2)) < 3]; })()"
    assert page.eval(place) == [True, True]  # on the block's left border line, level with the first line
    page.eval(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai .msg-fold').click()")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai.dropped')")
    gray = css_color(page, "--dim")
    look = f"(() => {{ const msg = {LEAF_BLOCK}.querySelector('.chat-msg.ai'); return [msg.querySelector('.msg-fold').getAttribute('aria-expanded'), getComputedStyle(msg).color, msg.querySelectorAll('.msg-cut').length," \
           " msg.querySelectorAll('.msg-child, .msg-sibling').length, msg.getBoundingClientRect().height <= 2 * parseFloat(getComputedStyle(msg).lineHeight)]; })()"
    assert page.eval(look) == ["false", gray, 1, 0, True]  # folded to its first line, grey, the extraction marks gone with the text
    reply = call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]["log"][1]
    assert reply["cuts"] == [[0, len(reply["text"])]] and app.chats["LEAF-001"].kept() == [{"role": "user", "text": "First"}]
    page.eval(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai .msg-fold').click()")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai:not(.dropped) .msg-child')")
    assert "cuts" not in call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]["log"][1] and len(app.chats["LEAF-001"].kept()) == 2


CHILD_ASK = "Make the text below a new child item of @LEAF-001, then carry its task on in the new item's own chat.\n\n"
SIBLING_ASK = "Make the text below the next sibling item of @LEAF-001 under @ROOT, then carry its task on in the new item's own chat.\n\n"


def settled(page, uid, messages):
    page.wait(f"state.chats.get('{uid}')?.log.length === {messages} && !state.chats.get('{uid}').turn")


def logged(app, uid):
    return [(m["role"], m["text"]) for m in app.chats[uid].log]


@pytest.mark.syngate("AI_CHAT-CONTROLS-ITEM", "marks")
def test_a_message_mark_sends_its_kept_text_as_a_turn_asking_the_ai_for_a_child_or_next_sibling_item_and_its_hand_over(server, chrome):
    base, app = server
    statement = "Leaf sentence\n\nIt shall be extracted."
    handed = [{"tool": "add", "uid": "LEAF-EXTRACTED", "parent": "ROOT", "description": statement}, {"tool": "agent", "uid": "LEAF-EXTRACTED", "prompt": "Deliver it."}]
    page = open_chat(server, chrome, echo=CallsConnector(statement, "Child asked.", "```syngate\n" + json.dumps(handed) + "\n```", "Delivered."))
    send(page, "LEAF-001", "Say something")
    settled(page, "LEAF-001", 2)
    page.eval("state.chats.get('LEAF-001').turn = 'LEAF-001:99'")
    page.eval(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai .msg-child').click()")
    assert page.eval(TOASTS)[-1] == "toast info:a turn of LEAF-001 is running — wait for it or stop it" and len(app.chats["LEAF-001"].log) == 2  # refused while a turn runs
    page.eval("state.chats.get('LEAF-001').turn = null")
    page.eval(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai .msg-child').click()")
    settled(page, "LEAF-001", 4)
    assert logged(app, "LEAF-001")[2:] == [("user", CHILD_ASK + statement), ("ai", "Child asked.")]
    assert page.eval(PATHS % "#tree") == ["ROOT", "ROOT/LEAF-001"]  # the page writes no item of its own: the AI words and names it
    page.eval(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai .msg-sibling').click()")
    settled(page, "LEAF-001", 6)
    assert logged(app, "LEAF-001")[4:] == [("user", SIBLING_ASK + statement), ("ai", "- added LEAF-EXTRACTED under ROOT\n- agent LEAF-EXTRACTED: Delivered.\nDelivered.")]
    assert logged(app, "LEAF-EXTRACTED") == [("user", "Deliver it."), ("ai", "Delivered.")]  # the task went on in the new item's own chat
    page.wait("document.querySelector('#tree [data-path=\"ROOT/LEAF-EXTRACTED\"]')")
    assert tree_item(server, "LEAF-EXTRACTED")["description_raw"] == statement + "\n"


SEL_TOOLS = "document.getElementById('sel-tools')"


def select_text(page, node, start, end):
    page.eval(f"(() => {{ const node = {node}; getSelection().setBaseAndExtent(node, {start}, node, {end}); }})()")


@pytest.mark.syngate("AI_CHAT-CONTROLS-ITEM", "selection")
@pytest.mark.syngate("AI_CHAT-CONTROLS-SELECTION")
def test_a_selection_inside_a_message_gets_the_three_marks_on_the_border_lines_cutting_or_extracting_the_selected_text_alone(server, chrome):
    base, app = server
    page = open_chat(server, chrome, echo=CallsConnector("Leaf sentence\n\nIt shall be extracted from the middle."))
    send(page, "LEAF-001", "Say something")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    reply = f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')"
    x, y = page.eval(f"(() => {{ const r = {reply}.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})()")
    page.mouse("mouseMoved", x, y, buttons=0)
    page.wait(f"getComputedStyle({reply}.querySelector('.msg-tools')).opacity === '1'")  # hovered: the message's own marks
    select_text(page, f"{reply}.querySelector('.msg-part p:last-child').firstChild", 9, 21)
    page.wait(f"{SEL_TOOLS}.matches(':popover-open')")
    look = f"(() => {{ const at = getSelection().getRangeAt(0).getBoundingClientRect(), block = {LEAF_BLOCK}.getBoundingClientRect(), mid = (b) => {{ const r = b.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }};" \
           f" const [fold, child, sibling] = [...{SEL_TOOLS}.querySelectorAll('button')].map(mid);" \
           f" return [{SEL_TOOLS}.text, [...document.querySelectorAll('.chat-msg.has-selection')].map((el) => el.className), [...{reply}.querySelectorAll('.msg-tools')].map((el) => getComputedStyle(el).opacity)," \
           f" [...{SEL_TOOLS}.querySelectorAll('button')].map((b) => b.className + (b.hidden ? ' hidden' : '')), Math.abs(fold[0] - block.left) < 2, Math.abs(child[0] - block.right) < 2, Math.abs(sibling[0] - block.right) < 2," \
           f" Math.abs(fold[1] - (at.top + at.height / 2)) < 2, Math.abs(child[1] - fold[1]) < 1, sibling[1] > child[1] + 20]; }})()"
    assert page.eval(look) == ["be extracted", ["chat-msg ai has-selection"], ["0", "0"], ["msg-fold", "msg-child", "msg-sibling"], True, True, True, True, True, True]  # the selection's marks stand in for the message's, on the border lines level with the selection
    page.eval(f"{SEL_TOOLS}.querySelector('.msg-fold').click()")
    page.wait(f"{reply}.querySelector('.msg-cut')")
    parts = f"[...{reply}.querySelectorAll('.msg-part, .msg-cut')].map((p) => p.className.split(' ')[0] + ':' + p.textContent)"
    assert page.eval(f"[{parts}, getSelection().isCollapsed, {SEL_TOOLS}.matches(':popover-open')]") == [["msg-part:Leaf sentenceIt shall", "msg-cut:be extracted", "msg-part:from the middle."], True, False]  # the selected text alone is cut, shown folded in its place
    page.wait("state.chats.get('LEAF-001').session === null")
    assert call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]["log"][1]["cuts"] == [[24, 36]] and app.chats["LEAF-001"].kept()[1]["text"] == "Leaf sentence\n\nIt shall  from the middle."
    assert page.eval(f"[...{reply}.querySelectorAll('.msg-fold')].map((b) => b.getAttribute('aria-expanded'))") == ["true", "false", "true"]  # every part carries its own fold mark
    page.eval(f"{reply}.querySelector('.msg-cut .msg-fold').click()")
    page.wait(f"!{reply}.querySelector('.msg-cut')")
    assert page.eval(parts) == ["msg-part:Leaf sentenceIt shall be extracted from the middle."] and "cuts" not in call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]["log"][1]  # expanded: one text again
    select_text(page, f"{reply}.querySelector('.msg-part p:last-child').firstChild", 9, 21)
    page.wait(f"{SEL_TOOLS}.matches(':popover-open')")
    page.eval(f"{SEL_TOOLS}.querySelector('.msg-child').click()")
    settled(page, "LEAF-001", 4)
    assert app.chats["LEAF-001"].log[2] == {"role": "user", "text": CHILD_ASK + "be extracted"}  # the selected text alone goes to the AI
    assert page.eval(f"[{SEL_TOOLS}.matches(':popover-open'), document.querySelectorAll('.has-selection').length, getSelection().isCollapsed]") == [False, 0, True]
    select_text(page, f"{LEAF_BLOCK}.querySelector('.chat-msg.user .msg-part').lastChild", 0, 3)
    page.wait(f"{SEL_TOOLS}.matches(':popover-open')")
    page.eval(f"{SEL_TOOLS}.querySelector('.msg-sibling').click()")
    settled(page, "LEAF-001", 6)
    assert app.chats["LEAF-001"].log[4] == {"role": "user", "text": SIBLING_ASK + "Say"} and page.eval(PATHS % "#tree") == ["ROOT", "ROOT/LEAF-001"]


@pytest.mark.syngate("AI_CHAT-050")
def test_an_at_reference_brings_the_named_item_into_the_turn(server, chrome, syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "SIDE-001", "Beside it.\n", parents=("ROOT",), order=30, tests=None)
    page = open_chat(server, chrome)
    send(page, "LEAF-001", "Compare with @SIDE-001 and @ROOT please")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    reply = page.eval(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai').textContent")
    assert reply.endswith("|Compare with @SIDE-001 and @ROOT please|model-a|low|edit,internet|None")  # the text stays as typed
    assert reply.split("|Compare with")[0].endswith("@LEAF-001 It shall leaf.@SIDE-001 Beside it.")  # the missing statement follows the seed context
    assert reply.split("|Compare with")[0].count("@ROOT") == 1  # the contained one brings no second copy


def pick(page, attribute, value):
    page.eval("document.querySelector('.chat-setup').click()")
    assert page.eval("document.getElementById('status-menu').matches(':popover-open')")
    page.eval(f"document.querySelector('#status-menu [data-chat-{attribute}=\"{value}\"]').click()")


class DefaultingConnector(EchoConnector):
    def settings(self):
        return {**super().settings(), "default": {"model": "model-b", "effort": "high"}}


@pytest.mark.syngate("AI_CONNECTION-DEFAULT", "page")
def test_a_chat_without_a_setup_starts_with_the_reported_default_model_and_effort(server, chrome):
    page = open_chat(server, chrome, echo=DefaultingConnector())
    assert page.eval(SETUP) == "b · high ▾"


@pytest.mark.syngate("AI_CHAT-010")
def test_the_connector_menu_selects_the_setup(server, chrome):
    page = open_chat(server, chrome, echo=EchoConnector(), other=EchoConnector("Other"), claude=synthetic.claude_code_connector())
    pick(page, "model", "model-b")
    assert page.eval(SETUP) == "Echo · b · low ▾"
    pick(page, "connector", "other")
    assert page.eval(SETUP) == "Other · a · low ▾"  # a new connector starts from its own defaults
    menu = "(() => { document.querySelector('.chat-setup').click(); const menu = document.getElementById('status-menu'), entries = (key) => [...menu.querySelectorAll(`[data-chat-${key}]`)];" \
           " const offered = [entries('model').map((b) => b.textContent.slice(2)), entries('effort').map((b) => b.textContent.slice(2))]; menu.hidePopover(); return offered; })()"
    rich, bare = (next((model for model, efforts in synthetic.CLAUDE_MODEL_EFFORTS.items() if bool(efforts) == has), None) for has in (True, False))
    names = [model.removeprefix("claude-") for model in synthetic.CLAUDE_MODELS]
    pick(page, "connector", "claude")
    if bare:
        pick(page, "model", bare)
        offered, setup = page.eval(menu), page.eval(SETUP)
        assert offered == [names, []] and setup == f"Claude Code · {bare.removeprefix('claude-')} ▾", f"bare model {bare!r}: menu {offered}, setup {setup!r}"  # no effort levels, no effort
        page.wait("state.chats.get('LEAF-001').effort === null")
    pick(page, "model", rich)
    offered, setup = page.eval(menu), page.eval(SETUP)
    expected = [names, list(synthetic.CLAUDE_MODEL_EFFORTS[rich])]
    assert offered == expected and setup == f"Claude Code · {rich.removeprefix('claude-')} · {synthetic.claude_code_connector.default_effort} ▾", f"rich model {rich!r}: menu {offered} expected {expected}, setup {setup!r}"


def css_color(page, var):
    return page.eval(f"(() => {{ const probe = document.createElement('span'); probe.style.color = 'var({var})'; document.body.append(probe);"
                     " const color = getComputedStyle(probe).color; probe.remove(); return color; })()")


MODES = "[...document.querySelectorAll('.block-ai .chat-mode')].map((el) => [el.textContent, el.getAttribute('aria-checked')])"


class PlainConnector(EchoConnector):
    modes = {"edit": True, "internet": True}


@pytest.mark.syngate("AI_CHAT-011")
@pytest.mark.syngate("AI_CHAT-PERMISSION-EDIT")
@pytest.mark.syngate("AI_CHAT-PERMISSION-INTERNET")
def test_the_permission_switches_show_their_labels_defaults_and_state_colors(server, chrome):
    page = open_chat(server, chrome, echo=EchoConnector(), claude=synthetic.claude_code_connector())
    assert page.eval(MODES) == [["Tree edit", "true"], ["Edit", "true"], ["Internet", "true"]]  # the harness's own Tree edit permission heads the connector's modes, on; the advanced one is not a pill
    look = "[...document.querySelectorAll('.block-ai .chat-mode')].map((el) => [el.className, getComputedStyle(el).color, getComputedStyle(el.querySelector('.ball')).backgroundColor])"
    accent, dim = css_color(page, "--accent"), css_color(page, "--dim")
    assert [entry[1:] for entry in page.eval(look)] == [[accent, accent], [accent, accent], [accent, accent]]
    assert [entry[0] for entry in page.eval(look)] == ["pill chat-mode on", "pill chat-mode on", "pill chat-mode on"]  # one pill class, the state a modifier
    assert page.eval("document.querySelector('.chat-mode[data-chat-mode=\"edit\"]').title") == "Edit: edit hint — allowed in this chat, click to switch"
    page.eval("document.querySelector('.chat-mode[data-chat-mode=\"edit\"]').click()")
    assert page.eval(MODES) == [["Tree edit", "true"], ["Edit", "false"], ["Internet", "true"]]
    assert page.eval("[getComputedStyle(document.querySelector('.chat-mode[data-chat-mode=\"edit\"]')).color, getComputedStyle(document.querySelector('.chat-mode[data-chat-mode=\"edit\"] .ball')).backgroundColor]") == [dim, dim]
    send(page, "LEAF-001", "Go.")
    page.wait("document.querySelector('.chat-msg.ai')")
    assert page.eval("document.querySelector('.chat-msg.ai').textContent").endswith("|Go.|model-a|low|internet|None")
    pick(page, "connector", "claude")
    assert page.eval(MODES) == [["Tree edit", "true"], ["Edit files", "true"], ["Internet", "true"]]  # the Claude Code connector's own switches and defaults
    assert page.eval("[...document.querySelectorAll('.block-ai .chat-mode')].map((el) => el.title.split(' — ')[0])") == [
        "Tree edit: add, edit, move and remove items; reading the tree stays on", "Edit files: change project files without asking", "Internet: search and fetch the web"]


def advanced_entries(page):
    page.eval("document.querySelector('.chat-advanced').click()")
    assert page.eval("document.getElementById('status-menu').matches(':popover-open')")
    return page.eval("[...document.querySelectorAll('#status-menu [data-chat-mode]')].map((b) => [b.textContent, b.getAttribute('role'), b.getAttribute('aria-checked'), b.title.split(' — ')[0]])")


@pytest.mark.syngate("AI_CHAT-PERMISSION-WORKFLOWS")
@pytest.mark.syngate("AI_CHAT-PERMISSION-BASH")
def test_the_advanced_list_gathers_the_connectors_own_switches_off_by_default(server, chrome):
    page = open_chat(server, chrome, echo=EchoConnector(), plain=PlainConnector("Plain"), claude=synthetic.claude_code_connector())
    pill = "(() => { const pill = document.querySelector('.block-ai .chat-advanced'); return pill && [pill.textContent, pill.className, pill.title]; })()"
    assert page.eval(pill) == ["advanced ▾", "pill chat-advanced", "advanced permissions — Workflows: not allowed; click to switch"]  # off at rest, dim like an off switch
    assert page.eval("getComputedStyle(document.querySelector('.chat-advanced')).color") == css_color(page, "--dim")
    assert advanced_entries(page) == [["○ Workflows", "menuitemcheckbox", "false", "workflows hint"]]
    page.eval("document.querySelector('#status-menu [data-chat-mode=\"workflows\"]').click()")
    page.wait("!document.getElementById('status-menu').matches(':popover-open')")
    page.wait("document.querySelector('.block-ai .chat-advanced.on')")
    assert page.eval(pill)[1:] == ["pill chat-advanced on", "advanced permissions — Workflows: allowed; click to switch"]
    assert page.eval("getComputedStyle(document.querySelector('.chat-advanced')).color") == css_color(page, "--accent")
    assert advanced_entries(page) == [["● Workflows", "menuitemcheckbox", "true", "workflows hint"]]
    page.eval("document.getElementById('status-menu').hidePopover()")
    assert page.eval(MODES) == [["Tree edit", "true"], ["Edit", "true"], ["Internet", "true"]]  # the switch row is untouched
    send(page, "LEAF-001", "Go.")
    page.wait("document.querySelector('.chat-msg.ai')")
    assert page.eval("document.querySelector('.chat-msg.ai').textContent").endswith("|Go.|model-a|low|edit,internet,workflows|None")  # the advanced mode travels like any other
    pick(page, "connector", "claude")
    assert advanced_entries(page) == [["○ Raw command", "menuitemcheckbox", "false", "run shell commands"], ["○ Workflows", "menuitemcheckbox", "false", "run workflow scripts"]]  # the Claude Code connector's own, both off
    page.eval("document.querySelector('#status-menu [data-chat-mode=\"bash\"]').click()")
    page.wait("state.chats.get('LEAF-001').modes.includes('bash')")
    assert page.eval(pill)[2] == "advanced permissions — Raw command: allowed, Workflows: not allowed; click to switch"
    pick(page, "connector", "plain")
    assert page.eval(pill) is None  # a connector without an advanced mode has no list


MENU_RESUME = "[...document.querySelectorAll('#status-menu [data-chat-resume]')].map((b) => b.dataset.chatResume)"


@pytest.mark.syngate("AI_CHAT-030", "hide")
def test_the_hide_pill_hides_the_chat_and_becomes_the_drop_down_showing_it_again(server, chrome):
    base, app = server
    page = open_chat(server, chrome)
    send(page, "LEAF-001", "Kept")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    closer = f"{LEAF_BLOCK}.querySelector('.block-ai .chat-hide')"
    assert page.eval(f"[{closer}.textContent, {closer}.tagName, getComputedStyle({closer}).color]") == ["▴ done", "BUTTON", css_color(page, "--dim")]
    page.eval(f"{closer}.click()")
    hidden = f"[{LEAF_BLOCK}.querySelectorAll('.chat-msg').length, {LEAF_BLOCK}.querySelector('.chat-input').placeholder, Boolean({LEAF_BLOCK}.querySelector('.block-ai .chat-hide')), Boolean({LEAF_BLOCK}.querySelector('.block-ai .chat-show'))]"
    assert page.eval(hidden) == [0, REST_HINT, False, True]  # the reply line stays, at rest
    page.eval(f"{LEAF_BLOCK}.querySelector('.block-ai .chat-show').click()")
    assert page.eval(f"{LEAF_BLOCK}.querySelectorAll('.chat-msg').length") == 0 and page.eval(MENU_RESUME) == ["live"]  # even one conversation is only listed
    page.eval("document.querySelector('#status-menu [data-chat-resume=\"live\"]').click()")
    assert page.eval(f"[...{LEAF_BLOCK}.querySelectorAll('.chat-msg')].map((el) => el.className)") == ["chat-msg user", "chat-msg ai"]  # shown once picked
    page.eval(f"{closer}.click()")
    enter_reply(page, "LEAF-001")
    users = f"[...{LEAF_BLOCK}.querySelectorAll('.chat-msg.user')].map((el) => el.textContent)"
    assert page.eval(users) == []  # the reply line of a hidden chat is the choice of a new conversation
    page.eval(f"{closer}.click()")
    assert page.eval("state.chats.get('LEAF-001').archive.length") == 0  # shown, never sent: nothing filed
    page.eval(f"{LEAF_BLOCK}.querySelector('.block-ai .chat-show').click()")
    assert page.eval(MENU_RESUME) == ["live"]
    page.eval("document.querySelector('#status-menu [data-chat-resume=\"live\"]').click()")
    page.eval("(() => { document.querySelector('.chat-setup').click(); document.querySelector('#status-menu [data-chat-reset=\"begin\"]').click(); })()")
    page.wait("state.chats.get('LEAF-001').archive.length === 1")
    page.eval(f"{closer}.click()")
    assert page.eval(hidden) == [0, REST_HINT, False, True]  # the live conversation is empty, yet ▾ leads to the filed one
    page.eval(f"{LEAF_BLOCK}.querySelector('.block-ai .chat-show').click()")
    assert page.eval(MENU_RESUME) == ["0"]  # the empty live conversation is not listed
    page.eval("document.querySelector('#status-menu [data-chat-resume=\"0\"]').click()")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    assert page.eval(users) == ["Kept"] and page.eval("state.chats.get('LEAF-001').archive.length") == 0  # the one filed conversation resumes once picked
    page.eval(f"{closer}.click()")
    edit_leaf(page, "It shall leaf anew.")
    page.eval("window.confirm = () => { throw new Error('nothing is erased, nothing to confirm'); }")
    page.eval(f"{LEAF_BLOCK}.querySelector('.block-ai .chat-send').click()")
    page.wait(f"{LEAF_BLOCK}.querySelectorAll('.chat-msg:not(.note)').length === 1 && {LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    assert page.eval(users) == []  # the old conversation is filed, the statement being the new one's first message
    assert page.eval(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai').textContent").endswith("|It shall leaf anew.|model-a|low|edit,internet|None")  # a new session, not the old one
    chat = call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]
    assert [m["role"] for m in chat["log"]] == ["ai"] and [(c["title"], c["messages"]) for c in chat["archive"]] == [("Kept", 2)]


@pytest.mark.syngate("AI_CHAT-CONVERSATIONS", "list")
def test_the_drop_down_of_a_hidden_chat_lists_the_items_conversations_to_resume_one(server, chrome):
    base, app = server
    page = open_chat(server, chrome)
    hide = f"{LEAF_BLOCK}.querySelector('.block-ai .chat-hide').click()"
    show = f"{LEAF_BLOCK}.querySelector('.block-ai .chat-show').click()"
    send(page, "LEAF-001", "First topic")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    page.eval(hide)
    enter_reply(page, "LEAF-001")
    send(page, "LEAF-001", "Second topic")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    page.eval(hide)
    assert page.eval(f"{LEAF_BLOCK}.querySelector('.block-ai .chat-show').title") == "pick a conversation of the item — every one is kept"
    page.eval(show)
    entries = "[...document.querySelectorAll('#status-menu [data-chat-resume]')].map((b) => [b.dataset.chatResume, b.getAttribute('role'), b.textContent.split(' · ').slice(0, 2).join(' · ')])"
    assert page.eval("document.getElementById('status-menu').matches(':popover-open')")
    assert page.eval(entries) == [["live", "menuitem", "● Second topic · 2 messages"], ["0", "menuitem", "○ First topic · 2 messages"]]  # the live one first, then the filed in start order
    assert page.eval("[...document.querySelectorAll('#status-menu [data-chat-resume]')].every((b) => /\\d\\d:\\d\\d$/.test(b.textContent))")  # begun today: the time of day closes the entry
    page.eval("document.querySelector('#status-menu [data-chat-resume=\"0\"]').click()")
    users = f"[...{LEAF_BLOCK}.querySelectorAll('.chat-msg.user')].map((el) => el.textContent).join()"
    page.wait(f"{users} === 'First topic'")
    chat = call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]
    assert [m["text"] for m in chat["log"] if m["role"] == "user"] == ["First topic"] and [c["title"] for c in chat["archive"]] == ["Second topic"]  # swapped
    send(page, "LEAF-001", "Still first")
    page.wait(f"{LEAF_BLOCK}.querySelectorAll('.chat-msg.ai').length === 2")
    assert page.eval(f"{LEAF_BLOCK}.querySelectorAll('.chat-msg.ai')[1].textContent").endswith("|Still first|model-a|low|edit,internet|session-1")  # the resumed conversation goes on in its session
    page.eval(hide)
    page.eval(show)
    assert page.eval(entries) == [["live", "menuitem", "● First topic · 4 messages"], ["0", "menuitem", "○ Second topic · 2 messages"]]
    page.eval("document.querySelector('#status-menu [data-chat-resume=\"live\"]').click()")
    assert page.eval(f"[{LEAF_BLOCK}.querySelectorAll('.chat-msg').length, document.getElementById('status-menu').matches(':popover-open')]") == [4, False]  # the live one shows as it is


@pytest.mark.syngate("AI-CHAT")
def test_the_chat_window_opens_under_the_item_and_sends_through_the_chosen_setup(server, chrome):
    page = open_chat(server, chrome)
    assert page.eval(PATHS % "#doc") == ["ROOT", "ROOT/LEAF-001"]  # no separate element: the item's own block expands
    assert page.eval("Boolean(document.querySelector('.block[data-uid=\"LEAF-001\"] .block-chat .chat-input'))")
    assert page.eval(SETUP) == "a · low ▾" and page.eval("document.querySelector('.chat-setup').title").startswith("Echo · model · effort")  # one connector: named in the title only
    pick(page, "model", "model-b")
    pick(page, "effort", "high")
    assert page.eval(SETUP) == "b · high ▾"
    send(page, "LEAF-001", "What is missing?")
    page.wait("document.querySelector('.chat-msg.ai')")
    user, ai = page.eval("[...document.querySelectorAll('.chat-msg')].map((el) => el.textContent.trim())")
    assert user == "What is missing?"
    assert ai.startswith("Tool calls") and ai.endswith("@ROOT Root branch@LEAF-001 It shall leaf.|What is missing?|model-b|high|edit,internet|None")  # the default prompt heads the seed
    send(page, "LEAF-001", "And next?")
    page.wait("document.querySelectorAll('.chat-msg.ai').length === 2")
    assert page.eval("document.querySelectorAll('.chat-msg.ai')[1].textContent").endswith("|And next?|model-b|high|edit,internet|session-1")


def send(page, uid, text):
    page.eval(f"(() => {{ const box = document.querySelector('.block[data-uid=\"{uid}\"]'); box.querySelector('.chat-input').value = '{text}'; box.querySelector('.chat-send').click(); }})()")


CHATTING = "[...document.querySelectorAll('#doc .block.chatting')].map((el) => [el.dataset.uid, el.querySelector('.block-chat .chat-input').tabIndex, Boolean(el.querySelector('.block-ai .chat-hide'))])"


@pytest.mark.syngate("AI_CHAT-MULTI-010", "several")
def test_several_chat_windows_are_open_at_once_each_under_its_own_item(server, chrome):
    page = open_chat(server, chrome)
    enter_reply(page, "ROOT")
    assert page.eval(CHATTING) == [["ROOT", 0, True], ["LEAF-001", 0, True]]
    send(page, "ROOT", "Root?")
    page.wait("document.querySelector('.block[data-uid=\"ROOT\"] .chat-msg.ai')")
    assert page.eval("document.querySelector('.block[data-uid=\"ROOT\"] .chat-msg.ai').textContent").endswith("|Root?|model-a|low|edit,internet|None")
    assert page.eval("document.querySelectorAll('.block[data-uid=\"LEAF-001\"] .chat-msg').length") == 0
    page.eval("document.querySelector('.block[data-uid=\"ROOT\"] .chat-hide').click()")
    assert page.eval(CHATTING) == [["LEAF-001", 0, True]]


def reload(page):
    page.cdp.call("Page.reload", session=page.session)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            if page.eval("Boolean(document.querySelector('#tree [data-uid=\"LEAF-001\"]'))"):
                return
        except (RuntimeError, AssertionError):
            pass
        time.sleep(0.05)
    raise AssertionError("the page never came back after reload")


@pytest.mark.syngate("AI_CHAT-030", "history")
def test_a_chat_keeps_its_history_while_hidden_and_shows_it_again_on_its_item(server, chrome):
    page = open_chat(server, chrome)
    send(page, "LEAF-001", "First")
    page.wait("document.querySelector('.chat-msg.ai')")
    page.eval("document.querySelector('.block-ai .chat-hide').click()")
    assert page.eval("document.querySelectorAll('.chat-msg').length") == 0
    page.eval("document.querySelector('#doc .block[data-uid=\"LEAF-001\"] .chat-show').click()")
    page.eval("document.querySelector('#status-menu [data-chat-resume=\"live\"]').click()")
    kinds = "[...document.querySelectorAll('.block[data-uid=\"LEAF-001\"] .chat-msg')].map((el) => el.className)"
    assert page.eval(kinds) == ["chat-msg user", "chat-msg ai"]
    send(page, "LEAF-001", "Second")
    page.wait("document.querySelectorAll('.chat-msg.ai').length === 2")
    assert page.eval("document.querySelectorAll('.chat-msg.ai')[1].textContent").endswith("|Second|model-a|low|edit,internet|session-1")  # the session goes on
    reload(page)
    page.wait("document.querySelector('.block[data-uid=\"LEAF-001\"] .chat-msg.ai')")
    assert page.eval(kinds) == ["chat-msg user", "chat-msg ai", "chat-msg user", "chat-msg ai"]
    assert page.eval(CHATTING) == [["LEAF-001", 0, True]]


class ReleasedConnector(EchoConnector):
    """Answers each message only once the test releases it, so exchanges overlap in the order the test dictates."""

    def __init__(self):
        super().__init__()
        self.gates = {}

    def release(self, text):
        self.gates.setdefault(text, threading.Event()).set()

    def dispatch(self, context, text, model=None, effort=None, modes=(), session=None, on_step=None, stopped=None):
        text = heard(text)
        assert self.gates.setdefault(text, threading.Event()).wait(10), f"{text} was never released"
        return f"reply to {text} in {session}", f"session-{text}"


@pytest.mark.syngate("AI_CHAT-MULTI-010", "parallel")
def test_chats_of_different_items_run_their_exchanges_in_parallel(server, chrome):
    echo = ReleasedConnector()
    page = open_chat(server, chrome, echo=echo)
    enter_reply(page, "ROOT")
    log = "[...document.querySelectorAll('.block[data-uid=\"%s\"] .chat-msg:not(.note)')].map((el) => el.className.replace('chat-msg ', '') + ':' + el.textContent.trim())"
    replies = "document.querySelectorAll('.block[data-uid=\"%s\"] .chat-msg.ai').length === %d"
    waiting = "Boolean(document.querySelector('.block[data-uid=\"%s\"] .chat-msg.note'))"
    send(page, "ROOT", "root-one")
    send(page, "LEAF-001", "leaf-one")
    echo.release("root-one")
    page.wait(replies % ("ROOT", 1))
    send(page, "ROOT", "root-two")
    echo.release("root-two")
    page.wait(replies % ("ROOT", 2))
    assert page.eval(log % "LEAF-001") == ["user:leaf-one"] and page.eval(waiting % "LEAF-001")
    echo.release("leaf-one")
    page.wait(replies % ("LEAF-001", 1))
    send(page, "LEAF-001", "leaf-two")
    echo.release("leaf-two")
    page.wait(replies % ("LEAF-001", 2))
    assert page.eval(log % "ROOT") == ["user:root-one", "ai:reply to root-one in None", "user:root-two", "ai:reply to root-two in session-root-one"]
    assert page.eval(log % "LEAF-001") == ["user:leaf-one", "ai:reply to leaf-one in None", "user:leaf-two", "ai:reply to leaf-two in session-leaf-one"]
    assert not page.eval(waiting % "ROOT") and not page.eval(waiting % "LEAF-001")


BLOCK_LOG = "[...document.querySelectorAll('.block[data-path=\"%s\"] .chat-msg:not(.note)')].map((el) => el.className.replace('chat-msg ', '') + ':' + el.textContent.trim())"


@pytest.mark.syngate("AI_CHAT-MULTI-010", "singleton")
def test_an_item_has_one_chat_shown_the_same_at_every_occurrence_and_in_every_tab(server, chrome, syngate_tree):
    base, app = server
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "BR-001", "Branch\n", parents=("ROOT",), header="Branch")
    make_item(syngate_dir, "LEAF-001", "It shall leaf.\n", parents=("ROOT", "BR-001"), header="First leaf", tests=None)
    page = item_page(server, chrome)
    first, second = "ROOT/LEAF-001", "ROOT/BR-001/LEAF-001"
    block = "document.querySelector('.block[data-path=\"%s\"]')"
    page.wait(block % second)
    page.eval(f"{block % first}.querySelector('.chat-input').click()")
    page.eval(f"(() => {{ const box = {block % first}; box.querySelector('.chat-input').value = 'Hello'; box.querySelector('.chat-send').click(); }})()")
    page.wait(f"{block % first}.querySelector('.chat-msg.ai')")
    assert page.eval(f"[{block % second}.classList.contains('chatting'), Boolean({block % second}.querySelector('.block-ai .chat-show'))]") == [False, True]
    page.eval(f"{block % second}.querySelector('.chat-input').click()")
    assert page.eval(BLOCK_LOG % second) == page.eval(BLOCK_LOG % first) and page.eval(BLOCK_LOG % first)[0] == "user:Hello"
    page.eval(f"(() => {{ const box = {block % second}; box.querySelector('.chat-input').value = 'Again'; box.querySelector('.chat-send').click(); }})()")
    page.wait(f"{block % second}.querySelectorAll('.chat-msg.ai').length === 2")
    assert page.eval(BLOCK_LOG % first) == page.eval(BLOCK_LOG % second) and page.eval(BLOCK_LOG % first)[3].endswith("|Again|model-a|low|edit,internet|session-1")
    other = Page(chrome, f"{base}/?token={app.token}")
    other.wait(f"{block % first} && {block % first}.querySelector('.block-ai .chat-show')")
    other.eval(f"{block % first}.querySelector('.block-ai .chat-show').click()")
    other.eval("document.querySelector('#status-menu [data-chat-resume=\"live\"]').click()")
    assert other.eval(BLOCK_LOG % first) == page.eval(BLOCK_LOG % first)
    other.eval(f"(() => {{ const box = {block % first}; box.querySelector('.chat-input').value = 'From the other tab'; box.querySelector('.chat-send').click(); }})()")
    other.wait(f"{block % first}.querySelectorAll('.chat-msg.ai').length === 3")
    page.activate()  # a tab brought back to the front catches up with the chat
    page.wait(f"{block % first}.querySelectorAll('.chat-msg.ai').length === 3")
    assert page.eval(BLOCK_LOG % first)[4] == "user:From the other tab" and page.eval(BLOCK_LOG % first) == other.eval(BLOCK_LOG % first)


@pytest.mark.syngate("AI_CHAT-MULTI-010", "turn_keys")
def test_turns_are_addressed_by_item_and_number_and_an_item_runs_one_turn_at_a_time(server):
    base, app = server
    gated = SteppingConnector()
    app.connectors = {"echo": gated}
    setup = {"connector": "echo", "model": "model-a", "effort": "low", "modes": []}
    status, started = call(base, app, "/api/turn", {"uid": "LEAF-001", "text": "Slow one", **setup})
    assert (status, started["turn"], started["chat"]["turn"], started["chat"]["log"]) == (200, "LEAF-001:1", "LEAF-001:1", [{"role": "user", "text": "Slow one"}])
    with pytest.raises(urllib.error.HTTPError) as refused:
        call(base, app, "/api/turn", {"uid": "LEAF-001", "text": "Meanwhile", **setup})
    assert refused.value.code == 409
    assert call(base, app, "/api/turn", {"uid": "ROOT", "text": "Other item", **setup})[1]["turn"] == "ROOT:1"
    with pytest.raises(urllib.error.HTTPError) as bare:
        call(base, app, "/api/turn/1")
    assert bare.value.code == 404
    deadline = time.monotonic() + 5
    while not all(call(base, app, f"/api/turn/{key}")[1].get("steps") for key in ("LEAF-001:1", "ROOT:1")) and time.monotonic() < deadline:
        time.sleep(0.02)
    running = call(base, app, "/api/turn/LEAF-001:1")[1]
    assert running["running"] and [(step["kind"], step["input"], step["result"]) for step in running["steps"]] == [("tool", {"file_path": "Slow one"}, "read")]
    assert running["steps"][0]["at"] >= 0.5 and call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]["steps"] == running["steps"]
    version = call(base, app, "/api/chats")[1]["version"]
    assert call(base, app, f"/api/chats?since={version}&wait=0.3")[1]["version"] == version  # nothing changed: the wait runs out
    gated.release.set()
    assert call(base, app, f"/api/chats?since={version}&wait=5")[1]["version"] > version  # one long poll awaits the turns' end, however many run
    assert call(base, app, "/api/turn/LEAF-001:1?wait=5")[1]["running"] is False
    assert call(base, app, "/api/turn/ROOT:1?wait=5")[1]["running"] is False
    chats = call(base, app, "/api/chats")[1]["chats"]
    assert [m["role"] for m in chats["LEAF-001"]["log"]] == ["user", "ai"] and chats["LEAF-001"]["turn"] is None
    assert chats["LEAF-001"]["log"][-1]["steps"] == running["steps"] and "steps" not in chats["LEAF-001"]
    assert call(base, app, "/api/turn", {"uid": "LEAF-001", "text": "Next", **setup})[1]["turn"] == "LEAF-001:2"


def linked_page(server, chrome):
    """The page with LEAF-001 linking docs/GUIDE.md, which links NOTES.md next to it."""
    base, app = server
    docs = app.root / "docs"
    docs.mkdir()
    (docs / "GUIDE.md").write_text("# Guide\n\nSee [the notes](NOTES.md).\n")
    (docs / "NOTES.md").write_text("# Notes\n")
    (app.syngate_dir / "LEAF-001.yml").write_text("---\nparents: [ROOT]\ntest: ~\n---\nIt shall leaf, see [the guide](docs/GUIDE.md).\n")
    page = item_page(server, chrome)
    page.wait(f"{LEAF_BLOCK}.querySelector('a.filelink')")
    return page


GUIDE = f"{LEAF_BLOCK}.querySelector('.file-view[data-file=\"docs/GUIDE.md\"]')"
NOTES = f"{LEAF_BLOCK}.querySelector('.file-view[data-file=\"docs/NOTES.md\"]')"


@pytest.mark.syngate("ASSASSIN-UI-STYLE-SOURCE", "styles")
def test_the_panes_carry_no_inline_styles_and_border_mounted_controls_share_one_look(server, chrome):
    page = linked_page(server, chrome)
    enter_reply(page, "LEAF-001")
    send(page, "LEAF-001", "Hi")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    page.eval(f"{LEAF_BLOCK}.querySelector('a.filelink').click()")
    page.wait(f"{GUIDE} && {GUIDE}.querySelector('.md')")
    assert page.eval("document.querySelectorAll('#tree [style], #doc [style]').length") == 0
    looks = "(() => { const seen = new Set(); for (const el of document.querySelectorAll('%s')) { const s = getComputedStyle(el);" \
            " seen.add([s.borderTopStyle, s.borderTopWidth, s.borderTopLeftRadius, s.paddingLeft, s.paddingRight, s.fontSize, s.fontFamily].join()); } return [...seen]; })()"
    assert page.eval("document.querySelectorAll('#doc .block-foot .pill, #doc .sub-foot .pill').length") >= 7  # send with setup, four permissions, hide, file name
    assert len(page.eval(looks % "#doc .block-foot .pill, #doc .sub-foot .pill")) == 1  # one pill shape, whatever the pill is for
    assert page.eval("document.querySelectorAll('#tree .tools button, #doc .file-view > .tools button').length") >= 3
    assert len(page.eval(looks % "#tree .tools button, #doc .file-view > .tools button")) == 1  # one icon-button shape
    assert page.eval("document.querySelectorAll('#doc .msg-tools button').length") >= 6
    assert len(page.eval(looks % "#doc .msg-tools button, #sel-tools button")) == 1  # one border-mark shape, the selection's marks included
    page.eval("CSS.supports = () => false")  # a browser without field-sizing: the editor grows by rows, never by an inline height
    edit_leaf(page, "It shall leaf\\nover three\\nlines.")
    assert page.eval("[document.querySelectorAll('#tree [style], #doc [style]').length, document.querySelector('#doc .block.editing textarea').rows]") == [0, 3]


@pytest.mark.syngate("ASSASSIN-UI-CONTENT-BLOCK-REST")
def test_a_block_at_rest_shows_no_border_or_controls_and_reveals_a_dim_line_on_hover_or_focus(page):
    at = f"(() => {{ const s = getComputedStyle({LEAF_BLOCK}); return [s.borderTopColor, getComputedStyle({LEAF_BLOCK}.querySelector('.block-foot')).visibility]; }})()"
    line, selection, none = css_color(page, "--line"), css_color(page, "--sel"), "rgba(0, 0, 0, 0)"
    settled = lambda color, visibility: page.wait(f"JSON.stringify({at}) === {json.dumps(json.dumps([color, visibility], separators=(',', ':')))}")  # past the line's transition
    settled(none, "hidden")
    x, y = page.eval(f"(() => {{ const r = {LEAF_BLOCK}.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})()")
    page.mouse("mouseMoved", x, y, buttons=0)
    settled(line, "visible")
    page.mouse("mouseMoved", 1, 1, buttons=0)
    settled(none, "hidden")
    page.eval("select('LEAF-001', 'ROOT/LEAF-001', { focus: 'block' })")
    settled(line, "visible")  # selected and focused: the dim line, never the selection color
    assert line != selection and page.eval(f"{LEAF_BLOCK}.classList.contains('selected')")
    page.eval("startEditing('ROOT/LEAF-001')")
    settled(line, "visible")


@pytest.mark.syngate("ASSASSIN-UI-CONTENT-FILE-PLACEMENT")
def test_a_referenced_file_opens_inside_the_block_of_the_item_that_references_it(server, chrome):
    page = linked_page(server, chrome)
    page.eval(f"{LEAF_BLOCK}.querySelector('a.filelink').click()")
    page.wait(f"{GUIDE} && {GUIDE}.querySelector('.md')")
    assert page.eval("[...document.querySelectorAll('#doc .block')].map((el) => el.dataset.path)") == ["ROOT", "ROOT/LEAF-001"]  # no block of its own
    assert page.eval(f"[{GUIDE}.dataset.path, {GUIDE}.parentElement.className, Boolean({LEAF_BLOCK}.contains({GUIDE}))]") == ["ROOT/LEAF-001#docs/GUIDE.md", "block-files", True]
    page.eval(f"{GUIDE}.querySelector('a.filelink').click()")
    page.wait(f"{NOTES} && {NOTES}.querySelector('.md')")
    assert page.eval(f"[{NOTES}.dataset.path, {GUIDE}.contains({NOTES})]") == ["ROOT/LEAF-001#docs/GUIDE.md#docs/NOTES.md", True]  # nested below its link's view
    page.eval(f"{GUIDE}.querySelector(':scope > .sub-body .md').dispatchEvent(new MouseEvent('dblclick', {{ bubbles: true }}))")
    assert page.eval(f"[state.editing, Boolean({GUIDE}.querySelector(':scope > .sub-body textarea')), {LEAF_BLOCK}.classList.contains('editing')]") == ["ROOT/LEAF-001#docs/GUIDE.md", True, False]
    page.eval(f"{NOTES}.querySelector('[data-act=\"close\"]').click()")
    assert page.eval(f"[Boolean({NOTES}), Boolean({GUIDE})]") == [False, True]
    page.eval(f"{GUIDE}.querySelector('[data-act=\"close\"]').click()")
    assert page.eval(f"[Boolean({GUIDE}), state.editing]") == [False, None]


@pytest.mark.syngate("ASSASSIN-UI-CONTENT-SUBELEMENTS")
def test_sub_elements_are_delimited_by_rules_and_shifts_with_their_tools_on_their_edge(server, chrome):
    page = linked_page(server, chrome)
    enter_reply(page, "LEAF-001")
    send(page, "LEAF-001", "Hi")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    page.eval(f"{LEAF_BLOCK}.querySelector('a.filelink').click()")
    page.wait(f"{GUIDE} && {GUIDE}.querySelector('.md')")
    edges = "(() => { const s = getComputedStyle(%s); return [s.borderTopStyle, s.borderBottomStyle, s.borderLeftStyle, s.borderRightStyle, parseFloat(s.marginLeft) > 0]; })()"
    assert page.eval(edges % GUIDE) == ["solid", "solid", "none", "none", True]
    assert page.eval(edges % f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")[:4] == ["none", "none", "none", "none"]
    place = f"(() => {{ const view = {GUIDE}, tools = view.querySelector(':scope > .tools').getBoundingClientRect(), box = view.getBoundingClientRect()," \
            f" name = view.querySelector('.sub-foot .pill').getBoundingClientRect();" \
            " return [tools.left - box.left < 4, Math.abs(tools.top - box.top) < parseFloat(getComputedStyle(view).lineHeight), Math.abs(name.top + name.height / 2 - box.bottom) < name.height]; })()"
    assert page.eval(place) == [True, True, True]  # tools at the left edge level with the first line, the file name on the bottom rule


@pytest.mark.syngate("ASSASSIN-UI-TREE-SPLITTER")
def test_the_splitter_resizes_the_outline_and_double_click_resets_it(page):
    width = "Math.round(document.getElementById('tree-pane').getBoundingClientRect().width)"
    default = page.eval(width)
    x, y = page.eval("(() => { const r = document.getElementById('splitter').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()")
    target = x - 60.5  # the splitter's centre sits on a half pixel
    page.mouse("mousePressed", x, y)
    page.mouse("mouseMoved", target, y)
    page.mouse("mouseReleased", target, y)
    assert page.eval(width) == round(target) != default
    assert page.eval("sessionStorage.getItem('assassin-tree-width')") == str(round(target))
    page.mouse("mousePressed", target + 2, y, clicks=2)
    page.mouse("mouseReleased", target + 2, y, clicks=2)
    assert page.eval(width) == default and page.eval("sessionStorage.getItem('assassin-tree-width')") is None
    assert 18 * 16 <= default <= 40 * 16 and default == round(0.3 * page.eval("innerWidth"))  # the default follows the window within its limits
    page.eval("document.getElementById('splitter').focus()")
    page.eval(KEY % ("document.getElementById('splitter')", "ArrowLeft"))
    assert page.eval(width) == default - 16 and page.eval("state.selected") is None  # the arrows move the splitter, not the selection
    page.eval(KEY % ("document.getElementById('splitter')", "ArrowRight"))
    assert page.eval(width) == default


SPAN = "(() => { const pane = document.getElementById('doc-pane'), doc = document.getElementById('doc').getBoundingClientRect(), box = pane.getBoundingClientRect(), s = getComputedStyle(pane);" \
       " const left = box.left + pane.clientLeft + parseFloat(s.paddingLeft), right = box.left + pane.clientLeft + pane.clientWidth - parseFloat(s.paddingRight);" \
       " return [Math.abs(doc.left - left) < 1, Math.abs(doc.right - right) < 1, parseFloat(s.paddingLeft) < parseFloat(s.paddingRight), Math.round(doc.width)]; })()"


@pytest.mark.syngate("ASSASSIN-UI-CONTENT-WIDTH")
def test_the_document_fills_the_width_the_splitter_leaves_with_a_left_margin_narrower_than_the_right(page):
    page.cdp.call("Emulation.setDeviceMetricsOverride", {"width": 1920, "height": 900, "deviceScaleFactor": 1, "mobile": False}, page.session)
    page.wait("innerWidth === 1920")
    wide = page.eval(SPAN)
    assert wide[:3] == [True, True, True]
    splitter = "document.getElementById('splitter')"
    page.eval(f"{splitter}.focus()")
    for _ in range(10):
        page.eval(KEY % (splitter, "ArrowLeft"))
    narrowed = page.eval(SPAN)
    assert narrowed[:3] == [True, True, True] and narrowed[3] == wide[3] + 160  # the outline gave up 160px, the document took them all
    page.eval("setTreeWidth(0)")
    page.cdp.call("Emulation.clearDeviceMetricsOverride", {}, page.session)
    page.wait("innerWidth === 1280")


class CallsConnector(EchoConnector):
    """Answers the given replies in order, the last one again and again, whatever the question."""

    def __init__(self, *replies):
        super().__init__()
        self.replies = list(replies)

    def dispatch(self, context, text, model=None, effort=None, modes=(), session=None, on_step=None, stopped=None):
        return (self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]), "session-2"


def _chat(server, *replies, uid="ROOT"):
    base, app = server
    app.connectors = {"echo": CallsConnector(*replies)}
    return call(base, app, "/api/chat", {"uid": uid, "connector": "echo", "model": "model-a", "effort": "low", "modes": ["tree"], "text": "Go."})


@pytest.mark.syngate("AI_CHAT-040")
def test_a_tree_call_answer_is_applied_to_the_tree_and_a_mixed_one_refused(server, syngate_tree):
    syngate_dir, _ = syngate_tree
    calls = [{"tool": "add", "uid": "NEW-001", "description": "New branch\n\nIt groups.", "kind": "branch"},
             {"tool": "add", "uid": "NEW-002", "parent": "NEW-001", "description": "New leaf\n\nIt shall be new.\n"},
             {"tool": "move", "uid": "LEAF-001", "to": "NEW-001", "before": "NEW-002"},
             {"tool": "remove", "uid": "NEW-002"}]
    status, result = _chat(server, "```syngate\n" + json.dumps(calls) + "\n```")
    assert status == 200 and result["session"] == "session-2" and result["calls"] == calls
    assert result["reply"] == "- added NEW-001 under ROOT\n- added NEW-002 under NEW-001\n- moved LEAF-001 under NEW-001\n- removed NEW-002"
    items, errors = syngatelib.load_tree(syngate_dir)
    assert errors == [] and sorted(items) == ["LEAF-001", "NEW-001", "ROOT"]
    assert (items["NEW-001"].title, items["NEW-001"].description, items["NEW-001"].parents, items["NEW-001"].tests) == ("New branch", "New branch\n\nIt groups.\n", ["ROOT"], None)
    assert items["LEAF-001"].parents == ["NEW-001"] and items["LEAF-001"].tests == {None: None}
    status, result = _chat(server, "Just talking.")
    assert (status, result["reply"]) == (200, "Just talking.")
    with pytest.raises(urllib.error.HTTPError) as refused:
        _chat(server, "Applying:\n```syngate\n" + json.dumps(calls[:1]) + "\n```")
    body = json.loads(refused.value.read())
    assert refused.value.code == 422 and body["session"] == "session-2" and "never both" in body["error"]
    status, result = _chat(server, "```syngate\n" + json.dumps([{"tool": "add", "uid": "NEW-003", "description": "D"}, {"tool": "remove", "uid": "@"}]) + "\n```", "Root stays.")
    assert status == 200 and result["reply"].startswith("- added NEW-003 under ROOT\n- remove ROOT refused: ROOT still has children") and result["reply"].endswith("\nRoot stays.")
    assert sorted(syngatelib.load_tree(syngate_dir)[0]) == ["LEAF-001", "NEW-001", "NEW-003", "ROOT"]  # the refusal ended the batch and came back as the next prompt


@pytest.mark.syngate("SYNGATE-API-RENAME", "chat")
def test_a_rename_carries_the_items_chat_and_the_anchor_to_the_new_uid_and_is_refused_while_another_turn_of_the_item_runs(server, syngate_tree):
    base, app = server
    syngate_dir, _ = syngate_tree
    batch = lambda *calls: "```syngate\n" + json.dumps(list(calls)) + "\n```"
    gated = GatedConnector()
    app.connectors = {"echo": CallsConnector(batch({"tool": "rename", "uid": "@", "new_uid": "TOP"}, {"tool": "query", "uid": "@"}), "Renamed."), "gated": gated}
    setup = {"connector": "echo", "model": "model-a", "effort": "low", "modes": ["tree"]}
    call(base, app, "/api/chat/ROOT", setup)
    chat = app.chats["ROOT"]
    call(base, app, "/api/turn", {**setup, "uid": "ROOT", "text": "Rename yourself."})
    outcome = chat.turn.snapshot(wait=10)
    assert (outcome["turn"], outcome["reply"]) == ("TOP:1", "- renamed ROOT to TOP\nRenamed.")  # the second round ran anchored at TOP
    assert [step["lines"][1].split(": ", 1)[0] for step in outcome["steps"] if step["kind"] == "calls"] == ["- TOP"]  # so did the query after the rename
    assert not (syngate_dir / "ROOT.yml").exists() and syngatelib.load_tree(syngate_dir)[0]["LEAF-001"].parents == ["TOP"]
    chats = call(base, app, "/api/chats")[1]["chats"]
    assert sorted(chats) == ["TOP"] and chats["TOP"]["uid"] == "TOP"
    assert [(m["role"], m["text"]) for m in chats["TOP"]["log"]] == [("user", "Rename yourself."), ("ai", "- renamed ROOT to TOP\nRenamed.")]
    app.save_chats()
    stored = json.loads(app.chats_file.read_text())
    assert sorted(stored) == ["TOP"] and [m["text"] for m in stored["TOP"]["log"]] == ["Rename yourself.", "- renamed ROOT to TOP\nRenamed."]

    held = call(base, app, "/api/turn", {**setup, "connector": "gated", "uid": "LEAF-001", "text": "Hold on."})[1]["turn"]
    app.connectors["echo"] = CallsConnector(batch({"tool": "rename", "uid": "LEAF-001", "new_uid": "LEAF-002"}), "Left as it is.")
    status, result = call(base, app, "/api/chat", {**setup, "uid": "TOP", "text": "Rename the leaf."})
    assert (status, result["reply"]) == (200, f"- rename LEAF-001 refused: a turn of LEAF-001 is running ({held})\nLeft as it is.")
    assert sorted(syngatelib.load_tree(syngate_dir)[0]) == ["LEAF-001", "TOP"] and app.chats["LEAF-001"].running
    gated.release.set()
    assert call(base, app, f"/api/turn/{held}?wait=5")[1]["reply"] == "late reply to Hold on."


@pytest.mark.syngate("ASSASSIN-UI-FEATURE-OFF")
def test_a_feature_switched_off_has_no_affordances_on_the_page(server, chrome, syngate_tree):
    base, app = server
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root branch\n", parents=(), features=())
    make_item(syngate_dir, "LEAF-001", "It shall leaf.\n", parents=("ROOT",), header="First leaf")
    page = Page(chrome, f"{base}/?token={app.token}")
    page.wait("document.querySelector('#tree [data-uid=\"LEAF-001\"]')")
    icon = "document.querySelector('#%s [data-uid=\"LEAF-001\"] .status')"
    look = f"[{icon % 'tree'}.className, {icon % 'tree'}.title, getComputedStyle({icon % 'tree'}).backgroundColor, document.querySelectorAll('#tree .status .eyes, #tree [data-act=\"tests\"], #doc .block-status').length]"
    assert page.eval(look) == ["status bare", "run actions", "rgba(0, 0, 0, 0)", 0]  # no fill, no glyph, no test button: the icon stays as the anchor of a run
    entries = "[...document.querySelectorAll('#tests-pop [data-run]')].map((el) => el.dataset.run + ':' + el.textContent)"
    detail = "document.querySelectorAll('#tests-pop .status-lines > div, #tests-pop .leaf-toggle, #tests-pop .binding-row').length"
    page.eval(f"{icon % 'doc'}.click()")
    assert page.eval(entries) == ["test:▶ Run test"] and page.eval(detail) == 0  # the tree awaits no tests, but a run stays offered
    page.eval("document.getElementById('tests-pop').hidePopover()")
    make_item(syngate_dir, "ROOT", "Root branch\n", parents=(), features=("review",))
    page.wait(f"{icon % 'tree'}.className === 'status bare not_reviewed'")  # picked up by the fingerprint poll
    assert page.eval(look)[1:] == ["not reviewed", "rgba(0, 0, 0, 0)", 0]
    page.eval(f"{icon % 'doc'}.click()")
    assert page.eval(entries) == ["test:▶ Run test", "review:👀 Mark reviewed"]
    assert page.eval("[...document.querySelectorAll('#tests-pop .status-lines > div')].map((el) => el.textContent)") == ["○ not reviewed"]


class GatedConnector(EchoConnector):
    """Answers the scripted `first` replies at once, then only when released; interrupted, it fails as a killed process does."""

    def __init__(self, *first):
        super().__init__()
        self.first = list(first)
        self.release = threading.Event()
        self.interrupted = False

    def dispatch(self, context, text, model=None, effort=None, modes=(), session=None, on_step=None, stopped=None):
        if self.first:
            return self.first.pop(0), "session-early"
        self.release.wait(10)
        if self.interrupted:
            raise synthetic.connection_error("claude exited with -9")
        return {"kind": "text", "text": f"late reply to {heard(text)}"}, "session-late"

    def interrupt(self, ident):
        self.interrupted = True
        self.release.set()


class SteppingConnector(GatedConnector):
    """Announces a tool step, then its result as the same step announced again, before the gated answer."""

    def dispatch(self, context, text, on_step=None, **kwargs):
        step = {"kind": "tool", "name": "Read", "input": {"file_path": heard(text)}, "result": None, "seconds": None, "at": 0.5}
        on_step(step)
        step.update(result="read", seconds=0.1)
        on_step(step)
        return super().dispatch(context, text, **kwargs)


class NarratingConnector(GatedConnector):
    """Narrates a reasoning and a pending tool call, then -- once `more` is set -- the call's result, a subagent and a diff, before the gated answer."""

    def __init__(self, *first):
        super().__init__(*first)
        self.more = threading.Event()

    def dispatch(self, context, text, on_step=None, **kwargs):
        tool = {"kind": "tool", "name": "Read", "input": {"file_path": "docs/GUIDE.md"}, "result": None, "seconds": None, "at": 0.2}
        on_step({"kind": "reasoning", "text": f"Thinking about {heard(text)}", "at": 0.1})
        on_step(tool)
        self.more.wait(10)
        tool.update(result="read", seconds=0.1)
        on_step(tool)
        on_step({"kind": "agent", "uid": "ROOT", "prompt": "Check the root", "report": "Root checked", "at": 0.4,
                 "steps": [{"kind": "tool", "name": "Grep", "input": {"pattern": "leaf"}, "result": "1 match", "seconds": 0.3, "at": 0.5}]})
        on_step({"kind": "diff", "files": [{"path": "docs/GUIDE.md", "status": "M", "hunks": "@@ -1 +1 @@\n-old\n+new"}], "at": 1.0})
        return super().dispatch(context, text, **kwargs)


LEAF = "document.querySelector('.block[data-uid=\"LEAF-001\"]')"
HEAD = f"{LEAF}.querySelector('.turn-activity .turn-head')"
STEPS = f"[...{LEAF}.querySelectorAll('.turn-activity > .turn-steps > .turn-step > .step-line')].map((line) => line.textContent)"


@pytest.mark.syngate("AI_CHAT-060")
def test_a_turn_is_awaited_on_the_server_and_a_reloaded_page_re_attaches_to_it(server, chrome):
    base, app = server
    gated = NarratingConnector()
    page = open_chat(server, chrome, echo=gated)
    send(page, "LEAF-001", "Slow one")
    page.wait(f"{HEAD} && {HEAD}.querySelector('.spinner') && {HEAD}.textContent.trim().startsWith('1 tool call')")
    assert page.eval(f"Boolean({LEAF}.querySelector('.chat-msg.note'))") is False  # the activity stands for the spinner note
    page.eval(f"{HEAD}.click()")
    assert page.eval(STEPS) == ["reasoningThinking about Slow one", "Readdocs/GUIDE.md …"]
    gated.more.set()
    page.wait(f"{HEAD}.textContent.trim().startsWith('1 tool call · 1 subagent · 1 file changed · ')")  # grows live
    assert page.eval(STEPS) == ["reasoningThinking about Slow one", "Readdocs/GUIDE.md · 0.1 s", "agent @ROOTCheck the root", "diff1 file changed"]
    turn = page.eval("state.chats.get('LEAF-001').turn")
    snapshot = call(base, app, f"/api/turn/{turn}")[1]
    assert turn == "LEAF-001:1" and snapshot["running"] and len(snapshot["steps"]) == 4
    reload(page)
    page.wait(f"{HEAD} && {HEAD}.querySelector('.spinner')")
    page.eval(f"{HEAD}.click()")
    assert page.eval(f"{LEAF}.querySelectorAll('.chat-msg.ai').length") == 0 and len(page.eval(STEPS)) == 4  # the steps so far
    gated.release.set()
    page.wait(f"{LEAF}.querySelector('.chat-msg.ai')")
    assert page.eval(f"{LEAF}.querySelector('.chat-msg.ai').textContent").strip() == "late reply to Slow one"
    assert page.eval(f"[{HEAD}.querySelector('.spinner'), {LEAF}.querySelector('.chat-msg.ai + .turn-activity') !== null, {STEPS}.length]") == [None, True, 4]
    assert page.eval("[state.chats.get('LEAF-001').turn, state.chats.get('LEAF-001').session]") == [None, "session-late"]
    assert call(base, app, f"/api/turn/{turn}")[1]["running"] is False  # the turn's outcome stays readable: it is also the chat's last message


@pytest.mark.syngate("AI_CHAT-STOP-BUTTON")
def test_while_a_turn_runs_the_hide_pill_is_a_stop_button_pressed_once_and_the_turn_reads_as_stopped(server, chrome):
    _, app = server
    gated = NarratingConnector({"kind": "calls", "calls": [{"tool": "query", "uid": "@"}]})
    gated.more.set()
    page = open_chat(server, chrome, echo=gated)
    pills = f"[Boolean({LEAF}.querySelector('.block-ai .chat-hide')), Boolean({LEAF}.querySelector('.block-ai .chat-stop')), Boolean({LEAF}.querySelector('.chat-pill.busy'))]"
    assert page.eval(pills) == [True, False, False]
    send(page, "LEAF-001", "Stuck one")
    page.wait(f"{LEAF}.querySelector('.block-ai .chat-stop')")
    assert page.eval(pills) == [False, True, True]
    stop = f"{LEAF}.querySelector('.block-ai .chat-stop')"
    assert page.eval(f"[{stop}.tagName, {stop}.textContent, {stop}.disabled, getComputedStyle({stop}).color]") == ["BUTTON", "■ stop", False, css_color(page, "--red")]
    turn = app.chats["LEAF-001"].turn
    page.eval(f"{stop}.click(); {stop}.click()")
    assert page.eval(f"[{stop}.textContent.trim(), {stop}.disabled, Boolean({stop}.querySelector('.spinner'))]") == ["stopping…", True, True]  # one press; then it waits
    page.wait(f"{LEAF}.querySelector('.chat-msg.stopped')")
    assert turn.stopped and gated.interrupted and turn.outcome["status"] == 409
    stopped = page.eval(f"{LEAF}.querySelector('.chat-msg.stopped').textContent").strip()
    assert stopped == "turn stopped" and [step["lines"][0][:13] for step in turn.steps if step["kind"] == "calls"] == ["- LEAF-001: {"]  # what was read stays in the steps
    assert page.eval(f"getComputedStyle({LEAF}.querySelector('.chat-msg.stopped .msg-body'), '::before').content") == '"■ stopped — "'
    assert page.eval(f"[...{LEAF}.querySelectorAll('.chat-msg.stopped .msg-tools button')].map((el) => el.className)") == ["msg-fold"]  # not an error: no retry, nothing to keep
    assert page.eval(pills) == [True, False, False] and page.eval("state.stopping.size") == 0
    page.eval(f"{LEAF}.querySelector('.chat-msg.stopped + .turn-activity .turn-head').click()")
    assert page.eval(f"{LEAF}.querySelector('.chat-msg.stopped + .turn-activity .turn-head').textContent").startswith("2 tool calls · 2 subagents · 1 file changed · ")
    calls = f"[...{LEAF}.querySelectorAll('.turn-activity > .turn-steps > .turn-step > .step-line')].find((line) => line.textContent.startsWith('calls'))"
    page.eval(f"{calls}.click()")
    assert page.eval(f"[{calls}.tagName, {calls}.textContent, {calls}.parentElement.querySelector('.step-detail .step-label').textContent]") == ["BUTTON", "callsquery", "read"]  # a read is not applied


class BackgroundConnector(EchoConnector):
    """Answers `Start` by launching a background subagent on ROOT, which holds on `Wait` until released; any other text is echoed."""

    def __init__(self):
        super().__init__()
        self.release = threading.Event()

    def dispatch(self, context, text, **kwargs):
        if heard(text) == "Wait":
            self.release.wait(10)
            return {"kind": "text", "text": "Waited."}, "session-child"
        if heard(text) == "Start":
            return {"kind": "calls", "calls": [{"tool": "agent", "uid": "ROOT", "prompt": "Wait", "background": True}]}, "session-parent"
        return super().dispatch(context, text, **kwargs)


@pytest.mark.syngate("AI_CHAT-AGENT-BACKGROUND")
def test_a_chat_whose_turn_ended_while_a_background_subagent_runs_shows_no_stop_pill_and_sends(server, chrome):
    _, app = server
    connector = BackgroundConnector()
    page = open_chat(server, chrome, echo=connector)
    pills = f"[Boolean({LEAF}.querySelector('.block-ai .chat-hide')), Boolean({LEAF}.querySelector('.block-ai .chat-stop')), Boolean({LEAF}.querySelector('.chat-pill.busy'))]"
    send(page, "LEAF-001", "Start")
    page.wait(f"{LEAF}.querySelector('.chat-msg.ai') && {LEAF}.querySelector('.agent-run')")
    assert app.chats["ROOT"].running and page.eval(pills) == [True, False, False] and page.eval(f"{LEAF}.getAttribute('aria-busy')") is None
    assert page.eval(f"{LEAF}.querySelector('.chat-log > .turn-activity:last-child .turn-head').textContent.trim()") == "1 background subagent running"
    send(page, "LEAF-001", "Again")
    page.wait(f"{LEAF}.querySelectorAll('.chat-msg.ai').length === 2")
    assert "|Again|" in page.eval(f"{LEAF}.querySelectorAll('.chat-msg.ai')[1].textContent") and app.chats["ROOT"].running  # the message went while the subagent ran

    connector.release.set()
    page.wait(f"{LEAF}.querySelector('.chat-msg.ai.agent-report') && !{LEAF}.querySelector('.agent-run')")
    report = f"{LEAF}.querySelector('.chat-msg.ai.agent-report')"
    assert page.eval(f"[{report}.querySelector('.msg-from').textContent, {report}.querySelector('.msg-part').textContent.trim()]") == ["report of @ROOT", "Waited."]


class RunningAgentConnector(GatedConnector):
    """Announces subagent steps still running on ROOT, on the chat's own item and on an unknown one before the gated answer."""

    def dispatch(self, context, text, on_step=None, **kwargs):
        for uid in ("ROOT", "LEAF-001", "NOPE-1"):
            on_step({"kind": "agent", "uid": uid, "prompt": f"Check {uid}", "report": None, "steps": [], "at": 0.3})
        return super().dispatch(context, text, on_step=on_step, **kwargs)


@pytest.mark.syngate("AI_CHAT-AGENT-LINK")
def test_the_run_indicator_of_a_subagent_on_another_item_is_a_link_jumping_to_that_item(server, chrome):
    gated = RunningAgentConnector()
    page = open_chat(server, chrome, echo=gated)
    send(page, "LEAF-001", "Slow one")
    page.wait(f"{LEAF}.querySelector('.turn-activity a.agent-run')")
    runs = f"[...{LEAF}.querySelectorAll('a.jump.agent-run')].map((a) => [a.dataset.uid, a.textContent.trim(), Boolean(a.querySelector('.spinner'))])"
    assert page.eval(runs) == [["ROOT", "@ROOT", True]]  # neither the chat's own item nor an unknown one
    page.eval(f"{HEAD}.click()")
    assert page.eval(f"[...{LEAF}.querySelectorAll('.turn-steps .step-line a.jump')].map((a) => a.dataset.uid)") == ["ROOT", "LEAF-001"]  # the step lines name their items alike
    page.eval(f"{LEAF}.querySelector('a.agent-run').click()")
    landed = "[state.selected, document.querySelector('#doc .block.selected')?.dataset.uid, document.activeElement.dataset.uid]"
    assert page.eval(landed) == ["ROOT", "ROOT", "ROOT"]
    gated.release.set()
    page.wait(f"{LEAF}.querySelector('.chat-msg.ai') && !{LEAF}.querySelector('.agent-run')")


class FlakyConnector(EchoConnector):
    """Echoes, except where `outcomes` names an error for the turn."""

    def __init__(self, *outcomes):
        super().__init__()
        self.outcomes = list(outcomes)

    def dispatch(self, context, text, **kwargs):
        error = self.outcomes.pop(0) if self.outcomes else None
        if error:
            raise synthetic.connection_error(error)
        return super().dispatch(context, text, **kwargs)


@pytest.mark.syngate("AI_CHAT-RETRY", "retry")
def test_a_failed_turns_message_offers_a_retry_in_the_same_session_and_its_removal(server, chrome):
    base, app = server
    page = open_chat(server, chrome, echo=FlakyConnector(None, "claude exited with 1"))
    send(page, "LEAF-001", "First")
    page.wait(f"{LEAF}.querySelector('.chat-msg.ai')")
    send(page, "LEAF-001", "Second")
    page.wait(f"{LEAF}.querySelector('.chat-msg.error')")
    marks = f"[...{LEAF}.querySelectorAll('.chat-msg')].map((el) => [...el.querySelectorAll('.msg-tools button')].map((b) => b.className).join(' '))"
    assert page.eval(marks) == ["msg-fold msg-child msg-sibling"] * 3 + ["msg-fold msg-retry msg-drop"]
    page.eval(f"{LEAF}.querySelector('.chat-msg.error .msg-retry').click()")
    page.wait(f"{LEAF}.querySelectorAll('.chat-msg.ai').length === 2")
    roles = lambda: [m["role"] for m in call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]["log"]]
    assert roles() == ["user", "ai", "user", "error", "ai"]  # the last message went again, not logged twice
    assert page.eval(f"{LEAF}.querySelectorAll('.chat-msg.ai')[1].textContent").endswith("|Second|model-a|low|edit,internet|session-1")  # the same session
    assert page.eval(marks)[3] == "msg-fold msg-drop"  # the retry stands only on the last message
    page.eval(f"{LEAF}.querySelector('.chat-msg.error .msg-drop').click()")
    page.wait(f"{LEAF}.querySelectorAll('.chat-msg').length === 4")
    assert roles() == ["user", "ai", "user", "ai"] and page.eval(f"Boolean({LEAF}.querySelector('.chat-msg.error'))") is False


class CostedConnector(EchoConnector):
    """Echoes after a closing usage step, as the Claude Code connector reports the CLI's result event."""

    def dispatch(self, context, text, on_step=None, **kwargs):
        on_step({"kind": "usage", "seconds": 48.2, "cost_usd": 0.123, "input_tokens": 12345, "output_tokens": 3210, "at": 48.2})
        return super().dispatch(context, text, **kwargs)


@pytest.mark.syngate("AI_CHAT-TURN-COST", "header")
def test_every_reply_closes_with_an_activity_header_carrying_the_wall_time_cost_and_tokens_when_known(server, chrome):
    page = open_chat(server, chrome, echo=EchoConnector(), costed=CostedConnector("Costed"))
    send(page, "LEAF-001", "Plain")
    page.wait(f"{LEAF}.querySelector('.chat-msg.ai')")
    heads = f"[...{LEAF}.querySelectorAll('.chat-msg + .turn-activity .turn-head')].map((el) => [el.tagName, el.textContent.trim(), getComputedStyle(el).borderTopStyle === 'none' && !el.classList.contains('pill')])"
    assert page.eval(heads) == [["SPAN", "no steps", True]]  # a turn without steps still shows the line, and it unfolds to nothing; no pill on the reply's rule
    pick(page, "connector", "costed")
    send(page, "LEAF-001", "Costed")
    page.wait(f"{LEAF}.querySelectorAll('.chat-msg.ai').length === 2")
    assert page.eval(heads) == [["SPAN", "no steps", True], ["SPAN", "48 s · $0.12 · 12k in / 3.2k out", True]]
    assert page.eval(f"{LEAF}.querySelectorAll('.chat-msg.user + .turn-activity').length") == 0


@pytest.mark.syngate("AI_CHAT-022", "refusal")
def test_sending_while_a_turn_runs_or_with_an_empty_statement_keeps_the_editor_and_says_so(server, chrome):
    base, app = server
    gated = GatedConnector()
    page = open_chat(server, chrome, echo=gated)
    send(page, "LEAF-001", "Slow one")
    page.wait(f"{LEAF}.querySelector('.block-ai .chat-stop')")
    edit_leaf(page, "It shall leaf meanwhile.")
    page.eval(CTRL_ENTER % "document.querySelector('#doc .block.editing textarea')")
    assert page.eval(TOASTS) == ["toast info:a turn of LEAF-001 is running — wait for it or stop it"]
    held = f"[state.editing, {LEAF}.querySelector('.chat-input').placeholder, {LEAF}.querySelector('.chat-pill').classList.contains('busy'), {LEAF}.querySelector('.chat-send').title]"
    assert page.eval(held) == ["ROOT/LEAF-001", WAIT_HINT, True, "a turn of LEAF-001 is running — wait for it or stop it"]
    page.eval(f"{LEAF}.querySelector('.chat-input').value = 'Waiting'")
    page.eval(f"{LEAF}.querySelector('.block-ai .chat-send').click()")
    assert page.eval(TOASTS) == ["toast info:a turn of LEAF-001 is running — wait for it or stop it"] * 2 and page.eval(f"{LEAF}.querySelector('.chat-input').value") == "Waiting"
    assert [m["role"] for m in call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]["log"]] == ["user"]
    gated.release.set()
    page.wait(f"{LEAF}.querySelector('.chat-msg.ai')")
    page.eval("document.getElementById('toasts').replaceChildren()")
    edit_leaf(page, " ")
    page.eval(f"{LEAF}.querySelector('.block-ai .chat-send').click()")
    page.wait("document.querySelector('#toasts .toast')")
    assert page.eval(TOASTS) == ["toast info:the statement is empty — nothing to send"] and page.eval("state.editing") == "ROOT/LEAF-001"
    assert [m["role"] for m in call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]["log"]] == ["user", "ai"]


@pytest.mark.syngate("AI_CHAT-CONTROLS-FOLD-KEEP", "drop_travels")
def test_a_fold_mark_is_frozen_while_a_turn_runs_and_folded_text_does_not_travel(server, chrome):
    base, app = server
    gated = GatedConnector({"kind": "text", "text": "first reply"})
    page = open_chat(server, chrome, echo=gated)
    send(page, "LEAF-001", "First")
    page.wait(f"{LEAF}.querySelector('.chat-msg.ai')")
    send(page, "LEAF-001", "Second")
    page.wait(f"{LEAF}.querySelector('.block-ai .chat-stop')")
    x, y = page.eval(f"(() => {{ const r = {LEAF}.querySelector('.chat-msg.user').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})()")
    page.mouse("mouseMoved", x, y, buttons=0)  # the marks of a hovered message are revealed; frozen, they take no click even so
    folds = f"[...{LEAF}.querySelectorAll('.msg-fold')].map((el) => el.getAttribute('aria-disabled'))"
    hovered = f"getComputedStyle({LEAF}.querySelector('.chat-msg.user .msg-fold')).pointerEvents"
    assert page.eval(f"[{folds}, {hovered}, {LEAF}.classList.contains('busy')]") == [["true"] * 3, "none", True]
    with pytest.raises(urllib.error.HTTPError) as frozen:
        call(base, app, "/api/chat/LEAF-001", {"message": {"index": 0, "cuts": [[0, 5]]}})
    assert frozen.value.code == 409
    gated.release.set()
    page.wait(f"{LEAF}.querySelectorAll('.chat-msg.ai').length === 2")
    assert page.eval(f"[{folds}, {hovered}, {LEAF}.classList.contains('busy')]") == [["false"] * 4, "auto", False]
    page.eval(f"{LEAF}.querySelector('.chat-msg.user .msg-fold').click()")
    page.wait(f"{LEAF}.querySelector('.chat-msg.user').classList.contains('dropped')")
    page.wait("state.chats.get('LEAF-001').session === null")
    send(page, "LEAF-001", "Third")
    page.wait(f"{LEAF}.querySelectorAll('.chat-msg.ai').length === 3")
    travelled = page.eval(f"{LEAF}.querySelectorAll('.chat-msg.ai')[2].textContent")
    assert "user: Second" in travelled and "assistant: first reply" in travelled and "user: First" not in travelled  # the kept messages head the new session


@pytest.mark.syngate("AI_CHAT-RESET", "reset")
def test_the_setup_menu_offers_a_new_session_and_a_confirmed_new_chat_both_refused_while_a_turn_runs(server, chrome):
    base, app = server
    gated = GatedConnector({"kind": "text", "text": "first reply"})
    page = open_chat(server, chrome, echo=gated)
    send(page, "LEAF-001", "First")
    page.wait(f"{LEAF}.querySelector('.chat-msg.ai')")
    entries = "(() => { document.querySelector('.chat-setup').click(); const menu = document.getElementById('status-menu');" \
              " const out = [...menu.querySelectorAll('[data-chat-reset]')].map((b) => [b.dataset.chatReset, b.textContent, b.disabled]); menu.hidePopover(); return out; })()"
    assert page.eval(entries) == [["session", "↺ New session", False], ["begin", "＋ New chat", False], ["chat", "✕ Delete chat", False]]
    reset = lambda strength: page.eval(f"(() => {{ document.querySelector('.chat-setup').click(); document.querySelector('#status-menu [data-chat-reset=\"{strength}\"]').click(); }})()")
    page.eval("window.asked = []; window.confirm = (text) => { window.asked.push(text); return false; }")
    reset("chat")
    assert page.eval("window.asked") == ["Delete this chat of LEAF-001? Its 2 messages and session are erased."]
    assert [m["role"] for m in call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]["log"]] == ["user", "ai"]  # declined: nothing erased
    reset("session")
    page.wait("state.chats.get('LEAF-001').session === null")
    assert page.eval(f"{LEAF}.querySelectorAll('.chat-msg').length") == 2 and page.eval("window.asked.length") == 1  # the history stays, no confirmation needed
    send(page, "LEAF-001", "Second")
    page.wait(f"{LEAF}.querySelector('.block-ai .chat-stop')")
    assert page.eval(entries) == [["session", "↺ New session", True], ["begin", "＋ New chat", True], ["chat", "✕ Delete chat", True]]
    gated.release.set()
    page.wait(f"{LEAF}.querySelectorAll('.chat-msg.ai').length === 2")
    assert "user: First assistant: first reply" in page.eval(f"{LEAF}.querySelectorAll('.chat-msg.ai')[1].textContent")  # the kept messages travel as the transcript
    reset("begin")
    page.wait(f"{LEAF}.querySelectorAll('.chat-msg').length === 0")
    page.wait("state.chats.get('LEAF-001').archive.length === 1")
    chat = call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]
    assert (chat["log"], page.eval("window.asked.length"), [c["messages"] for c in chat["archive"]]) == ([], 1, [4])  # a new chat files the old one, unasked
    send(page, "LEAF-001", "Third")
    page.wait(f"{LEAF}.querySelector('.chat-msg.ai')")
    page.eval("window.confirm = () => true")
    reset("chat")
    page.wait(f"{LEAF}.querySelectorAll('.chat-msg').length === 0")
    chat = call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]
    assert (chat["log"], [c["messages"] for c in chat["archive"]]) == ([], [4])  # the live conversation is deleted, the filed one untouched


LAYOUT = "(() => { const tree = document.getElementById('tree-pane'), width = (el) => Math.round(el.getBoundingClientRect().width), pad = (sel) => parseFloat(getComputedStyle(document.querySelector(sel)).paddingLeft);" \
         " return [innerWidth, getComputedStyle(document.querySelector('main')).flexDirection, getComputedStyle(document.getElementById('splitter')).display, width(tree)," \
         " Math.round(parseFloat(getComputedStyle(tree).maxHeight)) || null, width(document.getElementById('doc-pane')), pad('#tree .kids'), pad('#doc .kids'), width(document.getElementById('filter'))]; })()"


@pytest.mark.syngate("ASSASSIN-UI-NARROW")
def test_the_panes_stack_under_60rem_and_everything_stays_shown_without_hover(violated_page, syngate_tree):
    page, (syngate_dir, _) = violated_page, syngate_tree
    sourced = syngatelib.Item(uid="LEAF-002", path=syngate_dir / "LEAF-002.yml", description="Frozen\n\nIt shall freeze.\n", parents=["ROOT"], tests={None: "a" * 64},
                              sources=[f"src/ai_scratcher/a_rather_long_module_name_{i}.py" for i in range(6)])
    sourced.reviewed = syngatelib.compute_stamp(sourced)
    syngatelib.write_item(sourced)
    page.wait("document.querySelectorAll('#doc .block[data-uid=\"LEAF-002\"] .block-sources a').length === 6")
    wide = page.eval(LAYOUT)
    assert wide[:3] == [1280, "row", "block"] and wide[3] == round(0.3 * 1280)
    page.cdp.call("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 800, "deviceScaleFactor": 1, "mobile": True}, page.session)
    page.wait("innerWidth === 390")
    page.eval("new Promise((done) => requestAnimationFrame(() => setTimeout(done, 0)))")  # the resize event of the viewport change lands in a frame: let it, so it is not taken for one of the page's own later
    page.eval("setTreeWidth(600)")  # a remembered width does not apply while stacked
    narrow = page.eval(LAYOUT)
    assert narrow[:6] == [390, "column", "none", 390, round(0.38 * 800), 390]  # stacked: the outline capped, no splitter, the document at full width
    assert narrow[6:8] == [wide[6] / 2, wide[7] / 2] and narrow[8] > wide[8]  # half the depth shift in both panes, the filter spanning the header
    pane = "document.getElementById('doc-pane')"
    assert page.eval(f"{pane}.scrollWidth <= {pane}.clientWidth")  # the six source links wrap: the document never scrolls sideways
    page.eval(f"{pane}.scrollTop = 1e6")
    assert page.eval(f"!inView(document.querySelector('#doc .block[data-uid=\"ROOT\"]'), {pane})")
    page.eval("document.querySelector('#doc .block[data-uid=\"ROOT\"] legend .status').click()")
    assert page.eval(f"new Promise((done) => requestAnimationFrame(() => setTimeout(() => done({POPUP}), 0)))")[:2] == [True, "ROOT"]  # the scroll bringing the block into view is the page's own: the popup stays
    page.eval(f"{pane}.dispatchEvent(new Event('scroll'))")
    assert page.eval(POPUP)[0] is False  # a scroll a frame later is the user's
    page.eval("setTreeWidth(0)")
    page.cdp.call("Emulation.clearDeviceMetricsOverride", {}, page.session)
    page.wait("innerWidth === 1280")
    assert page.eval(LAYOUT)[:4] == wide[:4]
    page.cdp.call("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5}, page.session)
    page.wait("matchMedia('(hover: none)').matches")
    shown = "(() => { const row = document.querySelector('#tree [data-uid=\"LEAF-001\"]'), block = document.querySelector('#doc .block[data-uid=\"LEAF-001\"]');" \
            " return [getComputedStyle(row.querySelector('.tools')).visibility, getComputedStyle(block.querySelector('.block-foot')).visibility, getComputedStyle(block).borderTopColor]; })()"
    page.wait(f"JSON.stringify({shown}) === {json.dumps(json.dumps(['visible', 'visible', css_color(page, '--line')], separators=(',', ':')))}")  # a resting, unselected item: nothing hidden
    page.eval("startEditing('ROOT/LEAF-002')")
    page.wait("document.querySelector('#doc .block.editing .block-foot .pill')")
    hit = "(() => { const row = document.querySelector('#tree [data-uid=\"LEAF-002\"]'), block = document.querySelector('#doc .block[data-uid=\"LEAF-002\"]'), size = (el) => el.getBoundingClientRect();" \
          " return [size(block.querySelector('.block-foot .pill')).height >= 30, size(row.querySelector('.tools button')).width >= 32, size(row.querySelector('.tools button')).height >= 32, getComputedStyle(row.querySelector('.status'), '::after').position]; })()"
    assert page.eval(hit) == [True, True, True, "absolute"]  # finger-sized: the pills, the row menu, the hit box around the status icon


@pytest.mark.syngate("ASSASSIN-UI-RENDER", "problems")
def test_validation_problems_show_inline_in_the_block(violated_page):
    page = violated_page
    shown = "[...document.querySelectorAll('#doc .block')].map((el) => [el.dataset.uid, [...el.querySelectorAll(':scope > .block-body .block-problems > div')].map((p) => p.textContent)])"
    problems = dict(page.eval(shown))
    assert [uid for uid, lines in problems.items() if lines] == ["LEAF-002"]
    assert any("no test routine tagged [LEAF-002] found" in line for line in problems["LEAF-002"])
    where = "(() => { const body = document.querySelector('#doc .block[data-uid=\"LEAF-002\"] .block-body'), box = body.querySelector('.block-problems');" \
            " return [body.lastElementChild === box, getComputedStyle(box).color]; })()"
    assert page.eval(where) == [True, css_color(page, "--red")]  # under the statement, in the failure colour


@pytest.mark.syngate("AI_CHAT-011", "scheme")
def test_the_waiting_spinner_and_the_permission_pills_use_the_scheme_tokens(server, chrome):
    gated = GatedConnector()
    page = open_chat(server, chrome, echo=gated)
    send(page, "LEAF-001", "Slow one")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.note .spinner')")
    spinner = f"(() => {{ const note = {LEAF_BLOCK}.querySelector('.chat-msg.note'), s = getComputedStyle(note.querySelector('.spinner')); return [s.borderTopColor === getComputedStyle(note).color, s.borderTopColor]; }})()"
    on = f"getComputedStyle({LEAF_BLOCK}.querySelector('.chat-mode.on')).color"
    assert page.eval(spinner) == [True, css_color(page, "--dim")] and page.eval(on) == css_color(page, "--accent")  # the spinner takes its line's colour, the pills the accent
    scheme = "getComputedStyle(document.documentElement).colorScheme"
    assert page.eval(scheme) == "light"
    light = css_color(page, "--accent")
    page.cdp.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": "dark"}]}, page.session)
    page.wait("matchMedia('(prefers-color-scheme: dark)').matches")
    dark = css_color(page, "--accent")
    assert dark != light and page.eval(on) == dark and page.eval(spinner)[0] and page.eval(scheme) == "dark"  # the same tokens, redefined by the dark scheme, the browser's own widgets with them
    assert page.eval(f"getComputedStyle({LEAF_BLOCK}.querySelector('.chat-stop')).color") == css_color(page, "--red")
    gated.release.set()
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")


@pytest.mark.syngate("ASSASSIN-UI-CONTENT-JUMP")
def test_an_item_reference_in_a_statement_message_or_file_is_a_jump_link_to_its_block(server, chrome, syngate_tree):
    base, app = server
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "LEAF-002", "Second\n\nIt shall be second.\n", parents=("ROOT",), tests=None)
    (app.root / "docs").mkdir()
    (app.root / "docs" / "NOTES.md").write_text("# Notes\n\nSee @LEAF-002 and @NOPE-1.\n")
    (syngate_dir / "LEAF-001.yml").write_text("---\nparents: [ROOT]\ntest: ~\n---\nIt shall leaf after @LEAF-002, like [ROOT], not @NOPE-1 nor `@LEAF-002`; see [notes](docs/NOTES.md).\n")
    page = item_page(server, chrome)
    page.wait(f"{LEAF_BLOCK}.querySelector('a.filelink')")
    links = "[...%s.querySelectorAll('a.jump')].map((a) => a.dataset.uid + ':' + a.textContent)"
    text = f"{LEAF_BLOCK}.querySelector('.block-body .block-text')"
    assert page.eval(links % text) == ["LEAF-002:@LEAF-002", "ROOT:ROOT"]  # written as typed; an unknown UID and a code span stay text
    assert "@NOPE-1" in page.eval(f"{text}.textContent") and page.eval(f"{text}.querySelector('code').textContent") == "@LEAF-002"
    enter_reply(page, "LEAF-001")
    send(page, "LEAF-001", "Look at @LEAF-002")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    assert page.eval(links % f"{LEAF_BLOCK}.querySelector('.chat-msg.user')") == ["LEAF-002:@LEAF-002"]
    assert "LEAF-002:@LEAF-002" in page.eval(links % f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    page.eval(f"{LEAF_BLOCK}.querySelector('a.filelink').click()")
    notes = f"{LEAF_BLOCK}.querySelector('.file-view[data-file=\"docs/NOTES.md\"]')"
    page.wait(f"{notes} && {notes}.querySelector('.md')")
    assert page.eval(links % notes) == ["LEAF-002:@LEAF-002"]
    page.eval("state.expanded.clear(); persistExpanded(); render()")
    assert page.eval(PATHS % "#tree") == ["ROOT"]
    page.eval(f"{text}.querySelector('a.jump').click()")
    landed = "[state.selected, document.querySelector('#doc .block.selected')?.dataset.uid, document.querySelector('#tree .row.selected')?.dataset.uid, document.activeElement.dataset.uid]"
    assert page.eval(landed) == ["LEAF-002", "LEAF-002", "LEAF-002", "LEAF-002"]  # the block activated, the outline unfolded to its row


CHAT_MARK = "(() => { const el = document.querySelector('#tree [data-uid=\"LEAF-001\"] .chat-state'); return [el.hidden, el.className, el.title, el.textContent, Boolean(el.querySelector('.spinner')), getComputedStyle(el).color]; })()"


@pytest.mark.syngate("ASSASSIN-UI-TREE-CHAT-MARK")
def test_the_tree_row_marks_a_running_turn_an_unread_reply_a_hidden_chat_and_a_failed_turn(server, chrome):
    base, app = server
    gated = GatedConnector()
    page = open_chat(server, chrome, echo=gated)
    assert page.eval(CHAT_MARK)[:2] == [True, "chat-state"]  # no chat yet: no mark
    send(page, "LEAF-001", "Slow one")
    page.wait("document.querySelector('#tree [data-uid=\"LEAF-001\"] .chat-state.running .spinner')")
    assert page.eval(CHAT_MARK)[:3] == [False, "chat-state running", "the AI is answering"] and page.eval(f"{LEAF_BLOCK}.getAttribute('aria-busy')") == "true"
    other = Page(chrome, f"{base}/?token={app.token}")
    other.wait("document.querySelector('#tree [data-uid=\"LEAF-001\"] .chat-state.running')")  # every tab sees the running turn
    gated.release.set()
    page.wait("document.querySelector('#tree [data-uid=\"LEAF-001\"] .chat-state').hidden")
    assert page.eval(CHAT_MARK)[:2] == [True, "chat-state"] and page.eval(f"{LEAF_BLOCK}.getAttribute('aria-busy')") is None  # shown here: nothing waits, no mark
    other.wait("document.querySelector('#tree [data-uid=\"LEAF-001\"] .chat-state.unread')")
    assert other.eval(CHAT_MARK)[1:4] == ["chat-state unread", "a reply waits", "●"] and other.eval(CHAT_MARK)[5] == css_color(other, "--accent")
    other.eval("document.querySelector('#tree [data-uid=\"LEAF-001\"] .chat-state').click()")
    shown = "[state.selected, state.panel, document.querySelector('#doc .block[data-uid=\"LEAF-001\"]').classList.contains('chatting'), document.activeElement.classList.contains('chat-input')]"
    assert other.eval(shown) == ["LEAF-001", True, True, True] and other.eval(CHAT_MARK)[:2] == [True, "chat-state"]  # the click activates the block and shows the chat: the mark goes
    page.eval(f"{LEAF_BLOCK}.querySelector('.chat-hide').click()")
    assert page.eval(CHAT_MARK)[1:4] == ["chat-state idle", "the chat is hidden", "▾"] and page.eval(CHAT_MARK)[5] == css_color(page, "--dim")
    app.connectors = {"echo": FlakyConnector("claude exited with 1")}
    send(other, "LEAF-001", "Doomed")
    other.wait("document.querySelector('#tree [data-uid=\"LEAF-001\"] .chat-state.failed')")
    assert other.eval(CHAT_MARK)[1:4] == ["chat-state failed", "the last turn failed", "⚠"] and other.eval(CHAT_MARK)[5] == css_color(other, "--red")
    page.activate()
    page.wait("document.querySelector('#tree [data-uid=\"LEAF-001\"] .chat-state.failed')")  # the other tab too, its chat hidden
    other.eval("document.querySelector('#doc .block[data-uid=\"LEAF-001\"] .chat-msg.error .msg-drop').click()")
    other.wait("document.querySelector('#tree [data-uid=\"LEAF-001\"] .chat-state').hidden")  # the failure dropped, the chat shown: no mark


HELD = [sys.executable, "-c", "import sys, time; print('held', *sys.argv[1:]); sys.stdout.flush(); time.sleep(30)"]
CONSOLE = "[document.getElementById('console').classList.contains('open'), document.getElementById('job-argv').textContent, document.getElementById('job-out').textContent," \
          " document.getElementById('console-stop').hidden, document.getElementById('job-state').textContent.trim(), state.job?.id ?? null]"


@pytest.mark.syngate("ASSASSIN-UI-STATUS-POPUP-RUN", "reattach")
def test_a_reloaded_page_re_attaches_to_the_running_run_and_its_console_stops_it(page, server):
    base, app = server
    app.cli_prefix = HELD
    try:
        page.eval("document.querySelector('#tree [data-uid=\"LEAF-001\"] .status').click()")
        page.eval("document.querySelector('#tests-pop [data-run=\"test\"]').click()")
        page.wait("document.getElementById('job-out').textContent.includes('held')")
        before = page.eval(CONSOLE)
        assert before[:2] == [True, "test LEAF-001"] and before[2].startswith("held test LEAF-001 --build-dir") and before[3:] == [False, "running…", 1]
        reload(page)
        page.wait("state.job && document.getElementById('job-out').textContent.includes('held') && document.getElementById('job-argv').textContent")
        after = page.eval(CONSOLE)
        assert after[0] and after[1].startswith("test LEAF-001 --build-dir") and after[2] == before[2] and after[3:] == [False, "running…", 1]  # the same run, named from its argv
        page.eval("document.getElementById('console-stop').click()")
        page.wait("state.job === null")
        assert page.eval(CONSOLE)[3:5] == [True, "■ stopped"]
        snapshot = call(base, app, "/api/job/1")[1]
        assert snapshot["running"] is False and snapshot["returncode"] != 0
    finally:
        app.jobs.cancel()


@pytest.mark.syngate("ASSASSIN-UI-KEYS")
def test_the_keys_walk_the_focused_pane_tab_reaches_the_selected_row_its_tools_and_block_and_the_chat_keys_act_on_it(server, chrome, syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "LEAF-002", "Frozen\n\nIt shall freeze.\n", parents=("ROOT",), tests=None)
    gated = GatedConnector()
    page = item_page(server, chrome, echo=gated)
    page.eval("select('LEAF-002', 'ROOT/LEAF-002')")
    page.eval("document.getElementById('filter').focus()")
    assert [tab(page) for _ in range(7)] == ["LEAF-002 row", "status", "menu", "splitter", "LEAF-002 block", "status", "body"]  # the selected row, its tools, the selected block: nothing else in the way
    assert page.eval("[...document.querySelectorAll('#tree .row:not(.selected) button, #doc .block:not(.selected) legend .status')].every((el) => el.tabIndex === -1)")
    page.eval("document.getElementById('filter').focus()")
    tab(page)
    press(page, "ArrowUp", "ArrowUp", 38)
    assert page.eval(f"[state.selected, {FOCUS}, getComputedStyle(document.activeElement).outlineStyle]") == ["LEAF-001", "LEAF-001 row", "solid"]  # the tree walks its rows, the focus ring with it
    press(page, "Home", "Home", 36)
    assert page.eval(f"[state.selected, {FOCUS}]") == ["ROOT", "ROOT row"]
    for _ in range(4):
        tab(page)
    press(page, "ArrowDown", "ArrowDown", 40)
    assert page.eval(f"[state.selected, {FOCUS}, getComputedStyle(document.activeElement).outlineStyle]") == ["LEAF-001", "LEAF-001 block", "solid"]  # the document walks its blocks
    press(page, "/", "Slash", 191)
    assert page.eval(FOCUS) == "filter"
    press(page, "?", "Slash", 191, 8)
    assert page.eval("[document.getElementById('help-pop').matches(':popover-open'), document.getElementById('filter').value]") == [False, "?"]  # not while typing
    page.eval("(() => { const f = document.getElementById('filter'); f.value = ''; f.dispatchEvent(new Event('input', { bubbles: true })); f.blur(); })()")
    press(page, "?", "Slash", 191, 8)
    assert page.eval("document.getElementById('help-pop').matches(':popover-open')")
    press(page, "?", "Slash", 191, 8)
    assert page.eval("document.getElementById('help-pop').matches(':popover-open')") is False
    page.eval("select('LEAF-002', 'ROOT/LEAF-002', { focus: 'block' })")
    press(page, "m", "KeyM", 77)
    assert page.eval(MENU_ENTRIES) == [True, ["add-parent", "add", "delete"]] and page.eval("document.activeElement.getAttribute('role')") == "menuitem"  # m: the row menu of the focused block
    press(page, "Escape", "Escape", 27)
    assert page.eval(f"[{MENU_OPEN}, {FOCUS}]") == [False, "LEAF-002 block"]
    press(page, "s", "KeyS", 83)
    assert page.eval(POPUP)[:2] == [True, "LEAF-002"]  # s: its status popup
    page.eval("document.getElementById('tests-pop').hidePopover()")
    page.eval("select('LEAF-001', 'ROOT/LEAF-001', { focus: 'row' })")
    press(page, "s", "KeyS", 83)
    assert page.eval(POPUP)[:2] == [True, "LEAF-001"]  # the same keys on a focused row
    page.eval("document.getElementById('tests-pop').hidePopover()")
    press(page, "m", "KeyM", 77)
    assert page.eval(MENU_ENTRIES) == [True, ["add-parent", "add", "delete"]]
    press(page, "Escape", "Escape", 27)
    assert page.eval(FOCUS) == "menu"
    enter_reply(page, "LEAF-001")
    page.eval(f"{LEAF_BLOCK}.querySelector('.chat-input').focus()")
    assert tab(page) == "pill" and page.eval("document.activeElement.classList.contains('chat-hide')")  # Tab from the reply line reaches the state pill first
    strip = [tab(page) for _ in range(6)]
    assert strip == ["chat-send", "rev", "pill", "pill", "pill", "pill"]  # then send, setup, the three permissions and the advanced list
    assert page.eval("[...document.querySelectorAll('.block-ai .pill.chat-mode, .block-ai .pill.chat-advanced')].length + 3") == 7 and page.eval("document.activeElement.classList.contains('chat-advanced')")
    send(page, "LEAF-001", "Slow one")
    page.wait(f"{LEAF_BLOCK}.querySelector('.block-ai .chat-stop')")
    page.eval(f"{LEAF_BLOCK}.focus()")
    press(page, ".", "Period", 190, 2)
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.stopped')")  # Ctrl+. on the block stops its turn
    assert gated.interrupted


@pytest.mark.syngate("ASSASSIN-UI-STYLE-SOURCE", "buttons")
def test_every_control_is_a_button_with_a_focus_ring_operable_by_keyboard(server, chrome):
    narrated = NarratingConnector()
    narrated.more.set()
    narrated.release.set()
    page = open_chat(server, chrome, echo=narrated)
    send(page, "LEAF-001", "Hi")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    page.eval(f"{LEAF_BLOCK}.querySelector('.turn-head').click()")
    page.wait(f"{LEAF_BLOCK}.querySelector('.step-line')")
    controls = "#tree .status, #tree .chat-state, #tree .tools > *, #doc legend .status, #doc .block-ai > .pill:not(.chat-pill):not(.save-mark), #doc .chat-pill > *, #doc .msg-tools > *," \
               " #doc .turn-head:not(.bare), #doc .step-line, #sel-tools > *, #counts > *, #help, #console .bar button"
    assert page.eval(f"[...document.querySelectorAll('{controls}')].map((el) => el.tagName)").count("BUTTON") == page.eval(f"document.querySelectorAll('{controls}').length") >= 20
    assert page.eval("document.querySelectorAll('[role=button]:not(button), [role=switch]:not(button), [role=checkbox]:not(button)').length") == 0
    page.eval(f"{LEAF_BLOCK}.querySelector('.chat-input').focus()")
    tab(page)
    ring = "(() => { const s = getComputedStyle(document.activeElement); return [document.activeElement.className, s.outlineStyle, s.outlineColor]; })()"
    assert page.eval(ring) == ["pill chat-hide", "solid", css_color(page, "--accent")]  # reached by Tab: the focus ring
    assert tab(page, back=True) == "block-text" and page.eval("document.activeElement.classList.contains('chat-input')")
    assert tab(page, back=True) == "step-line"  # the unfolded steps are in the order too
    page.eval(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai .msg-fold').focus()")
    assert page.eval(f"[{FOCUS}, getComputedStyle(document.activeElement.parentElement).opacity]") == ["msg-fold", "1"]  # the marks of a message take the focus, and show with it
    press(page, " ", "Space", 32)
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai.dropped')")
    mode = f"{LEAF_BLOCK}.querySelector('.chat-mode')"
    before = page.eval(f"{mode}.getAttribute('aria-checked')")
    page.eval(f"{mode}.focus()")
    press(page, " ", "Space", 32)
    page.wait(f"{mode}.getAttribute('aria-checked') !== '{before}'")  # Space switches a permission
    page.eval(f"{LEAF_BLOCK}.querySelector('.chat-hide').focus()")
    press(page, "Enter", "Enter", 13)
    assert page.eval(f"[{LEAF_BLOCK}.classList.contains('chatting'), document.activeElement === {LEAF_BLOCK}]") == [False, True]  # Enter hides the chat, the block takes the focus back


@pytest.mark.syngate("ASSASSIN-UI-FILTER")
def test_the_filter_and_the_status_chips_narrow_both_panes_keeping_ancestors_and_unfolding_to_every_match(violated_page, server):
    page, (_, app) = violated_page, server
    page.eval("toggle('ROOT')")
    assert page.eval(PATHS % "#tree") == ["ROOT"]
    typed = "(() => { const f = document.getElementById('filter'); f.value = '%s'; f.dispatchEvent(new Event('input', { bubbles: true })); })()"
    page.eval(typed % "freeze")
    assert page.eval(PATHS % "#tree") == ["ROOT", "ROOT/LEAF-002"] and page.eval(PATHS % "#doc") == ["ROOT", "ROOT/LEAF-002"]  # a text match, its ancestor kept, the outline unfolded to it
    page.eval(typed % "leaf-001")
    assert page.eval(PATHS % "#tree") == ["ROOT", "ROOT/LEAF-001"]  # a UID match, whatever the case
    page.eval("move('LEAF-001', 'ROOT', 'ROOT', null)")
    assert page.eval(TOASTS) == ["toast info:clear the filters to move items"]
    page.eval(typed % "")
    assert page.eval(PATHS % "#tree") == ["ROOT"] and page.eval(PATHS % "#doc") == ["ROOT", "ROOT/LEAF-001", "ROOT/LEAF-002"]
    with open(app.run_coverage, "a") as coverage:
        coverage.write(json.dumps({"tags": ["LEAF-001"], "passed": True, "name": "", "log": ""}) + "\n")
    page.wait("document.querySelector('#counts .chip.st-test_passed')")
    chip = "document.querySelector('#counts .chip.st-test_passed')"
    assert page.eval(f"{chip}.textContent") == "1 passed"
    page.eval(f"{chip}.click()")
    assert page.eval(f"[{chip}.classList.contains('on'), getComputedStyle({chip}, '::after').content]") == [True, '" ×"']
    assert page.eval(PATHS % "#tree") == ["ROOT", "ROOT/LEAF-001"] and page.eval(PATHS % "#doc") == ["ROOT", "ROOT/LEAF-001"]  # the chosen status only, with its ancestor
    page.eval(f"{chip}.click()")
    assert page.eval(PATHS % "#doc") == ["ROOT", "ROOT/LEAF-001", "ROOT/LEAF-002"]


@pytest.mark.syngate("ASSASSIN-UI-LIVE")
def test_the_tree_is_re_read_after_a_change_on_disk_with_the_selection_editor_chat_and_draft_surviving(page, server, syngate_tree):
    _, app = server
    syngate_dir, make_item = syngate_tree
    enter_reply(page, "ROOT")
    edit_leaf(page, "It shall leaf, typed.")
    make_item(syngate_dir, "ROOT", "Root renamed\n", parents=())
    make_item(syngate_dir, "LEAF-002", "Second\n\nIt shall be second.\n", parents=("ROOT",), tests=None)
    page.wait("document.querySelector('#tree [data-uid=\"LEAF-002\"]') && document.querySelector('header h1').textContent === 'Root renamed'")  # picked up by the poll, not by a reload
    kept = "[state.selected, state.editing, document.querySelector('#doc .block.editing textarea').value, document.activeElement === document.querySelector('#doc .block.editing textarea')," \
           " document.querySelector('#doc .block[data-uid=\"ROOT\"]').classList.contains('chatting')]"
    assert page.eval(kept) == ["LEAF-001", "ROOT/LEAF-001", "It shall leaf, typed.", True, True]
    with open(app.run_coverage, "a") as coverage:
        coverage.write(json.dumps({"tags": ["LEAF-002"], "passed": False, "name": "", "log": ""}) + "\n")
    page.wait("document.querySelector('#tree [data-uid=\"LEAF-002\"] .status.red')")  # a coverage file too
    assert page.eval(kept) == ["LEAF-001", "ROOT/LEAF-001", "It shall leaf, typed.", True, True]


@pytest.mark.syngate("ASSASSIN-UI-CONFLICT")
def test_a_save_refused_for_a_disk_change_raises_the_conflict_bar_and_the_save_marks_read_the_state(page, server, syngate_tree):
    syngate_dir, make_item = syngate_tree
    marks = "[document.getElementById('save-state').className, document.getElementById('save-state').textContent, document.querySelector('#doc .block.editing .save-mark')?.textContent ?? null]"
    bar = "[...document.querySelectorAll('#conflicts .conflict')].map((el) => [el.textContent.split('keep')[0], [...el.querySelectorAll('button')].map((b) => b.textContent)])"
    edit_leaf(page, "It shall leaf, mine.")
    assert page.eval(marks) == ["unsaved", "● unsaved", "● unsaved"]
    make_item(syngate_dir, "LEAF-001", "It shall leaf, theirs.\n", parents=("ROOT",), tests=None)
    page.eval("flushAll()")
    assert page.eval(bar) == [["⚠ LEAF-001 description changed on disk while you were editing it", ["keep mine", "take theirs"]]]
    assert page.eval(marks) == ["unsaved", "⚠ conflict", "⚠ conflict"]
    page.eval("document.querySelector('#conflicts [data-take]').click()")
    page.wait("drafts.size === 0 && document.querySelector('#doc .block.editing textarea').value === 'It shall leaf, theirs.'")  # theirs: the draft dropped, the disk value shown
    assert page.eval(bar) == []
    edit_leaf(page, "It shall leaf, mine again.")
    make_item(syngate_dir, "LEAF-001", "It shall leaf, theirs again.\n", parents=("ROOT",), tests=None)
    page.eval("flushAll()")
    assert page.eval(f"{bar}.length") == 1
    page.eval("document.querySelector('#conflicts [data-keep]').click()")
    page.wait("drafts.size === 0 && document.getElementById('save-state').textContent.startsWith('✓ saved ')")
    assert tree_item(server, "LEAF-001")["description_raw"] == "It shall leaf, mine again.\n"  # mine: stored over the disk value
    page.eval("window.served = window.fetch; window.fetch = (url, opts = {}) => opts.method === 'POST' && String(url).startsWith('/api/item/')"
              " ? Promise.resolve(new Response('{\"error\": \"boom\"}', { status: 500, headers: { 'Content-Type': 'application/json' } })) : window.served(url, opts)")
    edit_leaf(page, "It shall leaf, blocked.")
    page.eval("flushAll()")
    assert page.eval(marks) == ["failed", "✗ not saved — click to retry", "✗ not saved — click to retry"] and page.eval(TOASTS) == ["toast :not saved: boom"]
    assert page.eval("document.querySelector('#doc .block.editing .save-mark').classList.contains('failed')")
    page.eval("window.fetch = window.served")
    page.eval("document.querySelector('#doc .block.editing .save-mark').click()")
    page.wait("drafts.size === 0")
    assert tree_item(server, "LEAF-001")["description_raw"] == "It shall leaf, blocked.\n"  # the click retries


@pytest.mark.syngate("ASSASSIN-UI-BINDINGS")
def test_the_binding_editor_switches_the_test_key_and_adds_or_removes_named_bindings_as_a_compare_and_swap(violated_page, server, syngate_tree):
    page, (base, app), (syngate_dir, _) = violated_page, server, syngate_tree
    icon = "document.querySelector('#doc .block[data-uid=\"%s\"] legend .status')"
    names = "[...document.querySelectorAll('#tests-pop .binding-row .name')].map((el) => el.textContent)"
    on_disk = lambda: syngatelib.parse_item((syngate_dir / "LEAF-001.yml").read_text()).get("test", "absent")
    settled = lambda expected: page.wait(f"JSON.stringify({names}) === {json.dumps(json.dumps(expected, separators=(',', ':')))}")
    page.eval(f"{icon % 'LEAF-001'}.click()")
    assert page.eval(f"[document.getElementById('f-isleaf').checked, {names}, getComputedStyle(document.getElementById('f-add-binding')).flexGrow]") == [True, ["(default)"], "1"]  # the name field takes the row's width
    page.eval("document.getElementById('f-isleaf').click()")
    page.wait("document.getElementById('f-isleaf') && !document.getElementById('f-isleaf').checked && !document.getElementById('f-add-binding')")
    assert on_disk() == "absent"  # the test key switched off: a branch-like item, no bindings to edit
    page.eval("document.getElementById('f-isleaf').click()")
    settled(["(default)"])
    assert on_disk() is None  # the default binding alone, unfrozen
    add = lambda name: page.eval(f"(() => {{ document.getElementById('f-add-binding').value = '{name}'; document.getElementById('add-binding-btn').click(); }})()")
    add("alpha")
    assert page.eval(TOASTS)[-1] == "toast :the default binding stands alone; name all bindings to have several"
    page.eval("document.querySelector('#tests-pop .unbind').click()")
    settled([])
    add("alpha")
    settled(["alpha"])
    add("Alpha!")
    assert page.eval(TOASTS)[-1] == "toast :binding names are lowercase letters, digits and underscores"
    add("beta")
    settled(["alpha", "beta"])
    assert list(on_disk()) == ["alpha", "beta"]
    with pytest.raises(urllib.error.HTTPError) as stale:
        call(base, app, "/api/item/LEAF-001", {"tests": ["gamma"], "base": {"tests": ["alpha"]}})
    assert stale.value.code == 409 and list(on_disk()) == ["alpha", "beta"]  # every change is a compare-and-swap of the list
    page.eval(f"{icon % 'LEAF-002'}.click()")
    page.wait("document.getElementById('tests-pop').dataset.uid === 'LEAF-002'")
    page.eval(ASK % "false")
    page.eval("document.querySelector('#tests-pop .unbind').click()")
    assert page.eval("window.asked") == ["Binding '(default)' was frozen by a review; removing it releases that. Remove?"]
    assert page.eval(names) == ["(default)"] and syngatelib.parse_item((syngate_dir / "LEAF-002.yml").read_text())["test"] == "a" * 64  # declined: the frozen binding stays


@pytest.mark.syngate("AI_CHAT-CONTROLS")
def test_every_message_carries_its_marks_on_the_border_lines_shown_under_the_pointer_and_the_statement_none(server, chrome):
    page = open_chat(server, chrome, echo=CallsConnector("Reply line one\n\nReply line two, a paragraph of its own."))
    send(page, "LEAF-001", "Question")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    place = f"[...{LEAF_BLOCK}.querySelectorAll('.chat-msg')].map((msg) => {{ const block = {LEAF_BLOCK}.getBoundingClientRect(), line = parseFloat(getComputedStyle(msg).lineHeight), part = msg.querySelector('.msg-part').getBoundingClientRect()," \
            " mid = (el) => {{ const r = el.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }}, [fold, child, sibling] = [...msg.querySelectorAll('.msg-tools button')].map(mid);" \
            " return [msg.classList[1], [...msg.querySelectorAll('.msg-tools button')].map((b) => b.className), Math.abs(fold[0] - block.left) < 2, Math.abs(child[0] - block.right) < 2, Math.abs(sibling[0] - block.right) < 2," \
            " Math.abs(fold[1] - (part.top + line / 2)) < 3, Math.abs(child[1] - fold[1]) < 1, sibling[1] >= Math.max(part.bottom - line / 2 - 3, child[1] + 20), [...msg.querySelectorAll('.msg-tools')].map((el) => [getComputedStyle(el).opacity, getComputedStyle(el).pointerEvents].join())]; })"
    marks = ["msg-fold", "msg-child", "msg-sibling"]
    assert page.eval(place) == [["user", marks, True, True, True, True, True, True, ["0,none", "0,none"]], ["ai", marks, True, True, True, True, True, True, ["0,none", "0,none"]]]  # fold on the left line, child and sibling on the right, level with the first and the last line, hidden without the pointer
    x, y = page.eval(f"(() => {{ const r = {LEAF_BLOCK}.querySelector('.chat-msg.ai').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})()")
    page.mouse("mouseMoved", x, y, buttons=0)
    page.wait(f"[...{LEAF_BLOCK}.querySelector('.chat-msg.ai').querySelectorAll('.msg-tools')].every((el) => getComputedStyle(el).opacity === '1')")
    assert page.eval(place)[0][-1] == ["0,none", "0,none"]  # the pointer reveals the marks of its row alone
    assert page.eval(f"{LEAF_BLOCK}.querySelectorAll('.block-body .msg-tools, .block-body .tools').length") == 0  # the statement, shown once as the content, carries none
    page.eval(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai .msg-fold').click()")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai.dropped')")
    assert page.eval(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai').getBoundingClientRect().height <= 2 * parseFloat(getComputedStyle({LEAF_BLOCK}.querySelector('.chat-msg.ai')).lineHeight)")  # the mark acts on the whole message: both paragraphs fold away
