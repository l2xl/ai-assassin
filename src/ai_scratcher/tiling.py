# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Compositor tiling of a new surf window where the browser cannot position its windows: the tiling method read from the desktop the
harness runs on, and under KDE Plasma on Wayland the KWin script, loaded over D-Bus, that sets the surf window and its session's
Assassin window side by side. The design is in BROWSER_EXTENSION.md; stdlib only, like the server that calls it."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading

METHODS = ("browser", "kwin", "none")
QDBUS = ("qdbus6", "qdbus")
SERVICE = "org.kde.KWin"
SCRIPTING = "/Scripting"
INTERFACE = "org.kde.kwin.Scripting"
NAME = "ai-assassin-websurf"
TITLE_CHARS = 300
# Seconds a D-Bus call may take before the tiling gives up: it runs off the turn, so this bounds a thread, never a websurf call.
DBUS_SECONDS = 10
# The KWin 6 script, run after the constants SURF -- the surf window's caption prefix -- and ASSASSIN -- the Assassin window's caption
# prefix, or null -- set in front of it: it waits for the surf window to be mapped and labelled, then tiles it once.
SCRIPT = r"""
function halves(area) {
  const wide = area.width >= area.height;
  const first = Math.floor((wide ? area.width : area.height) / 2);
  return wide
    ? [{ x: area.x, y: area.y, width: first, height: area.height }, { x: area.x + first, y: area.y, width: area.width - first, height: area.height }]
    : [{ x: area.x, y: area.y, width: area.width, height: first }, { x: area.x, y: area.y + first, width: area.width, height: area.height - first }];
}
const caption = (w) => String(w.caption || '');
const isSurf = (w) => Boolean(w.normalWindow) && caption(w).startsWith(SURF);
const isAssassin = (w) => ASSASSIN !== null && Boolean(w.normalWindow) && !isSurf(w) && caption(w).startsWith(ASSASSIN);
function place(w, rect) {
  if (w.fullScreen) w.fullScreen = false;
  w.setMaximize(false, false);
  w.frameGeometry = rect;
}
let done = false;
function consider(w) {
  if (done || !isSurf(w)) return false;
  done = true;
  workspace.windowAdded.disconnect(watch);
  const assassin = workspace.windowList().find(isAssassin);
  const [first, second] = halves(workspace.clientArea(KWin.MaximizeArea, assassin || w));
  if (assassin) place(assassin, first);
  place(w, second);
  return true;
}
function watch(w) {
  if (!consider(w)) w.captionChanged.connect(() => consider(w));
}
workspace.windowAdded.connect(watch);
workspace.windowList().forEach(watch);
"""


def qdbus(env=os.environ):
    """The qdbus command found on the PATH of `env` -- qdbus6, else qdbus -- or None."""
    return next(filter(None, (shutil.which(name, path=env.get("PATH")) for name in QDBUS)), None)


def _call(tool, *args, env=None, check=False):
    return subprocess.run([tool, SERVICE, *args], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=DBUS_SECONDS,
                          env=None if env is None else dict(env), check=check)


def method(env=os.environ, platform=sys.platform):
    """The tiling method of the desktop the harness runs on: `browser` where the browser positions its windows -- X11, Windows, macOS,
    any session telling no Wayland --, `kwin` under KDE Plasma on Wayland with KWin's scripting on the session bus, `none` on any other
    Wayland desktop."""
    if platform in ("win32", "cygwin", "darwin") or env.get("XDG_SESSION_TYPE") != "wayland":
        return "browser"
    tool = qdbus(env) if "KDE" in env.get("XDG_CURRENT_DESKTOP", "").split(":") else None
    try:
        if tool and _call(tool, SCRIPTING, env=env).returncode == 0:
            return "kwin"
    except (OSError, subprocess.SubprocessError):
        pass
    return "none"


def script(surf, assassin):
    """The KWin script tiling the window whose caption starts with `surf` against the one whose caption starts with `assassin`."""
    return f"const SURF = {json.dumps(surf)};\nconst ASSASSIN = {json.dumps(assassin)};\n{SCRIPT.lstrip()}"


def _titles(placed):
    """(surf, assassin) of the `tile` an `open` answer carries -- the surf window's label, the Assassin tab's title or None --, else
    ValueError."""
    surf, assassin = (placed.get("surf"), placed.get("assassin")) if isinstance(placed, dict) else (None, None)
    if not isinstance(surf, str) or not surf.strip() or len(surf) > TITLE_CHARS:
        raise ValueError("a tiling names the surf window's label")
    if assassin is not None and (not isinstance(assassin, str) or not assassin.strip() or len(assassin) > TITLE_CHARS):
        raise ValueError("a tiling names the Assassin tab's title or none")
    return surf, assassin


def tile(placed, env=os.environ):
    """Load and run over D-Bus the KWin script setting the surf window `placed` names beside the Assassin window, the session's
    previous script -- named by the port its label carries -- unloaded first; -> the script's id. Raises on any failure."""
    surf, assassin = _titles(placed)
    tool = qdbus(env)
    if tool is None:
        raise OSError("no qdbus6 or qdbus found")
    name = f"{NAME}-{''.join(filter(str.isdigit, surf)) or 'surf'}"
    _call(tool, SCRIPTING, f"{INTERFACE}.unloadScript", name)
    fd, path = tempfile.mkstemp(prefix=f"{name}-", suffix=".js")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(script(surf, assassin))
        ident = int(_call(tool, SCRIPTING, f"{INTERFACE}.loadScript", path, name, check=True).stdout.strip())
        if ident < 0:
            raise RuntimeError(f"KWin refused to load the script {name}")
        # KWin answers `run` once it has read the file, so it may go then
        _call(tool, f"{SCRIPTING}/Script{ident}", "org.kde.kwin.Script.run", check=True)
        return ident
    finally:
        os.unlink(path)


def tile_later(placed):
    """Tile what an `open` answer's `tile` names off the calling thread, a failure told on stderr alone; nothing without one."""
    if placed is None:
        return None

    def run():
        try:
            tile(placed)
        except Exception as err:  # a tiling that fails never fails the websurf call
            print(f"websurf tiling failed: {err}", file=sys.stderr)

    thread = threading.Thread(target=run, name="websurf-tiling", daemon=True)
    thread.start()
    return thread
