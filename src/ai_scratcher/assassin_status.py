# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""assassin-status (ORCHESTRATOR-SERVICES-DIAGNOSE): why a chat of the live AI Assassin server is stuck -- the server's process, the
blocking alert of the model services with every failing role, the locators tried and their failures, and every chat not idle with what
it is asked, its queued messages and its running or held turn; `--retry` checks the failed roles again, clearing the alert once every
one answers, the queued messages then sent."""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

SERVER_FILE = "assassin_server.json"


def find_record(start):
    """The server record of the project `start` lies in: the nearest ancestor holding `assassin_server.json`. -> (path, record) or (None, {})."""
    for folder in (Path(start).resolve(), *Path(start).resolve().parents):
        path = folder / SERVER_FILE
        if path.is_file():
            try:
                return path, json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return path, {}
    return None, {}


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def call(record, path, payload=None, timeout=120):
    """The JSON answer of the server the record names to a GET of `path`, a POST with `payload`."""
    request = urllib.request.Request(f"http://127.0.0.1:{record['port']}{path}", method="GET" if payload is None else "POST",
                                     data=None if payload is None else json.dumps(payload).encode(),
                                     headers={"X-Assassin-Token": record["token"], "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def report(state, out=sys.stdout):
    """The diagnosis as lines for a person: the alert and its roles, then each chat not idle."""
    alert = state.get("alert")
    print(f"model services: {'BLOCKING ALERT — ' + alert if alert else 'every role answers'}", file=out)
    for role, tried in (state.get("failures") or {}).items():
        for attempt in tried:
            locator = attempt.get("locator") or {}
            where = f"{locator.get('connection')}/{locator.get('model')}" if locator else "(no locator)"
            print(f"  ✗ {role} → {where}: {attempt.get('error')}", file=out)
    for role, locator in (state.get("active") or {}).items():
        print(f"  ✓ {role} → {locator.get('connection')}/{locator.get('model')}", file=out)
    chats = state.get("chats") or {}
    blocked = [uid for uid, chat in chats.items() if chat.get("state") == "blocked"]
    print(f"chats not idle: {len(chats)}" + (f" ({len(blocked)} blocked{', by the services alert' if alert else ''})" if blocked else ""), file=out)
    for uid, chat in chats.items():
        if chat.get("services") and not chat.get("queue") and not chat.get("turn"):
            continue  # an idle chat under the alert says nothing the alert line did not
        line = f"  {uid}: {chat.get('state')}"
        if chat.get("turn"):
            line += f", turn {chat['turn']}" + (" held" if chat.get("held") is not None else "")
        if chat.get("asked") and not chat.get("services"):
            line += f" — asked: {chat['asked']}"
        print(line, file=out)
        for text in chat.get("queue") or ():
            print(f"      queued: {text[:160]}{'…' if len(text) > 160 else ''}", file=out)
    quiet = sum(1 for chat in chats.values() if chat.get("services") and not chat.get("queue") and not chat.get("turn"))
    if quiet:
        print(f"  … and {quiet} idle chats standing under the alert", file=out)
    if alert:
        print("hint: `assassin-status --retry` checks the failed roles again; the queued messages go once every role answers", file=out)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="assassin-status", description=__doc__)
    parser.add_argument("--root", default=".", help="the managed project, or any folder inside it (default: the working directory)")
    parser.add_argument("--retry", action="store_true", help="check the failed model services again before reporting")
    parser.add_argument("--json", action="store_true", help="print the diagnosis as JSON")
    args = parser.parse_args(argv)
    path, record = find_record(args.root)
    if path is None:
        print(f"assassin-status: no {SERVER_FILE} at or above {Path(args.root).resolve()}: no server was started for this project", file=sys.stderr)
        return 2
    if not all(record.get(key) for key in ("pid", "port", "token")):
        print(f"assassin-status: {path} is not a server record", file=sys.stderr)
        return 2
    if not alive(record["pid"]):
        print(f"assassin-status: the server of {path} (pid {record['pid']}) is gone; start `assassin` again", file=sys.stderr)
        return 1
    try:
        if args.retry:
            retried = call(record, "/api/services/retry", {})
            print(f"retry: {'still blocked — ' + retried['alert'] if retried.get('alert') else 'the alert cleared'}", file=sys.stderr)
        state = call(record, "/api/services")
    except urllib.error.HTTPError as err:
        hint = " (a server started before this tool lacks /api/services: restart it)" if err.code == 404 else ""
        print(f"assassin-status: the server answered {err.code}{hint}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as err:
        print(f"assassin-status: the server on port {record['port']} does not answer: {err}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"server": {"pid": record["pid"], "port": record["port"]}, **state}, indent=1, ensure_ascii=False))
    else:
        print(f"server: pid {record['pid']}, port {record['port']} ({path})")
        report(state)
    return 3 if state.get("alert") else 0


if __name__ == "__main__":
    sys.exit(main())
