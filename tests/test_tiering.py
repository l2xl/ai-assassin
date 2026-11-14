# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""The pure part of file measuring (ORCHESTRATOR-TIER-*): the token count, the signals, their fusion and propagation, the pinning and the
budget taking files whole or as references."""

import types

import pytest

import tiering


@pytest.mark.syngate("ORCHESTRATOR-TIER-TOKEN")
def test_tokens_counts_the_budget_at_four_characters_to_a_token():
    assert [tiering.tokens(text) for text in ("", "abc", "abcd", "abcde", "a" * 400)] == [0, 0, 1, 1, 100]


SELECTION = ["ROOT", "A", "C", "B"]


def make(uid, description, parents=(), sources=()):
    return types.SimpleNamespace(uid=uid, description=description, parents=list(parents), sources=list(sources), order=0)


def tree(*entries):
    return {entry.uid: entry for entry in entries}


def base():
    return tree(make("ROOT", "Root\nthe whole project"), make("A", "Alpha\nthe alpha statement", ["ROOT"], ["src/a.py"]),
                make("B", "Beta\nthe beta statement", ["ROOT"], ["src/b.py", "src/big.py"]),
                make("C", "Gamma\nmentions beta and `apply_call`", ["A"], ["src/big.py"]))


def keywords(texts):
    return [[text.lower().count("alpha"), text.lower().count("beta")] for text in texts]


def contents():
    return {"src/a.py": "x" * 40, "src/b.py": "y" * 40, "src/big.py": "SECRET-LINE\n" * 100}


@pytest.mark.syngate("ORCHESTRATOR-TIER-DENSE")
def test_dense_signal_ranks_by_similarity_to_the_statement_embedded_with_its_ancestors_subjects():
    items, seen = base(), []

    def embed(texts):
        seen.append(texts)
        return keywords(texts)

    ranking = tiering.dense_ranking(items, "alpha", embed)
    assert len(seen) == 1 and seen[0][0] == "alpha"
    assert seen[0][1:] == [tiering.embedded_text(items, uid) for uid in items]
    assert tiering.embedded_text(items, "C") == "Root / Alpha\nGamma\nmentions beta and `apply_call`"
    assert tiering.embedded_text(items, "ROOT") == "Root\nthe whole project"
    assert ranking == ["A", "C", "B", "ROOT"]
    with pytest.raises(ValueError):
        tiering.dense_ranking(items, "alpha", lambda texts: [[1, 0]])


@pytest.mark.syngate("ORCHESTRATOR-TIER-RERANK")
def test_rerank_signal_ranks_the_dense_shortlist_by_the_score_of_the_message_against_each_statement():
    items, calls = base(), []

    def rerank(message, texts, scale=1):
        calls.append((message, texts))
        return [sum(word in text.lower() for word in message.split()) * scale for text in texts]

    assert tiering.rerank_ranking(items, "beta statement", ["A", "B", "C"], rerank) == ["B", "A", "C"]
    assert calls == [("beta statement", [items[uid].description for uid in ("A", "B", "C")])]
    assert tiering.rerank_ranking(items, "beta statement", ["A", "B", "C"], lambda m, t: rerank(m, t, 1000)) == ["B", "A", "C"]
    seen = []
    rankings = tiering.signals(items, SELECTION, "beta statement", embed=keywords,
                               rerank=lambda message, texts: seen.append(texts) or rerank(message, texts), shortlist=2)
    assert rankings["dense"] == ["B", "C", "A", "ROOT"]
    assert seen == [[items["B"].description, items["C"].description]] and rankings["rerank"] == ["B", "C"]
    assert set(tiering.signals(items, SELECTION, "beta")) == {"names", "activity"}


@pytest.mark.syngate("ORCHESTRATOR-TIER-NAMES")
def test_lexical_signal_ranks_by_the_file_names_and_identifiers_the_message_names():
    items = base()
    message = "look at src/b.py and big.py, plus apply_call; notbig.py is no match"
    assert tiering.names_ranking(items, message) == ["B", "C"]
    assert tiering.names_ranking(items, "notbig.py") == []
    assert tiering.names_ranking(items, "nothing named here") == []


@pytest.mark.syngate("ORCHESTRATOR-TIER-ACTIVITY")
def test_activity_signal_ranks_by_what_the_chat_read_edited_and_named():
    items = base()
    assert tiering.activity_ranking(items, read=["src/a.py"], edited=["B"], named=["C"]) == ["B", "C", "A"]
    assert tiering.activity_ranking(items, edited=["src/big.py"]) == ["B", "C"]
    assert tiering.activity_ranking(items) == []


@pytest.mark.syngate("ORCHESTRATOR-TIER-WEIGHT")
def test_signal_weight_is_the_settings_weight_or_one():
    assert tiering.signal_weight({"dense": 2}, "dense") == 2.0
    bad = (None, {}, {"names": 3}, {"dense": "x"}, {"dense": True}, {"dense": -1}, {"dense": float("nan")})
    assert [tiering.signal_weight(settings, "dense") for settings in bad] == [1.0] * 7
    rankings = {"dense": ["A", "B"], "names": ["B", "A"]}
    even = tiering.fuse(rankings)
    assert even["A"] == pytest.approx(even["B"])
    weighted = tiering.fuse(rankings, {"dense": 2})
    assert weighted["A"] > weighted["B"]
    assert tiering.fuse(rankings, {"dense": 0}) == {"A": pytest.approx(1 / 62), "B": pytest.approx(1 / 61)}


@pytest.mark.syngate("ORCHESTRATOR-TIER-RANK")
def test_fusion_orders_by_the_ranks_under_each_signal_never_by_raw_scores():
    fused = tiering.fuse({"one": ["x", "y", "z"], "two": ["y"]})
    assert tiering.by_score(fused) == ["y", "x", "z"]
    items = base()
    scaled = lambda scale: tiering.rerank_ranking(items, "m", ["A", "B", "C"], lambda message, texts: [scale * n for n in (0.2, 0.9, 0.5)])
    assert scaled(1) == scaled(1000) == ["B", "C", "A"]
    assert tiering.fuse({"rerank": scaled(1)}) == tiering.fuse({"rerank": scaled(1000)})


@pytest.mark.syngate("ORCHESTRATOR-TIER-PROPAGATE")
def test_propagation_spreads_scores_along_parent_and_shared_source_edges():
    items = base()
    spread = tiering.propagate(items, {"A": 1.0})
    assert max(spread, key=spread.get) == "A" and spread["ROOT"] > 0 and spread["C"] > 0 and spread["B"] > 0
    assert sum(spread.values()) == pytest.approx(1)
    assert set(tiering.propagate(items, {}).values()) == {0.0}
    shared = tree(make("P", "P\np", sources=["s.py"]), make("Q", "Q\nq", sources=["s.py"]), make("R", "R\nr", sources=["r.py"]))
    spread = tiering.propagate(shared, {"P": 1.0})
    assert spread["P"] > spread["Q"] > 0 and spread["R"] == 0


@pytest.mark.syngate("ORCHESTRATOR-TIER-LEXICAL")
def test_the_active_and_the_named_items_stand_ahead_of_the_estimated_order():
    assert tiering.pinned(SELECTION, "C", "see @B and @MISSING and @B") == ["C", "B"]
    assert tiering.estimate_order(SELECTION, {"A": 0.9}, "C", "see @B and @MISSING") == ["C", "B", "A", "ROOT"]
    assert tiering.estimate_order(SELECTION, {"B": 0.9, "A": 0.1}, "ROOT", "nothing") == ["ROOT", "B", "A", "C"]


@pytest.mark.syngate("ORCHESTRATOR-TIER-GRAPH")
def test_every_statement_enters_whole_whatever_the_message_and_the_budget():
    items = base()
    measured = tiering.measure(items, SELECTION, "nothing relevant", "ROOT", {}, contents(), 0)
    assert list(measured.statements) == SELECTION
    assert measured.statements == {uid: items[uid].description for uid in SELECTION}
    assert measured.whole == [] and set(measured.heavy) == {"src/a.py", "src/big.py", "src/b.py"}


@pytest.mark.syngate("ORCHESTRATOR-TIER-FILE")
def test_a_file_is_counted_once_at_the_importance_of_the_most_important_item_naming_it():
    items = base()
    assert tiering.file_order(items, ["A", "C", "B", "ROOT"]) == ["src/a.py", "src/big.py", "src/b.py"]
    assert tiering.file_order(items, ["B", "C", "A", "ROOT"]) == ["src/b.py", "src/big.py", "src/a.py"]
    files = {"src/a.py": "x" * 40, "src/b.py": "y" * 40, "src/big.py": "z" * 40}
    measured = tiering.measure(items, SELECTION, "x", "ROOT", {}, files, 30)
    assert measured.files == ["src/a.py", "src/big.py", "src/b.py"] and measured.whole == measured.files and measured.heavy == {}


@pytest.mark.syngate("ORCHESTRATOR-TIER-PATH")
def test_a_heavy_file_is_its_path_and_line_count_under_every_item_naming_it():
    measured = tiering.measure(base(), SELECTION, "x", "ROOT", {}, contents(), 30)
    assert measured.whole == ["src/a.py", "src/b.py"]
    assert measured.heavy == {"src/big.py": "src/big.py (100 lines)"} == {"src/big.py": tiering.reference("src/big.py", contents()["src/big.py"])}
    assert measured.references == {"ROOT": [], "A": [], "C": ["src/big.py (100 lines)"], "B": ["src/big.py (100 lines)"]}


@pytest.mark.syngate("ORCHESTRATOR-TIER-AI")
def test_the_measurement_prepares_no_outline_or_excerpt_of_a_heavy_file():
    measured = tiering.measure(base(), SELECTION, "x", "ROOT", {}, contents(), 30)
    assert measured._fields == ("statements", "order", "files", "whole", "heavy", "references")
    assert "SECRET-LINE" not in repr(measured)


@pytest.mark.syngate("ORCHESTRATOR-TIER-BUDGET")
def test_the_budget_bounds_the_files_alone_and_takes_them_in_order_into_what_is_left():
    files = {"f1": "a" * 16, "f2": "b" * 80, "f3": "c" * 20, "empty": ""}
    assert tiering.take_files(["f1", "f2", "f3", "empty", "missing"], files, 10) == (["f1", "f3", "empty", "missing"], ["f2"])
    assert tiering.take_files(["f1", "empty"], files, 0) == (["empty"], ["f1"])
    items = tree(make("ROOT", "Root\n" + "statement " * 1000, sources=["f1"]), make("A", "A\n" + "statement " * 1000, ["ROOT"], ["f3"]))
    measured = tiering.measure(items, ["ROOT", "A"], "x", "ROOT", {}, files, 9)
    assert measured.whole == ["f1", "f3"] and measured.heavy == {}
