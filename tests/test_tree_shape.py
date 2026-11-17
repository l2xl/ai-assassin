# Open Trader
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Tests for syngatelib.load_tree + validate_structure tree-shape semantics -- [SYNGATE-TREE-LAYOUT]."""

import pytest
import yaml

import syngatelib


def _errors(syngate_dir):
    items, load_errors = syngatelib.load_tree(syngate_dir)
    return items, load_errors, syngatelib.validate_structure(items)


def _matching(errors, needle):
    return [e for e in errors if needle in e]


def _seed_minimal(syngate_dir, make_item):
    """One root branch with a single valid test-bearing leaf child."""
    make_item(syngate_dir, "ROOT-1", "the product shall exist", header="root")
    make_item(syngate_dir, "LEAF-1", "the leaf shall pass", parents=["ROOT-1"], tests=None)


def test_any_yaml_is_an_item_uid_is_stem_folders_meaningless(syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT-1", "root shall be here", header="root")
    make_item(syngate_dir / "deep" / "nested", "LEAF-1", "the leaf shall pass", parents=["ROOT-1"], tests=None)
    items, load_errors, errors = _errors(syngate_dir)
    assert load_errors == []
    assert set(items) == {"ROOT-1", "LEAF-1"}
    assert items["LEAF-1"].uid == "LEAF-1"
    assert errors == []


def test_bare_feature_name_without_numbered_suffix_is_a_valid_uid(syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT-1", "root shall be here", header="root")
    make_item(syngate_dir, "EXCHANGE", "exchange integrations shall be grouped here", parents=["ROOT-1"])
    make_item(syngate_dir, "EXCHANGE-1", "the leaf shall pass", parents=["EXCHANGE"], tests=None)
    _items, load_errors, errors = _errors(syngate_dir)
    assert load_errors == []
    assert errors == []


def test_duplicate_stem_across_folders_is_rejected(syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir / "a", "ROOT-1", "root shall be one", header="root")
    make_item(syngate_dir / "b", "ROOT-1", "root shall be two", header="dup")
    _items, load_errors, _errs = _errors(syngate_dir)
    assert _matching(load_errors, "duplicate UID")


def test_unknown_field_is_rejected(syngate_tree):
    syngate_dir, make_item = syngate_tree
    _seed_minimal(syngate_dir, make_item)
    (syngate_dir / "LEAF-1.yml").write_text(
        yaml.safe_dump({"header": "x", "description": "the leaf shall pass", "parents": ["ROOT-1"], "tests": None, "bogus": 1}),
        encoding="utf-8",
    )
    _items, load_errors, _errs = _errors(syngate_dir)
    assert _matching(load_errors, "unknown field 'bogus'")


def test_unknown_parent_is_rejected(syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT-1", "root shall exist", header="root")
    make_item(syngate_dir, "LEAF-1", "the leaf shall pass", parents=["MISSING-9"], tests=None)
    _items, _load_errors, errors = _errors(syngate_dir)
    assert _matching(errors, "unknown parent 'MISSING-9'")


def test_exactly_one_root_required(syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT-1", "root a shall exist", header="a")
    make_item(syngate_dir, "ROOT-2", "root b shall exist", header="b")
    _items, _load_errors, errors = _errors(syngate_dir)
    assert _matching(errors, "expected exactly one root")


def test_multi_parent_dag_is_allowed(syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT-1", "root shall exist", header="root")
    make_item(syngate_dir, "A-1", "branch a shall exist", parents=["ROOT-1"])
    make_item(syngate_dir, "B-1", "branch b shall exist", parents=["ROOT-1"])
    make_item(syngate_dir, "C-1", "the leaf shall pass", parents=["A-1", "B-1"], tests=None)
    _items, load_errors, errors = _errors(syngate_dir)
    assert load_errors == []
    assert errors == []


def test_cycle_is_rejected(syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT-1", "root shall pass", header="root", tests=None)
    make_item(syngate_dir, "X-1", "branch x shall exist", parents=["Y-1"])
    make_item(syngate_dir, "Y-1", "branch y shall exist", parents=["X-1"])
    _items, _load_errors, errors = _errors(syngate_dir)
    assert _matching(errors, "cycle")


@pytest.mark.syngate("SYNGATE-TEST-BEARING-BRANCH")
def test_a_branch_passes_only_with_its_own_tests_and_its_children(syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT-1", "root shall pass", header="root", tests=None)
    make_item(syngate_dir, "LEAF-1", "the leaf shall pass", parents=["ROOT-1"], tests=None)
    items, load_errors, errors = _errors(syngate_dir)
    assert not load_errors and not errors
    passed = [{"passed": True, "name": "", "log": ""}]

    def test_axis(records):
        return syngatelib.compute_axes(items, records)["ROOT-1"]["test"]

    assert test_axis({("LEAF-1", None): passed}) == "unknown"  # the branch's own binding never ran
    assert test_axis({("ROOT-1", None): passed}) == "unknown"
    assert test_axis({("ROOT-1", None): passed, ("LEAF-1", None): passed}) == "test_passed"
    assert test_axis({("ROOT-1", None): [{"passed": False, "name": "", "log": ""}], ("LEAF-1", None): passed}) == "test_failed"
    assert syngatelib.compute_status(items, {("LEAF-1", None): passed})["ROOT-1"]["status"] == "partially_implemented"
    items["ROOT-1"].tests = {None: "a" * 64}
    items["ROOT-1"].reviewed = syngatelib.compute_stamp(items["ROOT-1"])
    assert syngatelib.compute_axes(items, {})["ROOT-1"]["review"] == "not_reviewed"  # LEAF-1 still is not
    problems = syngatelib.item_problems(items, {})  # the stamped routine is gone
    assert list(problems) == ["ROOT-1"]
    axes = syngatelib.compute_axes(items, {("ROOT-1", None): passed, ("LEAF-1", None): passed}, problems)["ROOT-1"]
    assert axes == {"test": "test_passed", "review": "review_violated"}  # a violated review never touches the test axis


def test_childless_item_without_tests_is_structurally_valid(syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT-1", "root shall exist", header="root")
    make_item(syngate_dir, "STUB-1", "not planned yet", parents=["ROOT-1"])
    _items, _load_errors, errors = _errors(syngate_dir)
    assert errors == []


def test_leaf_description_wording_is_unconstrained(syngate_tree):
    """No 'shall' wording rule: a wording nit is not a review-status or test
    failure, so it must not redden an item."""
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT-1", "root shall exist", header="root")
    make_item(syngate_dir, "LEAF-1", "the leaf just passes, no matter the wording", parents=["ROOT-1"], tests=None)
    _items, _load_errors, errors = _errors(syngate_dir)
    assert errors == []


@pytest.mark.syngate("SYNGATE-STAMP-FORMAT")
def test_malformed_reviewed_stamp_reads_as_absent(syngate_tree):
    syngate_dir, make_item = syngate_tree
    _seed_minimal(syngate_dir, make_item)
    make_item(syngate_dir, "ROOT-1", "the product shall exist", header="root", reviewed="not-a-sha")
    items, load_errors, _errs = _errors(syngate_dir)
    assert not _matching(load_errors, "review")
    assert items["ROOT-1"].reviewed is None


def test_reviewed_stamp_must_match_computed_content(syngate_tree):
    syngate_dir, make_item = syngate_tree
    _seed_minimal(syngate_dir, make_item)
    items, _load_errors = syngatelib.load_tree(syngate_dir)
    good = syngatelib.item_stamp(items, "ROOT-1")  # ROOT-1 has a child, and the child set is inside the stamp

    make_item(syngate_dir, "ROOT-1", "the product shall exist", header="root", reviewed=good)
    _items, load_errors, errors = _errors(syngate_dir)
    assert load_errors == []
    assert _matching(errors, "reviewed") == []

    make_item(syngate_dir, "ROOT-1", "the product shall exist", header="root", reviewed="0" * 64)
    _items, _load_errors, errors = _errors(syngate_dir)
    assert _matching(errors, "reviewed stamp does not match")


def test_review_state_is_attributed_to_the_item_that_carries_it(syngate_tree):
    """A stale stamp is a defect of its own item: it is a review problem, never a
    layout one, so it cannot redden whatever item covers the layout."""
    syngate_dir, make_item = syngate_tree
    _seed_minimal(syngate_dir, make_item)
    make_item(syngate_dir, "ROOT-1", "the product shall exist", header="root", reviewed="0" * 64)
    items, load_errors = syngatelib.load_tree(syngate_dir)
    assert load_errors == []

    assert syngatelib.validate_layout(items) == []
    assert _matching(syngatelib.validate_structure(items), "reviewed stamp does not match")
    assert _matching(syngatelib.item_problems(items)["ROOT-1"], "reviewed stamp does not match")
    assert "LEAF-1" not in syngatelib.item_problems(items)


@pytest.mark.syngate("SYNGATE-TREE-LAYOUT")
def test_live_syngate_tree_has_a_valid_layout():
    """The real syngate/ tree loads and satisfies the layout this item
    describes: UIDs are file stems and `parents` forms a DAG with one root.

    Review state is deliberately out of scope here. A stale stamp or a drifted
    frozen routine is the tree's data; the status rollup reddens the item that
    carries it. Detecting such a violation is this item working, so
    asserting the tree is clean here would redden SYNGATE for another item's fault.
    """
    items, load_errors = syngatelib.load_tree()
    assert load_errors == []
    assert syngatelib.validate_layout(items) == []


@pytest.mark.syngate("SYNGATE-010")
def test_walk_selects_ancestors_root_first_then_descendants_each_uid_once(syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT-1", "root", header="root")
    make_item(syngate_dir, "SIDE-B", "side b", parents=["ROOT-1"], order=20)
    make_item(syngate_dir, "SIDE-A", "side a", parents=["ROOT-1"], order=10)
    make_item(syngate_dir, "MID-1", "mid", parents=["SIDE-B", "SIDE-A"])
    make_item(syngate_dir, "LEAF-2", "the leaf shall two", parents=["MID-1"], order=20, tests=None)
    make_item(syngate_dir, "LEAF-1", "the leaf shall one", parents=["MID-1"], order=10, tests=None)
    items, _ = syngatelib.load_tree(syngate_dir)
    assert syngatelib.walk(items, "MID-1") == ["ROOT-1", "SIDE-B", "SIDE-A", "MID-1"]
    assert syngatelib.walk(items, "MID-1", descendants=True) == ["ROOT-1", "SIDE-B", "SIDE-A", "MID-1", "LEAF-1", "LEAF-2"]
    assert syngatelib.walk(items, "LEAF-2") == ["ROOT-1", "SIDE-B", "SIDE-A", "MID-1", "LEAF-2"]
    assert syngatelib.walk(items) == ["ROOT-1", "SIDE-A", "MID-1", "LEAF-1", "LEAF-2", "SIDE-B"]


@pytest.mark.syngate("SYNGATE-FEATURE-SWITCHES")
def test_the_root_switches_the_test_and_review_features_both_off_when_absent(syngate_tree):
    syngate_dir, make_item = syngate_tree
    (syngate_dir / "ROOT-1.yml").write_text(yaml.safe_dump({"header": "root", "description": "root shall exist", "parents": []}), encoding="utf-8")
    make_item(syngate_dir, "LEAF-1", "the leaf shall pass", parents=["ROOT-1"], tests=None)
    make_item(syngate_dir, "STAMPED-1", "approved", parents=["ROOT-1"], reviewed="0" * 64)
    items, load_errors, errors = _errors(syngate_dir)
    assert load_errors == [] and syngatelib.features(items) == {"test": False, "review": False}
    assert not _matching(errors, "feature")
    make_item(syngate_dir, "ROOT-1", "root shall exist", header="root", features=("test",))
    items, load_errors, errors = _errors(syngate_dir)
    assert load_errors == [] and syngatelib.features(items) == {"test": True, "review": False}
    assert not _matching(errors, "feature")
    make_item(syngate_dir, "ROOT-1", "root shall exist", header="root", tests=None, reviewed="0" * 64)  # the root's own binding and stamp switch both on
    items, load_errors, errors = _errors(syngate_dir)
    assert load_errors == [] and syngatelib.features(items) == {"test": True, "review": True} and not _matching(errors, "feature is off")
    make_item(syngate_dir, "LEAF-1", "the leaf shall pass", parents=["ROOT-1"], tests="disabled")  # an item below the root switches its own subtree
    items, load_errors, _errs = _errors(syngate_dir)
    assert load_errors == [] and syngatelib.features(items) == {"test": True, "review": True} and syngatelib.features(items, "LEAF-1") == {"test": False, "review": True}


@pytest.mark.syngate("SYNGATE-SWITCH-OVERRIDE")
def test_a_switch_below_the_root_sets_the_feature_for_its_item_and_everything_below_it(syngate_tree):
    syngate_dir, make_item = syngate_tree
    on, off, uids = {"test": True, "review": True}, {"test": False, "review": False}, ("ROOT-1", "PLAIN-1", "SUB-1", "MID-1", "LEAF-1")
    make_item(syngate_dir, "ROOT-1", "root shall exist", header="root", features=())
    make_item(syngate_dir, "SUB-1", "sub shall gate", parents=["ROOT-1"], tests="enabled", reviewed="enabled")
    make_item(syngate_dir, "MID-1", "mid shall group", parents=["SUB-1"])
    make_item(syngate_dir, "LEAF-1", "the leaf shall pass", parents=["MID-1"], tests=None, reviewed="0" * 64)
    make_item(syngate_dir, "PLAIN-1", "plain shall stay", parents=["ROOT-1"])
    items, load_errors, errors = _errors(syngate_dir)
    assert load_errors == [] and not _matching(errors, "feature")
    assert [syngatelib.features(items, uid) for uid in uids] == [off, off, on, on, on]
    assert (items["SUB-1"].tests, items["SUB-1"].reviewed) == (None, None)  # the word stands in the key's place
    assert syngatelib.parse_item(syngatelib.dump_item(items["SUB-1"])) == {"description": "sub shall gate\n", "parents": ["ROOT-1"], "test": "enabled", "review": "enabled"}
    assert syngatelib.stampable(items) == {"SUB-1", "MID-1", "LEAF-1"}  # the item carrying the switch is stamped like any other
    items["SUB-1"].reviewed = syngatelib.item_stamp(items, "SUB-1")  # the stamp takes the word's place, and clearing it puts the word back
    assert syngatelib.parse_item(syngatelib.dump_item(items["SUB-1"]))["review"] == items["SUB-1"].reviewed and syngatelib.features(items, "MID-1")["review"] is True
    syngatelib.clear_review(items["SUB-1"], items)
    assert syngatelib.parse_item(syngatelib.dump_item(items["SUB-1"]))["review"] == "enabled"
    make_item(syngate_dir, "ROOT-1", "root shall exist", header="root")
    make_item(syngate_dir, "SUB-1", "sub shall gate", parents=["ROOT-1"], tests="disabled", reviewed="disabled")
    items, load_errors, errors = _errors(syngate_dir)
    assert load_errors == [] and [syngatelib.features(items, uid) for uid in uids] == [on, on, off, off, on]  # a misplaced switch still reads as set, and is reported
    assert _matching(errors, "one override per path") == ["LEAF-1: a test binding under an item that already overrides the test feature (one override per path)",
                                                          "LEAF-1: a review stamp under an item that already overrides the review feature (one override per path)"]


@pytest.mark.syngate("SYNGATE-SWITCH-MARK")
def test_a_binding_or_stamp_under_parents_with_the_feature_off_switches_it_on_for_the_subtree(syngate_tree):
    syngate_dir, make_item = syngate_tree
    on, off = {"test": True, "review": True}, {"test": False, "review": False}
    make_item(syngate_dir, "ROOT-1", "root shall exist", header="root", features=())
    make_item(syngate_dir, "SUB-1", "sub shall gate", parents=["ROOT-1"], tests=None, reviewed="0" * 64)
    make_item(syngate_dir, "LEAF-1", "the leaf shall pass", parents=["SUB-1"])
    make_item(syngate_dir, "PLAIN-1", "plain shall stay", parents=["ROOT-1"])
    items, load_errors, errors = _errors(syngate_dir)
    assert load_errors == [] and not _matching(errors, "feature")
    assert [syngatelib.features(items, uid) for uid in ("ROOT-1", "PLAIN-1", "SUB-1", "LEAF-1")] == [off, off, on, on]
    assert syngatelib.stampable(items) == {"SUB-1", "LEAF-1"}
    syngatelib.clear_review(items["SUB-1"], items)  # the dropped stamp leaves the word, so the subtree stays gated
    assert syngatelib.parse_item(syngatelib.dump_item(items["SUB-1"])) == {"description": "sub shall gate\n", "parents": ["ROOT-1"], "test": None, "review": "enabled"}
    assert syngatelib.features(items, "LEAF-1") == on
    syngatelib.edit_item(items, "PLAIN-1", {"tests": [""]})  # bindings given through an edit make the same switch
    assert syngatelib.features(items, "PLAIN-1") == {"test": True, "review": False}
    make_item(syngate_dir, "ROOT-1", "root shall exist", header="root")  # under parents handing the feature on, the key is the item's plain one
    items, load_errors, errors = _errors(syngate_dir)
    assert load_errors == [] and not _matching(errors, "feature")
    syngatelib.clear_review(items["SUB-1"], items)
    assert "review" not in syngatelib.parse_item(syngatelib.dump_item(items["SUB-1"]))
    make_item(syngate_dir, "OFF-1", "off shall free", parents=["ROOT-1"], tests="disabled", reviewed="disabled")  # an override is never overridden back
    make_item(syngate_dir, "SUB-1", "sub shall gate", parents=["OFF-1"], tests=None, reviewed="0" * 64)
    make_item(syngate_dir, "FREE-1", "free shall stay", parents=["OFF-1"])
    items, load_errors, errors = _errors(syngate_dir)
    assert load_errors == [] and _matching(errors, "one override per path") == ["SUB-1: a test binding under an item that already overrides the test feature (one override per path)",
                                                                                "SUB-1: a review stamp under an item that already overrides the review feature (one override per path)"]
    with pytest.raises(syngatelib.tree_error, match="one override per path"):
        syngatelib.edit_item(items, "FREE-1", {"tests": [""]})


@pytest.mark.syngate("SYNGATE-SWITCH-ONCE")
def test_a_switch_under_an_override_or_repeating_what_it_inherits_is_a_layout_problem(syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT-1", "root shall exist", header="root", features=("review",))
    make_item(syngate_dir, "SUB-1", "sub shall gate", parents=["ROOT-1"], tests="enabled")
    make_item(syngate_dir, "DEEP-1", "deep shall not switch back", parents=["SUB-1"], tests="disabled")
    make_item(syngate_dir, "SAME-1", "same shall not repeat", parents=["ROOT-1"], reviewed="enabled")
    items, load_errors, errors = _errors(syngate_dir)
    assert load_errors == [] and not _matching(errors, "SUB-1")
    assert _matching(errors, "DEEP-1") == ["DEEP-1: 'test: disabled' under an item that already overrides the test feature (one override per path)"]
    assert _matching(errors, "SAME-1") == ["SAME-1: 'review: enabled' repeats what the item inherits"]
    assert set(syngatelib.item_problems(items)) == {"DEEP-1", "SAME-1"}


@pytest.mark.syngate("SYNGATE-SWITCH-CONFLICT")
def test_an_item_whose_parents_hand_it_different_values_of_a_feature_is_red_and_reads_it_as_on(syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT-1", "root shall exist", header="root", features=("review",))
    make_item(syngate_dir, "ON-1", "on shall test", parents=["ROOT-1"], tests="enabled")
    make_item(syngate_dir, "OFF-1", "off shall not", parents=["ROOT-1"])
    make_item(syngate_dir, "MEET-1", "meet shall be settled", parents=["ON-1", "OFF-1"], tests=None)
    make_item(syngate_dir, "BELOW-1", "below shall follow", parents=["MEET-1"], tests=None)
    items, load_errors, errors = _errors(syngate_dir)
    assert load_errors == [] and _matching(errors, "MEET-1") == ["MEET-1: the test feature is enabled through ON-1 and disabled through OFF-1"]
    assert syngatelib.features(items, "MEET-1")["test"] is True and not _matching(errors, "BELOW-1")  # reported once, where the paths meet
    problems = syngatelib.item_problems(items)
    assert set(problems) == {"MEET-1"}
    assert syngatelib.compute_status(items, {}, problems)["MEET-1"]["status"] == syngatelib.TEST_FAILED
    assert syngatelib.compute_axes(items, {}, problems)["MEET-1"]["review"] == syngatelib.REVIEW_VIOLATED
    make_item(syngate_dir, "MEET-1", "meet shall be settled", parents=["ON-1"], tests=None)  # the user's settlement: one link dropped
    items, _load_errors, errors = _errors(syngate_dir)
    assert not _matching(errors, "MEET-1")


@pytest.mark.syngate("SYNGATE-KEY-SPELLING")
def test_bindings_and_stamp_are_read_from_test_and_review_and_their_old_spellings_and_written_back_new(syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT-1", "root shall exist", header="root")
    sha, stamp = "a" * 64, "b" * 64
    (syngate_dir / "OLD-1.yml").write_text(yaml.safe_dump({"header": "old", "description": "old shall bind", "parents": ["ROOT-1"], "tests": {"a": sha}, "reviewed": stamp}), encoding="utf-8")
    (syngate_dir / "NEW-1.yml").write_text(yaml.safe_dump({"header": "new", "description": "new shall bind", "parents": ["ROOT-1"], "test": {"a": sha}, "review": stamp}), encoding="utf-8")
    (syngate_dir / "BOTH-1.yml").write_text(yaml.safe_dump({"header": "both", "description": "both shall not", "parents": ["ROOT-1"], "test": None, "tests": None}), encoding="utf-8")
    items, load_errors = syngatelib.load_tree(syngate_dir)
    assert load_errors == ["BOTH-1: both 'test' and its old spelling 'tests'"]
    assert (items["OLD-1"].tests, items["OLD-1"].reviewed) == ({"a": sha}, stamp) == (items["NEW-1"].tests, items["NEW-1"].reviewed)
    assert syngatelib.parse_item(syngatelib.dump_item(items["OLD-1"])) == {"description": "old\n\nold shall bind\n", "parents": ["ROOT-1"], "test": {"a": sha}, "review": stamp}
    assert syngatelib.parse_item(syngatelib.dump_item(items["ROOT-1"])) == {"description": "root\n\nroot shall exist\n", "parents": [], "test": "enabled", "review": "enabled"}
    items["ROOT-1"].features["review"] = False
    assert syngatelib.parse_item(syngatelib.dump_item(items["ROOT-1"]))["review"] == "disabled"


def test_an_item_is_a_front_matter_of_attributes_over_a_body_whose_first_line_is_its_title_and_a_legacy_flat_mapping_reads_the_same(syngate_tree):
    syngate_dir, make_item = syngate_tree
    make_item(syngate_dir, "ROOT-1", "root shall exist", header="root")
    stamp = "b" * 64
    body = "New shape\n\nIt shall read.\n\nTwice.\n"
    front_matter = f"---\nparents: [ROOT-1]\norder: 10\nsources: [src/new.py, docs/NEW.md]\ntest: ~\nreview: {stamp}\n---\n{body}"
    (syngate_dir / "NEW-1.yml").write_text(front_matter, encoding="utf-8")
    make_item(syngate_dir, "OLD-1", "It shall read.\n\nTwice.\n", header="New shape", parents=["ROOT-1"], order=10, tests=None, reviewed=stamp)
    (syngate_dir / "BARE-1.yml").write_text("---\nparents: [ROOT-1]\n---\n  Bare  \nIt shall follow without a blank line.\n", encoding="utf-8")
    (syngate_dir / "ATTR-1.yml").write_text("---\nheader: Misplaced\nparents: [ROOT-1]\n---\nIt shall be refused.\n", encoding="utf-8")
    (syngate_dir / "AWAY-1.yml").write_text("---\nparents: [ROOT-1]\nsources: [../secret]\n---\nIt shall list no file outside the project.\n", encoding="utf-8")
    items, load_errors = syngatelib.load_tree(syngate_dir)
    assert load_errors == ["ATTR-1: 'header' is the body of a front-matter item, not an attribute", "AWAY-1: '../secret' is not a normalised root-relative path"]
    new, old = items["NEW-1"], items["OLD-1"]
    assert (new.description, new.title, new.order, new.sources, new.tests, new.reviewed) == (body, "New shape", 10, ["src/new.py", "docs/NEW.md"], {None: None}, stamp)
    assert (old.description, old.sources) == (body, []) and items["AWAY-1"].sources == []
    assert syngatelib.compute_stamp(new) == syngatelib.compute_stamp(old)  # the header folded into the body, the sources outside the stamp
    assert (items["BARE-1"].title, items["BARE-1"].description) == ("Bare", "  Bare  \nIt shall follow without a blank line.\n")
    assert syngatelib.dump_item(new) == front_matter  # the writer emits the front-matter shape, the stamp standing
    assert syngatelib.dump_item(old) == front_matter.replace("sources: [src/new.py, docs/NEW.md]\n", "")
    syngatelib.write_item(items["BARE-1"])
    assert (syngate_dir / "BARE-1.yml").read_text() == "---\nparents: [ROOT-1]\n---\n  Bare  \nIt shall follow without a blank line.\n"
