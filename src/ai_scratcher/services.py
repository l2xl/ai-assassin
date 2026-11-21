# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Model services (ORCHESTRATOR-SERVICES): the roles the orchestrator gives a model locator -- a model of an AI connection -- or a list of them, their health and the blocking
alert that stands while one of them is not configured or does not answer."""

import json
import shutil
import sys
import threading
import urllib.request

MODEL_ROLES = ("embed", "rerank")
AGENTS = "agents"
DEFAULT_AGENT = "default"
# The model of a locator naming whichever model its connection reports loaded (ORCHESTRATOR-SERVICES-LOADED).
LOADED = "@loaded"
# What the probe of a role posts to its connection, and the key of the answer proving that the model answered.
PROBES = {"embed": ("/embeddings", lambda model: {"model": model, "input": ["probe"]}, "data"),
          "rerank": ("/rerank", lambda model: {"model": model, "query": "probe", "documents": ["probe"]}, "results")}
PROBE_TIMEOUT = 60
NOT_CONFIGURED = "not configured — give it a model locator in the orchestrator section of the server settings"
# Seconds between two looks at whether a held call was stopped meanwhile.
HOLD_POLL = 0.5
# Seconds between two checks of the failed roles while the alert stands (ORCHESTRATOR-SERVICES-RECHECK).
RECHECK = 60


class service_error(Exception):
    """A role that does not answer: the failure the blocking alert names."""


def serves_chat(entry):
    """Whether the connection settings `entry` serve chat: one naming `serves` -- a kind or a list of them -- without `chat` is offered to no chat."""
    serves = entry.get("serves") if isinstance(entry, dict) else None
    if serves is None:
        return True
    return "chat" in ([serves] if isinstance(serves, str) else serves if isinstance(serves, list) else [])


def single_locator(entry):
    if isinstance(entry, dict) and all(isinstance(entry.get(key), str) and entry[key].strip() for key in ("connection", "model")):
        return {"connection": entry["connection"], "model": entry["model"],
                **({"effort": entry["effort"]} if isinstance(entry.get("effort"), str) and entry["effort"].strip() else {})}
    return None


def locators(entry):
    """The model locators of an entry of the settings, best first: one locator, or every entry of a list naming a connection and a model --
    the others skipped -- each as {connection, model} with its `effort` where it names one; [] while it names none."""
    return [locator for item in (entry if isinstance(entry, list) else [entry]) if (locator := single_locator(item))]


def locator_of(entry):
    """{connection, model} of the head of an entry of the settings -- one model locator or a list of them -- None while it names none."""
    listed = locators(entry)
    return {"connection": listed[0]["connection"], "model": listed[0]["model"]} if listed else None


def role_locators(section):
    """(role, [locator, ...]) of every role the `orchestrator` section must give a model -- embed, rerank, the default agent and every agent it
    names -- its model locators best first, [] for a role given none."""
    section = section if isinstance(section, dict) else {}
    agents = section.get(AGENTS) if isinstance(section.get(AGENTS), dict) else {}
    return ([(role, locators(section.get(role))) for role in MODEL_ROLES]
            + [(f"{AGENTS}.{name}", locators(agents.get(name))) for name in (DEFAULT_AGENT, *(name for name in agents if name != DEFAULT_AGENT))])


def resolve_locator(connectors, locator):
    """The locator with the model it names now: a `LOADED` one takes the model its connection of `connectors` reports loaded, asked anew at this
    call, any other is itself; no such connection or no model loaded raises `service_error`."""
    if locator["model"] != LOADED:
        return dict(locator)
    connection = connectors.get(locator["connection"])
    if connection is None:
        raise service_error(f"no connection '{locator['connection']}'")
    model = getattr(connection, "loaded_model", lambda: None)()
    if not model:
        raise service_error(f"no model loaded on '{locator['connection']}'")
    return {**locator, "model": model}


def agent_role(section, name):
    """The role the agent `name` is served as: `agents.<name>` where the `orchestrator` section gives it model locators of its own, else `agents.default`."""
    agents = section.get(AGENTS) if isinstance(section, dict) and isinstance(section.get(AGENTS), dict) else {}
    return f"{AGENTS}.{name}" if locators(agents.get(name)) else f"{AGENTS}.{DEFAULT_AGENT}"


def failure_line(role, tried):
    """The role, every model locator it was tried on and what failed on each, as the alert names them: `rerank → a: refused, → b: no model
    'x'`; a role given none is `role: <error>`."""
    return role + ",".join(f" → {locator['connection']}: {error}" if locator else f": {error}" for locator, error in tried)


# Texts one embeddings request carries: a model server bounds its batch.
EMBED_BATCH = 32


def post(connection, path, body, timeout=PROBE_TIMEOUT):
    """The JSON answer of the connection's server to a post of `body` to `path`; a server that does not answer raises `service_error`."""
    config = connection.read_config()
    request = urllib.request.Request(connection.base_url(config) + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **connection.auth(connection.api_key(config))})
    try:
        with connection.open(request, timeout, config) as response:
            return json.loads(response.read())
    except (OSError, ValueError) as err:
        raise service_error(str(getattr(err, "reason", None) or err)) from None


def embedder(connection, model):
    """The `embed(texts)` of the dense signal over the embeddings of `model` on the connection: one vector per text, in the texts' order."""
    def embed(texts):
        texts, vectors = list(texts), []
        for start in range(0, len(texts), EMBED_BATCH):
            answer = post(connection, "/embeddings", {"model": model, "input": texts[start:start + EMBED_BATCH]})
            try:
                vectors += [row["embedding"] for row in sorted(answer["data"], key=lambda row: row.get("index", 0))]
            except (KeyError, TypeError, AttributeError):
                raise service_error("no embeddings in the answer of /embeddings") from None
        return vectors
    return embed


def cached(embed, cache):
    """`embed` keeping every vector it computes in `cache` -- text -> vector -- so that a text it has seen is never embedded again."""
    def embed_cached(texts):
        texts = list(texts)
        missing = list(dict.fromkeys(text for text in texts if text not in cache))
        if missing:
            vectors = embed(missing)
            if len(vectors) != len(missing):
                raise ValueError(f"the embedding returned {len(vectors)} vectors for {len(missing)} texts")
            cache.update(zip(missing, vectors))
        return [cache[text] for text in texts]
    return embed_cached


def reranker(connection, model):
    """The `rerank(message, statements)` of the rerank signal over the reranker `model` on the connection: one score per statement, in order."""
    def rerank(message, texts):
        texts = list(texts)
        answer = post(connection, "/rerank", {"model": model, "query": message, "documents": texts})
        scores = [0.0] * len(texts)
        try:
            for row in answer["results"]:
                scores[row["index"]] = float(row["relevance_score"])
        except (KeyError, TypeError, IndexError, ValueError):
            raise service_error("no scores in the answer of /rerank") from None
        return scores
    return rerank


def prober(connectors, which=shutil.which):
    """The probe of a role over the connectors `connectors()` returns: the model locator's connection must exist and offer its model; an embed or rerank
    model must give one real answer of its kind, an agent's Claude Code connection must find its CLI. A failure raises `service_error`."""
    def probe(role, locator):
        known = connectors()
        locator = resolve_locator(known, locator)
        connection = known.get(locator["connection"])
        if connection is None:
            raise service_error(f"no connection '{locator['connection']}'")
        if locator["model"] not in tuple(connection.models):
            raise service_error(f"the connection offers no model '{locator['model']}'")
        if role in PROBES:
            path, body, key = PROBES[role]
            config = connection.read_config()
            request = urllib.request.Request(connection.base_url(config) + path, data=json.dumps(body(locator["model"])).encode(), method="POST",
                                             headers={"Content-Type": "application/json", **connection.auth(connection.api_key(config))})
            try:
                with connection.open(request, PROBE_TIMEOUT, config) as response:
                    answer = json.loads(response.read())
            except (OSError, ValueError) as err:
                raise service_error(str(getattr(err, "reason", None) or err)) from None
            if not (isinstance(answer, dict) and answer.get(key)):
                raise service_error(f"no {key} in the answer of {path}")
        elif getattr(connection, "cli", None) and which(connection.cli[0]) is None:
            raise service_error(f"{connection.cli[0]} is not installed")
    return probe


class health:
    """The health of the model services: every role of `role_locators()` -- each given a list of model locators, best first -- is probed by
    `probe(role, locator)` on `check` -- when the server starts --, the first locator of its list that passes becoming the role's locator in
    use (`locator`). A call failing on that locator is told by `failed`, which moves the role on to the next locator whose probe passes; the
    role fails only while none of its locators passes. The outcome is kept in between, read without probing. `on_clear` is called whenever a
    check leaves every role answering, `on_fail` whenever a check or a call leaves one failing."""

    def __init__(self, role_locators, probe, on_clear=None, on_fail=None, resolve=None):
        self.role_locators, self.probe, self.on_clear, self.on_fail = role_locators, probe, on_clear or (lambda: None), on_fail or (lambda: None)
        self.resolve = resolve or dict  # the locator with the model it names at the call: a `LOADED` one resolved anew every time
        self.failures, self.active = {}, {}
        self.checked = False
        self.lock = threading.Condition()

    def listed(self):
        """role -> its model locators, a single one or None taken as a list of one or of none."""
        return {role: locators(listed) for role, listed in self.role_locators()}

    def attempt(self, role, locator):
        try:
            self.probe(role, locator)
        except Exception as err:
            return str(err) or type(err).__name__
        return None

    def settle(self, role, candidates, tried=()):
        """(locator in use, None) of the first of `candidates` whose probe passes, else (None, every locator tried with its failure) -- the
        `tried` ones first; a role with no candidate and nothing tried is not configured."""
        tried = list(tried)
        for locator in candidates:
            error = self.attempt(role, locator)
            if error is None:
                return locator, None
            tried.append((locator, error))
        return None, tried or [(None, NOT_CONFIGURED)]

    def check(self, roles=None):
        """Probe every role, or the `roles` named, each from the head of its list, the others' outcome kept. -> {role: [(locator, failure), ...]}
        of the probed roles none of whose locators answered."""
        listed = self.listed()
        probed = [role for role in listed if roles is None or role in roles]
        settled = {role: self.settle(role, listed[role]) for role in probed}
        found = {role: tried for role, (_, tried) in settled.items() if tried}
        with self.lock:
            kept = {} if roles is None else {role: failure for role, failure in self.failures.items() if role in listed and role not in probed}
            self.failures, self.checked = {**kept, **found}, True
            self.active = {**{role: locator for role, locator in self.active.items() if role in listed and role not in probed},
                           **{role: locator for role, (locator, _) in settled.items() if locator}}
            clear = not self.failures
            self.lock.notify_all()
        (self.on_clear if clear else self.on_fail)()
        return found

    def retry(self):
        """The alert's retry: probe the failed roles again, each from the head of its list. -> what still fails."""
        with self.lock:
            failed = list(self.failures)
        return self.check(failed) if failed else {}

    def locator(self, role):
        """The model locator `role` is served by: the one in use, else the head of its list; None for a role given none."""
        listed = self.listed().get(role) or []
        with self.lock:
            active = self.active.get(role)
        return active if active in listed else listed[0] if listed else None

    def failed(self, role, error):
        """Mark the locator in use of `role` failed by the `error` a call to it raised and move the role on to the next locator of its list whose
        probe passes -- those after the failed one, then those ahead of it; with none passing the role fails. -> the locator moved to, None."""
        listed, locator = self.listed().get(role) or [], self.locator(role)
        at = listed.index(locator) if locator in listed else -1
        moved, tried = self.settle(role, listed[at + 1:] + listed[:max(at, 0)], [(locator, str(error) or type(error).__name__)])
        with self.lock:
            if moved:
                self.active[role] = moved
                self.failures.pop(role, None)
            else:
                self.active.pop(role, None)
                self.failures[role] = tried
            self.lock.notify_all()
        if not moved:
            self.on_fail()
        return moved

    def recovered(self, role):
        """A call to `role` answered: a role marked failed answers again, its failure dropped, and the alert clears once no role fails
        (ORCHESTRATOR-SERVICES-RECOVER). -> whether the role was failed."""
        with self.lock:
            if role not in self.failures:
                return False
            self.failures.pop(role)
            clear = not self.failures
            self.lock.notify_all()
        if clear:
            self.on_clear()
        return True

    def watch(self, interval=RECHECK, stop=None):
        """Check the failed roles again every `interval` seconds while the alert stands, until `stop` -- a `threading.Event` -- is set, so an
        alert raised by a passing failure clears by itself (ORCHESTRATOR-SERVICES-RECHECK)."""
        stop = stop or threading.Event()
        while not stop.wait(interval):
            if self.blocked():
                try:
                    self.retry()
                except Exception as err:  # the watch outlives a failing callback: the next round checks again
                    print(f"assassin: model services recheck: {type(err).__name__}: {err}", file=sys.stderr)

    def state(self):
        """The health as the diagnosis reads it: {alert, checked, failures: {role: [{locator, error}]}, active: {role: locator}}."""
        with self.lock:
            failures, active, checked = dict(self.failures), dict(self.active), self.checked
        return {"alert": self.alert(), "checked": checked, "active": active,
                "failures": {role: [{"locator": locator, "error": error} for locator, error in tried] for role, tried in failures.items()}}

    def blocked(self):
        with self.lock:
            return bool(self.failures)

    def alert(self):
        """The blocking alert -- every failing role with every locator it was tried on and its failure -- None while every role answers."""
        with self.lock:
            failures = dict(self.failures)
        return "; ".join(failure_line(role, tried) for role, tried in failures.items()) or None

    def serve(self, role, call, errors=(Exception,)):
        """The answer of `call(locator)` on the model locator `role` is served by: a call failing with one of `errors` moves the role on and is
        made again on the next answering locator; with none answering the failure is raised, the role failed. The locator is resolved at every
        call, a `LOADED` one naming no model failing as a call does."""
        while True:
            locator = self.locator(role)
            try:
                resolved = self.resolve(locator)
            except service_error as err:
                if self.failed(role, err) is None:
                    raise
                continue
            try:
                answer = call(resolved)
            except errors as err:
                if self.failed(role, err) is None:
                    raise
                continue
            self.recovered(role)
            return answer

    def hold(self, role, call, stopped=lambda: False, errors=(Exception,)):
        """The answer of `call()` to `role`: a call failing with one of `errors` moves the role on and is made again on the next answering
        locator; with none answering it is held -- the alert standing -- until a check finds the role answering, then made again; a turn
        `stopped` meanwhile raises the failure."""
        while True:
            try:
                answer = call()
            except errors as err:
                if stopped():
                    raise
                self.failed(role, err)
                with self.lock:
                    while role in self.failures and not stopped():
                        self.lock.wait(HOLD_POLL)
                if stopped():
                    raise
                continue
            self.recovered(role)
            return answer
