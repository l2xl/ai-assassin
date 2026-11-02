# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The OpenAI-compatible API connections: settings, offer, trust, models queried and loaded, request, session, answer schema,
streaming, stop and errors -- [OPEN-AI-API].

Every dispatch goes to a fake OpenAI-compatible server on loopback, speaking the chat completions stream and, for the queried models,
the model listing and load endpoint of a llama.cpp router."""

import http.server
import json
import select
import shutil
import socket
import ssl
import subprocess
import threading
import time

import pytest

import api_connection
import syngatelib
import synthetic
from test_assassin_ui import app, call, server  # noqa: F401 -- the server fixtures of the page tests


def chunk(content=None, reasoning=None, usage=None):
    """One `data:` payload of the stream: a delta of content and/or reasoning, or the closing usage chunk."""
    delta = {**({"content": content} if content is not None else {}), **({"reasoning_content": reasoning} if reasoning is not None else {})}
    return {"id": "chatcmpl-1", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": delta}] if delta else [],
            **({"usage": usage} if usage else {})}


class fake_api:
    """A loopback OpenAI-compatible server: every request is recorded with its method, path, headers and body. A chat POST is answered
    by the next of `answers`, else by `answer` -- a list of chunks streamed as server-sent events closed by `[DONE]`, or (status, body)
    for an error -- after `delay` seconds; `stall` holds it unanswered, as a llama.cpp server reading a prompt does, until it is set or
    the client closes the connection, and `hold` keeps the stream open until it is set; `closed` tells a client gone. `GET …/models`
    answers `listing` (404 while it is None), `POST /models/load` succeeds. With `context`, an `ssl.SSLContext`, it speaks HTTPS."""

    def __init__(self, context=None):
        self.requests, self.answer, self.answers, self.hold, self.closed = [], [chunk(content="Hello.")], [], None, threading.Event()
        self.listing, self.delay, self.stall = None, 0, None
        fake = self

        class handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, text, kind="application/json"):
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(text.encode())))
                self.end_headers()
                self.wfile.write(text.encode())

            def do_GET(self):
                fake.requests.append({"method": "GET", "path": self.path, "authorization": self.headers.get("Authorization"), "body": None})
                if self.path.endswith("/models") and fake.listing is not None:
                    return self.reply(200, json.dumps(fake.listing))
                self.reply(404, '{"error": {"message": "File Not Found"}}')

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append({"method": "POST", "path": self.path, "authorization": self.headers.get("Authorization"), "body": body})
                if self.path == "/models/load":
                    return self.reply(200, '{"success": true}')
                answer = fake.answers.pop(0) if fake.answers else fake.answer
                time.sleep(fake.delay)
                while fake.stall is not None and not fake.stall.wait(0.05):
                    if select.select([self.connection], [], [], 0)[0]:
                        try:  # the request is read whole: anything readable now is the client going away
                            left = self.connection.recv(1) if isinstance(self.connection, ssl.SSLSocket) else self.connection.recv(1, socket.MSG_PEEK)
                        except (OSError, ValueError):
                            left = b""
                        if not left:
                            fake.closed.set()
                            return
                if isinstance(answer, tuple):
                    return self.reply(*answer)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    for event in answer:
                        self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                        self.wfile.flush()
                    while fake.hold is not None and not fake.hold.wait(0.05):
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                    self.wfile.write(b"data: [DONE]\n\n")
                except (BrokenPipeError, ConnectionResetError):
                    fake.closed.set()

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        if context is not None:
            self.httpd.socket = context.wrap_socket(self.httpd.socket, server_side=True)
        self.url = f"{'https' if context else 'http'}://127.0.0.1:{self.httpd.server_address[1]}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def chats(self):
        return [request for request in self.requests if request["path"].endswith("/chat/completions")]


@pytest.fixture
def fake():
    """A fake OpenAI-compatible server on loopback."""
    server = fake_api()
    yield server
    server.httpd.shutdown()


@pytest.fixture
def connection(fake, tmp_path, monkeypatch):
    """(fake server, connection `gpt` set up against it with its sessions under tmp_path, the settings entry it reads)."""
    monkeypatch.delenv("TEST_API_KEY", raising=False)
    entry = {"label": "MixRoute", "api_key": "sk-test", "base_url": fake.url, "models": ["gpt-5.5"]}
    return fake, api_connection.api_connection("gpt", cwd=tmp_path, config=lambda: entry, sessions_dir=tmp_path / "sessions"), entry


def write_settings(app, connections):
    (app.root / "assassin_settings.json").write_text(json.dumps({"connections": connections}))


def offered(base, app):
    return call(base, app, "/api/tree")[1]["connectors"]


def until(condition, seconds=5):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.02)
    return condition()


@pytest.mark.syngate("OPEN-AI-API-SETTINGS")
def test_the_connections_section_of_the_server_settings_sets_up_each_connection_by_its_id_at_every_use(server, fake, monkeypatch, tmp_path):
    base, app = server
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("TEST_API_KEY", "sk-env")
    write_settings(app, {"mix": {"label": "MixRoute", "api_key": "sk-file", "base_url": fake.url, "default_model": "glm-5.3", "default_effort": "high",
                                 "models": ["gpt-5.5", {"id": "glm-5.3", "name": "GLM 5.3", "efforts": []}, {"id": "kimi-k3", "efforts": ["high"]}]},
                         "local": {"base_url": fake.url, "api_key_env": "TEST_API_KEY", "efforts": ["low"], "models": ["qwen"]}})
    connectors = offered(base, app)
    assert connectors["mix"]["models"] == [{"id": "gpt-5.5", "name": "gpt-5.5", "efforts": ["low", "medium", "high"]},
                                           {"id": "glm-5.3", "name": "GLM 5.3", "efforts": []}, {"id": "kimi-k3", "name": "kimi-k3", "efforts": ["high"]}]
    assert connectors["mix"]["default"] == {"model": "glm-5.3", "effort": None} and connectors["mix"]["label"] == "MixRoute"
    assert connectors["local"]["models"] == [{"id": "qwen", "name": "qwen", "efforts": ["low"]}] and connectors["local"]["label"] == "local"
    assert connectors["local"]["default"] == {"model": "qwen", "effort": "low"}
    app.connectors["mix"].dispatch("seed", "Hi.", model="gpt-5.5")
    assert fake.requests[-1]["authorization"] == "Bearer sk-file" and fake.requests[-1]["path"] == "/v1/chat/completions"
    app.connectors["local"].dispatch("seed", "Hi.", model="qwen")
    assert fake.requests[-1]["authorization"] == "Bearer sk-env" and fake.requests[-1]["body"]["model"] == "qwen"
    assert len(list((tmp_path / "state" / "ai-assassin" / "mix").glob("*.json"))) == 1
    assert len(list((tmp_path / "state" / "ai-assassin" / "local").glob("*.json"))) == 1
    write_settings(app, {"mix": {"api_key": "sk-other", "base_url": fake.url, "models": ["gpt-5.5", "o5"], "default_model": "o5"}})
    assert app.connectors["mix"].settings()["default"] == {"model": "o5", "effort": "medium"}
    app.connectors["mix"].dispatch("seed", "Hi.", model="o5")
    assert fake.requests[-1]["authorization"] == "Bearer sk-other"


@pytest.mark.syngate("OPEN-AI-API-OFFER")
def test_the_page_offers_every_configured_connection_with_a_model_and_its_declared_key(server, fake, monkeypatch):
    base, app = server
    monkeypatch.delenv("TEST_API_KEY", raising=False)
    assert list(offered(base, app)) == ["claude_code"]
    write_settings(app, {"keyless": {"base_url": fake.url, "models": ["m"]},
                         "unset": {"base_url": fake.url, "api_key": "", "models": ["m"]},
                         "from_env": {"base_url": fake.url, "api_key_env": "TEST_API_KEY", "models": ["m"]},
                         "modelless": {"base_url": fake.url, "models": []},
                         "nowhere": {"models": ["m"]},
                         "keyed": {"base_url": fake.url, "api_key": "sk-file", "models": ["m"]}})
    connectors = offered(base, app)
    assert list(connectors) == ["claude_code", "keyless", "keyed"]
    assert [mode["id"] for mode in connectors["keyed"]["modes"]] == ["tree", "patch", "bash"] and connectors["keyed"]["library"] == "text"
    monkeypatch.setenv("TEST_API_KEY", "sk-env")
    assert list(offered(base, app)) == ["claude_code", "keyless", "from_env", "keyed"]
    fake.listing = {"object": "list", "data": []}
    write_settings(app, {"queried": {"base_url": fake.url, "models": "query"}})
    assert list(offered(base, app)) == ["claude_code"]
    write_settings(app, {})
    assert list(offered(base, app)) == ["claude_code"]


@pytest.mark.syngate("OPEN-AI-API-TRUST")
def test_the_certificates_named_by_ca_are_trusted_besides_the_systems_so_a_self_signed_server_is_reached(tmp_path):
    if shutil.which("openssl") is None:
        pytest.skip("no openssl to make a certificate")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=127.0.0.1",
                    "-addext", "subjectAltName=IP:127.0.0.1", "-keyout", str(tmp_path / "key.pem"), "-out", str(tmp_path / "cert.pem")],
                   check=True, capture_output=True)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tmp_path / "cert.pem", tmp_path / "key.pem")
    fake = fake_api(context)
    try:
        entry = {"base_url": fake.url, "models": ["m"]}
        connection = api_connection.api_connection("tls", cwd=tmp_path, config=lambda: entry, sessions_dir=tmp_path / "sessions")
        with pytest.raises(synthetic.connection_error, match="CERTIFICATE_VERIFY_FAILED|certificate verify failed"):
            connection.dispatch("seed", "Hi.", model="m")
        entry["ca"] = "cert.pem"
        assert connection.dispatch("seed", "Hi.", model="m")[0] == "Hello."
        entry["ca"] = [str(tmp_path / "cert.pem")]
        assert connection.dispatch("seed", "Hi.", model="m")[0] == "Hello."
        fake.listing = {"data": [{"id": "q"}]}
        entry["models"] = "query"
        assert [model["id"] for model in connection.settings()["models"]] == ["q"]
    finally:
        fake.httpd.shutdown()


@pytest.mark.syngate("OPEN-AI-API-MODELS")
def test_the_model_id_goes_unchanged_and_the_effort_only_with_a_model_listing_it(connection, syngate_tree):
    fake, connector, entry = connection
    entry["models"] = ["claude-opus-5-5", {"id": "deepseek-v4-pro", "efforts": []}]
    connector.dispatch("seed", "Hi.", model="claude-opus-5-5", effort="high")
    assert fake.requests[-1]["body"]["model"] == "claude-opus-5-5" and fake.requests[-1]["body"]["reasoning_effort"] == "high"
    connector.dispatch("seed", "Hi.", model="deepseek-v4-pro", effort="high")
    assert fake.requests[-1]["body"]["model"] == "deepseek-v4-pro" and "reasoning_effort" not in fake.requests[-1]["body"]
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root.\n", parents=())
    items, _ = syngatelib.load_tree(syngate_dir)
    synthetic.query({"gpt": connector}, items, "ROOT", "Hi.", "gpt", "deepseek-v4-pro", None)
    assert "reasoning_effort" not in fake.requests[-1]["body"]
    with pytest.raises(synthetic.query_error):
        synthetic.query({"gpt": connector}, items, "ROOT", "Hi.", "gpt", "gpt-5.5", "low")


@pytest.mark.syngate("OPEN-AI-API-QUERY")
def test_the_query_setting_offers_the_servers_model_listing_without_efforts_and_with_its_load_states(connection):
    fake, connector, entry = connection
    entry.update(models="query", efforts=["high"])
    fake.listing = {"object": "list", "data": [{"id": "Qwen-A", "object": "model", "status": {"value": "loaded"}},
                                               {"id": "Qwen-B", "object": "model", "status": {"value": "unloaded", "args": []}}]}
    settings = connector.settings()
    assert settings["models"] == [{"id": "Qwen-A", "name": "Qwen-A", "efforts": [], "state": "loaded"},
                                  {"id": "Qwen-B", "name": "Qwen-B", "efforts": [], "state": "unloaded"}]
    assert settings["default"] == {"model": "Qwen-A", "effort": None} and connector.available()
    listed = [request for request in fake.requests if request["method"] == "GET"]
    assert listed[-1]["path"] == "/v1/models" and listed[-1]["authorization"] == "Bearer sk-test"
    connector.dispatch("seed", "Hi.", model="Qwen-B", effort="high")
    assert fake.chats()[-1]["body"]["model"] == "Qwen-B" and "reasoning_effort" not in fake.chats()[-1]["body"]
    gone = api_connection.api_connection("gone", config=lambda: {"base_url": fake.url, "models": "query"})
    fake.listing = None
    assert gone.settings()["models"] == [] and not gone.available()
    fake.listing = {"data": [{"id": "gpt-5.5", "object": "model", "owned_by": "openai"}]}
    plain = api_connection.api_connection("plain", config=lambda: {"base_url": fake.url, "models": "query"})
    assert plain.settings()["models"] == [{"id": "gpt-5.5", "name": "gpt-5.5", "efforts": []}]


@pytest.mark.syngate("OPEN-AI-API-LOAD")
def test_choosing_a_model_of_a_router_asks_it_to_load_the_model_at_once(server, fake):
    base, app = server
    fake.listing = {"data": [{"id": "Qwen-A", "status": {"value": "loaded"}}, {"id": "Qwen-B", "status": {"value": "unloaded"}},
                             {"id": "Qwen-C", "status": {"value": "loading"}}]}
    write_settings(app, {"gpu": {"base_url": fake.url, "models": "query"}, "plain": {"base_url": fake.url, "models": ["m", "n"]}})
    assert "gpu" in offered(base, app)
    loads = lambda: [request["body"] for request in fake.requests if request["path"] == "/models/load"]
    call(base, app, "/api/chat/LEAF-001", {"connector": "gpu", "model": "Qwen-B"})
    assert until(lambda: loads() == [{"model": "Qwen-B"}])
    call(base, app, "/api/chat/LEAF-001", {"model": "Qwen-A"})
    call(base, app, "/api/chat/LEAF-001", {"model": "Qwen-C"})
    call(base, app, "/api/chat/LEAF-001", {"connector": "plain", "model": "n"})
    time.sleep(0.5)
    assert loads() == [{"model": "Qwen-B"}] and fake.chats() == []


@pytest.mark.syngate("OPEN-AI-API-LOADING")
def test_a_turn_waits_for_a_loading_model_and_goes_again_after_a_load_the_server_reports_failed(connection):
    fake, connector, entry = connection
    entry.update(timeout=5, models=["Qwen-B"])
    fake.delay = 1.5
    assert connector.dispatch("seed", "Hi.", model="Qwen-B")[0] == "Hello."
    fake.delay = 0
    failed = (500, '{"error": {"code": 500, "message": "model name=Qwen-B failed to load", "type": "server_error"}}')
    unloaded = (400, '{"error": {"code": 400, "message": "model is not loaded", "type": "invalid_request_error"}}')
    fake.requests.clear()
    fake.answers = [failed, unloaded]
    assert connector.dispatch("seed", "Hi.", model="Qwen-B")[0] == "Hello."
    assert [request["path"] for request in fake.requests] == ["/v1/chat/completions", "/models/load", "/v1/chat/completions",
                                                              "/models/load", "/v1/chat/completions"]
    assert all(request["body"] == {"model": "Qwen-B"} for request in fake.requests if request["path"] == "/models/load")
    fake.requests.clear()
    fake.answer, entry["load_retries"] = failed, 1
    with pytest.raises(synthetic.connection_error, match="failed to load"):
        connector.dispatch("seed", "Hi.", model="Qwen-B")
    assert len(fake.chats()) == 2
    fake.requests.clear()
    fake.answer = (500, '{"error": {"message": "upstream down"}}')
    with pytest.raises(synthetic.connection_error, match="upstream down"):
        connector.dispatch("seed", "Hi.", model="Qwen-B")
    assert len(fake.requests) == 1


@pytest.mark.syngate("OPEN-AI-API-REQUEST")
def test_the_request_carries_the_bearer_key_the_seed_as_system_message_and_the_text_with_its_images(connection):
    fake, connector, entry = connection
    image = {"media_type": "image/png", "data": "iVBORw0KGgo="}
    connector.dispatch("The seed context.", "Look at this.", model="gpt-5.5", images=[image])
    request = fake.requests[-1]
    assert request["authorization"] == "Bearer sk-test"
    assert request["body"]["messages"] == [
        {"role": "system", "content": "The seed context."},
        {"role": "user", "content": [{"type": "text", "text": "Look at this."},
                                     {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}]}]
    assert request["body"]["stream"] is True
    assert request["body"]["max_tokens"] == api_connection.MAX_TOKENS
    entry["max_tokens"] = 4000
    connector.dispatch("seed", "Hi.", model="gpt-5.5")
    assert fake.requests[-1]["body"]["max_tokens"] == 4000
    del entry["api_key"]
    connector.dispatch("seed", "Hi.", model="gpt-5.5")
    assert fake.requests[-1]["authorization"] is None


@pytest.mark.syngate("OPEN-AI-API-SESSION")
def test_a_session_is_opened_resent_on_resume_written_only_once_answered_and_a_missing_one_fails(connection, tmp_path):
    fake, connector, _ = connection
    fake.answer = [chunk(content="First answer.")]
    reply, session = connector.dispatch("seed one", "First question.", model="gpt-5.5")
    assert reply == "First answer." and (tmp_path / "sessions" / f"{session}.json").is_file()
    fake.answer = [chunk(content="Second answer.")]
    assert connector.dispatch("seed two", "Second question.", model="gpt-5.5", session=session) == ("Second answer.", session)
    assert fake.requests[-1]["body"]["messages"] == [{"role": "system", "content": "seed two"}, {"role": "user", "content": "First question."},
                                                     {"role": "assistant", "content": "First answer."}, {"role": "user", "content": "Second question."}]
    kept = (tmp_path / "sessions" / f"{session}.json").read_text()
    fake.answer = (500, '{"error": {"message": "upstream down"}}')
    with pytest.raises(synthetic.connection_error):
        connector.dispatch("seed", "Third question.", model="gpt-5.5", session=session)
    assert (tmp_path / "sessions" / f"{session}.json").read_text() == kept
    fake.answer = [chunk(content="Other answer.")]
    assert connector.dispatch("seed", "Other.", model="gpt-5.5")[1] != session
    for gone in ("0123456789abcdef", "../escape"):
        with pytest.raises(synthetic.connection_error, match="new session"):
            connector.dispatch("seed", "Hi.", model="gpt-5.5", session=gone)


@pytest.mark.syngate("OPEN-AI-API-ANSWER", "schema")
def test_the_answer_schema_goes_as_response_format_and_a_json_object_answered_is_the_structured_answer(connection):
    fake, connector, entry = connection
    calls = {"kind": "calls", "calls": [{"tool": "query", "uid": "@"}]}
    fake.answer = [chunk(content=json.dumps(calls)[:20]), chunk(content=json.dumps(calls)[20:])]
    library = synthetic.load_prompts()
    assert connector.dispatch("seed", "Hi.", model="gpt-5.5", library=library)[0] == calls
    response_format = fake.requests[-1]["body"]["response_format"]
    schema = {name: value for name, value in synthetic.answer_schema(library).items() if name != "description"}
    assert response_format["json_schema"]["name"] == "answer" and response_format["type"] == "json_schema"
    assert {**response_format["json_schema"]["schema"], "properties": {**schema["properties"], "text": synthetic.STRING}} == {
        **schema, "properties": {**schema["properties"], "text": synthetic.STRING}} and "calls" in response_format["json_schema"]["schema"]["properties"]
    mixed, steps = {"kind": "calls", "text": "Let me look.", "calls": calls["calls"]}, []
    fake.answer = [chunk(content=json.dumps(mixed))]
    answer = connector.dispatch("seed", "Hi.", model="gpt-5.5", on_step=steps.append)[0]
    assert answer == mixed and synthetic.parse_reply(answer) == ("calls", calls["calls"]) and synthetic.split_reply(answer) == ("Let me look.", calls["calls"])
    assert [step for step in steps if step["kind"] != "usage"] == []  # the text beside the calls becomes a message in `query`, not here
    fake.answer = [chunk(content=json.dumps({"kind": "text", "text": "Said.", "calls": calls["calls"]}))]
    assert synthetic.parse_reply(connector.dispatch("seed", "Hi.", model="gpt-5.5")[0]) == ("calls", calls["calls"])
    fake.answer = [chunk(content="```json\n" + json.dumps({"kind": "text", "text": "Fenced."}) + "\n```")]
    assert connector.dispatch("seed", "Hi.", model="gpt-5.5")[0] == {"kind": "text", "text": "Fenced."}
    inside = "Here.\n```syngate\n" + json.dumps(calls["calls"]) + "\n```"
    fake.answer = [chunk(content=json.dumps({"kind": "text", "text": inside}))]
    assert synthetic.split_reply(connector.dispatch("seed", "Hi.", model="gpt-5.5")[0]) == ("Here.", calls["calls"])  # a call block in the text field
    fake.answer = [chunk(content="Just prose.")]
    assert connector.dispatch("seed", "Hi.", model="gpt-5.5")[0] == "Just prose."
    block = '```syngate\n[{"tool": "query", "uid": "@"}]\n```'
    for content, remark in (('\n<invoke name="query">\n</invoke>\n' + block, ""), ("Let me look first.\n" + block, "Let me look first.")):
        fake.answer = [chunk(content=content)]
        reply = connector.dispatch("seed", "Hi.", model="gpt-5.5")[0]
        assert synthetic.split_reply(reply) == (remark, calls["calls"]) and synthetic.parse_reply(reply) == ("calls", calls["calls"])
    fake.answer = [chunk(content=block + "\n" + block)]
    assert synthetic.parse_reply(connector.dispatch("seed", "Hi.", model="gpt-5.5")[0]) == ("calls", calls["calls"] * 2)
    entry["structured"] = False
    fake.answer = [chunk(content=json.dumps(calls))]
    assert connector.dispatch("seed", "Hi.", model="gpt-5.5")[0] == json.dumps(calls)
    assert "response_format" not in fake.requests[-1]["body"]
    assert api_connection.api_connection.library_delivery == "text"


def strict_objects(schema):
    """Every object schema of `schema` lacking the strict form: a property left out of `required`, extra properties allowed, or a
    property schema with no `type` (an `anyOf` aside) -- [] for a strict schema."""
    if isinstance(schema, list):
        return [found for value in schema for found in strict_objects(value)]
    if not isinstance(schema, dict):
        return []
    found = [found for key, value in schema.items() if key not in ("const", "enum") for found in strict_objects(value)]
    if "properties" in schema and (schema.get("required") != list(schema["properties"]) or schema.get("additionalProperties") is not False
                                   or any("type" not in prop and "anyOf" not in prop for prop in schema["properties"].values())):
        found.append(schema)
    return found


@pytest.mark.syngate("OPEN-AI-API-FORMAT")
def test_a_refused_response_format_goes_again_strict_then_without_a_schema_and_the_model_keeps_the_form_that_served(connection):
    fake, connector, entry = connection
    entry["models"] = ["gpt-5.5", "deepseek-flash"]
    library = synthetic.load_prompts()
    invalid = (400, json.dumps({"error": {"message": "Invalid schema for response_format 'answer': In context=('properties', 'tool'), schema must have a 'type' key."}}))
    calls = {"kind": "calls", "calls": [{"tool": "query", "uid": "@"}]}
    fake.answers = [invalid, [chunk(content=json.dumps({"kind": "calls", "text": None, "calls": [{"tool": "query", "uid": "@", "name": None}]}))]]
    assert connector.dispatch("seed", "Hi.", model="gpt-5.5", library=library)[0] == calls  # the nulls the strict form asks for are dropped
    full, strict = (request["body"]["response_format"]["json_schema"]["schema"] for request in fake.chats())
    assert strict_objects(full) and strict_objects(strict) == []
    assert strict["properties"]["text"]["type"] == ["string", "null"] and strict["properties"]["calls"]["type"] == ["array", "null"]
    call = strict["properties"]["calls"]["items"]  # one call object: a strict decoder cannot tell shapes apart by a `tool` it writes last
    assert call["properties"]["tool"] == {"type": "string", "enum": list(synthetic.library_calls(library))} and "anyOf" not in call
    assert {"uid", "command", "diff", "url"} <= set(call["properties"]) and call["properties"]["diff"]["type"] == ["string", "null"]
    fake.answer = [chunk(content=json.dumps(calls))]
    connector.dispatch("seed", "Again.", model="gpt-5.5", library=library)
    assert len(fake.chats()) == 3 and strict_objects(fake.chats()[-1]["body"]["response_format"]["json_schema"]["schema"]) == []  # kept strict
    unavailable = (400, json.dumps({"error": {"message": "This response_format type is unavailable now"}}))
    block = '```syngate\n[{"tool": "query", "uid": "@"}]\n```'
    fake.answers = [unavailable, unavailable, [chunk(content=block)]]
    reply = connector.dispatch("seed", "Hi.", model="deepseek-flash", library=library)[0]
    assert synthetic.parse_reply(reply) == ("calls", calls["calls"])
    assert ["response_format" in request["body"] for request in fake.chats()[3:]] == [True, True, False]
    fake.answer = [chunk(content="Plain.")]
    assert connector.dispatch("seed", "Hi.", model="deepseek-flash", library=library)[0] == "Plain."
    assert len(fake.chats()) == 7 and "response_format" not in fake.chats()[-1]["body"]  # kept without a schema
    fake.answers = [(400, json.dumps({"error": {"message": "max_tokens is too large"}}))]
    with pytest.raises(synthetic.connection_error, match="max_tokens is too large"):
        connector.dispatch("seed", "Hi.", model="gpt-5.5", library=library)
    assert len(fake.chats()) == 8  # any other refusal fails the turn at once


@pytest.mark.syngate("OPEN-AI-API-STREAM")
def test_the_reasoning_grows_as_a_step_and_the_usage_chunk_closes_the_turn(connection):
    fake, connector, _ = connection
    fake.answer = [chunk(reasoning="Thinking "), chunk(reasoning="it over."), chunk(content="Done."),
                   chunk(usage={"prompt_tokens": 120, "completion_tokens": 7, "total_tokens": 127})]
    steps = []
    assert connector.dispatch("seed", "Hi.", model="gpt-5.5", on_step=lambda step: steps.append(json.loads(json.dumps(step))))[0] == "Done."
    reasoning = [step for step in steps if step["kind"] == "reasoning"]
    assert reasoning[-1]["text"] == "Thinking it over."
    assert steps[-1]["kind"] == "usage" and (steps[-1]["input_tokens"], steps[-1]["output_tokens"], steps[-1]["cost_usd"]) == (120, 7, None)
    assert fake.requests[-1]["body"]["stream_options"] == {"include_usage": True}
    fake.answer = [chunk(content="Plain.")]
    steps.clear()
    connector.dispatch("seed", "Hi.", model="gpt-5.5", on_step=steps.append)
    assert [step["kind"] for step in steps] == ["usage"] and steps[0]["input_tokens"] is None


@pytest.mark.syngate("OPEN-AI-API-STOP")
def test_a_stop_ends_the_dispatch_at_once_closes_the_response_and_leaves_the_session(connection, tmp_path):
    fake, connector, _ = connection
    reply, session = connector.dispatch("seed", "First.", model="gpt-5.5")
    kept = (tmp_path / "sessions" / f"{session}.json").read_text()
    fake.answer, fake.hold = [chunk(content="Partial")], threading.Event()
    failure, threads = [], []

    def dispatch():
        threads.append(threading.get_ident())
        try:
            connector.dispatch("seed", "Second.", model="gpt-5.5", session=session)
        except synthetic.connection_error as err:
            failure.append(str(err))

    worker = threading.Thread(target=dispatch)
    worker.start()
    assert until(lambda: len(fake.requests) >= 2)
    stopped_at = time.monotonic()
    connector.interrupt(threads[0])
    worker.join(5)
    assert failure == ["turn stopped"] and time.monotonic() - stopped_at < 1
    assert fake.closed.wait(5)
    fake.hold.set()
    assert (tmp_path / "sessions" / f"{session}.json").read_text() == kept
    sent = len(fake.requests)
    with pytest.raises(synthetic.connection_error, match="turn stopped"):
        connector.dispatch("seed", "Third.", model="gpt-5.5", stopped=lambda: True)
    assert len(fake.requests) == sent
    fake.hold, fake.stall, fake.closed = None, threading.Event(), threading.Event()
    failure.clear()
    worker = threading.Thread(target=dispatch)
    worker.start()
    assert until(lambda: len(fake.requests) > sent)
    stopped_at = time.monotonic()
    connector.interrupt(threads[-1])
    worker.join(5)
    assert failure == ["turn stopped"] and fake.closed.wait(2) and time.monotonic() - stopped_at < 2  # no answer begun, the connection shut all the same
    fake.stall.set()
    assert (tmp_path / "sessions" / f"{session}.json").read_text() == kept


@pytest.mark.syngate("OPEN-AI-API-PROGRESS")
def test_a_turn_on_a_router_asks_for_the_prompt_progress_and_records_it_as_a_growing_prompt_step(connection):
    fake, connector, entry = connection
    progress = lambda processed: {"choices": [{"index": 0, "delta": {"role": "assistant", "content": None}}], "object": "chat.completion.chunk",
                                  "prompt_progress": {"total": 5022, "cache": 1024, "processed": processed, "time_ms": processed * 3}}
    fake.answer = [progress(0), progress(2048), progress(5022), chunk(content="Read.")]
    steps = []
    assert connector.dispatch("seed", "Hi.", model="gpt-5.5", on_step=lambda step: steps.append(json.loads(json.dumps(step))))[0] == "Read."
    assert "return_progress" not in fake.chats()[-1]["body"]  # a gateway is never sent llama.cpp's own field
    entry["models"] = "query"
    fake.listing = {"data": [{"id": "Qwen-B", "status": {"value": "loaded"}}]}
    steps.clear()
    assert connector.dispatch("seed", "Hi.", model="Qwen-B", on_step=lambda step: steps.append(json.loads(json.dumps(step))))[0] == "Read."
    assert fake.chats()[-1]["body"]["return_progress"] is True
    prompt = [step for step in steps if step["kind"] == "prompt"]
    assert [step["processed"] for step in prompt] == [0, 2048, 5022]
    assert {key: prompt[-1][key] for key in ("total", "cached", "seconds")} == {"total": 5022, "cached": 1024, "seconds": 15.07}
    assert [step["kind"] for step in steps][-1] == "usage"


@pytest.mark.syngate("OPEN-AI-API-ERROR")
def test_an_http_error_a_stream_error_and_a_missing_key_fail_as_connection_errors_naming_the_cause(connection):
    fake, connector, entry = connection
    fake.answer = (401, '{"error": {"message": "Invalid Token", "type": "invalid_request_error"}}')
    with pytest.raises(synthetic.connection_error, match="MixRoute 401: Invalid Token"):
        connector.dispatch("seed", "Hi.", model="gpt-5.5")
    fake.answer = (503, "Model Unavailable")
    with pytest.raises(synthetic.connection_error, match="MixRoute 503: Model Unavailable"):
        connector.dispatch("seed", "Hi.", model="gpt-5.5")
    fake.answer = [chunk(content="Part"), {"error": {"message": "rate limit exceeded"}}]
    with pytest.raises(synthetic.connection_error, match="rate limit exceeded"):
        connector.dispatch("seed", "Hi.", model="gpt-5.5")
    entry.update(api_key="", api_key_env="TEST_API_KEY")
    sent = len(fake.requests)
    with pytest.raises(synthetic.connection_error, match=r"connections\.gpt\.api_key.*TEST_API_KEY"):
        connector.dispatch("seed", "Hi.", model="gpt-5.5")
    assert len(fake.requests) == sent
    entry.update(api_key="sk-test", base_url="http://127.0.0.1:9/v1")
    with pytest.raises(synthetic.connection_error, match="MixRoute is unreachable"):
        connector.dispatch("seed", "Hi.", model="gpt-5.5")
    entry.update(base_url=fake.url)
    fake.answer = [chunk(content="The answer goes on and"), {"id": "chatcmpl-1", "choices": [{"index": 0, "delta": {}, "finish_reason": "length"}]}]
    with pytest.raises(synthetic.connection_error, match="output limit of 32000 tokens"):
        connector.dispatch("seed", "Hi.", model="gpt-5.5")
    del entry["label"]
    fake.answer = (401, '{"error": {"message": "Invalid Token"}}')
    with pytest.raises(synthetic.connection_error, match="gpt 401: Invalid Token"):
        connector.dispatch("seed", "Hi.", model="gpt-5.5")


@pytest.mark.syngate("OPEN-AI-API-MODEL-KEY")
def test_a_model_listed_with_its_own_key_goes_with_that_key_and_the_page_never_sees_it(connection):
    fake, connector, entry = connection
    entry["models"] = [{"id": "auto", "efforts": [], "api_key": "sk-route"}, "gpt-5.5", {"id": "fallback", "api_key": ""}]
    assert connector.settings()["models"][0] == {"id": "auto", "name": "auto", "efforts": []}
    assert "sk-route" not in json.dumps(connector.settings())
    connector.dispatch("seed", "Hi.", model="auto", effort="high")
    assert fake.requests[-1]["authorization"] == "Bearer sk-route" and fake.requests[-1]["body"]["model"] == "auto"
    assert "reasoning_effort" not in fake.requests[-1]["body"]
    connector.dispatch("seed", "Hi.", model="gpt-5.5")
    assert fake.requests[-1]["authorization"] == "Bearer sk-test"
    connector.dispatch("seed", "Hi.", model="fallback")
    assert fake.requests[-1]["authorization"] == "Bearer sk-test"


@pytest.mark.syngate("OPEN-AI-API-PREAMBLE")
def test_prose_a_gateway_joins_ahead_of_the_json_answer_is_its_text_and_the_object_ending_the_content_is_the_answer(connection):
    fake, connector, _ = connection
    calls = [{"tool": "query", "uid": "@"}]
    notes = "I’ll check the item first.The token repository isn’t in the tree yet, so I’ll look."
    fake.answer = [chunk(content=notes), chunk(content=json.dumps({"calls": [{**calls[0], "diff": None}], "kind": "calls", "text": None}))]
    answer = connector.dispatch("seed", "Hi.", model="gpt-5.5")[0]
    assert answer == {"calls": calls, "kind": "calls", "text": notes} and synthetic.split_reply(answer) == (notes, calls)
    fake.answer = [chunk(content="Said first. " + json.dumps({"kind": "text", "text": "Then this."}))]
    assert connector.dispatch("seed", "Hi.", model="gpt-5.5")[0] == {"kind": "text", "text": "Said first. Then this."}
    for prose in ("A set {a, b} is fine.", "Ends with {not json}", 'Quotes {"kind": "text"} mid-sentence, then goes on.'):
        fake.answer = [chunk(content=prose)]
        assert connector.dispatch("seed", "Hi.", model="gpt-5.5")[0] == prose  # an object must end the content and hold `kind`
