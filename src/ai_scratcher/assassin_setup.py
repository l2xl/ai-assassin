# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""First setup (ORCHESTRATOR-SETUP): the `assassin-setup` command writing the model services a project starts with -- the embedding and
rerank models of the card at hand, the routes of the off-context agents -- into the server settings, which it never overwrites."""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from . import api_connection, local_models, services, syngatelib

SETTINGS_FILE = "assassin_settings.json"
SECTION = "orchestrator"
CLAUDE_ROUTE = {"connection": "claude_code", "model": "haiku"}
CLAUDE_CLI = "claude"
NO_AGENT_ROUTE = "the claude CLI is not installed and no connection of the settings offers a chat model"


def read_settings(file):
    """The server settings of `file`: {} while it is missing; one that is no JSON object is a setup error, never overwritten."""
    try:
        data = json.loads(Path(file).read_text(encoding="utf-8")) if Path(file).exists() else {}
    except (OSError, ValueError) as error:
        raise local_models.setup_error(f"{file} is unreadable: {error}") from None
    if not isinstance(data, dict):
        raise local_models.setup_error(f"{file} is not a JSON object — fix it by hand, setup does not overwrite it")
    return data


def write_settings(file, data):
    """The settings written to `file` as the server writes them: a draft beside it, then replacing it whole."""
    draft = Path(file).with_suffix(".json.tmp")
    draft.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(draft, file)


def entries(value, here):
    """The dotted paths a value added at `here` is reported by: a container of entries -- a dict of dicts -- by those of its entries."""
    if isinstance(value, dict) and value and all(isinstance(entry, dict) for entry in value.values()):
        return [path for key, entry in value.items() for path in entries(entry, f"{here}.{key}")]
    return [here]


def fill(held, wanted, path=""):
    """(`held` with every key of `wanted` it lacks added -- a dict held beside a dict wanted filled the same way, any other value held kept --
    and the dotted paths added)."""
    merged, added = dict(held), []
    for key, value in wanted.items():
        here = f"{path}.{key}" if path else key
        if key not in held:
            merged[key] = value
            added += entries(value, here)
        elif isinstance(held[key], dict) and isinstance(value, dict):
            merged[key], more = fill(held[key], value, here)
            added += more
    return merged, added


def listed_models(name, entry):
    """The model ids the server of a `models: query` connection lists, the first being the one offered first; none while it does not answer."""
    return list(api_connection.api_connection(name, config=lambda: entry).setup()[1])


def first_model(name, entry, listing=listed_models):
    """The first model id the connection entry offers, None while it offers none."""
    models = entry.get("models")
    if models == "query":
        models = listing(name, entry)
    ids = [model.get("id") if isinstance(model, dict) else model for model in models] if isinstance(models, list) else []
    return next((model for model in ids if isinstance(model, str) and model), None)


def chat_route(connections, listing=listed_models):
    """The route to the first connection of `connections` that offers a chat model, on its first model; None without one."""
    for name, entry in connections.items():
        if isinstance(entry, dict) and services.serves_chat(entry) and (model := first_model(name, entry, listing)):
            return {"connection": name, "model": model}
    return None


def fitting_preset(shipped, total):
    """The shipped preset that fits a card of `total` MiB -- its models on the card declaring no more than that, on this machine's own docker --
    and routes both orchestrator roles; of those, the one using the card most. A setup error when there is none."""
    best = None
    for folder in local_models.presets(None, shipped).values():
        try:
            preset = local_models.read_preset(folder)
        except local_models.setup_error:
            continue
        wanted = sum(model["memory_mb"] for model in preset["models"].values() if model["gpu"])
        if (preset["host"] or not wanted or wanted > total
                or not set(local_models.ORCHESTRATOR_ROLES) <= set(local_models.routes(preset).get("orchestrator", {}))):
            continue
        if best is None or wanted > best[0]:
            best = (wanted, preset)
    if best is None:
        raise local_models.setup_error(f"no shipped preset fits a card of {total} MiB")
    return best[1]


def run(root, say=print, sh=local_models.sh, fetch=local_models.fetch, which=shutil.which, wait=local_models.WAIT, listing=listed_models,
        shipped=local_models.SHIPPED):
    """Writes the model services the project at `root` starts with into its server settings -- the preset fitting the card served and routed for
    the embed and rerank roles still unrouted, then the agents' routes -- every step reported to `say`; a key the settings hold stays.
    -> {wrote: the dotted paths added, unrouted: [(role, why)] of the roles the settings still do not route}; an unreadable settings file
    raises `local_models.setup_error`."""
    file = Path(root) / SETTINGS_FILE
    settings, wrote, why = read_settings(file), [], {}

    def merge(wanted):
        nonlocal settings
        settings, added = fill(settings, wanted)
        if added:
            write_settings(file, settings)
            wrote.extend(added)

    held = lambda: settings.get(SECTION) if isinstance(settings.get(SECTION), dict) else {}
    missing = [role for role in local_models.ORCHESTRATOR_ROLES if services.locator_of(held().get(role)) is None]
    if missing:
        say("hardware: asking for a card")
        try:
            total = local_models.card_memory(sh)
            if total is None:
                raise local_models.setup_error("no NVIDIA card answers nvidia-smi")
            preset = fitting_preset(shipped, total)
            say(f"hardware: serving the preset {preset['name']} for a card of {total} MiB")
            local_models.up(preset, sh=sh, fetch=fetch, wait=wait, say=say)
        except local_models.setup_error as error:
            why.update({role: str(error) for role in missing})
            say(f"hardware: {error}")
        else:
            merge(local_models.routes(preset))
    say("agents: routing")
    if which(CLAUDE_CLI):
        merge({SECTION: {services.AGENTS: {name: dict(CLAUDE_ROUTE) for name in (services.DEFAULT_AGENT, "scan")}}})
    elif route := chat_route(settings.get("connections") if isinstance(settings.get("connections"), dict) else {}, listing):
        merge({SECTION: {services.AGENTS: {services.DEFAULT_AGENT: route}}})
    unrouted = [(role, why.get(role) or (NO_AGENT_ROUTE if role.startswith(services.AGENTS) else services.NOT_CONFIGURED))
                for role, listed in services.role_locators(held()) if not listed]
    return {"wrote": wrote, "unrouted": unrouted}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="assassin-setup", description=__doc__)
    parser.add_argument("--root", help="managed project root whose server settings are written (default: as the assassin command finds it)")
    parser.add_argument("--wait", type=int, default=local_models.WAIT, help="seconds to wait for the models to become healthy")
    args = parser.parse_args(argv)
    try:
        root = syngatelib.find_root(args.root)
    except FileNotFoundError:
        root = Path.cwd()
    try:
        report = run(root, wait=args.wait)
    except local_models.setup_error as error:
        print(f"assassin-setup: {error}", file=sys.stderr)
        return 1
    print(f"wrote: {', '.join(report['wrote'])}" if report["wrote"] else "wrote: nothing, the settings hold what setup would write")
    for role, why in report["unrouted"]:
        print(f"could not route {role}: {' '.join(why.split())}")
    return 1 if report["unrouted"] else 0


if __name__ == "__main__":
    sys.exit(main())
