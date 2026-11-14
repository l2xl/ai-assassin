# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""ORCHESTRATOR-SERVICES: the model services' model locators, their fallback (ORCHESTRATOR-SERVICES-FALLBACK), their health, the blocking
alert, its retry and a role failing in a turn."""

import io
import json
import threading

import pytest

from ai_scratcher import services
from test_agents import Heard
from test_assassin_ui import app  # noqa: F401 -- the app fixture of the page tests

SECTION = {"embed": {"connection": "emb", "model": "bge-m3"}, "rerank": {"connection": "rer", "model": "bge-reranker"},
           "agents": {"default": {"connection": "claude_code", "model": "haiku"}}}
ALERT = "embed → emb: connection refused"


class Probe:
    """A probe failing the roles of `down`, counting its calls."""

    def __init__(self, *down):
        self.down, self.calls = set(down), []

    def __call__(self, role, locator):
        self.calls.append(role)
        if role in self.down:
            raise services.service_error("connection refused")


class Served:
    """An API connection whose server answers `answer` to every post, keeping the URLs posted to."""
    models = ("bge-m3",)

    def __init__(self, answer):
        self.answer, self.posted = answer, []

    def read_config(self):
        return {}

    def base_url(self, config):
        return "http://127.0.0.1:1/v1"

    def api_key(self, config):
        return None

    def auth(self, key):
        return {}

    def open(self, request, timeout, config):
        self.posted.append(request.full_url)
        return io.BytesIO(json.dumps(self.answer).encode())


@pytest.mark.syngate("ORCHESTRATOR-SERVICES-SERVES")
def test_a_connection_serving_embeddings_or_reranking_serves_no_chat():
    assert services.serves_chat({}) and services.serves_chat({"serves": ["chat", "embedding"]})
    assert not services.serves_chat({"serves": "embedding"}) and not services.serves_chat({"serves": ["reranking"]})


@pytest.mark.syngate("ORCHESTRATOR-SERVICES-HEALTH")
def test_health_is_checked_at_start_and_on_a_failed_call_and_kept_in_between():
    probe = Probe()
    health = services.health(lambda: services.role_locators(SECTION), probe)
    assert health.check() == {} and probe.calls == ["embed", "rerank", "agents.default"]
    assert health.alert() is None and not health.blocked() and probe.calls == ["embed", "rerank", "agents.default"]  # kept: read, not probed
    health.failed("rerank", services.service_error("connection refused"))
    assert health.blocked() and health.alert() == "rerank → rer: connection refused" and len(probe.calls) == 3


def test_the_probe_asks_an_embedding_and_finds_a_missing_model_or_connection():
    served = Served({"data": [{"embedding": [0.1]}]})
    probe = services.prober(lambda: {"emb": served})
    probe("embed", {"connection": "emb", "model": "bge-m3"})
    assert served.posted == ["http://127.0.0.1:1/v1/embeddings"]
    with pytest.raises(services.service_error, match="no model 'other'"):
        probe("embed", {"connection": "emb", "model": "other"})
    with pytest.raises(services.service_error, match="no connection 'gone'"):
        probe("embed", {"connection": "gone", "model": "bge-m3"})
    with pytest.raises(services.service_error, match="no results"):
        services.prober(lambda: {"rer": Served({})})("rerank", {"connection": "rer", "model": "bge-m3"})


@pytest.mark.syngate("ORCHESTRATOR-SERVICES-BLOCK")
def test_the_alert_names_every_role_not_configured_or_not_answering_with_its_locators_and_failures():
    health = services.health(lambda: services.role_locators({**SECTION, "rerank": None}), Probe("embed"))
    health.check()
    assert health.blocked()
    assert health.alert() == f"embed → emb: connection refused; rerank: {services.NOT_CONFIGURED}"


@pytest.mark.syngate("ORCHESTRATOR-SERVICES-RETRY")
def test_the_retry_checks_the_failed_role_again_and_clears_the_alert():
    probe, cleared = Probe("rerank"), []
    health = services.health(lambda: services.role_locators(SECTION), probe, on_clear=lambda: cleared.append(True))
    health.check()
    assert health.retry() and probe.calls[-1] == "rerank" and health.blocked() and not cleared
    probe.down.clear()
    probe.calls.clear()
    assert health.retry() == {} and probe.calls == ["rerank"] and not health.blocked() and cleared == [True]


@pytest.mark.syngate("ORCHESTRATOR-SERVICES-MIDTURN")
def test_a_role_failing_in_a_turn_holds_the_call_on_the_alert_until_the_role_answers():
    probe, attempts = Probe(), []
    health = services.health(lambda: services.role_locators(SECTION), probe)
    health.check()

    def call():
        attempts.append(1)
        if len(attempts) == 1:
            raise services.service_error("connection refused")
        return "answer"
    answered = []
    worker = threading.Thread(target=lambda: answered.append(health.hold("embed", call)))
    worker.start()
    for _ in range(200):
        if health.blocked():
            break
        threading.Event().wait(0.01)
    assert health.alert() == "embed → emb: connection refused" and not answered  # held on the alert
    health.retry()
    worker.join(5)
    assert answered == ["answer"] and len(attempts) == 2 and not health.blocked()


@pytest.mark.syngate("ORCHESTRATOR-SERVICES-FALLBACK")
def test_a_role_given_a_list_is_served_by_its_first_answering_locator_and_a_failed_call_moves_it_on():
    down = set()

    def probe(role, locator):
        if locator["connection"] in down:
            raise services.service_error("connection refused")
    section = {**SECTION, "embed": [{"connection": "a", "model": "m"}, "not a locator", {"connection": "b", "model": "m"}]}
    health = services.health(lambda: services.role_locators(section), probe)
    down.add("a")
    assert health.check() == {} and health.locator("embed") == {"connection": "b", "model": "m"} and not health.blocked()
    down.clear()
    assert health.check() == {} and health.locator("embed")["connection"] == "a"  # every check starts again at the head
    served = []

    def call(locator):
        served.append(locator["connection"])
        if locator["connection"] in down:
            raise services.service_error("refused")
        return "answer"
    down.add("a")
    assert health.serve("embed", call, errors=(services.service_error,)) == "answer" and served == ["a", "b"] and not health.blocked()
    down.add("b")
    with pytest.raises(services.service_error):
        health.serve("embed", call, errors=(services.service_error,))
    assert health.blocked() and health.alert() == "embed → b: refused, → a: connection refused"


class Loaded:
    """A connection reporting `loaded` -- a model id or None -- as its loaded model, counting the times it was asked."""

    def __init__(self, loaded):
        self.loaded, self.asked = loaded, 0
        self.models = ("Qwen-A", "Qwen-B")

    def loaded_model(self):
        self.asked += 1
        return self.loaded


@pytest.mark.syngate("ORCHESTRATOR-SERVICES-LOADED", "resolve")
def test_a_loaded_locator_is_resolved_at_every_probe_and_call_and_fails_on_to_the_next_locator_while_nothing_is_loaded():
    gpu, other = Loaded("Qwen-A"), Loaded("Qwen-B")
    connectors = {"gpu": gpu, "other": other}
    assert services.resolve_locator(connectors, {"connection": "gpu", "model": services.LOADED}) == {"connection": "gpu", "model": "Qwen-A"}
    assert services.resolve_locator(connectors, {"connection": "gpu", "model": "Qwen-B"}) == {"connection": "gpu", "model": "Qwen-B"}
    services.prober(lambda: connectors)("agents.default", {"connection": "gpu", "model": services.LOADED})
    assert gpu.asked == 2
    section = {**SECTION, "agents": {"default": [{"connection": "gpu", "model": services.LOADED}, {"connection": "other", "model": "Qwen-B"}]}}
    health = services.health(lambda: services.role_locators(section), lambda role, locator: services.resolve_locator(connectors, locator),
                             resolve=lambda locator: services.resolve_locator(connectors, locator))
    assert health.check() == {} and health.locator("agents.default") == {"connection": "gpu", "model": services.LOADED}
    served = lambda: health.serve("agents.default", lambda locator: locator["model"], errors=())
    assert served() == "Qwen-A"
    gpu.loaded = "Qwen-B"  # the user switched the server to another model: the next call follows it
    assert served() == "Qwen-B"
    gpu.loaded = None  # nothing loaded: the locator fails and the role moves on
    assert served() == "Qwen-B" and health.locator("agents.default") == {"connection": "other", "model": "Qwen-B"} and not health.blocked()
    gpu.loaded = "Qwen-A"
    assert health.check() == {} and served() == "Qwen-A"  # every check starts again at the head
    with pytest.raises(services.service_error, match="no connection 'gone'"):
        services.resolve_locator(connectors, {"connection": "gone", "model": services.LOADED})


def _served(app, probe):
    """The app given the model locators of `SECTION`, its agents a Heard connection, its services probed by `probe`. -> the connection."""
    app.connectors = {"heard": (heard := Heard())}
    app.settings_file.write_text(json.dumps({"orchestrator": {**SECTION, "agents": {"default": {"connection": "heard", "model": "model-a"}}}}))
    app.health.probe = probe
    return heard


def _until(condition, seconds=5):
    for _ in range(int(seconds * 100)):
        if condition():
            return True
        threading.Event().wait(0.01)
    return False


@pytest.mark.syngate("ORCHESTRATOR-SERVICES")
def test_the_app_checks_the_services_stands_its_chats_under_the_alert_and_holds_a_failing_model_call(app):
    probe = Probe("embed")
    _served(app, probe)
    app._chat("LEAF-001")
    app.health.check()
    assert {key: app.chats_snapshot()["chats"]["LEAF-001"][key] for key in ("state", "asked")} == {"state": "blocked", "asked": ALERT}
    assert app._chat("ROOT").asked == ALERT  # a chat opened under the alert stands under it too
    probe.down.clear()
    app.health.retry()
    assert app.chats["LEAF-001"].asked is None and app.chats["ROOT"].asked is None
    attempts, answered = [], []

    def embed(texts):
        attempts.append(texts)
        if len(attempts) == 1:
            raise services.service_error("connection refused")
        return [[0.0]]
    app.embed = embed
    held = app.rankers(app.settings("orchestrator"))[0]
    worker = threading.Thread(target=lambda: answered.append(held(["a"])))
    worker.start()
    assert _until(lambda: app.chats["LEAF-001"].asked is not None)
    assert app.chats_snapshot()["chats"]["LEAF-001"]["asked"] == ALERT and not answered  # the call is held on the alert
    app.health.retry()
    worker.join(5)
    assert answered == [[[0.0]]] and len(attempts) == 2 and app.chats["LEAF-001"].asked is None


def test_a_message_under_the_alert_waits_queued_and_is_sent_by_itself_once_every_role_answers(app):
    probe = Probe("rerank")
    heard = _served(app, probe)
    app.health.check()
    outcome = app.start_turn({"uid": "LEAF-001", "text": "Hello.", "connector": "heard", "model": "model-a", "effort": "low"})
    assert outcome["queued"] == 1 and not heard.heard and not app.chats["LEAF-001"].running
    probe.down.clear()
    app.health.retry()
    assert _until(lambda: any(message["role"] == "ai" for message in app.chats["LEAF-001"].log)), app.chats["LEAF-001"].log
    assert "Hello." in heard.heard[0]["text"] and not app.chats["LEAF-001"].queue
