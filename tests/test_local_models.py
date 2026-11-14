# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Local models (LOCAL-MODELS): the model presets as docker compose projects, the shipped ones, and the commands serving, checking,
listing and removing a preset and printing its routes -- docker and the servers scripted, none of them run."""

import json

import pytest
import yaml

from ai_scratcher import local_models

COMPOSE = """
name: assassin-{name}
x-assassin: {{description: A test preset{host}}}
services:
  embed:
    ports: ["127.0.0.1:19001:8080"]
    labels: {{ai-assassin.serve: embedding, ai-assassin.model: tiny-embed, ai-assassin.memory-mb: "{memory}"}}
    deploy: {{resources: {{reservations: {{devices: [{{driver: nvidia, count: all, capabilities: [gpu]}}]}}}}}}
  judge:
    ports: ["127.0.0.1:19002:8080"]
    labels: ["ai-assassin.serve=chat", "ai-assassin.model=tiny-chat"]
"""


def write_preset(root, name="test", memory=600, host="", text=None):
    """A preset folder under the `model_presets/` of `root`, holding the test compose project or `text`; the preset as read."""
    folder = root / "model_presets" / name
    folder.mkdir(parents=True)
    (folder / "compose.yaml").write_text(text if text is not None else COMPOSE.format(name=name, memory=memory, host=f", host: {host}" if host else ""))
    return folder


class Host:
    """A scripted workstation: the card's memory, the ports whose server answers, how `compose up` ends, what `compose ps` lists."""

    def __init__(self, memory=4096, answering=(19001, 19002), up=(0, ""), ps=()):
        self.memory, self.answering, self.up_result, self.ps, self.calls, self.said, self.asked = memory, set(answering), up, ps, [], [], []

    def sh(self, argv):
        self.calls.append(argv)
        if argv[0] == "nvidia-smi":
            return (0, str(self.memory)) if self.memory else (127, "nvidia-smi: command not found")
        words = argv[argv.index("compose"):] if "compose" in argv else argv
        if "version" in words:
            return 0, "29.0"
        if "up" in words:
            return self.up_result
        if "logs" in words:
            return 0, "judge-1  | error: model file is corrupt"
        if "ps" in words:
            return 0, "\n".join(json.dumps(row) for row in self.ps)
        if "down" in words:
            return 0, ""
        raise AssertionError(argv)

    def fetch(self, url, body=None, timeout=5):
        self.asked.append((url, body))
        if int(url.split(":")[2].split("/")[0]) not in self.answering:
            return None
        return {"data": [{"embedding": [0.1]}], "results": [{"index": 0}], "choices": [{}]}

    def composed(self):
        return [argv[argv.index("compose") + 1:] for argv in self.calls if "compose" in argv]


@pytest.mark.syngate("LOCAL-MODELS-PRESET")
def test_preset_is_a_folder_holding_one_compose_project(tmp_path, monkeypatch, capsys):
    shipped = tmp_path / "shipped"
    for name in ("alpha", "beta"):
        write_preset(shipped / "x", name)
    (shipped / "x" / "model_presets" / "no-compose").mkdir()
    project = tmp_path / "project"
    own = write_preset(project, "beta", memory=900)
    found = local_models.presets(project, shipped=shipped / "x" / "model_presets")
    assert list(found) == ["alpha", "beta"] and found["beta"] == own

    preset = local_models.read_preset(found["beta"])
    assert (preset["name"], preset["project"], preset["host"], preset["description"]) == ("beta", "assassin-beta", None, "A test preset")
    assert preset["models"] == {"embed": {"serve": "embedding", "name": "tiny-embed", "port": 19001, "memory_mb": 900, "gpu": True},
                                "judge": {"serve": "chat", "name": "tiny-chat", "port": 19002, "memory_mb": 0, "gpu": False}}
    assert local_models.compose_argv(preset, "ps") == ["docker", "compose", "-f", str(own / "compose.yaml"), "-p", "assassin-beta", "ps"]

    (found["alpha"] / "compose.yaml").write_text("services: [")
    monkeypatch.setattr(local_models, "presets", lambda root=None: found)
    assert local_models.main(["list"]) == 0  # an unreadable preset is listed as such, the others still shown
    listed = capsys.readouterr().out.splitlines()
    assert listed[0].startswith("alpha  unreadable: preset alpha:") and listed[1].startswith("beta  2 model(s)  A test preset")
    with pytest.raises(local_models.setup_error, match="unknown preset 'gamma' — the presets are alpha, beta"):
        local_models.chosen_preset(found, "gamma")
    for text, word in (("services: {m: {ports: ['127.0.0.1:1:8080']}}", "carries no label ai-assassin.serve"),
                       ("services: {m: {ports: ['0.0.0.0:1:8080'], labels: {ai-assassin.serve: chat}}}", "exactly one port on 127.0.0.1"),
                       ("services: {m: {ports: ['127.0.0.1:1:8080'], labels: {ai-assassin.serve: chat}}, n: {ports: ['127.0.0.1:1:8080'], labels: {ai-assassin.serve: chat}}}", "share the port 1")):
        with pytest.raises(local_models.setup_error, match=word):
            local_models.read_preset(write_preset(tmp_path / word[:6].strip(), "broken", text=text))


@pytest.mark.syngate("LOCAL-MODELS-HOST")
def test_preset_naming_a_docker_host_is_served_there(tmp_path):
    preset = local_models.read_preset(write_preset(tmp_path, "far", memory=32000, host="ssh://gpu.example"))
    assert local_models.compose_argv(preset, "up")[:4] == ["docker", "--host", "ssh://gpu.example", "compose"]
    host = Host(memory=None)
    local_models.up(preset, sh=host.sh, fetch=host.fetch, say=host.said.append)
    assert not [argv for argv in host.calls if argv[0] == "nvidia-smi"]
    assert all(argv[1:3] == ["--host", "ssh://gpu.example"] for argv in host.calls)


@pytest.mark.syngate("LOCAL-MODELS-UP")
def test_up_brings_the_compose_project_up_and_waits_for_health(tmp_path):
    preset = local_models.read_preset(write_preset(tmp_path))
    host = Host()
    local_models.up(preset, sh=host.sh, fetch=host.fetch, wait=120, say=host.said.append)
    assert host.composed() == [["-f", str(preset["file"]), "-p", "assassin-test", "up", "-d", "--wait", "--wait-timeout", "120"]]
    assert host.said == ["test/embed: embedding tiny-embed answers on 127.0.0.1:19001", "test/judge: chat tiny-chat answers on 127.0.0.1:19002"]


@pytest.mark.syngate("LOCAL-MODELS-MEMORY")
def test_up_refuses_a_preset_larger_than_the_card(tmp_path):
    preset = local_models.read_preset(write_preset(tmp_path, memory=6000))
    small = Host(memory=4096)
    with pytest.raises(local_models.setup_error, match="preset test declares 6000 MiB on a card of 4096 MiB"):
        local_models.up(preset, sh=small.sh, fetch=small.fetch)
    absent = Host(memory=None)
    with pytest.raises(local_models.setup_error, match="needs a card and no NVIDIA card answers"):
        local_models.up(preset, sh=absent.sh, fetch=absent.fetch)
    assert not small.composed() and not absent.composed()


@pytest.mark.syngate("LOCAL-MODELS-READY")
def test_up_ends_on_a_real_answer_of_every_model_or_fails(tmp_path):
    preset = local_models.read_preset(write_preset(tmp_path))
    warm = Host()
    local_models.up(preset, sh=warm.sh, fetch=warm.fetch, say=warm.said.append)
    assert [url for url, _ in warm.asked] == ["http://127.0.0.1:19001/v1/embeddings", "http://127.0.0.1:19002/v1/chat/completions"]

    unhealthy = Host(up=(1, "container assassin-test-judge-1 is unhealthy"))
    with pytest.raises(local_models.setup_error, match=r"did not come up: container assassin-test-judge-1 is unhealthy\n.*corrupt"):
        local_models.up(preset, sh=unhealthy.sh, fetch=unhealthy.fetch)
    assert not unhealthy.asked

    mute = Host(answering={19001})
    with pytest.raises(local_models.setup_error, match="is up but gave no answer from: judge"):
        local_models.up(preset, sh=mute.sh, fetch=mute.fetch, say=mute.said.append)


@pytest.mark.syngate("LOCAL-MODELS-STATUS")
def test_status_lists_every_model_with_its_container_state(tmp_path):
    preset = local_models.read_preset(write_preset(tmp_path))
    host = Host(ps=[{"Service": "embed", "State": "running", "Health": "healthy"}])
    assert local_models.status(preset, sh=host.sh) == ["test/embed  running healthy  127.0.0.1:19001  embedding tiny-embed",
                                                       "test/judge  absent  127.0.0.1:19002  chat tiny-chat"]
    assert host.composed()[0][-4:] == ["ps", "--all", "--format", "json"]
    host.sh = lambda argv: (1, "Cannot connect to the Docker daemon")
    with pytest.raises(local_models.setup_error, match="docker does not answer for preset test: Cannot connect"):
        local_models.status(preset, sh=host.sh)


@pytest.mark.syngate("LOCAL-MODELS-PROBE")
def test_probe_asks_every_model_for_an_answer_of_its_kind(tmp_path):
    preset = local_models.read_preset(write_preset(tmp_path))
    host = Host(answering={19001})
    assert local_models.probe(preset, fetch=host.fetch) == ["judge"]
    assert host.asked == [("http://127.0.0.1:19001/v1/embeddings", {"model": "tiny-embed", "input": ["probe"]}),
                          ("http://127.0.0.1:19002/v1/chat/completions", {"model": "tiny-chat", "messages": [{"role": "user", "content": "probe"}], "max_tokens": 1})]


@pytest.mark.syngate("LOCAL-MODELS-DOWN")
def test_down_removes_the_containers_and_keeps_the_volume(tmp_path):
    preset = local_models.read_preset(write_preset(tmp_path))
    host = Host()
    local_models.down(preset, sh=host.sh, say=host.said.append)
    assert host.composed() == [["-f", str(preset["file"]), "-p", "assassin-test", "down"]]
    assert host.said == ["test: removed, its downloaded models kept"]


@pytest.mark.syngate("LOCAL-MODELS-ROUTES")
def test_routes_are_the_settings_reaching_the_preset(capsys):
    routes = local_models.routes(local_models.read_preset(local_models.presets()["cuda-4gb"]))
    assert routes["connections"]["cuda-4gb-embed"] == {"label": "cuda-4gb embed", "base_url": "http://127.0.0.1:18081/v1", "models": ["bge-m3"], "serves": "embedding"}
    assert routes["orchestrator"] == {"embed": {"connection": "cuda-4gb-embed", "model": "bge-m3"},
                                      "rerank": {"connection": "cuda-4gb-rerank", "model": "bge-reranker-v2-m3"}}
    assert local_models.main(["routes", "cuda-4gb"]) == 0
    assert json.loads(capsys.readouterr().out) == routes


@pytest.mark.syngate("LOCAL-MODELS-ROUTES-BUDGET")
def test_routes_list_efforts_and_reasoning_budgets_of_chat_models_alone(tmp_path):
    text = COMPOSE.format(name="mix", memory=600, host="") + """  rank:
    ports: ["127.0.0.1:19003:8080"]
    labels: {ai-assassin.serve: reranking, ai-assassin.model: tiny-rank}
"""
    connections = local_models.routes(local_models.read_preset(write_preset(tmp_path, "mix", text=text)))["connections"]
    assert connections["mix-judge"] == {"label": "mix judge", "base_url": "http://127.0.0.1:19002/v1", "models": ["tiny-chat"],
                                        "efforts": ["low", "medium", "high"], "reasoning_budgets": {"low": 1024, "medium": 2048, "high": 4096}}
    for role in ("embed", "rank"):  # an embedding or reranking model reasons not: neither key reaches its connection
        assert not {"efforts", "reasoning_budgets"} & set(connections[f"mix-{role}"])


@pytest.mark.syngate("LOCAL-MODELS-CUDA-4GB")
def test_cuda_4gb_preset_serves_embedding_and_rerank_within_4_gb():
    preset = local_models.read_preset(local_models.presets()["cuda-4gb"])
    assert {role: (model["serve"], model["port"], model["gpu"]) for role, model in preset["models"].items()} == {
        "embed": ("embedding", 18081, True), "rerank": ("reranking", 18082, True)}
    assert sum(model["memory_mb"] for model in preset["models"].values()) <= 4096
    assert preset["project"] == "assassin-cuda-4gb" and preset["host"] is None


@pytest.mark.syngate("LOCAL-MODELS-MI50-HOST")
def test_mi50_presets_name_the_docker_host_of_their_server():
    for name in ("mi50-llamacpp", "mi50-strata"):
        preset = local_models.read_preset(local_models.presets()[name])
        assert preset["host"] == "ssh://alexey@213.158.1.168:49999" and preset["project"] == f"assassin-{name}"
        assert local_models.compose_argv(preset, "up")[:4] == ["docker", "--host", preset["host"], "compose"]


def mi50_compose(name):
    """The compose file of a shipped mi50 preset parsed whole, its x- blocks included."""
    return yaml.safe_load((local_models.presets()[name] / "compose.yaml").read_text())


@pytest.mark.syngate("LOCAL-MODELS-MI50-LLAMACPP")
def test_mi50_llamacpp_services_build_on_the_pinned_gfx906_llamacpp_image():
    server = mi50_compose("mi50-llamacpp")["x-server"]
    image, _, tag = server["image"].partition(":")
    assert image == "mixa3607/llama.cpp-gfx906" and tag.endswith("-rocm-10.1") and tag != "latest-rocm-10.1"
    assert server["devices"] == ["/dev/kfd:/dev/kfd", "/dev/dri:/dev/dri"] and server["volumes"][0].endswith(":/models:ro")
    assert local_models.read_preset(local_models.presets()["mi50-llamacpp"])["models"] == {}  # still generic: no model of its own


@pytest.mark.syngate("LOCAL-MODELS-MI50-STRATA")
def test_mi50_strata_preset_runs_the_built_image_on_the_same_cards_and_models():
    server, compose = mi50_compose("mi50-llamacpp")["x-server"], mi50_compose("mi50-strata")
    strata = compose["x-strata"]
    assert "strata" in strata["image"] and not strata["image"].startswith("mixa3607/") and "build" not in strata
    assert all(strata[key] == server[key] for key in ("devices", "group_add")) and strata["volumes"][0] == server["volumes"][0]
    assert strata["environment"]["MODEL_PATH"] == "/models" and "strata-data" in compose["volumes"]
    assert strata["ulimits"]["memlock"] == {"soft": -1, "hard": -1} and strata["shm_size"] == "2g" and strata["stop_grace_period"] == "2m"
    assert not compose["services"]  # the preset defines no model of its own
