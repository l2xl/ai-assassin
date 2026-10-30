# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The MixRoute connector: settings, offer, request, session, answer schema, streaming, stop and errors -- [MIXROUTE].

Every dispatch goes to a fake MixRoute served on loopback, speaking the OpenAI chat completions stream; the live binding alone reaches
the real API, and only with an API key."""

import http.server
import json
import threading
import time

import pytest

import syngatelib
import synthetic
from test_assassin_ui import app, call, server  # noqa: F401 -- the server fixtures of the page tests


def chunk(content=None, reasoning=None, usage=None):
    """One `data:` payload of the stream: a delta of content and/or reasoning, or the closing usage chunk."""
    delta = {**({"content": content} if content is not None else {}), **({"reasoning_content": reasoning} if reasoning is not None else {})}
    return {"id": "chatcmpl-1", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": delta}] if delta else [],
            **({"usage": usage} if usage else {})}


class fake_mixroute:
    """A loopback MixRoute: every POST is recorded with its headers and body and answered by `answer` -- a list of chunks streamed as
    server-sent events closed by `[DONE]`, or (status, body) for an error; `hold` keeps the stream open until it is set."""

    def __init__(self):
        self.requests, self.answer, self.hold, self.closed = [], [chunk(content="Hello.")], None, threading.Event()
        fake = self

        class handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append({"path": self.path, "authorization": self.headers.get("Authorization"), "body": body})
                if isinstance(fake.answer, tuple):
                    status, text = fake.answer
                    self.send_response(status)
                    self.end_headers()
                    self.wfile.write(text.encode())
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    for event in fake.answer:
                        self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                        self.wfile.flush()
                    while fake.hold is not None and not fake.hold.wait(0.05):
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                    self.wfile.write(b"data: [DONE]\n\n")
                except (BrokenPipeError, ConnectionResetError):
                    fake.closed.set()

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def mixroute(tmp_path, monkeypatch):
    """(fake MixRoute, connector set up against it with its sessions under tmp_path, the settings section it reads)."""
    monkeypatch.delenv(synthetic.MIXROUTE_KEY_ENV, raising=False)
    fake = fake_mixroute()
    section = {"api_key": "sk-test", "base_url": fake.url}
    yield fake, synthetic.mixroute_connector(cwd=tmp_path, config=lambda: section, sessions_dir=tmp_path / "sessions"), section
    fake.httpd.shutdown()


@pytest.mark.syngate("MIXROUTE-SETTINGS")
def test_the_mixroute_section_of_the_server_settings_sets_up_key_base_url_models_and_default_at_every_use(server, mixroute, monkeypatch, tmp_path):
    base, app = server
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    fake, _, _ = mixroute
    connector = app.connectors["mixroute"]
    assert connector.settings()["models"][0] == {"id": "auto", "name": "auto", "efforts": []}
    assert connector.settings()["models"][1] == {"id": "claude-sonnet-5-5", "name": "claude-sonnet-5-5", "efforts": ["low", "medium", "high"]}
    assert connector.settings()["default"] == {"model": "claude-sonnet-5-5", "effort": "medium"} and connector.settings()["modes"] == []
    (app.root / "assassin_settings.json").write_text(json.dumps({"mixroute": {
        "api_key": "sk-file", "base_url": fake.url, "default_model": "glm-5.3", "default_effort": "high",
        "models": ["gpt-5.5", {"id": "glm-5.3", "name": "GLM 5.3", "efforts": []}, {"id": "kimi-k3", "efforts": ["high"]}]}}))
    settings = connector.settings()
    assert settings["models"] == [{"id": "auto", "name": "auto", "efforts": []}, {"id": "gpt-5.5", "name": "gpt-5.5", "efforts": ["low", "medium", "high"]},
                                  {"id": "glm-5.3", "name": "GLM 5.3", "efforts": []}, {"id": "kimi-k3", "name": "kimi-k3", "efforts": ["high"]}]
    assert settings["default"] == {"model": "glm-5.3", "effort": None}
    connector.dispatch("seed", "Hi.", model="gpt-5.5")
    assert fake.requests[-1]["authorization"] == "Bearer sk-file" and fake.requests[-1]["path"] == "/v1/chat/completions"
    monkeypatch.setenv(synthetic.MIXROUTE_KEY_ENV, "sk-env")
    (app.root / "assassin_settings.json").write_text(json.dumps({"mixroute": {"base_url": fake.url}}))
    connector.dispatch("seed", "Hi.", model="gpt-5.5")
    assert fake.requests[-1]["authorization"] == "Bearer sk-env"
    assert len(list((tmp_path / "state" / "ai-assassin" / "mixroute").glob("*.json"))) == 2
    assert synthetic.mixroute_connector().settings()["default"]["model"] == "claude-sonnet-5-5"


@pytest.mark.syngate("MIXROUTE-OFFER")
def test_the_page_offers_the_mixroute_connector_only_while_an_api_key_is_set(server, monkeypatch):
    base, app = server
    monkeypatch.delenv(synthetic.MIXROUTE_KEY_ENV, raising=False)
    assert "mixroute" not in call(base, app, "/api/tree")[1]["connectors"]
    (app.root / "assassin_settings.json").write_text(json.dumps({"mixroute": {"api_key": "sk-file"}}))
    offered = call(base, app, "/api/tree")[1]["connectors"]
    assert offered["mixroute"]["label"] == "MixRoute" and [mode["id"] for mode in offered["mixroute"]["modes"]] == ["tree", "patch"]
    assert list(offered)[0] == "claude_code"
    (app.root / "assassin_settings.json").write_text("{}")
    monkeypatch.setenv(synthetic.MIXROUTE_KEY_ENV, "sk-env")
    assert "mixroute" in call(base, app, "/api/tree")[1]["connectors"]


@pytest.mark.syngate("MIXROUTE-MODELS")
def test_the_model_id_goes_unchanged_and_the_effort_only_with_a_model_listing_it(mixroute, syngate_tree):
    fake, connector, section = mixroute
    section["models"] = ["claude-opus-5-5", {"id": "deepseek-v4-pro", "efforts": []}]
    connector.dispatch("seed", "Hi.", model="claude-opus-5-5", effort="high")
    assert fake.requests[-1]["body"]["model"] == "claude-opus-5-5" and fake.requests[-1]["body"]["reasoning_effort"] == "high"
    connector.dispatch("seed", "Hi.", model="deepseek-v4-pro", effort="high")
    assert fake.requests[-1]["body"]["model"] == "deepseek-v4-pro" and "reasoning_effort" not in fake.requests[-1]["body"]
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root.\n", parents=())
    items, _ = syngatelib.load_tree(syngate_dir)
    synthetic.query({"mixroute": connector}, items, "ROOT", "Hi.", "mixroute", "deepseek-v4-pro", None)
    assert "reasoning_effort" not in fake.requests[-1]["body"]
    with pytest.raises(synthetic.query_error):
        synthetic.query({"mixroute": connector}, items, "ROOT", "Hi.", "mixroute", "gpt-5.5", "low")


@pytest.mark.syngate("MIXROUTE-REQUEST")
def test_the_request_carries_the_bearer_key_the_seed_as_system_message_and_the_text_with_its_images(mixroute):
    fake, connector, section = mixroute
    image = {"media_type": "image/png", "data": "iVBORw0KGgo="}
    connector.dispatch("The seed context.", "Look at this.", model="gpt-5.5", images=[image])
    request = fake.requests[-1]
    assert request["authorization"] == "Bearer sk-test"
    assert request["body"]["messages"] == [
        {"role": "system", "content": "The seed context."},
        {"role": "user", "content": [{"type": "text", "text": "Look at this."},
                                     {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}]}]
    assert request["body"]["stream"] is True
    assert request["body"]["max_tokens"] == synthetic.MIXROUTE_MAX_TOKENS
    section["max_tokens"] = 4000
    connector.dispatch("seed", "Hi.", model="gpt-5.5")
    assert fake.requests[-1]["body"]["max_tokens"] == 4000


@pytest.mark.syngate("MIXROUTE-SESSION")
def test_a_session_is_opened_resent_on_resume_written_only_once_answered_and_a_missing_one_fails(mixroute, tmp_path):
    fake, connector, _ = mixroute
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


@pytest.mark.syngate("MIXROUTE-ANSWER", "schema")
def test_the_answer_schema_goes_as_response_format_and_a_json_object_answered_is_the_structured_answer(mixroute):
    fake, connector, section = mixroute
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
    fake.answer = [chunk(content=json.dumps(calls)[:20]), chunk(content=json.dumps(calls)[20:])]
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
    section["structured"] = False
    fake.answer = [chunk(content=json.dumps(calls))]
    assert connector.dispatch("seed", "Hi.", model="gpt-5.5")[0] == json.dumps(calls)
    assert "response_format" not in fake.requests[-1]["body"]
    assert synthetic.mixroute_connector.library_delivery == "text"


@pytest.mark.syngate("MIXROUTE-STREAM")
def test_the_reasoning_grows_as_a_step_and_the_usage_chunk_closes_the_turn(mixroute):
    fake, connector, _ = mixroute
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


@pytest.mark.syngate("MIXROUTE-STOP")
def test_a_stop_ends_the_dispatch_at_once_closes_the_response_and_leaves_the_session(mixroute, tmp_path):
    fake, connector, _ = mixroute
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
    deadline = time.monotonic() + 5
    while len(fake.requests) < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
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


@pytest.mark.syngate("MIXROUTE-ERROR")
def test_an_http_error_a_stream_error_and_a_missing_key_fail_as_connection_errors_naming_the_cause(mixroute, tmp_path):
    fake, connector, section = mixroute
    fake.answer = (401, '{"error": {"message": "Invalid Token", "type": "invalid_request_error"}}')
    with pytest.raises(synthetic.connection_error, match="MixRoute 401: Invalid Token"):
        connector.dispatch("seed", "Hi.", model="gpt-5.5")
    fake.answer = (503, "Model Unavailable")
    with pytest.raises(synthetic.connection_error, match="MixRoute 503: Model Unavailable"):
        connector.dispatch("seed", "Hi.", model="gpt-5.5")
    fake.answer = [chunk(content="Part"), {"error": {"message": "rate limit exceeded"}}]
    with pytest.raises(synthetic.connection_error, match="rate limit exceeded"):
        connector.dispatch("seed", "Hi.", model="gpt-5.5")
    del section["api_key"]
    sent = len(fake.requests)
    with pytest.raises(synthetic.connection_error, match=synthetic.MIXROUTE_KEY_ENV):
        connector.dispatch("seed", "Hi.", model="gpt-5.5")
    assert len(fake.requests) == sent
    section.update(api_key="sk-test", base_url="http://127.0.0.1:9/v1")
    with pytest.raises(synthetic.connection_error, match="unreachable"):
        connector.dispatch("seed", "Hi.", model="gpt-5.5")
    section.update(base_url=fake.url)
    fake.answer = [chunk(content="The answer goes on and"), {"id": "chatcmpl-1", "choices": [{"index": 0, "delta": {}, "finish_reason": "length"}]}]
    with pytest.raises(synthetic.connection_error, match="output limit of 32000 tokens"):
        connector.dispatch("seed", "Hi.", model="gpt-5.5")


@pytest.mark.syngate("MIXROUTE-FREE")
def test_the_free_model_glm_4_flash_is_offered_by_default_without_efforts(mixroute):
    fake, connector, section = mixroute
    assert {"id": "glm-4-flash", "name": "glm-4-flash", "efforts": []} in connector.settings()["models"]


@pytest.mark.syngate("MIXROUTE-AUTO")
def test_auto_is_the_top_model_and_is_sent_with_the_smart_routing_key(mixroute):
    fake, connector, section = mixroute
    assert connector.settings()["models"][0] == {"id": "auto", "name": "auto", "efforts": []}
    assert connector.settings()["default"]["model"] == "claude-sonnet-5-5"
    section["smart_routing"] = {"api_key": "sk-route"}
    connector.dispatch("seed", "Hi.", model="auto", effort="high")
    assert fake.requests[-1]["authorization"] == "Bearer sk-route" and fake.requests[-1]["body"]["model"] == "auto"
    assert "reasoning_effort" not in fake.requests[-1]["body"]
    section["smart_routing"] = "sk-bare"
    connector.dispatch("seed", "Hi.", model="auto")
    assert fake.requests[-1]["authorization"] == "Bearer sk-bare"
    section["smart_routing"] = {"api_key": ""}
    connector.dispatch("seed", "Hi.", model="auto")
    assert fake.requests[-1]["authorization"] == "Bearer sk-test"
    section["default_model"] = "gpt-5.5"
    assert connector.settings()["default"]["model"] == "gpt-5.5"

