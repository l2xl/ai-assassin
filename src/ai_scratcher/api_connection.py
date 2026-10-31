# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The OpenAI-compatible API connections of the server settings' `connections` section -- MixRoute, a self-hosted llama.cpp server,
as many side by side as configured ([OPEN_AI_API.md](../../OPEN_AI_API.md))."""

import http.client
import json
import os
import queue
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from . import synthetic
from .synthetic import connection_error

# The output budget of a turn when the settings name none: a provider default cuts a long answer of tree calls short, reasoning included.
MAX_TOKENS = 32000
# The efforts a model listed as a bare id offers when the connection names none.
EFFORTS = ("low", "medium", "high")
LOAD_RETRIES = 2
TIMEOUT = 600
# Seconds a queried model listing is kept, and the most a listing request may take: the page asks for it at every poll.
LISTING_TTL = 5.0
LISTING_TIMEOUT = 5
# The load states of a llama.cpp router in which a model needs no load request.
RUNNING_STATES = ("loaded", "loading", "sleeping")
# The refusals of a llama.cpp router for a model whose load fell over or that is not loaded: the request goes again after a load request.
LOAD_REFUSED_RE = re.compile(r"failed to load|not loaded|not running", re.IGNORECASE)
SESSION_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
JSON_FENCE_RE = re.compile(r"\A```[a-z]*[ \t]*\n(.*)\n[ \t]*```\Z", re.DOTALL)


class load_refused(connection_error):
    """The server refused a request because its model failed to load or is not loaded."""


def closable_opener(context, cancelled, held):
    """A urllib opener whose connections join `held` as they open, so another thread can shut their sockets down at once; one
    connecting once `cancelled` is set closes before it sends anything."""
    def closable(base):
        class connection(base):
            def connect(self):
                held.append(self)
                super().connect()
                if cancelled.is_set():
                    self.sock.close()
                    raise OSError("turn stopped")
        return connection

    class http_handler(urllib.request.HTTPHandler):
        def http_open(self, req):
            return self.do_open(closable(http.client.HTTPConnection), req)

    class https_handler(urllib.request.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(closable(http.client.HTTPSConnection), req, context=context)

    return urllib.request.build_opener(http_handler, https_handler)


def shut(held):
    """Shut down the sockets of the connections `held`, waking a read blocked on them; the server sees the client gone."""
    for connection in list(held):
        sock = connection.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except (OSError, ValueError):
                pass


def default_sessions_dir(name):
    """Where the connection `name` keeps its sessions: `$XDG_STATE_HOME/ai-assassin/<name>`, `~/.local/state` without the variable."""
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "ai-assassin" / name


def openai_content(text, images=()):
    """The content of an OpenAI-style user message: the plain text, or, with `images`, its text part followed by one `data:` URL image part each."""
    if not images:
        return text
    return [{"type": "text", "text": text},
            *({"type": "image_url", "image_url": {"url": f"data:{image['media_type']};base64,{image['data']}"}} for image in images)]


def json_answer(content):
    """The structured answer a content holds -- a JSON object, bare or in one fenced block -- else None."""
    fenced = JSON_FENCE_RE.match(content.strip())
    try:
        answer = json.loads(fenced.group(1) if fenced else content)
    except ValueError:
        return None
    return answer if isinstance(answer, dict) else None


def api_message(label, body, status):
    """The message of an API error body -- `error.message`, or the body itself -- naming the connection and the status."""
    try:
        error = json.loads(body).get("error")
        message = error.get("message") if isinstance(error, dict) else error
    except (ValueError, AttributeError):
        message = None
    return f"{label} {status}: {message or body.strip() or 'no message'}"


class api_connection:
    """The AI connection `name` to an OpenAI-compatible chat completions API, set up by its entry of the `connections` section of the
    server settings that `config` reads at every use; the conversation is a session file of the connection's own."""
    library_delivery = "text"
    modes = {}
    # Seconds between two announcements of a growing reasoning step.
    announce_every = 0.25

    def __init__(self, name, cwd=None, config=None, sessions_dir=None):
        self.name = name
        self.cwd = cwd
        self.config = config or (lambda: {})
        self.sessions_dir = sessions_dir
        self.halted = set()
        self._listing = (None, 0.0, {})
        self._lock = threading.Lock()

    # -- setup ------------------------------------------------------------

    def read_config(self):
        config = self.config()
        return config if isinstance(config, dict) else {}

    @property
    def label(self):
        return self.label_of(self.read_config())

    def label_of(self, config):
        label = config.get("label")
        return label if isinstance(label, str) and label.strip() else self.name

    def setup(self):
        """(settings entry, {model id: {name, efforts, key, state}}) as the settings read now give them, a `query` entry's models listed by its server."""
        config = self.read_config()
        efforts = config.get("efforts")
        efforts = tuple(effort for effort in efforts if isinstance(effort, str)) if isinstance(efforts, list) else EFFORTS
        listed = config.get("models")
        if listed == "query":
            return config, self.queried(config)
        models = {}
        for entry in listed if isinstance(listed, list) else ():
            if isinstance(entry, str) and entry:
                models[entry] = {"name": entry, "efforts": efforts, "key": None, "state": None}
            elif isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry["id"]:
                own = entry.get("efforts")
                models[entry["id"]] = {"name": str(entry.get("name") or entry["id"]), "key": entry.get("api_key"), "state": None,
                                       "efforts": tuple(effort for effort in own if isinstance(effort, str)) if isinstance(own, list) else efforts}
        return config, models

    def queried(self, config):
        """{model id: spec} of the server's `GET <base_url>/models`, each without efforts and with the load state it reports; kept
        `LISTING_TTL` seconds, a listing that fails offering no model."""
        key = self.api_key(config)
        stamp = (self.base_url(config), key, json.dumps(config.get("ca")))
        with self._lock:
            kept, at, models = self._listing
            if kept == stamp and time.monotonic() - at < LISTING_TTL:
                return models
        models = {}
        if stamp[0]:
            request = urllib.request.Request(stamp[0] + "/models", headers={"Accept": "application/json", **self.auth(key)})
            try:
                with self.open(request, LISTING_TIMEOUT, config) as response:
                    listing = json.loads(response.read())
                for entry in listing.get("data") or () if isinstance(listing, dict) else ():
                    if isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry["id"]:
                        status = entry.get("status")
                        state = status.get("value") if isinstance(status, dict) and isinstance(status.get("value"), str) else None
                        models[entry["id"]] = {"name": entry["id"], "efforts": (), "key": None, "state": state}
            except (OSError, ValueError, connection_error):
                models = {}
        with self._lock:
            self._listing = (stamp, time.monotonic(), models)
        return models

    def forget_listing(self):
        with self._lock:
            self._listing = (None, 0.0, {})

    @property
    def models(self):
        return tuple(self.setup()[1])

    @property
    def efforts(self):
        return tuple(dict.fromkeys(effort for spec in self.setup()[1].values() for effort in spec["efforts"]))

    def base_url(self, config):
        url = config.get("base_url")
        return url.strip().rstrip("/") if isinstance(url, str) else ""

    def root_url(self, config):
        """The server root a llama.cpp router's model endpoints are at: the base URL without its trailing `/v1`."""
        url = self.base_url(config)
        return url[:-3] if url.endswith("/v1") else url

    def declares_key(self, config):
        return "api_key" in config or "api_key_env" in config

    def api_key(self, config):
        """The connection's key: `api_key`, else the variable `api_key_env` names, else None."""
        key = config.get("api_key")
        if isinstance(key, str) and key.strip():
            return key.strip()
        env = config.get("api_key_env")
        return (os.environ.get(env, "").strip() or None) if isinstance(env, str) and env else None

    def model_key(self, config, spec):
        """The key a turn of the model `spec` goes with: the model's own, else the connection's."""
        own = (spec or {}).get("key")
        return own.strip() if isinstance(own, str) and own.strip() else self.api_key(config)

    @staticmethod
    def auth(key):
        return {"Authorization": f"Bearer {key}"} if key else {}

    def available(self):
        """Whether the page offers the connection: it has a base URL, a model to offer and the key it declares."""
        config, models = self.setup()
        return bool(self.base_url(config) and models and (not self.declares_key(config) or self.api_key(config)))

    def settings(self):
        config, models = self.setup()
        model = config.get("default_model") if config.get("default_model") in models else next(iter(models), None)
        efforts = models[model]["efforts"] if model else ()
        effort = config.get("default_effort") if config.get("default_effort") in efforts else "medium" if "medium" in efforts else next(iter(efforts), None)
        return {"label": self.label_of(config), "library": self.library_delivery,
                "models": [{"id": model_id, "name": spec["name"], "efforts": list(spec["efforts"]), **({"state": spec["state"]} if spec["state"] else {})}
                           for model_id, spec in models.items()],
                "efforts": list(self.efforts), "default": {"model": model, "effort": effort}, "modes": []}

    # -- transport --------------------------------------------------------

    def context(self, config):
        """The TLS context of the connection's requests: the system's certificates plus the PEM files `ca` names, relative to the
        project root; None without `ca`."""
        ca = config.get("ca")
        files = [ca] if isinstance(ca, str) and ca else [entry for entry in ca if isinstance(entry, str) and entry] if isinstance(ca, list) else []
        if not files:
            return None
        context = ssl.create_default_context()
        for name in files:
            path = Path(name) if Path(name).is_absolute() else Path(self.cwd or ".") / name
            try:
                context.load_verify_locations(cafile=str(path))
            except (OSError, ssl.SSLError) as err:
                raise connection_error(f"{self.label_of(config)} cannot trust the certificate {name}: {err}") from None
        return context

    def open(self, request, timeout, config):
        return urllib.request.urlopen(request, timeout=timeout, context=self.context(config))

    def load(self, config, key, model):
        """Ask a llama.cpp router to load `model`; True once it took the request. A model loading or loaded already is refused, harmlessly."""
        request = urllib.request.Request(self.root_url(config) + "/models/load", data=json.dumps({"model": model}).encode("utf-8"), method="POST",
                                         headers={"Content-Type": "application/json", **self.auth(key)})
        try:
            with self.open(request, 30, config):
                return True
        except (OSError, ValueError, connection_error):
            return False
        finally:
            self.forget_listing()

    def select(self, model):
        """Load `model` at once when the connection is a llama.cpp router -- its listing reports load states -- and the model is not
        running yet; True when the load was asked for."""
        config, models = self.setup()
        spec = models.get(model)
        if not spec or not spec["state"] or spec["state"] in RUNNING_STATES:
            return False
        return self.load(config, self.model_key(config, spec), model)

    def interrupt(self, ident):
        """End the dispatch the thread `ident` is running at once, its response closed."""
        self.halted.add(ident)

    # -- session ----------------------------------------------------------

    def session_path(self, session):
        label = self.label
        if not SESSION_ID_RE.fullmatch(session):
            raise connection_error(f"{label} session {session!r} is not a session of this connection — start a new session")
        return Path(self.sessions_dir or default_sessions_dir(self.name)) / f"{session}.json"

    def read_session(self, session):
        path, label = self.session_path(session), self.label
        try:
            messages = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise connection_error(f"{label} session {session} is gone — start a new session") from None
        if not isinstance(messages, list):
            raise connection_error(f"{label} session {session} is unreadable — start a new session")
        return messages

    def write_session(self, session, messages):
        path = self.session_path(session)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(messages, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)

    # -- turn -------------------------------------------------------------

    def read_stream(self, config, opener, request, timeout, lines, cancelled):
        """Put every `data:` payload of the streamed answer into `lines`, then None; a failure goes in as its `connection_error`, a
        refusal for a model that did not load as `load_refused`."""
        label = self.label_of(config)
        try:
            with opener.open(request, timeout=timeout) as response:
                for raw in response:
                    if cancelled.is_set():
                        return
                    line = raw.decode("utf-8", "replace").strip()
                    if line.startswith("data:"):
                        lines.put(line[5:].strip())
            lines.put(None)
        except urllib.error.HTTPError as err:
            message = api_message(label, err.read().decode("utf-8", "replace"), err.code)
            lines.put((load_refused if LOAD_REFUSED_RE.search(message) else connection_error)(message))
        except connection_error as err:
            lines.put(err)
        except (OSError, ValueError) as err:
            lines.put(connection_error(f"{label} is unreachable: {getattr(err, 'reason', None) or err}"))

    def stream(self, config, key, body, timeout, halted, on_step, started):
        """(content, finish reason, usage) of one streamed request, its reasoning announced as a growing step and the prompt progress a
        llama.cpp router reports as a growing prompt step; a stop fails it at once, the connection shut down even before an answer began."""
        request = urllib.request.Request(self.base_url(config) + "/chat/completions", data=json.dumps(body).encode("utf-8"), method="POST",
                                         headers={"Content-Type": "application/json", "Accept": "text/event-stream", **self.auth(key)})
        lines, cancelled, held = queue.Queue(), threading.Event(), []
        opener = closable_opener(self.context(config), cancelled, held)
        threading.Thread(target=self.read_stream, args=(config, opener, request, timeout, lines, cancelled), daemon=True).start()
        content, reasoning, prompt, usage, announced, finish = [], None, None, None, 0.0, None
        try:
            while True:
                try:
                    line = lines.get(timeout=0.1)
                except queue.Empty:
                    line = ""
                if halted():
                    raise connection_error("turn stopped")
                if line == "":
                    continue
                if isinstance(line, connection_error):
                    raise line
                if line is None or line == "[DONE]":
                    break
                try:
                    chunk = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(chunk, dict):
                    continue
                if chunk.get("error"):
                    raise connection_error(api_message(self.label_of(config), json.dumps({"error": chunk["error"]}), "stream error"))
                usage = chunk["usage"] if isinstance(chunk.get("usage"), dict) else usage
                progress = chunk.get("prompt_progress")
                if isinstance(progress, dict) and isinstance(progress.get("total"), int):
                    if prompt is None:
                        prompt = {"kind": "prompt", "processed": 0, "total": 0, "cached": 0, "seconds": 0.0, "at": round(time.monotonic() - started, 2)}
                    prompt.update(processed=progress.get("processed") or 0, total=progress["total"], cached=progress.get("cache") or 0,
                                  seconds=round((progress.get("time_ms") or 0) / 1000, 2))
                    on_step(prompt)
                for choice in chunk.get("choices") or ():
                    if isinstance(choice, dict):
                        finish = choice.get("finish_reason") or finish
                    delta = choice.get("delta") if isinstance(choice, dict) and isinstance(choice.get("delta"), dict) else {}
                    thought = delta.get("reasoning_content") or delta.get("reasoning")
                    if isinstance(thought, str) and thought and (reasoning is not None or thought.strip()):
                        if reasoning is None:
                            reasoning = {"kind": "reasoning", "text": "", "at": round(time.monotonic() - started, 2)}
                        reasoning["text"] += thought
                        if time.monotonic() - announced >= self.announce_every:
                            announced = time.monotonic()
                            on_step(reasoning)
                    if isinstance(delta.get("content"), str):
                        content.append(delta["content"])
        finally:
            cancelled.set()
            shut(held)
        if reasoning is not None:
            on_step(reasoning)
        return "".join(content), finish, usage

    def dispatch(self, context, text, model=None, effort=None, modes=(), session=None, on_step=None, stopped=lambda: False, library=None, images=()):
        """(answer, session id) of one streamed chat completion: the seed context is the system message, the messages of `session` --
        a fresh one without it -- follow, then the text with its `images`. The answer is the structured answer the content holds when
        `structured` is on, the answer schema of the prompt `library` going as the response format, else the content as text. A
        request refused because its model did not load goes again after a load request, up to `load_retries` times. The reasoning the
        stream exposes grows as a reasoning step, the usage chunk closes the turn as a usage step, and the session is written only once
        the answer is in. A stop -- `stopped`, or `interrupt` of the dispatching thread -- fails the dispatch at once as a connection
        error, before the request is sent if it comes that early."""
        config, models = self.setup()
        label, ident, started = self.label_of(config), threading.get_ident(), time.monotonic()
        key = self.model_key(config, models.get(model))
        on_step = on_step or (lambda step: None)
        halted = lambda: stopped() or ident in self.halted
        self.halted.discard(ident)
        try:
            if not self.base_url(config):
                raise connection_error(f"{label} has no base URL: set `connections.{self.name}.base_url` in the server settings")
            if self.declares_key(config) and not key:
                env = config.get("api_key_env")
                raise connection_error(f"{label} has no API key: set `connections.{self.name}.api_key` in the server settings"
                                       + (f" or the environment variable {env}" if isinstance(env, str) and env else ""))
            if halted():
                raise connection_error("turn stopped")
            history = self.read_session(session) if session else []
            asked = {"role": "user", "content": openai_content(text, images)}
            limit = config.get("max_tokens")
            body = {"model": model, "messages": [{"role": "system", "content": context}, *history, asked], "stream": True,
                    "stream_options": {"include_usage": True}, "max_tokens": limit if isinstance(limit, int) and limit > 0 else MAX_TOKENS}
            if effort and effort in (models.get(model) or {}).get("efforts", ()):
                body["reasoning_effort"] = effort
            if any(spec["state"] for spec in models.values()):
                # a llama.cpp router reads a long prompt silently: its progress keeps the request alive and shows on the page
                body["return_progress"] = True
            if config.get("structured", True) is not False:
                schema = {name: value for name, value in synthetic.answer_schema(synthetic.read_library(library)).items() if name != "description"}
                schema["properties"] = {**schema["properties"], "text": {**synthetic.STRING, "description": "The reply, only with kind text; leave it out with kind calls"}}
                body["response_format"] = {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema}}
            timeout = config.get("timeout") if isinstance(config.get("timeout"), (int, float)) and config["timeout"] > 0 else TIMEOUT
            retries = config.get("load_retries") if type(config.get("load_retries")) is int and config["load_retries"] >= 0 else LOAD_RETRIES
            for attempt in range(retries + 1):
                try:
                    reply, finish, usage = self.stream(config, key, body, timeout, halted, on_step, started)
                    break
                except load_refused:
                    if attempt == retries or halted():
                        raise
                    self.load(config, key, model)
        finally:
            self.halted.discard(ident)
        on_step({"kind": "usage", "seconds": round(time.monotonic() - started, 2), "cost_usd": None,
                 "input_tokens": (usage or {}).get("prompt_tokens"), "output_tokens": (usage or {}).get("completion_tokens"),
                 "at": round(time.monotonic() - started, 2)})
        if finish == "length":
            raise connection_error(f"{label} cut the answer at its output limit of {body['max_tokens']} tokens: raise `max_tokens` of the connection {self.name}")
        if not reply.strip():
            raise connection_error(f"{label} answered without content")
        session = session or uuid.uuid4().hex
        self.write_session(session, [*history, asked, {"role": "assistant", "content": reply}])
        answer = json_answer(reply) if config.get("structured", True) is not False else None
        if answer is not None and not answer.get("calls") and "```syngate" in str(answer.get("text") or ""):
            # the schema is not enforced on every model behind a gateway: calls written as a block in the text field make a plain answer
            answer, reply = None, str(answer["text"])
        return (reply if answer is None else answer), session
