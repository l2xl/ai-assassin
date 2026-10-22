# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The harness's compositor tiling of a new surf window: the tiling method read from the desktop, the KWin script loaded over D-Bus
through a stand-in `qdbus6` recording its calls, the script itself run by node against a fake KWin `workspace`, and the tiling started
by an `open` answer of the attached browser -- [BROWSER-EXTENSION-TILING]."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import assassin_ui
from ai_scratcher import tiling
from test_assassin_ui import app, call, server  # noqa: F401 -- the server fixtures of the page tests
from test_assassin_ui_api import Scripted, calls, turn
from test_websurf import NEWS, attached, frames, settle, surf, tab, text

LABEL = "WebSurf 8713 · "
TITLE = "AI-ASSASSIN · AI Assassin"
FAKE_QDBUS = """#!{python}
import json, shutil, sys
from pathlib import Path
args = sys.argv[1:]
folder = Path({folder!r})
with open(folder / "calls.jsonl", "a") as log:
    log.write(json.dumps(args) + "\\n")
if len(args) > 2 and args[2].endswith(".loadScript"):
    shutil.copy(args[3], folder / f"loaded-{{len(list(folder.glob('loaded-*')))}}.js")
    print({ident!r})
sys.exit({code})
"""
WORKSPACE = """
import vm from 'node:vm';
const cfg = JSON.parse(process.argv[1]);
const asked = [];
const signal = () => {
  const slots = new Set();
  return { slots, connect: (slot) => slots.add(slot), disconnect: (slot) => { if (!slots.delete(slot)) throw new Error('not connected'); },
           fire: (...args) => [...slots].forEach((slot) => slot(...args)) };
};
const windows = cfg.windows.map((w) => ({
  normalWindow: true, fullScreen: false, maximized: true, frameGeometry: null, ...w, captionChanged: signal(),
  setMaximize(vertically, horizontally) { this.maximized = vertically || horizontally; },
}));
const mapped = new Set(windows.filter((w) => !w.later));
const workspace = {
  windowList: () => windows.filter((w) => mapped.has(w)),
  windowAdded: signal(),
  clientArea: (kind, w) => { asked.push([kind, w.caption]); return { ...(cfg.areas[w.screen] || cfg.areas.default) }; },
};
vm.runInNewContext(cfg.script, { workspace, KWin: { MaximizeArea: 2 } });
// what comes after the script ran: a window mapped, a caption changed
for (const step of cfg.later || []) {
  const w = windows[step.window];
  if (step.map) { mapped.add(w); workspace.windowAdded.fire(w); }
  if (step.caption) { w.caption = step.caption; w.captionChanged.fire(); }
}
console.log(JSON.stringify({ windows: windows.map(({ caption, frameGeometry, maximized }) => ({ caption, frameGeometry, maximized })),
                             asked, waiting: workspace.windowAdded.slots.size }));
"""


def fake_qdbus(folder, name="qdbus6", code=0, ident="7"):
    """A stand-in qdbus named `name` in `folder`, recording its arguments to `folder/calls.jsonl` and keeping each script file it is
    given to load; it exits with `code` and answers a loadScript with `ident`. -> `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    tool = folder / name
    tool.write_text(FAKE_QDBUS.format(python=sys.executable, folder=str(folder), ident=ident, code=code))
    tool.chmod(0o755)
    return folder


def recorded(folder):
    log = folder / "calls.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def tiled(script, windows, areas, later=()):
    """The windows -- caption, frame geometry, maximized -- after the KWin `script` ran against a fake workspace holding `windows`, the
    work areas it was asked for and the windowAdded slots still waiting."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    cfg = {"script": script, "windows": windows, "areas": areas, "later": list(later)}
    out = subprocess.run([node, "--input-type=module", "-e", WORKSPACE, json.dumps(cfg)], capture_output=True, text=True, check=True, timeout=30)
    return json.loads(out.stdout)


def rect(x, y, width, height):
    return {"x": x, "y": y, "width": width, "height": height}


SURF_CAPTION = f"{LABEL}Example — Mozilla Firefox"
ASSASSIN_CAPTION = f"{TITLE} — Mozilla Firefox"


@pytest.mark.syngate("BROWSER-EXTENSION-TILING", "method")
def test_the_tiling_method_follows_the_desktop_and_goes_out_with_an_open_but_where_it_is_browser(tmp_path, monkeypatch, server):
    bus, off_bus, legacy = fake_qdbus(tmp_path / "bus"), fake_qdbus(tmp_path / "off", code=1), fake_qdbus(tmp_path / "legacy", name="qdbus")
    kde = {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "KDE", "PATH": str(bus)}
    assert tiling.method(kde, "linux") == "kwin"
    assert recorded(bus) == [["org.kde.KWin", "/Scripting"]]  # KWin's scripting asked for on the session bus
    assert tiling.method({**kde, "PATH": str(legacy)}, "linux") == "kwin"  # qdbus where there is no qdbus6
    assert tiling.method({**kde, "XDG_SESSION_TYPE": "x11"}, "linux") == "browser"
    assert tiling.method(kde, "win32") == tiling.method(kde, "darwin") == "browser"
    assert tiling.method({**kde, "XDG_CURRENT_DESKTOP": "GNOME"}, "linux") == "none"
    assert tiling.method({**kde, "PATH": str(off_bus)}, "linux") == "none"  # no KWin on the bus
    assert tiling.method({**kde, "PATH": str(tmp_path / "nothing")}, "linux") == "none"  # no qdbus found

    with monkeypatch.context() as desktop:
        desktop.setenv("XDG_SESSION_TYPE", "wayland")
        desktop.setenv("XDG_CURRENT_DESKTOP", "KDE")
        desktop.setenv("PATH", f"{bus}{os.pathsep}{os.environ['PATH']}")
        assert assassin_ui.AssassinApp(root=tmp_path).tiling == "kwin"  # read once, as the server starts

    base, app = server
    assert app.tiling == "browser"  # the suite's desktop pinned
    browser = attached(base, app)
    for method in ("browser", "kwin", "none"):
        app.tiling = method
        app.connectors = {"echo": Scripted(calls(surf("open", url=NEWS), surf("status")), text("Opened."))}
        assert turn(base, app, "LEAF-001", "Open it.", modes=["edit"])["reply"] == "Opened."
    assert frames(browser) == [{"type": "surf", "action": "open", "url": NEWS}, {"type": "surf", "action": "status"},
                               {"type": "surf", "action": "open", "url": NEWS, "tiling": "kwin"}, {"type": "surf", "action": "status"},
                               {"type": "surf", "action": "open", "url": NEWS, "tiling": "none"}, {"type": "surf", "action": "status"}]
    browser.close()


@pytest.mark.syngate("BROWSER-EXTENSION-TILING", "script")
def test_a_kwin_script_finding_both_windows_by_their_titles_is_loaded_and_run_over_dbus_the_sessions_previous_one_unloaded_first(tmp_path, monkeypatch):
    bus = fake_qdbus(tmp_path / "bus")
    monkeypatch.setenv("PATH", f"{bus}{os.pathsep}{os.environ['PATH']}")
    assert tiling.tile({"surf": LABEL, "assassin": TITLE}) == 7
    unload, load, run = recorded(bus)
    name = "ai-assassin-websurf-8713"
    assert unload == ["org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.unloadScript", name]
    assert load[:3] == ["org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.loadScript"] and load[4:] == [name] and load[3].endswith(".js")
    assert run == ["org.kde.KWin", "/Scripting/Script7", "org.kde.kwin.Script.run"]
    assert not Path(load[3]).exists()  # read by KWin as it ran, then gone
    script = (bus / "loaded-0.js").read_text()
    assert script == tiling.script(LABEL, TITLE)
    assert f"const SURF = {json.dumps(LABEL)};" in script and f"const ASSASSIN = {json.dumps(TITLE)};" in script
    assert "workspace.clientArea(KWin.MaximizeArea" in script and "workspace.windowAdded" in script

    tiling.tile({"surf": LABEL, "assassin": None})
    assert recorded(bus)[3] == unload and f"const ASSASSIN = null;" in (bus / "loaded-1.js").read_text()  # the previous one unloaded first
    for wrong in (None, {}, {"surf": ""}, {"surf": LABEL, "assassin": 3}, {"surf": 5, "assassin": TITLE}):
        with pytest.raises(ValueError):
            tiling.tile(wrong)
    assert len(recorded(bus)) == 6  # nothing reached D-Bus


@pytest.mark.syngate("BROWSER-EXTENSION-TILING", "halves")
def test_the_kwin_script_gives_the_assassin_window_and_the_surf_window_the_two_halves_of_the_assassin_screens_work_area_along_its_longer_side():
    script = tiling.script(LABEL, TITLE)
    assistant, surfed = {"caption": ASSASSIN_CAPTION, "screen": "wide"}, {"caption": SURF_CAPTION, "screen": "tall"}
    decoy, shell = {**assistant, "normalWindow": False}, {"caption": "Shell — Konsole", "screen": "wide"}
    areas = {"wide": rect(0, 30, 1920, 1050), "tall": rect(1920, 0, 1080, 1921), "default": rect(0, 0, 10, 10)}
    landscape = tiled(script, [decoy, assistant, surfed, shell], areas)
    placed_decoy, placed_assistant, placed_surf, placed_shell = landscape["windows"]
    assert placed_assistant == {"caption": ASSASSIN_CAPTION, "frameGeometry": rect(0, 30, 960, 1050), "maximized": False}
    assert placed_surf == {"caption": SURF_CAPTION, "frameGeometry": rect(960, 30, 960, 1050), "maximized": False}
    assert placed_decoy["frameGeometry"] is placed_shell["frameGeometry"] is None and placed_shell["maximized"]  # no other window touched
    assert landscape["asked"] == [[2, ASSASSIN_CAPTION]] and landscape["waiting"] == 0  # the Assassin window's screen, nothing left waiting

    portrait = tiled(script, [{**assistant, "screen": "tall"}, surfed], areas)
    assert [w["frameGeometry"] for w in portrait["windows"]] == [rect(1920, 0, 1080, 960), rect(1920, 960, 1080, 961)]

    # a surf window mapped after the script ran, its label set once it is
    late = tiled(script, [assistant, {"caption": "Mozilla Firefox", "screen": "wide", "later": True}], areas,
                 later=[{"window": 1, "map": True}, {"window": 1, "caption": SURF_CAPTION}])
    assert [w["frameGeometry"] for w in late["windows"]] == [rect(0, 30, 960, 1050), rect(960, 30, 960, 1050)] and late["waiting"] == 0
    waiting = tiled(script, [assistant], areas)
    assert waiting["windows"][0]["frameGeometry"] is None and waiting["waiting"] == 1  # nothing tiled before the surf window comes

    alone = tiled(tiling.script(LABEL, None), [assistant, surfed], areas)  # no Assassin window found: the surf window alone, on its own screen
    assert [w["frameGeometry"] for w in alone["windows"]] == [None, rect(1920, 960, 1080, 961)] and alone["asked"] == [[2, SURF_CAPTION]]
    elsewhere = tiled(tiling.script(LABEL, "LEAF-001 · AI Assassin"), [assistant, surfed], areas)
    assert [w["frameGeometry"] for w in elsewhere["windows"]] == [None, rect(1920, 960, 1080, 961)]


def tiling_answer(frame):
    """The answer of a Firefox under KWin: a new surf window labelled for the harness, the Assassin tab's title for its window."""
    answer = tab(frame)
    if frame["action"] == "open":
        answer.update(placement="tiled", tile={"surf": LABEL, "assassin": TITLE})
    return answer


@pytest.mark.syngate("BROWSER-EXTENSION-TILING", "call")
def test_an_open_answer_under_kwin_tiles_off_the_turn_and_a_tiling_that_fails_never_fails_the_call(tmp_path, monkeypatch, capsys, server):
    base, app = server
    app.tiling = "kwin"
    bus = fake_qdbus(tmp_path / "bus")
    monkeypatch.setenv("PATH", f"{bus}{os.pathsep}{os.environ['PATH']}")
    browser = attached(base, app, tiling_answer)
    app.connectors = {"echo": (scripted := Scripted(calls(surf("open", url=NEWS)), text("Opened.")))}
    assert turn(base, app, "LEAF-001", "Open it.", modes=["edit"])["reply"] == "Opened."
    assert "\n- websurf open https://example.com/news: placement tiled\n" in scripted.heard[1]["text"]
    assert settle(lambda: len(recorded(bus)) == 3) and (bus / "loaded-0.js").read_text() == tiling.script(LABEL, TITLE)

    app.tiling = "browser"  # the browser tiles its own windows: nothing goes to KWin
    app.connectors = {"echo": Scripted(calls(surf("open", url=NEWS)), text("Opened."))}
    assert turn(base, app, "LEAF-001", "Open it.", modes=["edit"])["reply"] == "Opened."

    app.tiling = "kwin"
    broken = fake_qdbus(tmp_path / "broken", code=1)
    monkeypatch.setenv("PATH", f"{broken}{os.pathsep}{os.environ['PATH']}")
    app.connectors = {"echo": (scripted := Scripted(calls(surf("open", url=NEWS)), text("Opened anyway.")))}
    assert turn(base, app, "LEAF-001", "Open it.", modes=["edit"])["reply"] == "Opened anyway."
    assert "\n- websurf open https://example.com/news: placement tiled\n" in scripted.heard[1]["text"]
    told = []
    assert settle(lambda: told.append(capsys.readouterr().err) or "tiling" in "".join(told))  # on stderr at most
    assert len(recorded(bus)) == 3 and len(recorded(broken)) == 2  # its unload and its failed load
    browser.close()
