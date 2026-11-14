# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""File measuring (ORCHESTRATOR-TIER), the pure part: the signals ranking the items of a seed context, their fusion, propagation and
pinning into one order, and the budget taking the files of that order whole or as their references. Nothing here reads a file, a model
or the session: the embedding and the reranker are callables the caller injects, the file contents a mapping it hands in."""

import math
import os
import re
from collections.abc import Mapping
from typing import NamedTuple

from . import segmenting, syngatelib

RANK_K = 60  # the constant of the reciprocal rank fusion
SHORTLIST = 50  # items of the dense ranking the reranker scores
DAMPING = 0.85  # the share of a propagated score that walks on to the neighbours
ITERATIONS = 50
DENSE_SEGMENTS = 16  # the segments of a long message the dense signal embeds: its first eight and its last eight
RERANK_SEGMENTS = 6  # those the reranker scores against every statement of the shortlist: the first three and the last three
TREE_EDITS = ("add", "edit", "remove", "move", "rename")
ACTIVITY_WEIGHTS = {"edited": 3, "named": 2, "read": 1}
REFERENCE_RE = re.compile(r"@([A-Z][A-Z_]*(?:-[A-Z0-9_]+)*)\b")
CODE_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]*)`")


def tokens(text):
    """The tokens of `text` in the budget: its characters over four, the remainder dropped."""
    return len(text) // 4


def subject(description):
    """The first non-blank line of a statement: the subject its item introduces."""
    return next((line.strip() for line in description.splitlines() if line.strip()), "")


def item_files(items, uid):
    """The files the item names, once each in order: its key sources, then the project files its statement links."""
    item = items[uid]
    return list(dict.fromkeys([*item.sources, *syngatelib.linked_files(item.description)]))


def by_score(scores):
    """The UIDs of `scores` ordered by descending score, equal scores by UID."""
    return sorted(scores, key=lambda uid: (-scores[uid], uid))


def embedded_text(items, uid):
    """The text the dense signal embeds for an item: the subjects of its ancestors, root first, over its whole statement."""
    ancestors = [found for found in syngatelib.walk(items, uid) if found != uid]
    head = " / ".join(subject(items[found].description) for found in ancestors)
    return (head + "\n" if head else "") + items[uid].description.strip()


def cosine(left, right):
    """The cosine of two vectors, 0 when either has no length."""
    norms = math.sqrt(sum(x * x for x in left)) * math.sqrt(sum(x * x for x in right))
    return sum(x * y for x, y in zip(left, right)) / norms if norms else 0.0


def dense_ranking(items, message, embed):
    """The UIDs of `items` ranked by the greatest cosine of any segment of the message -- its ends, when it is long -- to each item's embedded
    text, `embed` mapping a list of texts to their vectors and being called once, the segments first."""
    uids, heads = list(items), segmenting.ends(segmenting.segments(message), DENSE_SEGMENTS)
    vectors = embed([*heads, *(embedded_text(items, uid) for uid in uids)])
    if len(vectors) != len(uids) + len(heads):
        raise ValueError(f"the embedding returned {len(vectors)} vectors for {len(uids) + len(heads)} texts")
    return by_score({uid: max(cosine(head, vector) for head in vectors[:len(heads)]) for uid, vector in zip(uids, vectors[len(heads):])})


def rerank_ranking(items, message, shortlist, rerank):
    """The UIDs of `shortlist` -- the head of the dense ranking -- ranked by the greatest score `rerank(segment, statements)` gives a statement
    over the end segments of the message, one call for each."""
    shortlist = list(shortlist)
    scores = [0.0] * len(shortlist)
    for number, segment in enumerate(segmenting.ends(segmenting.segments(message), RERANK_SEGMENTS)):
        given = rerank(segment, [items[uid].description for uid in shortlist])
        if len(given) != len(shortlist):
            raise ValueError(f"the reranker returned {len(given)} scores for {len(shortlist)} statements")
        scores = list(given) if number == 0 else [max(had, now) for had, now in zip(scores, given)]
    return by_score(dict(zip(shortlist, scores)))


def item_names(items, uid):
    """The names an item answers to in a message: its files by path and by file name, and the identifiers its statement sets in code."""
    files = item_files(items, uid)
    return {*files, *(os.path.basename(rel) for rel in files), *CODE_RE.findall(items[uid].description)}


def named_in(message, name):
    """Whether the message names `name` as a whole word."""
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", message) is not None


def names_ranking(items, message):
    """The UIDs of the items whose file names or identifiers the message names, the most names first."""
    return by_score({uid: hits for uid in items if (hits := sum(named_in(message, name) for name in item_names(items, uid)))})


def activity_ranking(items, read=(), edited=(), named=()):
    """The UIDs of the items the chat touched, ranked by what it did: each UID or file of an item that the chat edited counts 3, named 2, read 1."""
    touched = {"read": set(read), "edited": set(edited), "named": set(named)}
    scores = {}
    for uid in items:
        files = {uid, *item_files(items, uid)}
        total = sum(weight * len(touched[kind] & files) for kind, weight in ACTIVITY_WEIGHTS.items())
        if total:
            scores[uid] = total
    return by_score(scores)


def signal_weight(settings, name):
    """The weight of the settings a signal enters the fusion under: a number of zero or more, else 1."""
    value = settings.get(name) if isinstance(settings, Mapping) else None
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
    return float(value) if ok else 1.0


def fuse(rankings, weights=None, k=RANK_K):
    """The reciprocal rank fusion of `rankings`, signal name -> UIDs best first: each item scores the sum over the signals ranking it of
    the signal's weight over `k` plus its rank. Only ranks enter, never a signal's own score."""
    scores = {}
    for name, ranking in rankings.items():
        weight = signal_weight(weights, name)
        for rank, uid in enumerate(ranking, 1):
            scores[uid] = scores.get(uid, 0.0) + weight / (k + rank)
    return scores


def neighbours(items):
    """The edges of the DAG a score spreads along, as UID -> UIDs: parent links and shared key sources, both ways."""
    edges = {uid: set() for uid in items}
    owners = {}
    for uid, item in items.items():
        for parent in item.parents:
            if parent in items:
                edges[uid].add(parent)
                edges[parent].add(uid)
        for rel in item.sources:
            owners.setdefault(rel, []).append(uid)
    for sharing in owners.values():
        for uid in sharing:
            edges[uid].update(other for other in sharing if other != uid)
    return edges


def propagate(items, scores, damping=DAMPING, iterations=ITERATIONS):
    """The personalised PageRank of the items seeded with `scores` along `neighbours`: every item of `items` with its score, summing to 1
    -- or all 0 when nothing is seeded -- an item rising by its position without having matched."""
    seed = {uid: max(scores.get(uid, 0.0), 0.0) for uid in items}
    total = sum(seed.values())
    if total <= 0:
        return {uid: 0.0 for uid in items}
    seed = {uid: value / total for uid, value in seed.items()}
    edges, rank = neighbours(items), dict(seed)
    for _ in range(iterations):
        stranded = sum(rank[uid] for uid in items if not edges[uid])
        rank = {uid: (1 - damping) * seed[uid] + damping * (stranded * seed[uid] + sum(rank[other] / len(edges[other]) for other in edges[uid]))
                for uid in items}
    return rank


def pinned(selection, active, message):
    """The UIDs of the selection that stand ahead of the estimated order: the active item, then the items whose UID the message names."""
    named = REFERENCE_RE.findall(message)
    return [uid for uid in dict.fromkeys([active, *named]) if uid in selection]


def estimate_order(selection, scores, active, message):
    """The selection in the order of its importance: the pinned items first, the rest by descending propagated score, equals in the
    selection's own order."""
    head = pinned(selection, active, message)
    return head + sorted((uid for uid in selection if uid not in head), key=lambda uid: -scores.get(uid, 0.0))


def file_order(items, order):
    """The files of the items in `order`, each once at the importance of the most important item naming it."""
    return list(dict.fromkeys(rel for uid in order for rel in item_files(items, uid)))


def take_files(files, contents, budget):
    """(whole, heavy) of the `files` in their order against a token `budget`: a file fitting what is left is whole, one that does not is
    heavy and the files after it are still tried; a file without content costs nothing."""
    left, whole, heavy = budget, [], []
    for rel in files:
        cost = tokens(contents[rel]) if contents.get(rel) is not None else 0
        if cost <= left:
            whole.append(rel)
            left -= cost
        else:
            heavy.append(rel)
    return whole, heavy


def reference(rel, text):
    """A heavy file as its items keep it: its path and its line count."""
    return f"{rel} ({len(text.splitlines())} lines)"


class measurement(NamedTuple):
    """What measuring a seed context decided: every statement whole by UID in the selection's order; the estimated `order` of the items;
    the `files` in the order of their importance, split into `whole` and `heavy`; the `heavy` files' references by path and, under every
    item naming a heavy file, its `references`."""
    statements: dict
    order: list
    files: list
    whole: list
    heavy: dict
    references: dict


def signals(items, selection, message, embed=None, rerank=None, activity=None, shortlist=SHORTLIST):
    """The rankings of the selection's items under each signal, by name: `dense` and, with a `rerank` over its first `shortlist` items,
    `rerank` when an `embed` is given, `names` and `activity` (`read`, `edited`, `named` of the chat) always."""
    sub = {uid: items[uid] for uid in selection}
    rankings = {}
    if embed:
        rankings["dense"] = dense_ranking(sub, message, embed)
        if rerank:
            rankings["rerank"] = rerank_ranking(sub, message, rankings["dense"][:shortlist], rerank)
    rankings["names"] = names_ranking(sub, message)
    rankings["activity"] = activity_ranking(sub, **(activity or {}))
    return rankings


def measure(items, selection, message, active, rankings, contents, budget, weights=None):
    """The measurement of the seed context of `selection` for `message`: the statements all whole; the items ordered by the fusion of
    `rankings`, propagated and pinned; the files of that order taken into the token `budget` over the `contents` of the files."""
    sub = {uid: items[uid] for uid in selection}
    order = estimate_order(list(selection), propagate(sub, fuse(rankings, weights)), active, message)
    files = file_order(sub, order)
    whole, heavy = take_files(files, contents, budget)
    references = {rel: reference(rel, contents[rel]) for rel in heavy}
    return measurement({uid: sub[uid].description for uid in selection}, order, files, whole, references,
                       {uid: [references[rel] for rel in item_files(sub, uid) if rel in references] for uid in selection})


def patched_paths(call):
    """The project files a patch or replace call changes, root-relative."""
    if call.get("tool") == "replace":
        return [os.path.normpath(call["path"])] if isinstance(call.get("path"), str) and call["path"].strip() else []
    if call.get("tool") == "patch":
        return [os.path.normpath(path) for path in re.findall(r"^\+\+\+ b/(\S+)", str(call.get("diff") or ""), re.M)]
    return []


def activity_of(log):
    """What the chat did, from the messages of its log: the items and files it `read` -- query and context calls, read calls -- the items and
    files it `edited` -- tree edits, patch and replace calls -- and the items its user `named` by `@UID`; each as a list, for `activity_ranking`."""
    read, edited, named = [], [], []
    for message in log:
        if message.get("role") == "user":
            named += REFERENCE_RE.findall(str(message.get("text") or ""))
        for step in message.get("steps") or ():
            if not isinstance(step, dict) or step.get("kind") != "calls":
                continue
            for entry in step.get("inputs") or ():
                for call in entry if isinstance(entry, list) else [entry]:
                    if not isinstance(call, dict):
                        continue
                    tool, uid = call.get("tool"), call.get("uid")
                    if tool in ("query", "context") and isinstance(uid, str) and uid != "@":
                        read.append(uid)
                    elif tool in TREE_EDITS and isinstance(uid, str) and uid != "@":
                        edited.append(uid)
                    elif tool == "read" and isinstance(call.get("path"), str) and call["path"].strip():
                        read.append(os.path.normpath(call["path"]))
                    else:
                        edited += patched_paths(call)
    return {"read": read, "edited": edited, "named": named}
