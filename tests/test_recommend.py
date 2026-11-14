# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The setup recommendation library (ORCHESTRATOR-RECOMMEND): the direction of a recommendation, the behaviour deciding over it, the denials kept against
showing it again, the one change a message may make, the line of an applied one and the setup a delegated turn starts on."""

import json

import pytest

from ai_scratcher import recommend

LISTING = [{"connection": "c", "model": "haiku", "family": "claude", "tier": 1, "efforts": ["low"]},
           {"connection": "c", "model": "sonnet", "family": "claude", "tier": 2, "efforts": ["low", "high"], "current": True},
           {"connection": "c", "model": "opus", "family": "claude", "tier": 3, "efforts": []},
           {"connection": "m", "model": "gpt", "family": "gpt", "tier": 3, "efforts": []},
           {"connection": "m", "model": "plain", "efforts": []},
           {"connection": "m", "model": "sonnet-copy", "family": "claude", "tier": 2, "efforts": []}]
CURRENT = ("c", "sonnet")
KINDS = ("lower", "raise", "switch")


def model(name, connection="c", effort=None):
    return recommend.model_recommendation(connection, name, "the task needs it", effort)


@pytest.mark.syngate("ORCHESTRATOR-RECOMMEND-DIRECTION")
def test_a_model_is_lower_or_raise_within_the_chats_family_and_a_switch_across_it_or_without_family_or_tier_and_a_permission_a_raise():
    asked = [("haiku", "c"), ("opus", "c"), ("gpt", "m"), ("plain", "m"), ("sonnet-copy", "m")]
    assert [recommend.direction(LISTING, CURRENT, model(name, connection)) for name, connection in asked] == ["lower", "raise", "switch", "switch", "switch"]
    assert recommend.direction(LISTING, CURRENT, recommend.permission_recommendation("bash", "a shell call is held")) == "raise"
    assert recommend.direction(LISTING, ("m", "plain"), model("opus")) == "switch"  # the chat's own model states no family
    with pytest.raises(recommend.recommend_error):
        recommend.direction(LISTING, CURRENT, model("nowhere"))


@pytest.mark.syngate("ORCHESTRATOR-RECOMMEND-BEHAVIOUR")
def test_the_behaviour_decides_over_the_direction_alone_whatever_made_the_recommendation():
    table = {"ask": ["asked"] * 3, "auto_lower": ["applied", "asked", "asked"], "auto": ["applied"] * 3}
    assert {behaviour: [recommend.decide(behaviour, kind) for kind in KINDS] for behaviour in recommend.BEHAVIOURS} == table
    by_model = recommend.direction(LISTING, CURRENT, model("opus"))
    by_permission = recommend.direction(LISTING, CURRENT, recommend.permission_recommendation("bash", "held"))
    assert by_model == by_permission and {recommend.decide(behaviour, by_model) for behaviour in ("auto_lower",)} == {"asked"}
    with pytest.raises(recommend.recommend_error):
        recommend.decide("never", "lower")
    with pytest.raises(recommend.recommend_error):
        recommend.decide("auto", "sideways")


@pytest.mark.syngate("ORCHESTRATOR-RECOMMEND-ASK")
def test_ask_behaviour_asks_every_lower_raise_and_switch():
    assert [recommend.decide("ask", kind) for kind in KINDS] == ["asked"] * 3


@pytest.mark.syngate("ORCHESTRATOR-RECOMMEND-AUTO")
def test_auto_behaviour_applies_every_lower_raise_and_switch():
    assert [recommend.decide("auto", kind) for kind in KINDS] == ["applied"] * 3


@pytest.mark.syngate("ORCHESTRATOR-RECOMMEND-AUTO-LOWER")
def test_auto_lower_behaviour_applies_a_lower_and_asks_a_raise_or_a_switch_a_permission_included():
    assert [recommend.decide("auto_lower", kind) for kind in KINDS] == ["applied", "asked", "asked"]
    permission = recommend.permission_recommendation("bash", "held")
    assert recommend.decide("auto_lower", recommend.direction(LISTING, CURRENT, permission)) == "asked"


@pytest.mark.syngate("ORCHESTRATOR-RECOMMEND-DEFAULT")
def test_the_default_behaviour_is_auto_lower_unless_the_settings_name_another_and_the_chats_own_choice_stands_over_both():
    assert recommend.DEFAULT_BEHAVIOUR == "auto_lower" and recommend.behaviour_of() == "auto_lower"
    assert recommend.behaviour_of(None, "auto") == "auto"
    assert recommend.behaviour_of("ask", "auto") == "ask"
    assert [recommend.behaviour_of("nonsense", "nonsense"), recommend.behaviour_of("nonsense", "ask")] == ["auto_lower", "ask"]


@pytest.mark.syngate("ORCHESTRATOR-RECOMMEND-ONCE")
def test_a_message_changes_the_model_once_and_a_further_setup_call_under_it_is_refused():
    assert recommend.once_refusal(0) is None
    assert [recommend.once_refusal(made) for made in (1, 2)] == [recommend.ONCE_REFUSED] * 2


@pytest.mark.syngate("ORCHESTRATOR-RECOMMEND-DENIED")
def test_a_denied_recommendation_is_not_shown_again_while_it_stays_the_same():
    denied = recommend.deny([], model("opus", effort="high"))
    assert json.loads(json.dumps(denied)) == denied  # kept with the chat log
    again = recommend.model_recommendation("c", "opus", "another reason", "high")
    assert recommend.is_denied(denied, again) and recommend.deny(denied, again) == denied
    different = [model("opus"), model("opus", effort="low"), model("haiku"), model("opus", connection="m"), recommend.permission_recommendation("bash", "held")]
    assert [recommend.is_denied(denied, other) for other in different] == [False] * 5
    both = recommend.deny(denied, different[-1])
    assert recommend.is_denied(both, different[-1]) and recommend.is_denied(both, again)
    assert not recommend.is_denied(both, recommend.permission_recommendation("workflows", "held"))


@pytest.mark.syngate("ORCHESTRATOR-RECOMMEND-APPLIED")
def test_an_applied_recommendation_leaves_one_line_naming_the_change_and_its_reason():
    assert recommend.applied_line(recommend.model_recommendation("c", "haiku", "a rename needs no more")) == "model → haiku: a rename needs no more"
    assert recommend.applied_line(recommend.model_recommendation("c", "haiku", "a rename\n  needs no more", "low")) == "model → haiku at low: a rename needs no more"
    assert recommend.applied_line(recommend.permission_recommendation("bash", "a shell call was held")) == "permission → bash: a shell call was held"


def named(name, connection="c", effort=None):
    return {"connection": connection, "model": name, "effort": effort}


@pytest.mark.syngate("ORCHESTRATOR-RECOMMEND-DELEGATING")
def test_a_setup_an_agent_call_names_that_differs_from_the_delegating_chats_own_is_a_recommendation_of_that_chat():
    own = named("sonnet", effort="high")
    assert [recommend.delegating_recommendation(own, other) for other in (None, named("sonnet"), named("sonnet", effort="high"))] == [None] * 3
    lowered = recommend.delegating_recommendation(own, named("haiku"), "a rename")
    assert lowered == recommend.model_recommendation("c", "haiku", "a rename")
    raised = recommend.delegating_recommendation(own, named("opus"))
    effort_only = recommend.delegating_recommendation(own, named("sonnet", effort="low"))
    assert effort_only["effort"] == "low"
    directions = [recommend.direction(LISTING, CURRENT, found) for found in (lowered, raised, effort_only)]
    assert directions == ["lower", "raise", "switch"]
    assert [recommend.decide("auto_lower", kind) for kind in directions] == ["applied", "asked", "asked"]  # it passes the delegating chat's behaviour


@pytest.mark.syngate("ORCHESTRATOR-RECOMMEND-DELEGATED")
def test_a_delegated_turn_starts_on_the_setup_and_behaviour_of_the_delegating_turn_unless_an_accepted_recommendation_names_another():
    own = named("sonnet", effort="high")
    assert recommend.delegated_start(own, "ask") == {**own, "behaviour": "ask"}
    asked = recommend.delegating_recommendation(own, named("opus"))
    assert recommend.delegated_start(own, "ask", asked) == {**own, "behaviour": "ask"}  # denied or not yet accepted
    assert recommend.delegated_start(own, "ask", asked, accepted=True) == {"connection": "c", "model": "opus", "effort": None, "behaviour": "ask"}
