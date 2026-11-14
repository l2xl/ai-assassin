# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Local models of AI Assassin: the model presets -- each a folder holding one docker compose project of llama.cpp servers, for one
kind of card -- served, checked, listed and removed by the `assassin-models` command, which also prints the settings routing to them."""

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from . import syngatelib

PRESETS_DIR = "model_presets"
COMPOSE_FILE = "compose.yaml"
SHIPPED = Path(__file__).parent / PRESETS_DIR
EXTENSION = "x-assassin"
LABEL = "ai-assassin."
SERVES = ("embedding", "reranking", "chat")
ORCHESTRATOR_ROLES = ("embed", "rerank")
WAIT = 900  # seconds a preset may take to become healthy: a model's first start downloads it
CHAT_EFFORTS = ("low", "medium", "high")  # what the connection of a chat model offers, each with the reasoning budget in tokens that follows
REASONING_BUDGETS = {"low": 1024, "medium": 2048, "high": 4096}


class setup_error(Exception):
    """What keeps a preset from being served, worded for the user."""


def sh(argv):
    """(exit status, output) of one command, the output being its stdout, or its stderr when it failed; a missing command fails with 127."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True)
    except FileNotFoundError:
        return 127, f"{argv[0]}: command not found"
    return done.returncode, (done.stdout if done.returncode == 0 else done.stderr or done.stdout).strip()


def fetch(url, body=None, timeout=5):
    """The parsed JSON answer of `url` -- a POST of `body` when one is given -- or None while the server does not answer with one."""
    request = urllib.request.Request(url, json.dumps(body).encode() if body is not None else None, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            return json.load(answer)
    except (urllib.error.URLError, OSError, ValueError):
        return None


def presets(root=None, shipped=SHIPPED):
    """The presets at hand as {name: folder}: every folder holding a compose file among those shipped with the package and those of
    the project's `model_presets/`, a project's own standing over a shipped one of its name."""
    found = {}
    for base in (Path(shipped), *([Path(root) / PRESETS_DIR] if root else [])):
        for folder in sorted(base.iterdir()) if base.is_dir() else ():
            if (folder / COMPOSE_FILE).is_file():
                found[folder.name] = folder
    return found


def read_preset(folder):
    """One preset read from the compose file of `folder`: its name -- the folder's -- file, compose project, the docker host it names
    if any, its description, and its models by service -- what each serves, the model id it answers under, its loopback port, the card
    memory it declares and whether it is handed a card."""
    folder = Path(folder)
    try:
        compose = yaml.safe_load((folder / COMPOSE_FILE).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as error:
        raise setup_error(f"preset {folder.name}: {folder / COMPOSE_FILE} is unreadable: {error}") from None
    own = compose.get(EXTENSION) or {}
    models, ports = {}, {}
    for role, service in (compose.get("services") or {}).items():
        labels = service.get("labels") or {}
        if isinstance(labels, list):
            labels = dict(label.split("=", 1) for label in labels if "=" in label)
        serve, published = labels.get(LABEL + "serve"), [str(port) for port in service.get("ports") or ()]
        if serve not in SERVES:
            raise setup_error(f"preset {folder.name}: service {role} carries no label {LABEL}serve naming one of {', '.join(SERVES)}")
        if len(published) != 1 or not published[0].startswith("127.0.0.1:"):
            raise setup_error(f"preset {folder.name}: service {role} publishes {', '.join(published) or 'no port'} — exactly one port on 127.0.0.1 is expected")
        port = int(published[0].split(":")[1])
        if port in ports:
            raise setup_error(f"preset {folder.name}: services {ports[port]} and {role} share the port {port}")
        ports[port] = role
        devices = (((service.get("deploy") or {}).get("resources") or {}).get("reservations") or {}).get("devices") or ()
        models[role] = {"serve": serve, "name": str(labels.get(LABEL + "model") or role), "port": port,
                        "memory_mb": int(labels.get(LABEL + "memory-mb") or 0), "gpu": bool(devices)}
    return {"name": folder.name, "file": folder / COMPOSE_FILE, "project": compose.get("name") or f"assassin-{folder.name}",
            "host": own.get("host"), "description": own.get("description") or "", "models": models}


def chosen_preset(found, name):
    """The preset `name` of those found, read; a setup error naming the presets at hand for an unknown one."""
    if name not in found:
        raise setup_error(f"unknown preset '{name}' — the presets are {', '.join(found) or 'none'}")
    return read_preset(found[name])


def compose_argv(preset, *words):
    """The `docker compose` command line of `preset` -- on the docker host the preset names, as its own project -- followed by `words`."""
    return ["docker", *(["--host", preset["host"]] if preset["host"] else []), "compose", "-f", str(preset["file"]), "-p", preset["project"], *words]


def address(preset, model):
    """The base URL the server of `model` answers at: loopback, a preset on another docker host being reached through a tunnel to it."""
    return f"http://127.0.0.1:{model['port']}"


def card_memory(sh=sh):
    """The memory of the first card in MiB as `nvidia-smi` reports it, None while there is no card to ask."""
    code, out = sh(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"])
    try:
        return int(out.splitlines()[0]) if code == 0 else None
    except (ValueError, IndexError):
        return None


def check_memory(preset, sh=sh):
    """Refuses a preset whose models on the card declare more memory together than this machine's card has; a preset served on another
    docker host is not checked here."""
    wanted = sum(model["memory_mb"] for model in preset["models"].values() if model["gpu"])
    if not wanted or preset["host"]:
        return
    total = card_memory(sh)
    if total is None:
        raise setup_error(f"preset {preset['name']} needs a card and no NVIDIA card answers nvidia-smi")
    if wanted > total:
        raise setup_error(f"preset {preset['name']} declares {wanted} MiB on a card of {total} MiB")


def probe(preset, fetch=fetch):
    """Asks every model of the preset for one real answer of the kind it serves -- an embedding, a rerank, a completion -- and returns
    the services that gave none."""
    asks = {"embedding": ("/v1/embeddings", lambda name: {"model": name, "input": ["probe"]}, "data"),
            "reranking": ("/v1/rerank", lambda name: {"model": name, "query": "probe", "documents": ["probe"]}, "results"),
            "chat": ("/v1/chat/completions", lambda name: {"model": name, "messages": [{"role": "user", "content": "probe"}], "max_tokens": 1}, "choices")}
    failed = []
    for role, model in preset["models"].items():
        path, body, key = asks[model["serve"]]
        if not (fetch(address(preset, model) + path, body(model["name"]), timeout=180) or {}).get(key):
            failed.append(role)
    return failed


def up(preset, sh=sh, fetch=fetch, wait=WAIT, say=print):
    """Serves the preset: checks its memory against the card, brings its compose project up -- compose leaving what is unchanged and
    replacing what changed -- waits until every service is healthy, then takes one real answer from every model, which also warms it.
    A service that does not come up in time fails the command with the tail of the project's log, one that gives no answer by name."""
    if not preset["models"]:
        raise setup_error(f"preset {preset['name']} defines no model yet")
    code, out = sh(["docker", *(["--host", preset["host"]] if preset["host"] else []), "version", "--format", "{{.Server.Version}}"])
    if code != 0:
        raise setup_error(f"docker does not answer: {out}")
    check_memory(preset, sh)
    code, out = sh(compose_argv(preset, "up", "-d", "--wait", "--wait-timeout", str(wait)))
    if code != 0:
        _, log = sh(compose_argv(preset, "logs", "--tail", "15"))
        raise setup_error(f"preset {preset['name']} did not come up: {out}\n{log}")
    failed = probe(preset, fetch)
    if failed:
        raise setup_error(f"preset {preset['name']} is up but gave no answer from: {', '.join(failed)}")
    for role, model in preset["models"].items():
        say(f"{preset['name']}/{role}: {model['serve']} {model['name']} answers on 127.0.0.1:{model['port']}")


def down(preset, sh=sh, say=print):
    """Removes the containers of the preset's project; its volume, and so every downloaded model, stays."""
    code, out = sh(compose_argv(preset, "down"))
    if code != 0:
        raise setup_error(f"preset {preset['name']} was not removed: {out}")
    say(f"{preset['name']}: removed, its downloaded models kept")


def status(preset, sh=sh):
    """One line per model of the preset: its service, the state and health docker reports for its container -- `absent` without one --
    its port and what it serves; a preset without models says so in one line, and docker failing is a setup error, not an absence."""
    if not preset["models"]:
        return [f"{preset['name']}: no model defined yet"]
    code, out = sh(compose_argv(preset, "ps", "--all", "--format", "json"))
    if code != 0:
        raise setup_error(f"docker does not answer for preset {preset['name']}: {out}")
    held = {}
    for line in out.splitlines():
        try:
            rows = json.loads(line)
        except ValueError:
            continue
        for row in rows if isinstance(rows, list) else [rows]:
            held[row.get("Service")] = " ".join(word for word in (row.get("State"), row.get("Health")) if word)
    return ["  ".join((f"{preset['name']}/{role}", held.get(role) or "absent", f"127.0.0.1:{model['port']}", f"{model['serve']} {model['name']}"))
            for role, model in preset["models"].items()]


def routes(preset):
    """The settings that reach the preset: one connection per model, `<preset>-<service>` -- that of a chat model listing the efforts and
    reasoning budgets above, that of one serving no chat saying what it `serves`, which keeps it out of the chats' model menu -- and the
    orchestrator's route of every service named as an orchestrator's role -- `embed`, `rerank` -- to its connection and model."""
    name = lambda role: f"{preset['name']}-{role}"
    connections = {name(role): {"label": f"{preset['name']} {role}", "base_url": address(preset, model) + "/v1", "models": [model["name"]],
                                **({"efforts": list(CHAT_EFFORTS), "reasoning_budgets": dict(REASONING_BUDGETS)} if model["serve"] == "chat"
                                   else {"serves": model["serve"]})}
                   for role, model in preset["models"].items()}
    orchestrator = {role: {"connection": name(role), "model": model["name"]} for role, model in preset["models"].items() if role in ORCHESTRATOR_ROLES}
    return {"connections": connections, **({"orchestrator": orchestrator} if orchestrator else {})}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="assassin-models", description=__doc__)
    parser.add_argument("--root", help="managed project root whose model_presets/ are offered beside the shipped presets (default: as the syngate command finds it)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list the presets")
    serve = sub.add_parser("up", help="serve a preset, replacing what changed")
    serve.add_argument("preset")
    serve.add_argument("--wait", type=int, default=WAIT, help="seconds to wait for the models to become healthy")
    for command, text in (("down", "remove a preset's containers, keeping its downloaded models"), ("probe", "ask every model of a preset for one real answer"),
                          ("routes", "print the settings that route to a preset")):
        sub.add_parser(command, help=text).add_argument("preset")
    sub.add_parser("status", help="list the models of a preset, or of every preset").add_argument("preset", nargs="?")
    args = parser.parse_args(argv)
    try:
        try:
            root = syngatelib.find_root(args.root)
        except FileNotFoundError:
            root = None
        found = presets(root)
        if args.command == "list":
            for name in found:
                try:
                    preset = read_preset(found[name])
                except setup_error as error:
                    print(f"{name}  unreadable: {' '.join(str(error).split())}")
                    continue
                print(f"{name}  {len(preset['models'])} model(s)  {preset['description']}  [{found[name]}]")
        elif args.command == "status":
            print("\n".join(line for name in ([args.preset] if args.preset else found) for line in status(chosen_preset(found, name))))
        elif args.command == "up":
            up(chosen_preset(found, args.preset), wait=args.wait)
        elif args.command == "down":
            down(chosen_preset(found, args.preset))
        elif args.command == "probe":
            preset = chosen_preset(found, args.preset)
            failed = probe(preset)
            print("\n".join(f"{preset['name']}/{role}: {'no answer' if role in failed else 'answers'}" for role in preset["models"]))
            return 1 if failed else 0
        else:
            print(json.dumps(routes(chosen_preset(found, args.preset)), indent=2))
    except setup_error as error:
        print(f"assassin-models: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
