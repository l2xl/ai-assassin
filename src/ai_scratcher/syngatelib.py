# Open Trader
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Synergy Context Gate (syngate) toolkit core (no doorstop).

Tree layout: every `*.yml` under `syngate/` (any depth) is a syngate item; the
UID is the file stem; folders carry no semantics. Item file: a YAML front matter
of attributes over a markdown body, the body being the item's statement (its
`description`) and the body's first line naming it in the outline (its `title`):

    ---
    parents: [UID, ...]        # DAG edges; exactly one item in the tree has none
    order: 10                  # optional presentation-only sibling sort key
    sources: [src/a.py, ...]   # optional root-relative key source files, read into the seed context
    test: ~ | <sha> | {name: sha|~, ...}   # test bindings; absent on items without own tests
    test: {stamp: <bindings>, run: CMD, files: [GLOB], report: FORMAT, env: {K: V}}   # or a setup, bindings under `stamp`
    review: <sha256 hex>       # user-only approval stamp, or absent; a malformed stamp reads as absent
    ---
    One-line title

    Free-form markdown prose.

A legacy file is one flat mapping holding `header` and `description` as keys next
to the attributes; its header reads as the first line of the body and the file
takes the front-matter shape when written back. The old spellings `tests` /
`reviewed` are read as the same keys. On the root item (empty parents)
`test: enabled|disabled` and `review: enabled|disabled` switch the tree's test
and review features; both are off when absent, and a root's own binding or stamp
switches its feature on as well. The same words on an item below the root
override the feature for that item and its subtree, once per path, and so does
a binding or a stamp of an item whose parents all hand it the feature off.

A binding is identified purely by tags: the default binding is the `[UID]` tag
alone, a named binding is the `[UID][name]` tag pair (binding name immediately
after the UID tag; item tags go last in the tag list). Test locations are
discovered from tags at check time, never declared in items.

The reviewed stamp is transparent: sha256 hex over the canonical JSON
    {"children": [UID, ...], "description": ..., "header": ..., "parents": [...], "setup": {...}, "tests": {name: sha} | null}
serialized with sort_keys=True, separators=(",", ":"), ensure_ascii=False,
UTF-8 encoded (default binding name is ""; unstamped shas are ""). "header" is
the body's first line and "description" the rest past one blank line -- the split
the body carried as two fields before -- so the stamps of that time stand.
"children" holds the immediate child UIDs and is present only for an item that
has any, so adding or removing a child moves its parent's stamp. "setup" holds the item's own test setup (run, files, report, env,
absent keys left out) and is present only on an item carrying one. Verify with:
    python3 -c 'import syngatelib,sys; items,_=syngatelib.load_tree(); print(syngatelib.item_stamp(items, sys.argv[1]))' <UID>

Coverage joins `syngate_coverage.jsonl` records `{"tags": [...], "passed": bool}`
(optional "name"/"log") emitted by the pytest conftest hook and the Catch2
listener against the items' `tests` bindings.
"""

import ast
import fnmatch
import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml



def find_root(start=None):
    """Managed project root: `start` when given, else SYNGATE_ROOT, else the nearest ancestor of the working directory holding a syngate/ folder."""
    if start:
        return Path(start).resolve()
    if os.environ.get("SYNGATE_ROOT"):
        return Path(os.environ["SYNGATE_ROOT"]).resolve()
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if (candidate / "syngate").is_dir():
            return candidate
    raise FileNotFoundError(f"no syngate/ folder above {here}; pass --root or set SYNGATE_ROOT")


def set_root(root=None):
    """Bind the module to one managed project; the CLI calls it once after parsing --root."""
    global ROOT, SYNGATE_DIR
    ROOT = find_root(root)
    SYNGATE_DIR = ROOT / "syngate"
    return ROOT


try:
    ROOT = find_root()
except FileNotFoundError:
    ROOT = Path.cwd()
SYNGATE_DIR = ROOT / "syngate"

UID_RE = re.compile(r"^[A-Z](?:[A-Z0-9_-]*[A-Z0-9])?$")
BINDING_NAME_RE = re.compile(r"^[a-z0-9_]+$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
KNOWN_FIELDS = {"header", "description", "parents", "order", "sources", "test", "review", "tests", "reviewed"}
BODY_FIELDS = ("header", "description")  # the legacy spelling of the body; refused as attributes of a front matter
FRONT_MATTER_RE = re.compile(r"\A---[ \t]*\n(.*?)^---[ \t]*(?:\n|\Z)", re.DOTALL | re.MULTILINE)
FEATURES = ("test", "review")
SWITCH = {"enabled": True, "disabled": False}
SETUP_KEYS = ("run", "files", "report", "env")
SETUP_STAMP = "stamp"  # the key of a setup holding the item's own bindings; refused as a binding name
LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)

PY_TEST_DIRS = ("scripts/tests", "tests")
CPP_TEST_DIRS = ("test",)

NOT_IMPLEMENTED = "not_implemented"
PARTIALLY_IMPLEMENTED = "partially_implemented"
TEST_PASSED = "test_passed"
TEST_FAILED = "test_failed"
UNKNOWN = "unknown"
NOT_REVIEWED = "not_reviewed"
REVIEWED = "reviewed"
REVIEW_VIOLATED = "review_violated"
# Rollup precedence of the two status axes: the first state present among the children wins.
TEST_RANK = (TEST_FAILED, UNKNOWN, TEST_PASSED)
REVIEW_RANK = (REVIEW_VIOLATED, NOT_REVIEWED, REVIEWED)


@dataclass
class Item:
    uid: str
    path: Path
    description: str = ""
    parents: list = field(default_factory=list)
    order: float = 0
    sources: list = field(default_factory=list)
    tests: dict = None  # None = branch (no tests key); {name|None: sha|None} otherwise
    reviewed: str = None
    folder: str = ""
    features: dict = field(default_factory=lambda: dict.fromkeys(FEATURES))  # the switch each feature key carries on this item, None where it carries none
    setup: dict = None  # the item's own test setup -- run, files, report, env, absent keys left out -- or None
    setup_extra: dict = field(default_factory=dict)  # the unknown keys of the setup, kept to be written back and reported as layout problems

    @property
    def is_leaf(self):
        return self.tests is not None

    @property
    def title(self):
        return self.description.partition("\n")[0].strip()


def features(items, uid=None):
    """{"test": bool, "review": bool} -- the feature switches declared on the tree's root item, both off when absent; with `uid`, the
    features of that item as the switches above it set them."""
    if uid is not None:
        return feature_scopes(items)[0].get(uid, dict.fromkeys(FEATURES, False))
    switches = dict.fromkeys(FEATURES, False)
    for item in items.values():
        if not item.parents:
            switches.update((feature, switches[feature] or bool(on)) for feature, on in item.features.items())
    return switches


def holds_key(item, feature):
    """Whether the item holds a binding, a test setup or a stamp of its own in the feature's key."""
    return (item.tests is not None or item.setup is not None) if feature == "test" else bool(item.reviewed)


def carries_switch(item, feature):
    """Whether an item below the root holds a switch word in the feature's key, no binding or stamp of its own having taken its place."""
    return bool(item.parents) and item.features.get(feature) is not None and not holds_key(item, feature)


def enable_mark(items, uid, feature):
    """Whether the item's own binding or stamp is what switches the feature on for its subtree: it holds one while every parent hands it the feature off."""
    item, scopes = items[uid], feature_scopes(items)[0]
    parents = [parent for parent in item.parents if parent in items and parent != uid]
    return holds_key(item, feature) and bool(parents) and not any(scopes[parent][feature] for parent in parents)


def feature_scopes(items):
    """({uid: {"test": bool, "review": bool}}, [(uid, message)]) -- every item's features and the misplaced switches. The root sets
    the value of the tree, off when absent; an item below it carrying a switch sets it for itself and everything below, once per
    path: a switch under an override, or repeating what the item inherits, is a problem of the item carrying it. A binding or a
    stamp of an item whose parents all hand it the feature off is such a switch, reading 'enabled'; elsewhere it is the item's plain
    key. An item whose parents hand it different values is a problem of its own and reads the feature as on, so nothing below it is
    reported twice."""
    scopes, overridden, problems = {}, {}, []

    def scope(uid):
        if uid in scopes:
            return
        item = items[uid]
        scopes[uid], overridden[uid] = dict.fromkeys(FEATURES, False), dict.fromkeys(FEATURES, False)  # cycle guard
        parents = [parent for parent in dict.fromkeys(item.parents) if parent in items and parent != uid]
        for parent in parents:
            scope(parent)
        for feature in FEATURES:
            own, keyed = item.features.get(feature), holds_key(item, feature)
            if not item.parents:
                scopes[uid][feature] = bool(own)
                continue
            on, off = ([parent for parent in parents if scopes[parent][feature] is value] for value in (True, False))
            nested = any(overridden[parent][feature] for parent in parents)
            if on and off:
                problems.append((uid, f"{uid}: the {feature} feature is enabled through {', '.join(on)} and disabled through {', '.join(off)}"))
            if keyed:  # the key holds no word: it switches the feature on where every parent hands it off, and is the item's plain key elsewhere
                own = True if parents and not on else None
            if own is None:
                scopes[uid][feature], overridden[uid][feature] = bool(on), nested
                continue
            switch = f"a {'review stamp' if feature == 'review' else 'test setup' if item.setup is not None else 'test binding'}" if keyed else f"'{feature}: {'enabled' if own else 'disabled'}'"
            if nested:
                problems.append((uid, f"{uid}: {switch} under an item that already overrides the {feature} feature (one override per path)"))
            elif parents and not (off if own else on):
                problems.append((uid, f"{uid}: {switch} repeats what the item inherits"))
            scopes[uid][feature], overridden[uid][feature] = bool(own), True

    for uid in sorted(items):
        scope(uid)
    return scopes, problems


def setup_scopes(items):
    """{uid: the UID of the item whose test setup holds for it, None for the built-in one} -- a setup holds for its item and
    everything below up to the next setup, the nearest one whole; an item carrying none takes the setup of its first parent."""
    scopes = {}

    def scope(uid):
        if uid not in scopes:
            scopes[uid] = uid if items[uid].setup is not None else None  # cycle guard
            if items[uid].setup is None:
                known = [parent for parent in items[uid].parents if parent in items and parent != uid]
                scopes[uid] = scope(known[0]) if known else None
        return scopes[uid]

    for uid in sorted(items):
        scope(uid)
    return scopes


def stampable(items):
    """The UIDs a review stamps: the items whose review feature is on, the one holding the switch of its subtree among them."""
    scopes = feature_scopes(items)[0]
    return {uid for uid in items if scopes[uid]["review"]}


def _silent(children, problems, own):
    """silent(uid) -- whether an item stands outside a status rollup: no state of its `own`, no problem, and nothing but such items below."""
    memo = {}

    def silent(uid):
        if uid not in memo:
            memo[uid] = True  # cycle guard
            memo[uid] = not (own(uid) or problems.get(uid)) and all(silent(child) for child in children[uid])
        return memo[uid]

    return silent


@dataclass
class Location:
    path: str  # repo-relative
    line: int  # 1-based first line of the routine
    name: str  # test routine / case identifier
    span: str  # raw source span hashed for the freeze
    routine: str = ""  # bare name of the routine, as a runner selects it; "" where discovery tells none


def _parse_tests(value, errors, uid):
    if isinstance(value, dict):
        tests = {}
        for name, sha in value.items():
            if not isinstance(name, str) or not BINDING_NAME_RE.match(name) or name == SETUP_STAMP:
                errors.append(f"{uid}: invalid binding name {name!r}")
                continue
            tests[name] = _parse_sha(sha, errors, uid)
        return tests
    return {None: _parse_sha(value, errors, uid)}


def _binding_value(value):
    """Whether a value is one a binding takes: `~` or a sha256 hex."""
    return value is None or isinstance(value, str) and bool(SHA_RE.match(value))


def is_setup(value):
    """Whether a `test` value is a setup rather than a mapping of bindings: it holds `stamp`, or a setup key with no binding value."""
    return isinstance(value, dict) and (SETUP_STAMP in value or any(key in value and not _binding_value(value[key]) for key in SETUP_KEYS))


def _parse_sha(sha, errors, uid):
    if sha is None:
        return None
    if not isinstance(sha, str) or not SHA_RE.match(sha):
        errors.append(f"{uid}: invalid routine sha {sha!r}")
        return None
    return sha


def _parse_stamp(value, errors, uid):
    if isinstance(value, str) and SHA_RE.match(value):
        return value
    return None


def _keyed(data, key, legacy, errors, uid):
    """(present, value) of `key`, or of its old spelling `legacy`."""
    if key in data and legacy in data:
        errors.append(f"{uid}: both '{key}' and its old spelling '{legacy}'")
    for name in (key, legacy):
        if name in data:
            return True, data[name]
    return False, None


def _read_feature(item, data, key, legacy, parse, errors):
    """A switch word sets the feature -- on the root item for the tree, below it for the item's subtree; any other present value is the item's own binding or stamp, which on the root switches its feature on."""
    present, value = _keyed(data, key, legacy, errors, item.uid)
    if not present:
        return None
    if isinstance(value, str) and value in SWITCH:
        item.features[key] = SWITCH[value]
        return None
    if key == "test" and is_setup(value):  # the setup stands where 'enabled' would, its bindings under `stamp`
        item.setup = {name: value[name] for name in SETUP_KEYS if name in value}
        item.setup_extra = {name: setting for name, setting in value.items() if name not in SETUP_KEYS and name != SETUP_STAMP}
        if not item.parents:
            item.features[key] = True
        return parse(value[SETUP_STAMP], errors, item.uid) if SETUP_STAMP in value else None
    if not item.parents:
        item.features[key] = True
    return parse(value, errors, item.uid)


def _split_body(body):
    """(first line, the rest past one blank line): the two fields the body was before, as the review stamp still reads it."""
    header, _, description = body.partition("\n")
    return header.strip(), description.removeprefix("\n")


def _join_body(header, description):
    """The body of a legacy item: its header as the first line over its description, kept byte for byte so its stamp stands."""
    header, description = str(header or "").strip(), str(description or "")
    return f"{header}\n\n{description}" if header and description else header + "\n" if header else description


def parse_item(text):
    """The fields of an item file in the flat spelling `load_tree` reads: the front matter's attributes with the body as
    `description`, or the mapping of a legacy file with its `header` folded into the description as the first line."""
    match = FRONT_MATTER_RE.match(text)
    if not match:
        data = yaml.safe_load(text)
        if isinstance(data, dict) and "header" in data:
            data["description"] = _join_body(data.pop("header"), data.get("description"))
        return data
    data = yaml.safe_load(match.group(1)) or {}
    if isinstance(data, dict):
        for key in BODY_FIELDS:
            if key in data:
                raise ValueError(f"'{key}' is the body of a front-matter item, not an attribute")
        data["description"] = text[match.end():]
    return data


def _parse_sources(value, errors, uid):
    try:
        return parse_sources(value)
    except tree_error as err:
        errors.append(f"{uid}: {err}")
        return []


def load_tree(syngate_dir=None):
    syngate_dir = Path(syngate_dir) if syngate_dir else SYNGATE_DIR
    """Return ({uid: Item}, [errors]); items with unusable YAML are skipped."""
    items, errors = {}, []
    for path in sorted(syngate_dir.rglob("*.yml")):
        uid = path.stem
        if uid in items:
            errors.append(f"{uid}: duplicate UID ({path.relative_to(syngate_dir)} and {items[uid].path.relative_to(syngate_dir)})")
            continue
        try:
            data = parse_item(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            errors.append(f"{uid}: unparsable YAML: {exc}")
            continue
        except ValueError as exc:
            errors.append(f"{uid}: {exc}")
            continue
        if not isinstance(data, dict):
            errors.append(f"{uid}: item file is not a mapping")
            continue
        item = Item(uid=uid, path=path, folder=str(path.parent.relative_to(syngate_dir.parent)))
        for key in sorted(set(data) - KNOWN_FIELDS):
            errors.append(f"{uid}: unknown field '{key}'")
        item.description = str(data.get("description") or "")
        parents = data.get("parents")
        if parents is None:
            parents = []
        if not isinstance(parents, list) or not all(isinstance(p, str) for p in parents):
            errors.append(f"{uid}: 'parents' must be a list of UIDs")
            parents = [p for p in parents if isinstance(p, str)] if isinstance(parents, list) else []
        item.parents = parents
        order = data.get("order", 0)
        if not isinstance(order, (int, float)) or isinstance(order, bool):
            errors.append(f"{uid}: 'order' must be a number")
            order = 0
        item.order = order
        item.sources = _parse_sources(data.get("sources"), errors, uid)
        item.tests = _read_feature(item, data, "test", "tests", _parse_tests, errors)
        item.reviewed = _read_feature(item, data, "review", "reviewed", _parse_stamp, errors)
        items[uid] = item
    return items, errors


def children_map(items):
    children = {uid: set() for uid in items}
    for item in items.values():
        for parent in item.parents:
            if parent in children:
                children[parent].add(item.uid)
    return children


def sorted_children(items, children, uid):
    return sorted(children.get(uid, ()), key=lambda c: (items[c].order, c))


def walk(items, anchor=None, descendants=False):
    """UIDs selected for `anchor`, each once at its first occurrence: its ancestors
    root first, the anchor, then on request its descendants in sibling order; the
    whole tree when no anchor is given."""
    children, selected, seen = children_map(items), [], set()

    def up(uid):
        if uid in seen or uid not in items:
            return
        seen.add(uid)
        for parent in items[uid].parents:
            up(parent)
        selected.append(uid)

    def down(uid):
        for child in sorted_children(items, children, uid):
            if child not in seen:
                seen.add(child)
                selected.append(child)
                down(child)

    for uid in [anchor] if anchor else sorted(uid for uid, item in items.items() if not item.parents):
        up(uid)
        if descendants or not anchor:
            down(uid)
    return selected


def stamp_payload(item, children=()):
    tests = None
    if item.tests is not None:
        tests = {name or "": sha or "" for name, sha in item.tests.items()}
    header, description = _split_body(item.description)
    payload = {"description": description, "header": header, "parents": list(item.parents), "tests": tests}
    # Only when the item has children, so a childless item's stamp is the one it
    # always was; it is what makes a child added or removed move its parent's stamp.
    if children:
        payload["children"] = sorted(children)
    # Likewise only on an item carrying a test setup, so every stamp of an item without one stands and a changed setup moves its item's.
    if item.setup is not None:
        payload["setup"] = dict(item.setup)
    return payload


def compute_stamp(item, children=()):
    canonical = json.dumps(stamp_payload(item, children), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def item_stamp(items, uid):
    """`compute_stamp` for an item of a loaded tree, over its immediate children."""
    return compute_stamp(items[uid], children_map(items)[uid])


def layout_problems(items):
    """[(uid|None, message)] -- how the tree is shaped: UID form, parent links,
    non-empty description, exactly one root, no cycles.

    Deliberately free of review state. A stale stamp is the tree's *data*, not a
    defect of its layout, so it reddens the item that carries it (see
    `review_problems`) instead of whatever item describes the layout.
    Tree-wide problems that name no single item carry a None uid."""
    problems = []
    children = children_map(items)
    roots = []
    misplaced = feature_scopes(items)[1]  # a binding or a stamp where the feature is off is a switch of its own, misplaced or not
    for uid, item in sorted(items.items()):
        if not UID_RE.match(uid):
            problems.append((uid, f"{uid}: file stem is not a valid UID"))
        for parent in item.parents:
            if parent == uid:
                problems.append((uid, f"{uid}: links to itself"))
            elif parent not in items:
                problems.append((uid, f"{uid}: unknown parent '{parent}'"))
        if len(set(item.parents)) != len(item.parents):
            problems.append((uid, f"{uid}: duplicate parents"))
        if not item.parents:
            roots.append(uid)
        if not item.description.strip():
            problems.append((uid, f"{uid}: empty description"))
        problems.extend((uid, f"{uid}: unknown key {key!r} in the test setup") for key in item.setup_extra)
    problems.extend(misplaced)
    if len(roots) != 1:
        problems.append((None, f"tree: expected exactly one root item with empty parents, found {len(roots)}: {sorted(roots)}"))
    problems.extend((None, message) for message in _cycle_errors(items, children))
    return problems


def review_problems(items):
    """[(uid, message)] -- each item's own user-approval state: a stamp that no
    longer matches its content, or a reviewed binding with no stamped sha."""
    problems, children = [], children_map(items)
    for uid, item in sorted(items.items()):
        if not item.reviewed:
            continue
        if item.is_leaf and any(sha is None for sha in item.tests.values()):
            problems.append((uid, f"{uid}: reviewed but a binding has no stamped routine sha"))
        elif compute_stamp(item, children[uid]) != item.reviewed:
            problems.append((uid, f"{uid}: reviewed stamp does not match item content (edit without user re-review)"))
    return problems


def validate_layout(items):
    return [message for _uid, message in layout_problems(items)]


def validate_structure(items):
    """The gate's structural check: layout plus review-stamp state."""
    return validate_layout(items) + [message for _uid, message in review_problems(items)]


def item_problems(items, discovered=None):
    """{uid: [message]} -- the problems each item owns, for the status rollup.

    Coverage gaps are deliberately excluded: a binding with no records already
    rolls up as not_implemented, and one missing coverage file would otherwise
    redden every reviewed leaf in the tree at once."""
    problems = {}
    attributed = layout_problems(items) + review_problems(items)
    if discovered is not None:
        attributed += frozen_problems(items, discovered)
    for uid, message in attributed:
        if uid is not None:
            problems.setdefault(uid, []).append(message)
    return problems


def _cycle_errors(items, children):
    state = {}  # uid -> 1 visiting, 2 done
    errors = []

    def visit(uid, trail):
        if state.get(uid) == 2:
            return
        if state.get(uid) == 1:
            errors.append(f"tree: cycle through {' -> '.join(trail + [uid])}")
            return
        state[uid] = 1
        for child in sorted(children.get(uid, ())):
            visit(child, trail + [uid])
        state[uid] = 2

    for uid in sorted(items):
        visit(uid, [])
    return errors


def bindings_from_tags(tags):
    """Ordered tag list -> [(uid, binding_name|None)]; the binding name is the
    tag immediately following its UID tag."""
    out = []
    for i, tag in enumerate(tags):
        if not UID_RE.match(tag):
            continue
        nxt = tags[i + 1] if i + 1 < len(tags) else None
        if nxt and BINDING_NAME_RE.match(nxt) and not UID_RE.match(nxt):
            out.append((tag, nxt))
        else:
            out.append((tag, None))
    return out


def _python_file(path, rel, found):
    """Adds to `found` the routines of one Python file bound by the pytest mark."""
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return
    lines = source.splitlines(keepends=True)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for binding in _syngate_marks(node):
            first = min([node.lineno] + [d.lineno for d in node.decorator_list])
            span = "".join(lines[first - 1:node.end_lineno])
            found.setdefault(binding, []).append(Location(rel, first, f"{rel}::{node.name}", span, node.name))


def _python_locations(root):
    found = {}
    for base in PY_TEST_DIRS:
        for path in sorted((root / base).rglob("*.py")):
            _python_file(path, str(path.relative_to(root)), found)
    return found


def _syngate_marks(node):
    for decorator in node.decorator_list:
        if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.func.attr == "syngate"):
            continue
        args = [a.value for a in decorator.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        if args:
            yield (args[0], args[1] if len(args) > 1 else None)


CPP_TEST_MACRO_RE = re.compile(r"^\s*(TEST_CASE|SCENARIO|TEMPLATE_TEST_CASE|TEST_CASE_METHOD)\s*\(", re.MULTILINE)
CPP_TAGS_RE = re.compile(r'"((?:\[[^\]"]+\])+)"')
CPP_STRING_RE = re.compile(r'"((?:\\.|[^"\\])*)"')
CPP_SUFFIXES = (".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx")


def _cpp_file(path, rel, found):
    """Adds to `found` the Catch2 cases of one C or C++ source bound by their tags, each named by the string its macro opens with."""
    source = path.read_text(encoding="utf-8", errors="replace")
    starts = [m.start() for m in CPP_TEST_MACRO_RE.finditer(source)]
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(source)
        span = source[start:end]
        tags_match = CPP_TAGS_RE.search(span)
        if not tags_match:
            continue
        tags = re.findall(r"\[([^\]]+)\]", tags_match.group(1))
        line = source[:start].count("\n") + 1
        named = CPP_STRING_RE.search(span)
        routine = named.group(1) if named and named.start() < tags_match.start() else ""
        for binding in bindings_from_tags(tags):
            found.setdefault(binding, []).append(Location(rel, line, f"{rel}:{line}", span, routine))


def _cpp_locations(root):
    found = {}
    for base in CPP_TEST_DIRS:
        for path in sorted((root / base).rglob("*.cpp")):
            _cpp_file(path, str(path.relative_to(root)), found)
    return found


def discover_bindings(root=None):
    root = Path(root) if root else ROOT
    """Map (uid, binding_name|None) -> [Location] over all known test trees."""
    found = _python_locations(root)
    for binding, locations in _cpp_locations(root).items():
        found.setdefault(binding, []).extend(locations)
    return found


def _setup_globs(items):
    """The `files` globs of the tree's test setups, each once: root-relative patterns, an empty or an absolute one matching nothing."""
    globs = []
    for uid in sorted(items):
        files = (items[uid].setup or {}).get("files") or []
        files = [files] if isinstance(files, str) else files if isinstance(files, list) else []
        globs.extend(pattern for pattern in files if isinstance(pattern, str) and pattern.strip() and not Path(pattern).is_absolute())
    return list(dict.fromkeys(globs))


def discover_setups(items, found=None, root=None):
    """({(uid, binding_name|None): [Location]}, [(uid, message)]) -- `found`, the routines of the built-in test trees, joined by those
    tagged in the `files` of the tree's test setups: pytest marks in `*.py`, Catch2 tags in C and C++ sources, comment tags in any text
    file. A routine found twice -- a file of two setups, or of a setup and a built-in tree -- is kept once, so *exactly one routine
    per binding* is judged over the files of all setups together. The problems are those of comment tags binding no routine."""
    from . import testtags  # which imports this module
    root = Path(root) if root else ROOT
    found = {binding: list(locations) for binding, locations in (found or {}).items()}
    globs, files, marked = _setup_globs(items), {}, {}
    if not globs:
        return found, []
    for pattern in globs:
        for path in root.glob(pattern):
            if path.is_file() and path.resolve().is_relative_to(root.resolve()):
                files[path.resolve().relative_to(root.resolve()).as_posix()] = path
    for rel in sorted(files):
        read = _python_file if rel.endswith(".py") else _cpp_file if rel.endswith(CPP_SUFFIXES) else None
        try:
            if read:
                read(files[rel], rel, marked)
        except (OSError, ValueError):  # unreadable or no text: it binds nothing
            continue
    tagged, problems = testtags.comment_locations(root, globs)
    problems = [(uid, message) for uid, message in problems if uid in items]  # a tag naming no item of the tree binds nothing and is no problem
    for binding, locations in [*marked.items(), *tagged.items()]:
        known = found.setdefault(binding, [])
        known.extend(location for location in locations if not any((k.path, k.line) == (location.path, location.line) for k in known))
    return found, problems


def routine_sha(location):
    return hashlib.sha256(location.span.encode("utf-8")).hexdigest()


def binding_tag(uid, name):
    return f"[{uid}][{name}]" if name else f"[{uid}]"


def frozen_problems(items, discovered):
    """[(uid, message)] -- reviewed leaves whose bindings no longer resolve to
    exactly one routine, or whose routine drifted from the stamped sha."""
    problems = []
    for uid, item in sorted(items.items()):
        if not (item.reviewed and item.is_leaf):
            continue
        for name, sha in item.tests.items():
            tag = binding_tag(uid, name)
            locations = discovered.get((uid, name), [])
            if not locations:
                problems.append((uid, f"{uid}: no test routine tagged {tag} found"))
            elif len(locations) > 1:
                problems.append((uid, f"{uid}: tag {tag} is ambiguous: {', '.join(l.name for l in locations)}"))
            elif sha and routine_sha(locations[0]) != sha:
                problems.append((uid, f"{uid}: frozen test routine {locations[0].name} modified after review (requires user re-review)"))
    return problems


def check_frozen(items, discovered):
    """Reviewed leaves: every binding resolves to exactly one routine whose
    span hash still matches the stamped sha."""
    return [message for _uid, message in frozen_problems(items, discovered)]


def check_bindings_exist(items, discovered):
    """Unreviewed leaves: report (non-fatal) bindings with no tagged routine yet."""
    pending = []
    for uid, item in sorted(items.items()):
        if item.reviewed or not item.is_leaf:
            continue
        for name in item.tests:
            if not discovered.get((uid, name)):
                pending.append(f"{uid}: no test routine tagged {binding_tag(uid, name)} yet")
    return pending


def load_coverage(paths):
    """[(binding -> [records])], [errors]; records keep optional name/log."""
    records, errors = {}, []
    for path in paths:
        path = Path(path)
        if not path.is_file():
            errors.append(f"coverage report missing: {path}")
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                tags = record["tags"]
                passed = bool(record["passed"])
            except (json.JSONDecodeError, KeyError, TypeError):
                errors.append(f"{path}:{n}: malformed coverage record")
                continue
            record = {"passed": passed, "name": record.get("name", ""), "log": record.get("log", ""), "tags": tags}
            for binding in bindings_from_tags([t for t in tags if isinstance(t, str)]):
                records.setdefault(binding, []).append(record)
    return records, errors


def _record_bindings(line):
    try:
        tags = json.loads(line)["tags"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []
    return bindings_from_tags([t for t in tags if isinstance(t, str)])


def merge_coverage(target, fresh):
    """Fold a re-run's records into `target`. A binding's fresh records replace
    its old ones: with 'any failed record reddens the leaf', an appended re-run
    could never turn a once-failed binding green again."""
    target, fresh = Path(target), Path(fresh)
    fresh_lines = [line for line in fresh.read_text(encoding="utf-8").splitlines() if line.strip()] if fresh.is_file() else []
    rerun = {binding for line in fresh_lines for binding in _record_bindings(line)}
    old_lines = [line for line in target.read_text(encoding="utf-8").splitlines() if line.strip()] if target.is_file() else []
    kept = [line for line in old_lines if not rerun.intersection(_record_bindings(line))]
    target.write_text("".join(line + "\n" for line in kept + fresh_lines), encoding="utf-8")


def check_coverage(items, records):
    """Reviewed leaf bindings need >=1 executed record; unknown UIDs in records
    are typos."""
    errors = []
    for uid, item in sorted(items.items()):
        if not (item.reviewed and item.is_leaf):
            continue
        for name in item.tests:
            if (uid, name) not in records:
                errors.append(f"{uid}: binding {binding_tag(uid, name)} bound but not run in any coverage report")
    known_bindings = {(uid, name) for uid, item in items.items() if item.is_leaf for name in item.tests}
    for (uid, name) in sorted(records, key=lambda b: (b[0], b[1] or "")):
        if uid not in items:
            errors.append(f"coverage: records tagged {binding_tag(uid, name)} match no known item")
        elif items[uid].is_leaf and (uid, name) not in known_bindings:
            errors.append(f"{uid}: coverage records for undeclared binding {binding_tag(uid, name)}")
    return errors


def leaf_status(item, records):
    if not item.is_leaf:
        return NOT_IMPLEMENTED
    per_binding = [records.get((item.uid, name), []) for name in item.tests]
    if all(not recs for recs in per_binding):
        return NOT_IMPLEMENTED
    if any(not r["passed"] for recs in per_binding for r in recs):
        return TEST_FAILED
    if all(recs for recs in per_binding):
        return TEST_PASSED
    return PARTIALLY_IMPLEMENTED


def aggregate(child_statuses):
    if not child_statuses:
        return NOT_IMPLEMENTED
    if TEST_FAILED in child_statuses:
        return TEST_FAILED
    if all(s == NOT_IMPLEMENTED for s in child_statuses):
        return NOT_IMPLEMENTED
    if all(s == TEST_PASSED for s in child_statuses):
        return TEST_PASSED
    return PARTIALLY_IMPLEMENTED


def compute_status(items, records, problems=None):
    """`problems` ({uid: [message]}, see `item_problems`) reddens the exact items
    it names. A bad stamp is a defect of that item, so it is reported there and
    aggregates up through its own parents -- never against the item whose
    tooling detected it."""
    problems = problems or {}
    children = children_map(items)
    memo, scopes = {}, feature_scopes(items)[0]
    # An item whose test feature is off awaits no test, so it and a branch of such items stand outside their parents' rollup.
    silent = _silent(children, problems, lambda uid: items[uid].is_leaf or (scopes[uid]["test"] and not children[uid]))

    def status_of(uid):
        if uid in memo:
            return memo[uid]
        memo[uid] = NOT_IMPLEMENTED  # cycle guard
        if problems.get(uid):
            memo[uid] = TEST_FAILED
            return memo[uid]
        kids = children[uid]
        own = [leaf_status(items[uid], records)] if items[uid].is_leaf or not kids else []
        memo[uid] = aggregate([status_of(k) for k in kids if not silent(k)] + own) if kids else own[0]
        return memo[uid]

    report = {}
    for uid, item in items.items():
        tests = []
        if item.is_leaf:
            for name in item.tests:
                for record in records.get((uid, name), []):
                    tests.append({"binding": name or "", "name": record["name"] or binding_tag(uid, name), "passed": record["passed"], "log": record["log"]})
        report[uid] = {
            "status": status_of(uid),
            "title": item.title,
            "description": item.description.strip(),
            "parents": list(item.parents),
            "children": sorted_children(items, children, uid),
            "order": item.order,
            "sources": list(item.sources),
            "folder": item.folder,
            "reviewed": bool(item.reviewed),
            "problems": list(problems.get(uid, ())),
            "tests": tests,
        }
    return report


def leaf_test_status(item, records):
    per_binding = [records.get((item.uid, name), []) for name in item.tests]
    if any(not r["passed"] for recs in per_binding for r in recs):
        return TEST_FAILED
    if any(not recs for recs in per_binding):
        return UNKNOWN
    return TEST_PASSED


def _worst(states, rank):
    present = set(states)
    return next(state for state in rank if state in present)


def compute_axes(items, records, problems=None):
    """{uid: {"test": …, "review": …}} -- two independent rollups over an item's
    own tests, if it carries any, and its children. Tests, from the run records
    alone: a failed item fails every ancestor, else one unknown item leaves them
    unknown. Review: an item's own validation problem -- a stale stamp, a
    stamped routine changed or gone -- is a violated review and never touches
    the test axis; violated outranks not reviewed, which outranks reviewed;
    every item's own stamp joins its rollup, so a branch is reviewed when it
    and all its children are. An item whose feature is off has no state of its own on that
    axis and, with nothing but such items below, stands outside its parents'."""
    problems = problems or {}
    children = children_map(items)
    memo, scopes, stamped = {}, feature_scopes(items)[0], stampable(items)
    untested = _silent(children, {}, lambda uid: items[uid].is_leaf or (scopes[uid]["test"] and not children[uid]))
    unstamped = _silent(children, problems, lambda uid: uid in stamped or bool(items[uid].reviewed))

    def axes(uid):
        if uid in memo:
            return memo[uid]
        memo[uid] = (UNKNOWN, NOT_REVIEWED)  # cycle guard
        item, below = items[uid], {k: axes(k) for k in children[uid]}
        tests = [state[0] for k, state in below.items() if not untested(k)]
        reviews = [state[1] for k, state in below.items() if not unstamped(k)]
        if item.is_leaf:
            tests.append(leaf_test_status(item, records))
        if uid in stamped or item.reviewed:
            reviews.append(REVIEWED if item.reviewed else NOT_REVIEWED)
        test, review = _worst(tests or [UNKNOWN], TEST_RANK), _worst(reviews or [NOT_REVIEWED], REVIEW_RANK)
        memo[uid] = (test, REVIEW_VIOLATED if problems.get(uid) else review)
        return memo[uid]

    return {uid: dict(zip(("test", "review"), axes(uid))) for uid in items}


class _ItemDumper(yaml.SafeDumper):
    pass


_ItemDumper.add_representer(type(None), lambda dumper, value: dumper.represent_scalar("tag:yaml.org,2002:null", "~"))


def dump_item(item):
    data = {"parents": list(item.parents)}
    if item.order:
        data["order"] = item.order
    if item.sources:
        data["sources"] = list(item.sources)
    bindings = None if item.tests is None else item.tests[None] if set(item.tests) == {None} else dict(item.tests)
    if item.setup is not None:
        data["test"] = ({SETUP_STAMP: bindings} if item.tests is not None else {}) | item.setup | item.setup_extra
    elif item.tests is not None:
        data["test"] = bindings
    elif not item.parents or carries_switch(item, "test"):
        data["test"] = "enabled" if item.features["test"] else "disabled"
    if item.reviewed:
        data["review"] = item.reviewed
    elif not item.parents or carries_switch(item, "review"):
        data["review"] = "enabled" if item.features["review"] else "disabled"
    front = yaml.dump(data, Dumper=_ItemDumper, sort_keys=False, default_flow_style=None, allow_unicode=True, width=120)
    body = item.description if item.description.endswith("\n") else item.description + "\n"
    return f"---\n{front}---\n{body}"


def clear_review(item, items=None):
    """Drop the item's stamp and routine shas. With the tree given, a stamp that switched the review feature on for the subtree
    leaves `review: enabled` in its place, so a cleared item stays gated rather than falling out of the review."""
    if items is not None and item.parents and item.reviewed:
        item.features["review"] = True if enable_mark(items, item.uid, "review") else None
    item.reviewed = None
    if item.tests is not None:
        item.tests = {name: None for name in item.tests}


def write_item(item):
    item.path.write_text(dump_item(item), encoding="utf-8")


# -- tree calls -------------------------------------------------------------
# One core entry point per call, over an already loaded tree, writing through
# the canonical writer. The command line is their genuine spelling; the editor
# and the AI wrapper reach the very same functions.

DEFAULT_DESCRIPTION = "TODO: The component shall ...\n"
# Fields under the review stamp: an edit of any of them clears the item's review.
STAMPED_FIELDS = ("description", "parents", "tests", "setup")
REPORT_FORMATS = ("junit", "tap", "ctrf")


class tree_error(ValueError):
    """A refused tree call."""


class unknown_uid(tree_error):
    pass


class stale_edit(tree_error):
    """A compare-and-swap edit whose base no longer matches the item on disk."""

    def __init__(self, message, current):
        super().__init__(message)
        self.current = current


def feature_off(feature):
    return tree_error(f"the {feature} feature is off for the item (switch it on with '{feature}: enabled' on the root item or on an item above it)")


def _addressed(items, uid):
    if uid not in items:
        raise unknown_uid(f"unknown UID '{uid}'")
    return items[uid]


def _settle(items, uids, clear):
    """Leave the stamps a call moved saying what happened to them. `clear` is the
    user standing behind the change: the stamp is dropped, and the item reads as
    not reviewed. Without it -- a file edited underneath the tooling, or a call
    proxied from an AI answer -- the stamp is left standing over content that no
    longer matches it, which `review_problems` reads as a violated review."""
    if not clear:
        return
    for uid in sorted(set(uids)):
        item = items.get(uid)
        if item is not None and item.reviewed:
            clear_review(item, items)
            write_item(item)


def check_parents(items, uid, parents):
    """Refuse a parent list that is malformed, unknown, duplicated, self-linked or cyclic."""
    if not isinstance(parents, list) or not all(isinstance(p, str) for p in parents):
        raise tree_error("'parents' must be a list of UIDs")
    if len(set(parents)) != len(parents):
        raise tree_error("duplicate parents")
    for parent in parents:
        if parent == uid:
            raise tree_error("an item cannot be its own parent")
        if parent not in items:
            raise tree_error(f"unknown parent '{parent}'")
    # Climbing the (edited) parent links from each new parent must never reach
    # uid, or the DAG gains a cycle.
    edges = {u: (parents if u == uid else item.parents) for u, item in items.items()}
    seen, stack = set(), list(parents)
    while stack:
        node = stack.pop()
        if node == uid:
            raise tree_error(f"parents {', '.join(parents)} would create a cycle through {uid}")
        if node in seen:
            continue
        seen.add(node)
        stack.extend(p for p in edges.get(node, ()) if p in items)


def parse_order(value):
    if value in (None, ""):
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise tree_error("'order' must be a number")
    return value


def parse_sources(value):
    """The `sources` list of a wire value: normalised root-relative paths, each once."""
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(s, str) for s in value):
        raise tree_error("'sources' must be a list of root-relative file paths")
    for rel in value:
        path = Path(rel)
        if not rel or path.is_absolute() or ".." in path.parts or rel != path.as_posix() or rel.startswith("-"):
            raise tree_error(f"'{rel}' is not a normalised root-relative path")
    return list(dict.fromkeys(value))


def parse_bindings(items, item, names):
    """{name|None: kept sha} for a wire list of binding names, None for a branch. Bindings given to an item whose parents hand it the
    test feature off make it the switch of its subtree; refused on the root, on an item switched off by its own word and where that
    switch would be misplaced."""
    if names is None:
        return None
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise tree_error("'tests' must be null or a list of binding names")
    if len(set(names)) != len(names):
        raise tree_error("duplicate binding names")
    if "" in names and len(names) > 1:
        raise tree_error("the default binding '' cannot be combined with named bindings")
    for name in names:
        if name and not BINDING_NAME_RE.match(name):
            raise tree_error(f"invalid binding name '{name}': lowercase letters, digits and underscores only")
        if name == SETUP_STAMP:
            raise tree_error(f"invalid binding name '{name}': it is the key of a test setup holding the bindings")
    old = item.tests or {}
    bindings = {(name or None): old.get(name or None) for name in names}
    if not features(items, item.uid)["test"]:
        if not item.parents or item.features.get("test") is False:
            raise feature_off("test")
        held, item.tests = item.tests, bindings
        misplaced = [message for uid, message in feature_scopes(items)[1] if uid == item.uid and "the test feature" in message]
        item.tests = held
        if misplaced:
            raise tree_error(misplaced[0])
    return bindings


def parse_setup(items, item, value):
    """The item's own test setup for a wire value -- a mapping of `run` and optionally `files`, `report`, `env` -- or None removing it. A
    setup given to an item whose parents hand it the test feature off makes it the switch of its subtree; refused on an item switched
    off by its own word and where that switch would be misplaced."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise tree_error("'setup' must be null or a mapping of run, files, report and env")
    unknown = sorted(set(value) - set(SETUP_KEYS))
    if unknown:
        raise tree_error(f"unknown key {unknown[0]!r} in the test setup: {', '.join(SETUP_KEYS)} only")
    run = value.get("run")
    if not isinstance(run, str) or not run.strip():
        raise tree_error("a test setup needs its 'run' command line")
    setup = {"run": run.strip()}
    if value.get("files") is not None:
        files = value["files"]
        if not isinstance(files, list) or not files or not all(isinstance(glob, str) and glob.strip() for glob in files):
            raise tree_error("'files' of a test setup must be a list of root-relative globs")
        setup["files"] = list(dict.fromkeys(files))
    if value.get("report") is not None:
        if value["report"] not in REPORT_FORMATS:
            raise tree_error(f"'report' of a test setup must be one of {', '.join(REPORT_FORMATS)}")
        setup["report"] = value["report"]
    if value.get("env") is not None:
        env = value["env"]
        if not isinstance(env, dict) or not all(isinstance(k, str) and k and isinstance(v, str) for k, v in env.items()):
            raise tree_error("'env' of a test setup must map variable names to text values")
        setup["env"] = dict(env)
    if item.features.get("test") is False:
        raise feature_off("test")
    if item.parents and not features(items, item.uid)["test"]:
        held, item.setup = item.setup, setup
        misplaced = [message for uid, message in feature_scopes(items)[1] if uid == item.uid and "the test feature" in message]
        item.setup = held
        if misplaced:
            raise tree_error(misplaced[0])
    return setup


def item_fields(item):
    """The editable fields in their wire form (bindings as a name list, the setup as its mapping or None)."""
    return {"description": item.description, "parents": list(item.parents), "order": item.order, "sources": list(item.sources),
            "tests": None if item.tests is None else [name or "" for name in item.tests],
            "setup": None if item.setup is None else dict(item.setup)}


def add_item(items, uid, parents, description=None, kind="leaf", folder=None, order=0, sources=None, syngate_dir=None, clear=False):
    """Scaffold a new item under `parents`; `kind` "leaf" carries a test binding
    when the tree's test feature is on, "branch" never does. -> the written Item."""
    syngate_dir = Path(syngate_dir) if syngate_dir else SYNGATE_DIR
    if not UID_RE.match(uid or ""):
        raise tree_error(f"'{uid}' is not a valid UID")
    if uid in items:
        raise tree_error(f"{uid} already exists at {items[uid].path}")
    parents = list(parents or [])
    if not parents:
        raise tree_error("a new item needs at least one parent (the tree has exactly one root)")
    check_parents(items, uid, parents)
    folder = str(folder or "").strip()
    directory = (syngate_dir.parent / folder).resolve() if folder else syngate_dir.resolve()
    if not directory.is_relative_to(syngate_dir.resolve()):
        raise tree_error(f"directory '{folder}' is outside the syngate tree")
    description = str(description or DEFAULT_DESCRIPTION)
    directory.mkdir(parents=True, exist_ok=True)
    item = Item(uid=uid, path=directory / f"{uid}.yml",
                description=description if description.endswith("\n") else description + "\n",
                parents=parents, order=parse_order(order), sources=parse_sources(sources),
                tests={None: None} if kind != "branch" and any(features(items, parent)["test"] for parent in parents) else None,
                folder=str(directory.relative_to(syngate_dir.parent.resolve())))
    write_item(item)
    items[uid] = item
    _settle(items, parents, clear)  # the new child moves its parents' stamps
    return item


def edit_item(items, uid, changes, base=None, clear=False):
    """Partial update: only the fields present in `changes` move. `base` maps a
    field to the value the caller started from and turns the write into a
    per-field compare-and-swap, so an edit made meanwhile on disk (agent, git,
    IDE) is never silently overwritten. -> the stored fields."""
    item = _addressed(items, uid)
    before = item_fields(item)
    if "description" in changes:
        text = str(changes["description"] or "")
        item.description = text if text.endswith("\n") else text + "\n"
    if "parents" in changes:
        parents = changes["parents"] or []
        check_parents(items, uid, parents)
        item.parents = parents
    if "order" in changes:
        item.order = parse_order(changes["order"])
    if "sources" in changes:
        item.sources = parse_sources(changes["sources"])
    if "tests" in changes:
        item.tests = parse_bindings(items, item, changes["tests"])
    if "setup" in changes:
        setup = parse_setup(items, item, changes["setup"])
        if setup is None and item.setup is not None and item.tests is None and item.parents and enable_mark(items, uid, "test"):
            item.features["test"] = True  # the setup switched the feature on for the subtree: `test: enabled` takes its place
        if setup != item.setup:
            item.setup, item.setup_extra = setup, {}
    after = item_fields(item)
    base = base if isinstance(base, dict) else {}
    clashed = sorted(f for f in base if f in before and before[f] != base[f] and before[f] != after[f])
    if clashed:
        raise stale_edit(f"{uid}: {', '.join(clashed)} changed on disk since it was loaded",
                         {f: before[f] for f in clashed})
    if after != before:
        if clear and item.reviewed and any(after[f] != before[f] for f in STAMPED_FIELDS):
            clear_review(item, items)
        write_item(item)
        _settle(items, set(before["parents"]) ^ set(after["parents"]), clear)
    return after


def _placement(items, uid, siblings, index):
    """{uid: order} landing `uid` at `index` among `siblings`: a free integer
    strictly between the neighbours' keys when there is one (one file written),
    else the whole family renumbered in steps of 10."""
    below = items[siblings[index - 1]].order if index else None
    above = items[siblings[index]].order if index < len(siblings) else None
    if below is None and above is None:
        return {}
    if below is None:
        key = math.floor(above) - 10
    elif above is None:
        key = math.floor(below) + 10
    else:
        key = math.floor((below + above) / 2)
    if (below is None or below < key) and (above is None or key < above):
        return {uid: key}
    return {u: (n + 1) * 10 for n, u in enumerate(siblings[:index] + [uid] + siblings[index:])}


def move_item(items, uid, to, before=None, source=None, link=False, clear=False):
    """Place `uid` under parent `to`, in front of sibling `before` (None = last),
    adding and removing parent links: its link to `source` is re-pointed at `to`,
    `link` keeps that link and adds `to` as one more parent instead, and naming a
    `source` that is a parent while `to` already is another drops `source`.
    `order` is one key per item, so a multi-parent item carries the same key
    under each of its parents. -> the UIDs written."""
    item = _addressed(items, uid)
    if to not in items:
        raise tree_error(f"unknown parent '{to}'")
    parents = list(item.parents)
    if to not in parents:
        if link or source not in parents:
            parents.append(to)
        else:
            parents[parents.index(source)] = to
    elif source != to and source in parents and not link:
        parents.remove(source)
    check_parents(items, uid, parents)
    relinked, was = parents != item.parents, list(item.parents)
    item.parents = parents
    if clear and relinked and item.reviewed:
        clear_review(item, items)
    family = sorted_children(items, children_map(items), to)
    siblings = [c for c in family if c != uid]
    if before is None:
        index = len(siblings)
    elif before in siblings:
        index = siblings.index(before)
    else:
        raise tree_error(f"'{before}' is not a sibling under {to}")
    orders = {} if siblings[:index] + [uid] + siblings[index:] == family else _placement(items, uid, siblings, index)
    written = {u for u, order in orders.items() if items[u].order != order} | ({uid} if relinked else set())
    for u, order in orders.items():
        items[u].order = order
    for u in sorted(written):
        write_item(items[u])
    _settle(items, set(was) ^ set(parents), clear)  # the relink moves both ends' stamps
    return sorted(written)


def rename_item(items, uid, new_uid, clear=False):
    """Give `uid` the UID `new_uid`: its file takes the new stem in its folder and every child's parent link follows it in place,
    a file of that stem already there -- an unparsable item included -- refusing it. The stamps of its parents and children move
    with it; its own holds no UID and stands. -> the UIDs written, the renamed one first."""
    item = _addressed(items, uid)
    if not UID_RE.match(new_uid or ""):
        raise tree_error(f"'{new_uid}' is not a valid UID")
    if new_uid in items:
        raise tree_error(f"{new_uid} already exists at {items[new_uid].path}")
    path = item.path.with_name(f"{new_uid}.yml")
    if path.exists():
        raise tree_error(f"{path} already exists")
    kids = [items[child] for child in sorted(children_map(items)[uid])]
    item.path.rename(path)
    del items[uid]
    item.uid, item.path, items[new_uid] = new_uid, path, item
    for kid in kids:
        kid.parents = [new_uid if parent == uid else parent for parent in kid.parents]
        if clear and kid.reviewed:
            clear_review(kid, items)
        write_item(kid)
    _settle(items, item.parents, clear)
    return [new_uid, *(kid.uid for kid in kids)]


def delete_item(items, uid, clear=False):
    """Remove a childless item's file. -> the path removed."""
    item = _addressed(items, uid)
    children = sorted(children_map(items)[uid])
    if children:
        raise tree_error(f"{uid} still has children {children}; re-parent or delete them first")
    item.path.unlink()
    del items[uid]
    _settle(items, item.parents, clear)  # the item is gone from its parents' stamps
    return item.path


def leaves_under(items, uid):
    """The items a test or review run addresses for `uid`: the item itself when
    it carries tests -- with the test feature off, when it is childless -- and
    every such item below it, in sibling order; a glob pattern addresses those
    of the items it matches, as the test command selects them. An unknown UID and
    a pattern matching nothing pass through untouched, for the addressed command
    to judge."""
    children, scopes = children_map(items), feature_scopes(items)[0]
    addressable = lambda node: items[node].is_leaf if scopes[node]["test"] else not children[node]
    if any(ch in uid for ch in "*?["):
        return [node for node in sorted(items) if fnmatch.fnmatchcase(node, uid) and addressable(node)] or [uid]
    if uid not in items:
        return [uid]
    leaves, seen, stack = [], set(), [uid]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        if addressable(node):
            leaves.append(node)
        stack.extend(reversed(sorted_children(items, children, node)))
    return leaves


def linked_files(description):
    """The project files a statement links: the targets of its markdown links that carry no scheme, without their fragment."""
    targets = (target.partition("#")[0] for target in LINK_RE.findall(description) if not SCHEME_RE.match(target))
    return [os.path.normpath(target) for target in targets if target]


def review_footprint(items, uid, discovered, root=None):
    """The root-relative files a review of `uid` stamps over: the item files, key sources and linked project files of its seed
    context -- its ancestors, itself and its descendants -- and the files of the routines bound to it and to the items below it."""
    root, files = Path(root or ROOT).resolve(), set()
    for selected in walk(items, uid, descendants=True):
        item = items[selected]
        if item.path.resolve().is_relative_to(root):
            files.add(item.path.resolve().relative_to(root).as_posix())
        files.update(item.sources)
        files.update(linked_files(item.description))
    for under in items_under(items, uid):
        for name in (items[under].tests or {}) if under in items else ():
            files.update(location.path for location in discovered.get((under, name), []))
    return files


def items_under(items, uid):
    """The items a review run stamps for `uid`: every item below it, children
    before their parent, then the item itself; an unknown UID passes through."""
    if uid not in items:
        return [uid]
    children, order, seen = children_map(items), [], set()

    def visit(node):
        if node in seen:
            return
        seen.add(node)
        for child in sorted_children(items, children, node):
            visit(child)
        order.append(node)

    visit(uid)
    return order
