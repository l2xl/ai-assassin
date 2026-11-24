# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""A skill naming a delivery enters the system prompts of the connections of that library delivery alone: the answer written as the message
content is told to text delivery, the structured answer through the answer tool to native delivery."""

import pytest

import syngatelib
import synthetic


def _library(folder):
    """Three default skills -- `rules` for every connection, `block` of text delivery, `tool` of native delivery -- and an agent listing all three."""
    folder.mkdir(exist_ok=True)
    (folder / "rules.md").write_text("---\nkind: skill\ndescription: The rules\ndefault: true\n---\n# Rules\nFollow them.\n")
    (folder / "block.md").write_text("---\nkind: skill\ndescription: Plain\ndefault: true\ndelivery: text\n---\n# Block\nFence it.\n")
    (folder / "tool.md").write_text("---\nkind: skill\ndescription: Tool\ndefault: true\ndelivery: native\n---\n# Tool\nCall it.\n")
    (folder / "odd.md").write_text("---\nkind: skill\ndescription: Odd\ndefault: true\ndelivery: pigeon\n---\n# Odd\nAnywhere.\n")
    (folder / "worker.md").write_text("---\nkind: agent\ndescription: Work\nskills: [rules, block, tool]\n---\n# Worker\nWork.\n")
    return synthetic.load_prompts(folder)


class Heard:
    """A connection of the given library delivery keeping the system prompt of every dispatch."""
    label, models, efforts, modes = "Heard", ("model-a",), ("low",), ()

    def __init__(self, delivery):
        self.library_delivery, self.contexts = delivery, []

    def dispatch(self, context, text, model=None, effort=None, modes=(), session=None, on_step=None, stopped=None, library=None, agent=None):
        self.contexts.append(context)
        return {"kind": "text", "text": "done"}, "session-h"


@pytest.mark.syngate("SYNTHETIC-SKILL-DELIVERY")
def test_a_skill_naming_a_delivery_enters_only_the_prompts_of_connections_of_that_delivery_default_or_white_listed(tmp_path, syngate_tree):
    library = _library(tmp_path / "prompts")
    assert [library[name].delivery for name in ("rules", "block", "tool", "odd")] == [None, "text", "native", None]  # an unknown delivery names none
    text, native = synthetic.default_prompt(library), synthetic.native_prompt(library)
    assert text.startswith("# Block\nFence it.\n\n# Odd\nAnywhere.\n\n# Rules\nFollow them.\n\n# Skills on request") and "# Tool" not in text
    assert native == "# Odd\nAnywhere.\n\n# Rules\nFollow them.\n\n# Tool\nCall it.\n"
    worker = library["worker"]
    assert synthetic.agent_prompt(worker, library, "text") == "# Worker\nWork.\n\n# Rules\nFollow them.\n\n# Block\nFence it.\n"
    assert synthetic.agent_prompt(worker, library, "native") == "# Worker\nWork.\n\n# Rules\nFollow them.\n\n# Tool\nCall it.\n"
    assert synthetic.agent_prompt(worker, library) == synthetic.agent_prompt(worker, library, "text")
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT", "Root.\n", parents=())
    items, _ = syngatelib.load_tree(syngate_dir)
    connectors = {"text": Heard("text"), "native": Heard("native")}
    for name, connection in connectors.items():
        synthetic.query(connectors, items, "ROOT", "Go.", name, "model-a", "low", library=library)  # the seed context of an item's turn
        synthetic.query(connectors, items, "ROOT", "Go.", name, "model-a", "low", library=library, agent=worker)  # an off-context agent's prompt
        seeded, agent = connection.contexts
        assert ("# Block" in seeded, "# Tool" in seeded) == ("# Block" in agent, "# Tool" in agent) == (name == "text", name == "native")
        assert agent == synthetic.agent_prompt(worker, library, name)
    for shipped in ("commit", "explore", "test"):  # every shipped agent that calls tools is told the carrier of its connection, never the other
        agent = synthetic.load_agents()[shipped]
        block, tool = synthetic.SKILLS["call_tool_text"].text, synthetic.SKILLS["call_tool_structured"].text
        told = [synthetic.agent_prompt(agent, delivery=delivery) for delivery in synthetic.DELIVERIES]
        assert [(block in prompt, tool in prompt) for prompt in told] == [(True, False), (False, True)]


@pytest.mark.syngate("SYNTHETIC-SKILL-CALL-TEXT")
def test_the_text_answer_skill_is_a_default_skill_of_text_delivery_stating_the_answer_object_or_the_plain_answer_with_its_fenced_block():
    skill = synthetic.SKILLS["call_tool_text"]
    assert skill.default and skill.delivery == "text" and skill.text.startswith("# Text answer\n")
    for phrase in ("content of your message", '{"kind": "text", "text": "…"}', '{"kind": "calls", "calls": [...], "text": "…"}', "write it plain",
                   "single fenced block tagged `syngate`", "```syngate\n[{\"tool\": \"query\", \"uid\": \"@\"}", "prose around that block", "tool-use markup"):
        assert phrase in skill.text
    assert "call_tool_block" not in synthetic.SKILLS and synthetic.ANSWER_TOOL not in skill.text
    library = synthetic.read_library()
    assert skill.text in synthetic.default_prompt(library) and skill.text not in synthetic.native_prompt(library)


@pytest.mark.syngate("SYNTHETIC-SKILL-CALL-STRUCTURED")
def test_the_structured_answer_skill_is_a_default_skill_of_native_delivery_telling_to_write_the_reply_as_text_and_close_the_round_with_the_tool_taking_no_text():
    skill = synthetic.SKILLS["call_tool_structured"]
    assert skill.default and skill.delivery == "native" and skill.text.startswith("# Structured answer\n")
    for phrase in (f"`{synthetic.ANSWER_TOOL}`", "takes the `kind` and the `calls` and no text", "Call it once to close the round", "`kind: text` to end the turn",
                   "Write your reply once, as text", "is your whole reply", "nothing written ahead of it is an empty answer, refused", "said on the way",
                   "asked to call it, call it at once and write nothing more", "the text you already wrote stands ahead of the call and is the reply",
                   "Once the tool has answered, write nothing",
                   "workflow you launch is awaited", "background is killed when the turn ends"):
        assert phrase in skill.text
    assert "`text`" not in skill.text and "call_tool_answer" not in synthetic.SKILLS  # no text field of the tool is offered
    library = synthetic.read_library()
    native = synthetic.native_prompt(library)
    assert synthetic.claude_code_connector.library_delivery == "native" and skill.text in native and skill.text not in synthetic.default_prompt(library)
    assert "```syngate" not in native and "fenced block" not in native  # no plain answer is offered to the CLI
