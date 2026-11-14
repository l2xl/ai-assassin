# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Agent match (ORCHESTRATOR-MATCH), the pure part: the gate ranking a message's agent examples and the items' statements against the match
threshold, and the confirmation by the match agent among several. Nothing here reads a file or reaches a model: the embedding and the judge are
callables the caller injects."""

import json

from . import tiering

# The origins a turn comes from (design/orchestrator/orchestrator.md): only the first is matched.
USER_MESSAGE = "message"
ORIGINS = (USER_MESSAGE, "editor", "retry", "queued", "delegated", "agent", "verdict")
# The cosine an agent's example or an item's statement reaches to be in for a message (`orchestrator.match_threshold` of the server settings).
MATCH_THRESHOLD = 0.75
# The cheap model the match agent runs on where the server settings give it no model locator of its own (`orchestrator.agents.match`).
MATCH_LOCATOR = {"connection": "claude_code", "model": "haiku", "effort": "low"}


def matchable(agents):
    """The off-context agents of `agents`, name -> agent, that can be matched: those with example phrasings and no answer schema of their own."""
    return {name: agent for name, agent in agents.items() if agent.examples and agent.schema is None}


def gate(items, agents, message, embed, threshold=MATCH_THRESHOLD):
    """(agents, statements) in for the message: the names of the agents whose best example reaches the `threshold`, best first, and the count
    of the items whose statement does. `embed` maps a list of texts to their vectors and is called once, and only when an agent has an example."""
    candidates = matchable(agents)
    examples = [(name, example) for name, agent in candidates.items() for example in agent.examples]
    if not examples:
        return [], 0
    uids = list(items)
    texts = [message, *(example for _, example in examples), *(tiering.embedded_text(items, uid) for uid in uids)]
    vectors = embed(texts)
    if len(vectors) != len(texts):
        raise ValueError(f"the embedding returned {len(vectors)} vectors for {len(texts)} texts")
    scores = [tiering.cosine(vectors[0], vector) for vector in vectors[1:]]
    best = {}
    for (name, _), score in zip(examples, scores):
        best[name] = max(score, best.get(name, score))
    statements = sum(1 for score in scores[len(examples):] if score >= threshold)
    return [name for name in sorted(best, key=lambda name: (-best[name], name)) if best[name] >= threshold], statements


def last_exchange(history):
    """The last user message of `history` -- messages of role and text -- with the replies after it, as role/text pairs; empty for none."""
    messages = [(message.get("role"), str(message.get("text") or "")) for message in history or ()]
    start = max((at for at, (role, _) in enumerate(messages) if role == "user"), default=None)
    return [] if start is None else [{"role": role, "text": text} for role, text in messages[start:]]


def shortlisted(agent, names):
    """The match `agent` narrowed to a shortlist: its schema's `agent` answer limited to one of `names` or null."""
    schema = json.loads(json.dumps(agent.schema))
    schema["properties"]["agent"] = {**schema["properties"]["agent"], "enum": [*names, None]}
    return agent._replace(schema=schema)


def judgement_data(agents, names, message, history):
    """The data the match agent judges, as JSON text: the message, the conversation's last exchange and the shortlisted agents, each by its
    name, description and example phrasings."""
    return json.dumps({"message": message, "last_exchange": last_exchange(history),
                       "agents": [{"name": name, "description": agents[name].description, "examples": list(agents[name].examples)} for name in names]},
                      ensure_ascii=False, indent=2)


def confirm(match_agent, agents, names, message, history, judge):
    """The name of the shortlisted agent the match agent confirms for the message, None for none -- an answer naming no shortlisted agent
    being none. `judge(agent, data)` returns the JSON answer of the verdict agent `agent` -- narrowed to `names` -- over the `data` text."""
    if not names:
        return None
    answer = judge(shortlisted(match_agent, names), judgement_data(agents, names, message, history))
    chosen = answer.get("agent") if isinstance(answer, dict) else None
    return chosen if isinstance(chosen, str) and chosen in names else None


def turn_origin(data, parent=None):
    """The origin of a turn the chat starts from `data`: a delegated turn under a `parent` or for an agent message, the editor's send of a
    statement, a retry, the queued messages of a running turn, else a user's message."""
    if parent is not None or data.get("agent"):
        return "delegated"
    if data.get("statement"):
        return "editor"
    if data.get("retry"):
        return "retry"
    return "queued" if isinstance(data.get("queued"), list) else USER_MESSAGE


def matched_report(name, message, report):
    """The matched exchange as the chat's session reads it at its next message: the user's message and the report of the agent `name` it went to."""
    return f"The user's message\n{message}\nwas answered by the off-context agent {name}, whose report reads:\n{report}\n\n"


def matched(origin):
    """Whether a turn of `origin` is matched against the off-context agents: a user's message alone."""
    return origin == USER_MESSAGE


def match(match_agent, items, agents, message, history, embed, judge, origin=USER_MESSAGE, threshold=MATCH_THRESHOLD):
    """The off-context agent a turn is handed to, None when it stays with the DAG: for a user's message, the one agent in for it when nothing else
    is, else the one the match agent confirms among the agents in, the items dropped; a turn of any other `origin` -- neither embedded nor judged --,
    no agent in and an agent in alone never reach the judge."""
    if not matched(origin):
        return None
    names, statements = gate(items, agents, message, embed, threshold)
    if len(names) == 1 and not statements:
        return names[0]
    return confirm(match_agent, agents, names, message, history, judge)
