# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The setup recommendation of the Orchestrator (ORCHESTRATOR-RECOMMEND): the recommendation of a model or a permission, its direction -- lower, raise
or switch --, the behaviour deciding whether it is applied or asked, the one change a message may make, the denials kept against showing it again
and what a delegated turn starts on. Pure: it reads a models listing as `synthetic.models_listing` builds it and holds no chat or connection."""

LOWER, RAISE, SWITCH = "lower", "raise", "switch"
APPLIED, ASKED = "applied", "asked"
BEHAVIOURS = ("ask", "auto_lower", "auto")
DEFAULT_BEHAVIOUR = "auto_lower"
ONCE_REFUSED = "setup refused: this message already changed the chat's model — a message changes it at most once"
OFF_CONTEXT_REFUSED = "an off-context agent recommends nothing: its setup is the route the settings give it"
SAME_REFUSED = "the setup call names the model this chat runs on — name another model of the listing, or go on"
UNHELD = " — asked, but no turn holds it here: go on on the model you have"
SOLE_REFUSED = "the setup call is the sole call of its answer — send it alone, the other calls would run on the model being left"
# The key of a chat's setup holding its own behaviour, and of the `orchestrator` section of the settings holding the server's.
BEHAVIOUR_KEY = "recommendations"
DENIED = " — denied: go on on the model you have"
DENIED_BEFORE = " — denied before in this conversation: go on on the model you have"
HANDOVER = ("{message}\n\nThis turn was started on another model and handed over to you: {change}. What it did so far:\n{done}\n"
            "Go on with the message from where it stands.")


class recommend_error(ValueError):
    """A recommendation naming a model the listing does not hold, or a decision over a behaviour or direction that is none."""


def model_recommendation(connection, model, reason, effort=None):
    """The recommendation of the model `model` of `connection`, at `effort` when one is named, its reason on one line."""
    return {"kind": "model", "connection": connection, "model": model, "effort": effort or None, "reason": " ".join(str(reason).split())}


def permission_recommendation(permission, reason):
    """The recommendation to switch the permission `permission` on, its reason on one line."""
    return {"kind": "permission", "permission": permission, "reason": " ".join(str(reason).split())}


def listed(listing, connection, model):
    """The entry of the models `listing` for the model `model` of `connection`, None where it holds none."""
    return next((entry for entry in listing if (entry["connection"], entry["model"]) == (connection, model)), None)


def ranked(entry):
    """Whether a listing entry states both a family and a tier, the two a lower or a raise is judged by."""
    return bool(entry and entry.get("family")) and isinstance(entry.get("tier"), (int, float)) and not isinstance(entry["tier"], bool)


def direction(listing, current, recommendation):
    """`lower`, `raise` or `switch` for a recommendation against the chat's own (connection, model): a model of its family at a lower or higher tier is a
    lower or a raise, any other -- another family, no family or tier, the same tier -- a switch, and a permission a raise; a model the listing lacks raises."""
    if recommendation["kind"] == "permission":
        return RAISE
    chosen = listed(listing, recommendation["connection"], recommendation["model"])
    if chosen is None:
        raise recommend_error(f"{recommendation['model']} of {recommendation['connection']} is not in the models listing")
    own = listed(listing, *current)
    if not (ranked(own) and ranked(chosen)) or own["family"] != chosen["family"] or own["tier"] == chosen["tier"]:
        return SWITCH
    return LOWER if chosen["tier"] < own["tier"] else RAISE


def behaviour_of(chosen=None, configured=None):
    """The behaviour in force: the chat's own choice, else the one the settings name, else the default -- a value that is no behaviour passing over."""
    for value in (chosen, configured):
        if value in BEHAVIOURS:
            return value
    return DEFAULT_BEHAVIOUR


def decide(behaviour, kind):
    """`applied` or `asked` for a recommendation of direction `kind` under `behaviour`, looking at nothing else of it."""
    if behaviour not in BEHAVIOURS or kind not in (LOWER, RAISE, SWITCH):
        raise recommend_error(f"no decision for behaviour {behaviour!r} and direction {kind!r}")
    return APPLIED if behaviour == "auto" or (behaviour == "auto_lower" and kind == LOWER) else ASKED


def applied_line(recommendation):
    """The one line an applied recommendation leaves in the log, naming the change and its reason."""
    if recommendation["kind"] == "permission":
        return f"permission → {recommendation['permission']}: {recommendation['reason']}"
    effort = f" at {recommendation['effort']}" if recommendation.get("effort") else ""
    return f"model → {recommendation['model']}{effort}: {recommendation['reason']}"


def asked_text(recommendation):
    """What a held turn asks the user on a recommendation: the change and its reason."""
    return f"recommendation {applied_line(recommendation)}"


def answer_of(answer):
    """(accepted, behaviour) of the user's answer to an asked recommendation: `accept` or `deny`, True or False, or {accept, behaviour} -- the
    behaviour chosen on the recommendation message, None where it names none."""
    if isinstance(answer, dict):
        chosen = answer.get(BEHAVIOUR_KEY) or answer.get("behaviour")
        return answer_of(answer.get("accept"))[0], chosen if chosen in BEHAVIOURS else None
    return answer is True or answer == "accept", None


def handover_text(message, done, recommendation):
    """The first text of the new session an accepted model takes the turn over in: the same message, the change and the lines of what the turn did so far."""
    return HANDOVER.format(message=message, change=applied_line(recommendation), done="\n".join(done) or "nothing yet")


def recommendation_key(recommendation):
    """What makes a recommendation the same one again -- the change it names, not its reason -- as a string kept with the chat log."""
    if recommendation["kind"] == "permission":
        return f"permission:{recommendation['permission']}"
    return f"model:{recommendation['connection']}/{recommendation['model']}@{recommendation.get('effort') or ''}"


def deny(denied, recommendation):
    """The list of denied recommendations' keys with this one added, once."""
    key = recommendation_key(recommendation)
    return list(denied) if key in denied else [*denied, key]


def is_denied(denied, recommendation):
    """Whether the same recommendation was denied in the conversation, so that it is not shown again."""
    return recommendation_key(recommendation) in denied


def once_refusal(made):
    """The refusal of a setup call under a message that has already made `made` of them, None while it made none."""
    return ONCE_REFUSED if made else None


def delegating_recommendation(own, named, reason="the subagent's task"):
    """The recommendation of the delegating chat that an agent call's `named` setup makes against its `own` -- both {connection, model, effort} --
    None where the call names none or the same; an effort left out is the model's own and differs from none."""
    if not named:
        return None
    if (named["connection"], named["model"]) == (own["connection"], own["model"]) and (not named.get("effort") or named["effort"] == own.get("effort")):
        return None
    return model_recommendation(named["connection"], named["model"], reason, named.get("effort"))


def delegated_start(own, behaviour, recommendation=None, accepted=False):
    """The setup and behaviour a delegated turn starts on: the delegating turn's own, or the model of the `recommendation` once it was `accepted`."""
    start = recommendation if accepted and recommendation else own
    return {"connection": start["connection"], "model": start["model"], "effort": start.get("effort"), "behaviour": behaviour}
