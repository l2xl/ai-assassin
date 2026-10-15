# Open Trader
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Local syngate editor UI: loopback HTTP server over syngatelib.

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
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

import syngate_ui
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
    return syngate_ui.SyngateUIApp(root=tmp_path, syngate_dir=syngate_dir, cli_prefix=STUB)


@pytest.fixture
def server(app):
    httpd = syngate_ui.make_server(app, port=0)
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

        argv = [binary, "--headless=new", "--remote-debugging-pipe", f"--user-data-dir={profile}", "--no-first-run", "--disable-gpu"]
        if os.geteuid() == 0:
            argv.append("--no-sandbox")
        self.process = subprocess.Popen(argv, preexec_fn=wire, pass_fds=(3, 4), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(to_chrome[0])
        os.close(from_chrome[1])
        self.sink, self.source, self.buffer, self.serial = to_chrome[1], from_chrome[0], b"", 0

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
            if reply.get("id") == self.serial:
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
        request.add_header("X-Syngate-Token", app.token if token is True else token)
    with urllib.request.urlopen(request) as response:
        body = response.read()
        return response.status, body if raw else json.loads(body)


@pytest.mark.syngate("SYNGATE_UI-010")
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
    conn.request("GET", "/api/tree", headers={"Host": "evil.example", "X-Syngate-Token": app.token})
    assert conn.getresponse().status == 403
    conn.close()
    status, _ = call(base, app, f"/api/tree?token={app.token}", token=False)
    assert status == 200  # EventSource cannot set headers; the query token is equivalent


@pytest.mark.syngate("SYNGATE_UI-039")
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


@pytest.mark.syngate("SYNGATE_UI-032", "guard")
def test_save_rejects_unknown_parent_and_cycle(server, syngate_tree):
    base, app = server
    syngate_dir, _ = syngate_tree
    before = (syngate_dir / "ROOT.yml").read_text()
    for parents in (["NOPE"], ["LEAF-001"]):  # unknown parent; child-of-own-child cycle
        with pytest.raises(urllib.error.HTTPError) as denied:
            call(base, app, "/api/item/ROOT", {"description": "Root branch\n", "parents": parents, "order": 0, "tests": None})
        assert denied.value.code == 400
    assert (syngate_dir / "ROOT.yml").read_text() == before


@pytest.mark.syngate("SYNGATE_UI-032", "cas")
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


@pytest.mark.syngate("SYNGATE_UI-033", "reorder")
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


@pytest.mark.syngate("SYNGATE_UI-033", "reparent")
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


@pytest.mark.syngate("SYNGATE_UI-034")
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


@pytest.mark.syngate("SYNGATE_UI-035", "stream")
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


@pytest.mark.syngate("SYNGATE_UI-035", "single_flight")
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


@pytest.mark.syngate("SYNGATE_UI-035", "branch")
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


@pytest.mark.syngate("SYNGATE_UI-036", "read")
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


@pytest.mark.syngate("SYNGATE_UI-036", "save")
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


@pytest.mark.syngate("SYNGATE_UI-020", "csp")
def test_the_page_runs_only_its_own_nonced_script(server):
    base, app = server
    request = urllib.request.Request(base + "/", headers={"X-Syngate-Token": app.token})
    with urllib.request.urlopen(request) as response:
        policy, page = response.headers["Content-Security-Policy"], response.read().decode()
    nonce = policy.split("script-src 'nonce-")[1].split("'")[0]
    assert "default-src 'none'" in policy and f'<script nonce="{nonce}">' in page and "<script>" not in page


PATHS = "[...document.querySelectorAll('%s [data-path]')].map((el) => el.dataset.path)"


@pytest.mark.syngate("SYNGATE_UI-020", "render")
def test_the_page_renders_every_tree_item_from_the_served_model(page):
    assert page.eval(PATHS % "#tree") == ["ROOT", "ROOT/LEAF-001"]
    assert page.eval(PATHS % "#doc") == ["ROOT", "ROOT/LEAF-001"]


@pytest.mark.syngate("SYNGATE_UI-TREE-015")
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


@pytest.mark.syngate("SYNGATE_UI-041")
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


ROW_PARTS = "[...document.querySelector('#tree [data-uid=\"LEAF-002\"]').querySelectorAll('.twist, .status, .node-uid, .dupmark, .title, .tools button:not([hidden])')]" \
            ".map((el) => el.dataset.act || el.className.split(' ')[0])"
MENU_ENTRIES = "[document.getElementById('status-menu').matches(':popover-open'), [...document.querySelectorAll('#status-menu [data-row-act]')].map((el) => el.dataset.rowAct)]"


def open_row_menu(page, uid):
    page.eval(f"document.querySelector('#tree [data-uid=\"{uid}\"] [data-act=\"menu\"]').click()")


@pytest.mark.syngate("SYNGATE-UI-TREE-010")
def test_a_tree_row_shows_collapse_mark_label_title_tests_button_and_menu_button_only(violated_page):
    page = violated_page
    assert page.eval(ROW_PARTS) == ["twist", "status", "node-uid", "title", "tests", "menu"]
    assert page.eval("Boolean(document.querySelector('#tree .row-problems'))") is False


@pytest.mark.syngate("SYNGATE_UI-TREE-020")
def test_the_row_menu_button_opens_a_drop_down_of_the_item_actions_fit_for_the_row(violated_page):
    page = violated_page
    open_row_menu(page, "LEAF-002")
    assert page.eval(MENU_ENTRIES) == [True, ["add-parent", "add", "remove"]]  # structure edits only behind the explicit menu
    open_row_menu(page, "ROOT")
    assert page.eval(MENU_ENTRIES) == [True, ["add"]]  # the root has no parent to add and an item with children cannot be removed


@pytest.mark.syngate("SYNGATE_UI-TREE-022")
def test_add_child_opens_the_new_uid_row_under_the_item(violated_page):
    page = violated_page
    open_row_menu(page, "ROOT")
    page.eval("document.querySelector('#status-menu [data-row-act=\"add\"]').click()")
    assert page.eval("Boolean(document.querySelector('#tree .row.adding .new-uid'))")


@pytest.mark.syngate("SYNGATE_UI-TREE-021")
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


SCROLL_SPY = "window.scrolled = []; Element.prototype.scrollIntoView = function () { window.scrolled.push(this.className.split(' ')[0]); }"


@pytest.mark.syngate("SYNGATE_UI-TREE-030")
def test_a_single_click_selects_the_row_without_activating_or_scrolling_to_its_panel(violated_page):
    page = violated_page
    page.eval(SCROLL_SPY)
    page.eval("document.querySelector('#tree [data-uid=\"LEAF-001\"] .cell-title').click()")
    selection = "[state.selected, document.querySelector('#tree .row.selected').dataset.uid, [...document.querySelectorAll('#doc .block.selected')].map((b) => b.dataset.uid), window.scrolled.includes('block')]"
    assert page.eval(selection) == ["LEAF-001", "LEAF-001", [], False]


@pytest.mark.syngate("SYNGATE_UI-TREE-035")
def test_a_double_click_activates_the_panel_and_scrolls_to_it_only_when_out_of_view(violated_page):
    page = violated_page
    page.eval(SCROLL_SPY)
    dblclick = "document.querySelector('#tree [data-uid=\"%s\"] .cell-title').dispatchEvent(new MouseEvent('dblclick', { bubbles: true }))"
    page.eval(dblclick % "LEAF-001")
    assert page.eval("[state.selected, document.querySelector('#doc .block.selected').dataset.uid, window.scrolled.includes('block')]") == ["LEAF-001", "LEAF-001", False]  # the panel is in view: activated, not scrolled
    page.eval("document.getElementById('doc-pane').style.height = '40px'; window.scrolled = []")
    page.eval(dblclick % "LEAF-002")
    assert page.eval("[state.selected, window.scrolled.includes('block')]") == ["LEAF-002", True]  # the panel is out of view: scrolled to


@pytest.mark.syngate("SYNGATE_UI-CONTENT-010")
def test_a_block_carries_the_status_label_without_title_or_menu_on_its_top_border(violated_page):
    page = violated_page
    label = "(() => { const block = document.querySelector('#doc .block[data-uid=\"LEAF-002\"]'), tag = block.querySelector('legend .tag'), at = tag.getBoundingClientRect(), box = block.getBoundingClientRect();" \
            " return [[...tag.children].filter((e) => !e.classList.contains('status')).map((e) => e.textContent).join(''), tag.querySelectorAll('button').length, Math.abs(at.top + at.height / 2 - box.top) < at.height]; })()"
    assert page.eval(label) == ["LEAF-002", 0, True]


@pytest.mark.syngate("SYNGATE_UI-CONTENT-020")
def test_the_status_button_sits_at_the_bottom_right_corner_and_its_popup_lists_tests_and_problems_by_status(violated_page):
    page = violated_page
    foot = "(() => { const block = document.querySelector('#doc .block[data-uid=\"LEAF-002\"]'), box = block.getBoundingClientRect()," \
           " pill = block.querySelector('.block-status .pill').getBoundingClientRect(); return [box.right - pill.right < 16, Math.abs(pill.top + pill.height / 2 - box.bottom) < pill.height]; })()"
    assert page.eval(foot) == [True, True]
    tip = "[...document.querySelectorAll('#doc .block[data-uid=\"LEAF-002\"] .block-status .tip > div')].map((el) => [el.className, el.textContent])"
    lines = page.eval(tip)
    assert lines[0] == ["tip-unknown", "unknown"] and lines[1][0] == "tip-unknown" and "no tagged routine yet" in lines[1][1]
    assert lines[-1][0] == "tip-review_violated" and "no test routine tagged [LEAF-002] found" in lines[-1][1]
    assert page.eval("getComputedStyle(document.querySelector('#doc .block[data-uid=\"LEAF-002\"] .tip')).display") == "none"  # shown on hover only


class EchoConnector:
    models, efforts, modes = ("model-a", "model-b"), ("low", "high"), {"edit": True, "internet": True, "workflows": False}

    def __init__(self, label="Echo"):
        self.label = label

    def settings(self):
        return {"label": self.label, "models": [{"id": model, "name": model.removeprefix("model-")} for model in self.models], "efforts": list(self.efforts),
                "modes": [{"id": mode, "label": mode.capitalize(), "hint": mode + " hint", "default": default} for mode, default in self.modes.items()]}

    def dispatch(self, context, text, model=None, effort=None, modes=(), session=None, on_step=None, stopped=None):
        return {"kind": "text", "text": f"{context}|{text}|{model}|{effort}|{','.join(modes)}|{session}"}, "session-1"


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


@pytest.mark.syngate("SYNGATE_UI-056")
def test_a_single_click_on_a_block_opens_its_editor_but_a_click_ending_a_text_selection_does_not(server, chrome):
    page = item_page(server, chrome)
    page.eval(f"{LEAF_BLOCK}.querySelector('.block-body .md').click()")
    editing = f"[state.editing, {LEAF_BLOCK}.classList.contains('editing'), document.activeElement === {LEAF_BLOCK}.querySelector('.block-body textarea')]"
    assert page.eval(editing) == ["ROOT/LEAF-001", True, True]
    page.eval(f"{LEAF_BLOCK}.querySelector('.block-body textarea').dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Escape', bubbles: true }}))")
    assert page.eval(editing) == [None, False, False]
    page.eval(f"(() => {{ const text = {LEAF_BLOCK}.querySelector('.block-body .md'), range = document.createRange(); range.selectNodeContents(text);"
              " getSelection().removeAllRanges(); getSelection().addRange(range); text.click(); })()")
    assert page.eval(editing) == [None, False, False]


@pytest.mark.syngate("AI_CHAT-070")
def test_the_reply_field_waits_under_every_item_without_hint_or_button_until_entered(server, chrome):
    page = item_page(server, chrome)
    rest = "[...document.querySelectorAll('#doc .block')].map((el) => [Boolean(el.querySelector('.block-body ~ .block-chat > textarea.chat-input')), el.querySelector('.chat-input').placeholder, el.querySelector('.block-ai').children.length])"
    assert page.eval(rest) == [[True, "", 0], [True, "", 0]]
    page.eval(f"{LEAF_BLOCK}.querySelector('.chat-input').focus()")
    assert page.eval(rest) == [[True, "", 0], [True, "Ask about LEAF-001 … (Ctrl+Enter sends)", 5]]  # send with setup, three modes, close
    page.eval(f"{LEAF_BLOCK}.querySelector('.chat-close').click()")
    assert page.eval(rest) == [[True, "", 0], [True, "", 0]]
    edit_leaf(page, "It shall leaf, edited.")
    assert page.eval(rest)[1] == [True, "Ask about LEAF-001 … (Ctrl+Enter sends)", 5]


@pytest.mark.syngate("AI_CHAT-022")
def test_editing_the_description_offers_the_ai_controls_and_sends_the_saved_statement(server, chrome):
    page = item_page(server, chrome)
    edit_leaf(page, "It shall leaf better.")
    controls = f"[...{LEAF_BLOCK}.querySelectorAll('.block-ai .chat-send, .block-ai .chat-setup, .block-ai .chat-mode')].length"
    assert page.eval(controls) == 5  # send, setup and the three mode switches, before anything is sent
    pick(page, "model", "model-b")
    page.eval(f"{LEAF_BLOCK}.querySelector('.block-ai .chat-send').click()")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    assert tree_item(server, "LEAF-001")["description_raw"].strip() == "It shall leaf better."
    assert page.eval(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai').textContent").endswith("It shall leaf better.|It shall leaf better.|model-b|low|edit,internet|None")
    assert page.eval(f"{LEAF_BLOCK}.querySelectorAll('.chat-msg.user').length") == 0  # the first message is the content itself
    edit_leaf(page, "It shall leaf by keyboard.")
    page.eval("document.querySelector('#doc .block.editing textarea').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, bubbles: true }))")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')?.textContent.includes('|It shall leaf by keyboard.|')")
    assert tree_item(server, "LEAF-001")["description_raw"].strip() == "It shall leaf by keyboard."
    assert page.eval(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai').textContent").endswith("|None")  # Ctrl+Enter sends as the button does: a new chat


@pytest.mark.syngate("AI_CHAT-025")
def test_user_messages_look_like_the_description_and_ai_replies_sit_right_highlighted(server, chrome):
    page = open_chat(server, chrome)
    send(page, "LEAF-001", "Styled?")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    look = f"(() => {{ const body = {LEAF_BLOCK}.querySelector('.block-body .block-text'), user = {LEAF_BLOCK}.querySelector('.chat-msg.user'), ai = {LEAF_BLOCK}.querySelector('.chat-msg.ai');" \
           " const css = (el) => getComputedStyle(el); return [css(user).backgroundColor === css(body).backgroundColor, css(user).alignSelf, css(ai).alignSelf, css(ai).backgroundColor !== css(body).backgroundColor]; })()"
    assert page.eval(look) == [True, "flex-start", "flex-end", True]


@pytest.mark.syngate("AI-CHAT-CONTROLS-010")
def test_every_reply_carries_fold_and_keep_tools_at_its_left_edge(server, chrome):
    page = open_chat(server, chrome)
    send(page, "LEAF-001", "First")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    tools = f"[...{LEAF_BLOCK}.querySelectorAll('.chat-msg')].map((el) => [Boolean(el.querySelector('.msg-fold')), Boolean(el.querySelector('.msg-keep')), el.querySelector('.msg-keep')?.getAttribute('aria-checked')])"
    assert page.eval(tools) == [[True, True, "true"], [True, True, "true"]]
    place = f"(() => {{ const msg = {LEAF_BLOCK}.querySelector('.chat-msg.ai'), tools = msg.querySelector('.msg-tools').getBoundingClientRect(), box = msg.getBoundingClientRect();" \
            " return [tools.left - box.left < 4, Math.abs(tools.top - box.top) < parseFloat(getComputedStyle(msg).lineHeight)]; })()"
    assert page.eval(place) == [True, True]
    page.eval(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai .msg-fold').click()")
    assert page.eval(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai .msg-fold').getAttribute('aria-expanded')") == "false"
    assert page.eval(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai').getBoundingClientRect().height <= 2 * parseFloat(getComputedStyle({LEAF_BLOCK}.querySelector('.chat-msg.ai')).lineHeight)")
    page.eval(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai .msg-keep').click()")
    gray = css_color(page, "--dim")
    assert page.eval(f"(() => {{ const msg = {LEAF_BLOCK}.querySelector('.chat-msg.ai'); return [msg.classList.contains('dropped'), getComputedStyle(msg).color]; }})()") == [True, gray]


@pytest.mark.syngate("AI-CHAT-CONTROLS-020")
def test_a_message_turns_into_a_child_or_next_sibling_item_while_the_chat_stays(server, chrome):
    page = open_chat(server, chrome, echo=CallsConnector("Leaf sentence\n\nIt shall be extracted."))
    send(page, "LEAF-001", "Say something")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    page.eval(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai .msg-child').click()")
    page.wait("document.querySelector('#tree [data-path^=\"ROOT/LEAF-001/\"]')")
    page.eval(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai .msg-sibling').click()")
    page.wait("document.querySelectorAll('#tree [data-path]').length === 4")
    paths = page.eval(PATHS % "#tree")
    child, sibling = paths[2].rsplit("/", 1)[1], paths[3].rsplit("/", 1)[1]
    assert paths[2].startswith("ROOT/LEAF-001/") and paths[3] == f"ROOT/{sibling}" and sibling != "LEAF-001"
    for uid in (child, sibling):
        extracted = tree_item(server, uid)
        assert (extracted["title"], extracted["description_raw"]) == ("Leaf sentence", "Leaf sentence\n\nIt shall be extracted.\n")
    assert page.eval(f"[...{LEAF_BLOCK}.querySelectorAll('.chat-msg')].map((el) => el.className)") == ["chat-msg user", "chat-msg ai"]


@pytest.mark.syngate("AI_CHAT-050")
def test_an_at_reference_brings_the_named_item_into_the_turn(server, chrome):
    page = open_chat(server, chrome)
    send(page, "LEAF-001", "Compare with @ROOT please")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    reply = page.eval(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai').textContent")
    assert reply.endswith("|Compare with @ROOT please|model-a|low|edit,internet|None")  # the text stays as typed
    assert "Root branch" in reply.split("|Compare with")[0].split("It shall leaf.")[-1]  # the referenced statement follows the seed context


def pick(page, attribute, value):
    page.eval("document.querySelector('.chat-setup').click()")
    assert page.eval("document.getElementById('status-menu').matches(':popover-open')")
    page.eval(f"document.querySelector('#status-menu [data-chat-{attribute}=\"{value}\"]').click()")


@pytest.mark.syngate("AI_CHAT-010")
def test_the_connector_menu_selects_the_setup(server, chrome):
    page = open_chat(server, chrome, echo=EchoConnector(), other=EchoConnector("Other"), claude=synthetic.claude_code_connector())
    pick(page, "model", "model-b")
    assert page.eval(SETUP) == "Echo · b · low ▾"
    pick(page, "connector", "other")
    assert page.eval(SETUP) == "Other · a · low ▾"  # a new connector starts from its own defaults
    menu = "(() => { document.querySelector('.chat-setup').click(); const menu = document.getElementById('status-menu'), entries = (key) => [...menu.querySelectorAll(`[data-chat-${key}]`)];" \
           " const offered = [entries('model').map((b) => b.textContent.slice(2)), entries('effort').map((b) => b.textContent.slice(2))]; menu.hidePopover(); return offered; })()"
    rich, bare = (next(model for model, efforts in synthetic.CLAUDE_MODEL_EFFORTS.items() if bool(efforts) == has) for has in (True, False))
    names = [model.removeprefix("claude-") for model in synthetic.CLAUDE_MODELS]
    pick(page, "connector", "claude")
    pick(page, "model", bare)
    assert page.eval(menu) == [names, []] and page.eval(SETUP) == f"Claude Code · {bare.removeprefix('claude-')} ▾"  # no effort levels, no effort
    page.wait("state.chats.get('LEAF-001').effort === null")
    pick(page, "model", rich)
    assert page.eval(menu) == [names, list(synthetic.CLAUDE_MODEL_EFFORTS[rich])] and page.eval(SETUP) == f"Claude Code · {rich.removeprefix('claude-')} · medium ▾"


def css_color(page, var):
    return page.eval(f"(() => {{ const probe = document.createElement('span'); probe.style.color = 'var({var})'; document.body.append(probe);"
                     " const color = getComputedStyle(probe).color; probe.remove(); return color; })()")


@pytest.mark.syngate("AI_CHAT-011")
def test_the_permission_switches_show_their_labels_defaults_and_state_colors(server, chrome):
    page = open_chat(server, chrome)
    modes = "[...document.querySelectorAll('.block-ai .chat-mode')].map((el) => [el.textContent, el.getAttribute('aria-checked')])"
    assert page.eval(modes) == [["Edit", "true"], ["Internet", "true"], ["Workflows", "false"]]
    look = "[...document.querySelectorAll('.block-ai .chat-mode')].map((el) => [el.className, getComputedStyle(el).color, getComputedStyle(el.querySelector('.ball')).backgroundColor])"
    green, gray = css_color(page, "--green"), css_color(page, "--gray")
    assert [entry[1:] for entry in page.eval(look)] == [[green, green], [green, green], [gray, gray]]
    assert all(entry[0].startswith("pill chat-mode st-") for entry in page.eval(look))  # the status label's own pill and tint classes
    page.eval("document.querySelector('.chat-mode[data-chat-mode=\"edit\"]').click()")
    page.eval("document.querySelector('.chat-mode[data-chat-mode=\"workflows\"]').click()")
    assert page.eval(modes) == [["Edit", "false"], ["Internet", "true"], ["Workflows", "true"]]
    send(page, "LEAF-001", "Go.")
    page.wait("document.querySelector('.chat-msg.ai')")
    assert page.eval("document.querySelector('.chat-msg.ai').textContent").endswith("|Go.|model-a|low|internet,workflows|None")


@pytest.mark.syngate("AI_CHAT-030")
def test_the_green_check_mark_hides_the_chat_and_becomes_the_drop_down_reopening_it(server, chrome):
    base, app = server
    page = open_chat(server, chrome)
    send(page, "LEAF-001", "Kept")
    page.wait(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    closer = f"{LEAF_BLOCK}.querySelector('.block-ai .chat-close')"
    assert page.eval(f"[{closer}.textContent, getComputedStyle({closer}).color]") == ["✓", css_color(page, "--green")]
    page.eval(f"{closer}.click()")
    hidden = f"[{LEAF_BLOCK}.querySelectorAll('.chat-msg').length, {LEAF_BLOCK}.querySelector('.chat-input').placeholder, Boolean({LEAF_BLOCK}.querySelector('.block-ai .chat-close')), {LEAF_BLOCK}.querySelector('.block-ai .chat-reopen')?.textContent]"
    assert page.eval(hidden) == [0, "", False, "▾"]  # the reply field stays, at rest
    page.eval(f"{LEAF_BLOCK}.querySelector('.block-ai .chat-reopen').click()")
    assert page.eval(f"[...{LEAF_BLOCK}.querySelectorAll('.chat-msg')].map((el) => el.className)") == ["chat-msg user", "chat-msg ai"]
    page.eval(f"{closer}.click()")
    enter_reply(page, "LEAF-001")
    users = f"[...{LEAF_BLOCK}.querySelectorAll('.chat-msg.user')].map((el) => el.textContent)"
    assert page.eval(users) == ["Kept"]  # the item has one chat: the reply field shows it again
    edit_leaf(page, "It shall leaf anew.")
    page.eval(f"{LEAF_BLOCK}.querySelector('.block-ai .chat-send').click()")
    page.wait(f"{LEAF_BLOCK}.querySelectorAll('.chat-msg:not(.note)').length === 1 && {LEAF_BLOCK}.querySelector('.chat-msg.ai')")
    assert page.eval(users) == []  # the old chat is erased, the statement being the new chat's first message
    assert page.eval(f"{LEAF_BLOCK}.querySelector('.chat-msg.ai').textContent").endswith("|It shall leaf anew.|model-a|low|edit,internet|None")  # a new session, not the old one
    assert [m["role"] for m in call(base, app, "/api/chats")[1]["chats"]["LEAF-001"]["log"]] == ["ai"]


@pytest.mark.syngate("AI_CHAT")
def test_the_chat_window_opens_under_the_item_and_sends_through_the_chosen_setup(server, chrome):
    page = open_chat(server, chrome)
    assert page.eval(PATHS % "#doc") == ["ROOT", "ROOT/LEAF-001"]  # no separate element: the item's own block expands
    assert page.eval("Boolean(document.querySelector('.block[data-uid=\"LEAF-001\"] .block-chat .chat-input'))")
    assert page.eval(SETUP) == "Echo · a · low ▾"
    pick(page, "model", "model-b")
    pick(page, "effort", "high")
    assert page.eval(SETUP) == "Echo · b · high ▾"
    send(page, "LEAF-001", "What is missing?")
    page.wait("document.querySelector('.chat-msg.ai')")
    user, ai = page.eval("[...document.querySelectorAll('.chat-msg')].map((el) => el.textContent.trim())")
    assert user == "What is missing?"
    assert ai.startswith("Tool calls") and ai.endswith("Root branch It shall leaf.|What is missing?|model-b|high|edit,internet|None")  # the default prompt heads the seed
    send(page, "LEAF-001", "And next?")
    page.wait("document.querySelectorAll('.chat-msg.ai').length === 2")
    assert page.eval("document.querySelectorAll('.chat-msg.ai')[1].textContent").endswith("|And next?|model-b|high|edit,internet|session-1")


def send(page, uid, text):
    page.eval(f"(() => {{ const box = document.querySelector('.block[data-uid=\"{uid}\"]'); box.querySelector('.chat-input').value = '{text}'; box.querySelector('.chat-send').click(); }})()")


CHATTING = "[...document.querySelectorAll('#doc .block.chatting')].map((el) => [el.dataset.uid, Boolean(el.querySelector('.block-chat .chat-input').placeholder), Boolean(el.querySelector('.block-ai .chat-close'))])"


@pytest.mark.syngate("AI_CHAT-001")
def test_several_chat_windows_are_open_at_once_each_under_its_own_item(server, chrome):
    page = open_chat(server, chrome)
    enter_reply(page, "ROOT")
    assert page.eval(CHATTING) == [["ROOT", True, True], ["LEAF-001", True, True]]
    send(page, "ROOT", "Root?")
    page.wait("document.querySelector('.block[data-uid=\"ROOT\"] .chat-msg.ai')")
    assert page.eval("document.querySelector('.block[data-uid=\"ROOT\"] .chat-msg.ai').textContent").endswith("|Root?|model-a|low|edit,internet|None")
    assert page.eval("document.querySelectorAll('.block[data-uid=\"LEAF-001\"] .chat-msg').length") == 0
    page.eval("document.querySelector('.block[data-uid=\"ROOT\"] .chat-close').click()")
    assert page.eval(CHATTING) == [["LEAF-001", True, True]]


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


@pytest.mark.syngate("AI_CHAT-MULTI")
def test_a_chat_keeps_its_history_while_closed_and_reopens_with_it_on_its_item(server, chrome):
    page = open_chat(server, chrome)
    send(page, "LEAF-001", "First")
    page.wait("document.querySelector('.chat-msg.ai')")
    page.eval("document.querySelector('.block-ai .chat-close').click()")
    assert page.eval("document.querySelectorAll('.chat-msg').length") == 0
    page.eval("document.querySelector('#doc .block[data-uid=\"LEAF-001\"] .chat-reopen').click()")
    kinds = "[...document.querySelectorAll('.block[data-uid=\"LEAF-001\"] .chat-msg')].map((el) => el.className)"
    assert page.eval(kinds) == ["chat-msg user", "chat-msg ai"]
    send(page, "LEAF-001", "Second")
    page.wait("document.querySelectorAll('.chat-msg.ai').length === 2")
    assert page.eval("document.querySelectorAll('.chat-msg.ai')[1].textContent").endswith("|Second|model-a|low|edit,internet|session-1")  # the session goes on
    reload(page)
    page.wait("document.querySelector('.block[data-uid=\"LEAF-001\"] .chat-msg.ai')")
    assert page.eval(kinds) == ["chat-msg user", "chat-msg ai", "chat-msg user", "chat-msg ai"]
    assert page.eval(CHATTING) == [["LEAF-001", True, True]]


class ReleasedConnector(EchoConnector):
    """Answers each message only once the test releases it, so exchanges overlap in the order the test dictates."""

    def __init__(self):
        super().__init__()
        self.gates = {}

    def release(self, text):
        self.gates.setdefault(text, threading.Event()).set()

    def dispatch(self, context, text, model=None, effort=None, modes=(), session=None, on_step=None, stopped=None):
        assert self.gates.setdefault(text, threading.Event()).wait(10), f"{text} was never released"
        return f"reply to {text} in {session}", f"session-{text}"


@pytest.mark.syngate("AI_CHAT-MULTI-020")
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
    assert page.eval(f"[{block % second}.classList.contains('chatting'), {block % second}.querySelector('.block-ai .chat-reopen')?.textContent]") == [False, "▾"]
    page.eval(f"{block % second}.querySelector('.chat-input').click()")
    assert page.eval(BLOCK_LOG % second) == page.eval(BLOCK_LOG % first) and page.eval(BLOCK_LOG % first)[0] == "user:Hello"
    page.eval(f"(() => {{ const box = {block % second}; box.querySelector('.chat-input').value = 'Again'; box.querySelector('.chat-send').click(); }})()")
    page.wait(f"{block % second}.querySelectorAll('.chat-msg.ai').length === 2")
    assert page.eval(BLOCK_LOG % first) == page.eval(BLOCK_LOG % second) and page.eval(BLOCK_LOG % first)[3].endswith("|Again|model-a|low|edit,internet|session-1")
    other = Page(chrome, f"{base}/?token={app.token}")
    other.wait(f"{block % first} && {block % first}.querySelector('.block-ai .chat-reopen')")
    other.eval(f"{block % first}.querySelector('.block-ai .chat-reopen').click()")
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


@pytest.mark.syngate("SYNGATE_UI-051")
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
    assert page.eval("document.querySelectorAll('#doc .block-foot .pill, #doc .sub-foot .pill').length") >= 7  # status, send, three modes, close, file name
    assert len(page.eval(looks % "#doc .block-foot .pill, #doc .sub-foot .pill")) == 1  # one pill shape, whatever the pill is for
    assert page.eval("document.querySelectorAll('#tree .tools button, #doc .msg-tools button, #doc .file-view > .tools button').length") >= 7
    assert len(page.eval(looks % "#tree .tools button, #doc .msg-tools button, #doc .file-view > .tools button")) == 1  # one icon-button shape


@pytest.mark.syngate("SYNGATE_UI-052")
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


@pytest.mark.syngate("SYNGATE_UI-053")
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


@pytest.mark.syngate("SYNGATE_UI-054")
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


@pytest.mark.syngate("SYNGATE_UI-038")
def test_the_splitter_resizes_the_outline_and_double_click_resets_it(page):
    width = "Math.round(document.getElementById('tree-pane').getBoundingClientRect().width)"
    default = page.eval(width)
    x, y = page.eval("(() => { const r = document.getElementById('splitter').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()")
    target = x - 150
    page.mouse("mousePressed", x, y)
    page.mouse("mouseMoved", target, y)
    page.mouse("mouseReleased", target, y)
    assert page.eval(width) == round(target) != default
    assert page.eval("sessionStorage.getItem('syngate-ui-tree-width')") == str(round(target))
    page.mouse("mousePressed", target + 2, y, clicks=2)
    page.mouse("mouseReleased", target + 2, y, clicks=2)
    assert page.eval(width) == default and page.eval("sessionStorage.getItem('syngate-ui-tree-width')") is None


class CallsConnector(EchoConnector):
    """Answers with one fixed reply, whatever the question."""

    def __init__(self, reply):
        super().__init__()
        self.reply = reply

    def dispatch(self, context, text, model=None, effort=None, modes=(), session=None, on_step=None, stopped=None):
        return self.reply, "session-2"


def _chat(server, reply, uid="ROOT"):
    base, app = server
    app.connectors = {"echo": CallsConnector(reply)}
    return call(base, app, "/api/chat", {"uid": uid, "connector": "echo", "model": "model-a", "effort": "low", "text": "Go."})


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
    with pytest.raises(urllib.error.HTTPError) as refused:
        _chat(server, "```syngate\n" + json.dumps([{"tool": "add", "uid": "NEW-003", "description": "D"}, {"tool": "remove", "uid": "@"}]) + "\n```")
    body = json.loads(refused.value.read())
    assert refused.value.code == 400 and body["error"].startswith("- added NEW-003 under ROOT\nremove ROOT refused: ROOT still has children")
    assert sorted(syngatelib.load_tree(syngate_dir)[0]) == ["LEAF-001", "NEW-001", "NEW-003", "ROOT"]


@pytest.mark.syngate("SYNGATE_UI-044")
def test_a_feature_switched_off_has_no_affordances_on_the_page(server, chrome, syngate_tree):
    base, app = server
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root branch\n", parents=(), features=())
    make_item(syngate_dir, "LEAF-001", "It shall leaf.\n", parents=("ROOT",), header="First leaf")
    page = Page(chrome, f"{base}/?token={app.token}")
    page.wait("document.querySelector('#tree [data-uid=\"LEAF-001\"]')")
    gone = "[Boolean(document.querySelector('#tree .status:not([hidden])')), Boolean(document.querySelector('#tree [data-act=\"tests\"]')), document.querySelectorAll('#tree .status .eyes').length]"
    assert page.eval(gone) == [False, False, 0]
    pill = "document.querySelector('#doc .block[data-uid=\"LEAF-001\"] .block-status .pill')"
    entries = "[...document.querySelectorAll('#status-menu [data-run]')].map((el) => el.dataset.run + ':' + el.textContent)"
    assert page.eval(f"{pill}.textContent.trim()") == "▶ run"  # the tree awaits no tests, but a run stays offered
    page.eval(f"{pill}.click()")
    assert page.eval(entries) == ["test:▶ Run test"]
    page.eval("document.getElementById('status-menu').hidePopover()")
    make_item(syngate_dir, "ROOT", "Root branch\n", parents=(), features=("review",))
    page.wait(f"{pill}.textContent.trim() === '○ not reviewed'")  # picked up by the fingerprint poll
    assert page.eval("[...document.querySelectorAll('#tree [data-uid=\"LEAF-001\"] .status, #tree [data-act=\"tests\"]')].map((el) => [el.className, el.hidden])") == [["status gray not_reviewed", False]]
    page.eval(f"{pill}.click()")
    assert page.eval(entries) == ["test:▶ Run test", "review:✓ Mark reviewed"]


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
        return {"kind": "text", "text": f"late reply to {text}"}, "session-late"

    def interrupt(self, ident):
        self.interrupted = True
        self.release.set()


class SteppingConnector(GatedConnector):
    """Announces a tool step, then its result as the same step announced again, before the gated answer."""

    def dispatch(self, context, text, on_step=None, **kwargs):
        step = {"kind": "tool", "name": "Read", "input": {"file_path": text}, "result": None, "seconds": None, "at": 0.5}
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
        on_step({"kind": "reasoning", "text": f"Thinking about {text}", "at": 0.1})
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


@pytest.mark.syngate("AI-CHAT-CONTROLS-030")
def test_while_a_turn_runs_the_close_mark_is_a_stop_button_that_stops_the_turn(server, chrome):
    _, app = server
    gated = NarratingConnector({"kind": "calls", "calls": [{"tool": "query", "uid": "@"}]})
    gated.more.set()
    page = open_chat(server, chrome, echo=gated)
    pills = f"[Boolean({LEAF}.querySelector('.block-ai .chat-close')), Boolean({LEAF}.querySelector('.block-ai .chat-stop')), Boolean({LEAF}.querySelector('.chat-pill.busy'))]"
    assert page.eval(pills) == [True, False, False]
    send(page, "LEAF-001", "Stuck one")
    page.wait(f"{LEAF}.querySelector('.block-ai .chat-stop')")
    assert page.eval(pills) == [False, True, True]
    turn = app.chats["LEAF-001"].turn
    page.eval(f"{LEAF}.querySelector('.block-ai .chat-stop').click()")
    page.wait(f"{LEAF}.querySelector('.chat-msg.error')")
    assert turn.stopped and gated.interrupted and turn.outcome["status"] == 409
    stopped = page.eval(f"{LEAF}.querySelector('.chat-msg.error').textContent").strip()
    assert stopped.startswith("- LEAF-001: {") and stopped.endswith("\nturn stopped")
    assert page.eval(pills) == [True, False, False]
    assert page.eval(f"{LEAF}.querySelector('.chat-msg.error + .turn-activity .turn-head').textContent").startswith("2 tool calls · 2 subagents · 1 file changed · ")
