#!/usr/bin/env python3
# Open Trader
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Synergy Context Gate (syngate) CLI: the genuine spelling of every tree call.

add / edit / move / rename / delete are the tree mutations, each one line over the core
call in syngatelib; AI Assassin and the Synthetic harness reach those same functions.
`query` and `context` read an item back the way the AI does: its fields and
children, and the seed context an AI call anchored at it is formed from.
`review` and `clear` are user-only: the reviewed stamp is the record of the
user's approval. `test` runs the routines bound to items without stamping.
`validate` is the CI gate entry point; `report` computes the recursive status
rollup from coverage JSONL and renders the static HTML site.
"""

import argparse
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from . import gitlib, syngatelib, synthetic, testreport, testselect


def _load_or_die():
    items, errors = syngatelib.load_tree()
    if errors:
        for line in errors:
            print(f"  {line}", file=sys.stderr)
        sys.exit(1)
    return items


def _mutate(run):
    """Perform one core tree call, reporting what it did or why it was refused."""
    items, _ = syngatelib.load_tree()
    try:
        print(run(items))
    except syngatelib.tree_error as err:
        print(err, file=sys.stderr)
        return 1
    return 0


def cmd_add(args):
    def run(items):
        item = syngatelib.add_item(items, args.uid, args.parent, description=args.description,
                                   kind="branch" if args.branch else "leaf", folder=args.dir, order=args.order,
                                   sources=args.source, clear=args.clear_review)
        return f"created {item.path.relative_to(syngatelib.ROOT)}"
    return _mutate(run)


def cmd_edit(args):
    changes = {field: value for field, value in (("description", args.description), ("order", args.order), ("sources", args.source)) if value is not None}
    shaped = any(value is not None for value in (args.files, args.report, args.env))
    if args.no_setup and (args.run is not None or shaped):
        print("--no-setup removes the test setup: it takes no --run, --files, --report or --env", file=sys.stderr)
        return 1
    if shaped and args.run is None:
        print("a test setup is given whole: --files, --report and --env go with its --run", file=sys.stderr)
        return 1
    if args.run is not None:
        env = {}
        for pair in args.env or ():
            key, eq, value = pair.partition("=")
            if not eq or not key:
                print(f"--env takes K=V, not {pair!r}", file=sys.stderr)
                return 1
            env[key] = value
        changes["setup"] = {"run": args.run, **({"files": args.files} if args.files else {}),
                            **({"report": args.report} if args.report else {}), **({"env": env} if env else {})}
    elif args.no_setup:
        changes["setup"] = None
    if not changes:
        print("nothing to edit: pass --description, --order, --source, --run or --no-setup", file=sys.stderr)
        return 1

    def run(items):
        syngatelib.edit_item(items, args.uid, changes, clear=args.clear_review)
        return f"{args.uid}: {', '.join(sorted(changes))} updated"
    return _mutate(run)


def cmd_move(args):
    def run(items):
        written = syngatelib.move_item(items, args.uid, args.to, before=args.before, source=args.source,
                                       link=args.link, clear=args.clear_review)
        return f"{args.uid}: under {', '.join(items[args.uid].parents)}" + (f" -- rewrote {', '.join(written)}" if written else " -- already placed")
    return _mutate(run)


def cmd_rename(args):
    def run(items):
        written = syngatelib.rename_item(items, args.uid, args.new_uid, clear=args.clear_review)
        return f"renamed {args.uid} to {args.new_uid}" + (f" -- rewrote {', '.join(written[1:])}" if written[1:] else "")
    return _mutate(run)


def cmd_delete(args):
    def run(items):
        return f"deleted {syngatelib.delete_item(items, args.uid, clear=args.clear_review).relative_to(syngatelib.ROOT)}"
    return _mutate(run)


def cmd_query(args):
    return _mutate(lambda items: json.dumps(synthetic.item_view(items, args.uid), ensure_ascii=False, indent=1))


def cmd_context(args):
    return _mutate(lambda items: synthetic.seed_context(items, args.uid, label=args.label).rstrip("\n"))


def _require(scopes, uid, feature):
    """False, with the switch to set printed, when the feature is off for the item; an unknown UID passes for the command to judge."""
    if uid not in scopes or scopes[uid][feature]:
        return True
    print(f"{uid}: the {feature} feature is off for the item; switch it on with '{feature}: enabled' on the root item or on a branch over it", file=sys.stderr)
    return False


def _addressable(items):
    """The items `review` and `test` address: those with own tests, or -- with the test feature off -- the childless ones."""
    scopes, children = syngatelib.feature_scopes(items)[0], syngatelib.children_map(items)
    return lambda item: item.is_leaf if scopes[item.uid]["test"] else not children[item.uid]


def _bindings_of(item, discovered, tests_on):
    """The binding names a run addresses. With the test feature on those are the
    item's declared bindings; with it off nothing is declared, so whatever
    routines are tagged for the item are run -- the switch withholds enforcement
    and stamping, never the run itself."""
    if tests_on:
        return list(item.tests or {})
    return [name for uid, name in discovered if uid == item.uid]


def _tagged_elsewhere(uid, discovered, names):
    """The routines tagged for `uid` under bindings other than `names`, as the hint of a binding that resolves to none."""
    found = [f"{syngatelib.binding_tag(uid, name)} {l.name}" for (tagged, name), locations in sorted(discovered.items(), key=lambda b: (b[0][0], b[0][1] or ""))
             if tagged == uid and name not in names for l in locations]
    return f"; routines tagged for {uid}: {', '.join(found)}" if found else ""


def _resolve(item, discovered, names):
    """({binding: Location}, {binding: why it cannot run}) -- a binding runs only when exactly one routine carries its tag pair."""
    resolved, unrun = {}, {}
    for name in names:
        locations = discovered.get((item.uid, name), [])
        if len(locations) == 1:
            resolved[name] = locations[0]
        else:
            found = ", ".join(l.name for l in locations) or "none"
            unrun[name] = (f"binding {syngatelib.binding_tag(item.uid, name)} must match exactly one routine, found: {found}"
                           + ("" if locations else _tagged_elsewhere(item.uid, discovered, names)))
            print(f"{item.uid}: {unrun[name]}", file=sys.stderr)
    return resolved, unrun


ENV_PASSED_RE = re.compile(r"^\$([A-Za-z_][A-Za-z0-9_]*)$")  # an `env` value passing a variable of the server through


def _discover(items):
    """({(uid, binding): [Location]}, [(uid, message)]) -- the routines of the built-in test trees joined by those of the files of all test setups, with the problems of comment tags binding none."""
    return syngatelib.discover_setups(items, syngatelib.discover_bindings())


def _setup_env(setup):
    """The environment of a setup's command: its `env` entries over the server's own, a value `$NAME` passing that variable through and leaving the entry out where the server has none."""
    env, entries = dict(os.environ), setup.get("env")
    for key, value in (entries.items() if isinstance(entries, dict) else ()):
        through = ENV_PASSED_RE.match(str(value))
        if not through:
            env[str(key)] = str(value)
        elif through.group(1) in os.environ:
            env[str(key)] = os.environ[through.group(1)]
        else:
            env.pop(str(key), None)
    return env


def _run_setup(holder, setup, bindings, recording, unrun):
    """Run the addressed bindings of the test setup of item `holder` by its command -- an argument list, never a shell line, in the
    project root under its `env` -- and record every outcome from the first source holding a result of theirs: the coverage records
    the run appended, its report file, its standard output, then the exit status of a command run one by one. The bindings of a
    command that cannot start land in `unrun` with that reason. -> all passed."""
    keys = lambda group: [(binding["uid"], binding["binding"]) for binding in group]

    def cannot(group, why):
        print(f"{holder}: {why}", file=sys.stderr)
        unrun.update(dict.fromkeys(keys(group), why))
        return False

    run = setup.get("run") if isinstance(setup.get("run"), str) else ""
    with tempfile.TemporaryDirectory() as scratch:
        coverage, report, select = (Path(scratch) / name for name in ("coverage.jsonl", "report", "select.jsonl"))
        try:
            runs = testselect.commands(run, bindings, syngatelib.ROOT, report)
        except ValueError as err:
            return cannot(bindings, f"its test setup cannot run: {err}")
        one_by_one = any(match.group(1) in testselect.SINGULAR for match in testselect.PLACEHOLDER_RE.finditer(run))
        env = _setup_env(setup) | {"SYNGATE_COVERAGE_FILE": str(coverage), "SYNGATE_REPORT_FILE": str(report), "SYNGATE_SELECT_FILE": str(select)}
        passed = True
        for argv, group in runs:
            coverage.unlink(missing_ok=True)
            report.unlink(missing_ok=True)
            select.write_text("".join(json.dumps(binding) + "\n" for binding in group), encoding="utf-8")
            print(f"running {shlex.join(argv)}", flush=True)
            try:
                done = subprocess.run(argv, cwd=syngatelib.ROOT, env=env, stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace")
            except OSError as err:
                passed = cannot(group, f"command cannot start: {argv[0]}: {err.strerror or err}")
                continue
            output = done.stdout + done.stderr
            print(output, end="", flush=True)
            records = syngatelib.load_coverage([coverage])[0] if coverage.is_file() else {}
            found = {key: [(record["passed"], record["name"], record["log"]) for record in records.get(key, [])] for key in keys(group)}
            for text in ([report.read_text(encoding="utf-8", errors="replace")] if report.is_file() else []) + [done.stdout]:
                if any(found.values()):
                    break
                joined = testreport.join(testreport.parse(text, setup.get("report")), group)
                found = {key: [(result["passed"], result["name"], result["log"]) for result in joined[key]] for key in joined}
            if one_by_one and not any(found.values()):
                found = {key: [(done.returncode == 0, group[0]["name"], output[-testreport.TAIL:])] for key in keys(group)}
            for key in keys(group):
                for ok, test, log in found[key] or [(False, "", testreport.verdict([], output)[1])]:
                    passed &= ok
                    recording.record(*key, ok, test, log)
                    if not ok:
                        summary = str(log).strip().splitlines()
                        print(f"{key[0]}: {syngatelib.binding_tag(*key)} failed: {summary[0] if summary else 'no log'}", file=sys.stderr)
    return passed


def _run_bound(items, resolved, build_dir, recording):
    """Run the routines of {uid: {binding: Location}}, each by the test setup holding for its item. Under a setup of the tree its
    command runs them and their outcomes go to `recording`; under the built-in one pytest routines are selected by node id in one
    process and Catch2 cases by an OR of their tag pairs in one process per binary, their own emitters recording.
    -> (all passed, {(uid, binding): why it did not run})."""
    scopes = syngatelib.setup_scopes(items)
    node_ids, tags_by_binary, by_setup, unrun = [], {}, {}, {}
    for uid, bindings in resolved.items():
        for name, loc in bindings.items():
            if scopes.get(uid):
                by_setup.setdefault(scopes[uid], []).append({"uid": uid, "binding": name, "tag": syngatelib.binding_tag(uid, name),
                                                             "name": loc.routine, "path": loc.path, "line": loc.line})
                continue
            if loc.path.endswith(".py"):
                node_ids.append(loc.name)
                continue
            binary = syngatelib.ROOT / build_dir / Path(loc.path).stem
            if binary.is_file():
                tags_by_binary.setdefault(binary, []).append(syngatelib.binding_tag(uid, name))
            else:
                unrun[(uid, name)] = f"test binary not built: {binary} (build target {binary.name} first)"
                print(f"{uid}: {unrun[(uid, name)]}", file=sys.stderr)
    passed = True
    if node_ids:
        print(f"running pytest: {' '.join(node_ids)}", flush=True)
        passed &= subprocess.run([sys.executable, "-m", "pytest", *node_ids], cwd=syngatelib.ROOT).returncode == 0
    for binary, tags in tags_by_binary.items():
        print(f"running {binary.name} \"{','.join(tags)}\"", flush=True)
        passed &= subprocess.run([str(binary), ",".join(tags)], cwd=syngatelib.ROOT).returncode == 0
    for holder, bindings in by_setup.items():
        passed &= _run_setup(holder, items[holder].setup, bindings, recording, unrun)
    return passed, unrun


class _Recording:
    """The coverage emitters of the tests run inside write to a scratch file
    that is folded into `coverage_out` on exit. A binding the run could not
    execute is recorded as failed: a test that cannot be found is a red test."""

    def __init__(self, coverage_out):
        self.coverage_out = coverage_out

    def __enter__(self):
        if self.coverage_out:
            self.scratch = tempfile.TemporaryDirectory()
            self.fresh = Path(self.scratch.name) / "coverage.jsonl"
            self.outer = os.environ.get("SYNGATE_COVERAGE_FILE")
            os.environ["SYNGATE_COVERAGE_FILE"] = str(self.fresh)
        return self

    def record(self, uid, name, passed, test="", log=""):
        """Append one result of a binding the way the coverage emitters of the tests append theirs: the outcome a setup's command told."""
        if self.coverage_out:
            with open(self.fresh, "a", encoding="utf-8") as f:
                f.write(json.dumps({"tags": [uid] + ([name] if name else []), "passed": passed, "name": test, "log": log}) + "\n")

    def unrun(self, uid, name, why):
        self.record(uid, name, False, log=why)

    def __exit__(self, *exc):
        if self.coverage_out:
            if self.outer is None:
                del os.environ["SYNGATE_COVERAGE_FILE"]
            else:
                os.environ["SYNGATE_COVERAGE_FILE"] = self.outer
            syngatelib.merge_coverage(self.coverage_out, self.fresh)
            self.scratch.cleanup()


def _expand_uids(items, uid_args, selectable, kind):
    """Expand literal UIDs and glob patterns (fnmatch: * ? [seq]) against the tree.

    Literals pass through untouched so per-command diagnostics stay precise;
    patterns select only items satisfying `selectable`, and matching nothing is
    an error. Order follows the sorted tree; duplicates collapse.
    """
    selected, errors = [], []
    for arg in uid_args:
        if any(ch in arg for ch in "*?["):
            matched = [uid for uid in sorted(items) if fnmatch.fnmatchcase(uid, arg) and selectable(items[uid])]
            if not matched:
                errors.append(f"pattern '{arg}' matches no {kind} item")
            selected.extend(matched)
        else:
            selected.append(arg)
    seen = set()
    return [uid for uid in selected if not (uid in seen or seen.add(uid))], errors


def _review_one(items, structural, discovered, uid, build_dir, recording, uncommitted=frozenset()):
    own = [e for e in structural if e.startswith(f"{uid}:") and "reviewed stamp" not in e and "no stamped routine sha" not in e]
    if own:
        for line in own:
            print(f"  {line}", file=sys.stderr)
        return False
    item = items.get(uid)
    if item is None:
        print(f"unknown UID '{uid}'", file=sys.stderr)
        return False
    blocked = sorted(uncommitted & syngatelib.review_footprint(items, uid, discovered)) if uncommitted else []
    if blocked:
        print(f"{uid}: uncommitted changes in its review footprint, commit them first: {', '.join(blocked)}", file=sys.stderr)
        return False
    resolved, unresolved = _resolve(item, discovered, item.tests) if item.is_leaf else ({}, {})
    passed, unrun = _run_bound(items, {uid: resolved}, build_dir, recording) if not unresolved else (False, {})
    for name, why in [*unresolved.items(), *((name, why) for (_, name), why in unrun.items())]:
        recording.unrun(uid, name, why)
    if unresolved or unrun:
        print(f"{uid}: bound test could not be run; not stamping", file=sys.stderr)
        return False
    # Test-first TDD: the routine is frozen by hash as soon as it runs and resolves
    # unambiguously, whether it currently passes or fails. A stamped-but-failing leaf
    # rolls up as test_failed until the covering implementation lands and turns it green.
    if item.is_leaf:
        item.tests = {name: syngatelib.routine_sha(loc) for name, loc in resolved.items()}
    item.reviewed = syngatelib.item_stamp(items, uid)
    syngatelib.write_item(item)
    state = "no bound test" if not resolved else "bound test currently passing" if passed else "bound test currently FAILING -- red, pending implementation"
    print(f"{uid}: reviewed ({item.reviewed}) -- {state}")
    return True


def cmd_review(args):
    items = _load_or_die()
    scopes, addressable = syngatelib.feature_scopes(items)[0], _addressable(items)
    uids, errors = _expand_uids(items, args.uid, lambda item: addressable(item) and scopes[item.uid]["review"], "leaf")
    if errors:
        for line in errors:
            print(line, file=sys.stderr)
        return 1
    discovered, tag_problems = _discover(items)
    structural = syngatelib.validate_structure(items) + [message for _uid, message in tag_problems]
    uncommitted = gitlib.content_uncommitted(syngatelib.ROOT) if gitlib.at_hand(syngatelib.ROOT) else set()  # review marks never block a review
    with _Recording(args.coverage_out) as recording:
        failed = [uid for uid in uids if not (_require(scopes, uid, "review") and _review_one(items, structural, discovered, uid, args.build_dir, recording, uncommitted))]
    if failed:
        print(f"review: {len(failed)}/{len(uids)} item(s) not stamped: {' '.join(failed)}", file=sys.stderr)
        return 1
    if len(uids) > 1:
        print(f"review: stamped {len(uids)} item(s)")
    return 0


def cmd_test(args):
    """Runs whichever way the test switch sits: off only means the tree does not
    enforce that its items carry tests, so the routines tagged for them still
    run and still record coverage. Stamping is `review`'s and stays gated."""
    items = _load_or_die()
    scopes = syngatelib.feature_scopes(items)[0]
    narrowed, whole, errors = {}, set(), []
    for arg in args.uid:
        pattern, _, name = arg.partition(":")
        matched, bad = _expand_uids(items, [pattern], _addressable(items), "leaf")
        errors += bad
        for uid in matched:
            narrowed.setdefault(uid, [])
            if name:
                narrowed[uid].append(name)
            else:
                whole.add(uid)
    uids = list(narrowed)
    discovered, tag_problems = _discover(items)
    errors += [message for uid, message in tag_problems if uid in narrowed]
    resolved, unresolved = {}, {}
    for uid in uids:
        item = items.get(uid)
        if item is None:
            errors.append(f"unknown UID '{uid}'")
            continue
        tests_on = scopes[uid]["test"]
        names = _bindings_of(item, discovered, tests_on)
        unknown = [name for name in dict.fromkeys(narrowed[uid]) if name not in names]
        declared = ", ".join(syngatelib.binding_tag(uid, name) for name in names) or "none"
        for name in unknown:
            unresolved[(uid, name)] = f"{uid}: no binding named {name}, the item declares {declared}{_tagged_elsewhere(uid, discovered, names)}"
            errors.append(unresolved[(uid, name)])
        if narrowed[uid] and uid not in whole:
            names = [name for name in dict.fromkeys(narrowed[uid]) if name in names]
        if not names:
            # With the switch off the tree never claimed the item has a test, so
            # having none is nothing to report; with it on, it binds none by mistake.
            if tests_on and not unknown:
                errors.append(f"{uid}: a branch binds no tests of its own")
            continue
        resolved[uid], missing = _resolve(item, discovered, names)
        unresolved.update({(uid, name): why for name, why in missing.items()})
    with _Recording(args.coverage_out) as recording:
        passed, unrun = _run_bound(items, resolved, args.build_dir, recording)
        unrun.update(unresolved)
        for (uid, name), why in unrun.items():
            recording.unrun(uid, name, why)
    for line in errors:
        print(line, file=sys.stderr)
    broken = {uid for uid, _ in unrun}
    print(f"test: {len(resolved.keys() - broken)}/{len(uids)} item(s) run -- {'passed' if passed and not unrun else 'FAILED'}")
    return 0 if passed and not errors and not unrun else 1


def cmd_clear(args):
    items = _load_or_die()
    scopes = syngatelib.feature_scopes(items)[0]
    uids, errors = _expand_uids(items, args.uid, lambda item: bool(item.reviewed), "reviewed")
    if errors:
        for line in errors:
            print(line, file=sys.stderr)
        return 1
    ret = 0
    for uid in uids:
        item = items.get(uid)
        if item is None:
            print(f"unknown UID '{uid}'", file=sys.stderr)
            ret = 1
            continue
        if not _require(scopes, uid, "review"):
            ret = 1
            continue
        if not item.reviewed:
            print(f"{uid}: not reviewed")
            continue
        syngatelib.clear_review(item, items)
        syngatelib.write_item(item)
        print(f"{uid}: review stamp cleared")
    return ret


def cmd_validate(args):
    items, errors = syngatelib.load_tree()
    errors.extend(syngatelib.validate_structure(items))
    discovered, tag_problems = _discover(items)
    errors.extend(message for _uid, message in tag_problems)
    errors.extend(syngatelib.check_frozen(items, discovered))
    if args.coverage:
        records, coverage_errors = syngatelib.load_coverage(args.coverage)
        errors.extend(coverage_errors)
        errors.extend(syngatelib.check_coverage(items, records))
    if args.strict:
        stampable = syngatelib.stampable(items)
        errors.extend(f"{uid}: not reviewed (strict mode)" for uid, item in sorted(items.items()) if uid in stampable and not item.reviewed)
    pending = syngatelib.check_bindings_exist(items, discovered)
    if pending:
        print(f"validate: {len(pending)} unreviewed binding(s) without a tagged routine yet (pending, non-fatal)")
    if errors:
        print(f"validate: {len(errors)} error(s):", file=sys.stderr)
        for line in errors:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"validate: OK ({len(items)} items)")
    return 0


def cmd_report(args):
    items = _load_or_die()
    records, coverage_errors = syngatelib.load_coverage(args.coverage)
    for line in coverage_errors:
        print(f"warning: {line}", file=sys.stderr)
    # Validation problems land on the items that own them, not on whichever
    # item's tooling found them.
    discovered, tag_problems = _discover(items)
    problems = syngatelib.item_problems(items, discovered)
    for uid, message in tag_problems:
        if uid in items:
            problems.setdefault(uid, []).append(message)
    report = syngatelib.compute_status(items, records, problems)
    out = Path(args.out)
    import json
    out.write_text(json.dumps(report, indent=2, sort_keys=True))
    counts = {}
    for entry in report.values():
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    print(f"wrote {out} -- {counts}")
    if args.html:
        import render_syngate_report
        render_syngate_report.run(out, Path(args.html))
        print(f"rendered site to {args.html}")
    return 0


def main():
    parser = argparse.ArgumentParser(prog="syngate", description=__doc__)
    parser.add_argument("--root", help="managed project root (default: SYNGATE_ROOT, else the nearest ancestor of the working directory holding syngate/)")
    sub = parser.add_subparsers(dest="command", required=True)

    def mutation(name, help):
        """A tree call: `--clear-review` is the user standing behind the change, dropping
        the stamps it moves. Omitted -- as when proxying an AI answer -- those stamps are
        left over changed content and the review reads as violated."""
        p = sub.add_parser(name, help=help)
        p.add_argument("uid")
        p.add_argument("--clear-review", action="store_true",
                       help="drop the review stamp of every item this call moves, instead of leaving it violated")
        return p

    p = mutation("add", "scaffold a syngate item")
    p.add_argument("--parent", action="append", required=True)
    p.add_argument("--dir", help="folder under the repo root, e.g. syngate/infra")
    p.add_argument("--order", type=int, default=0)
    p.add_argument("--description", help="the body: its first line names the item in the outline")
    p.add_argument("--source", action="append", help="root-relative key source file read into the seed context; repeatable")
    p.add_argument("--branch", action="store_true", help="carry no test binding of its own")
    p.set_defaults(func=cmd_add)

    p = mutation("edit", "change an item's description, key sources, sibling order or test setup")
    p.add_argument("--description", help="the body: its first line names the item in the outline")
    p.add_argument("--order", type=int)
    p.add_argument("--source", action="append", help="root-relative key source file; repeatable, the given list replaces the item's")
    p.add_argument("--run", help="the test setup's command line, run without a shell in the project root; the setup given replaces the item's")
    p.add_argument("--files", action="append", help="root-relative glob of the setup's test files; repeatable")
    p.add_argument("--report", choices=syngatelib.REPORT_FORMATS, help="the report format, overruling its detection")
    p.add_argument("--env", action="append", help="K=V over the environment of the run; repeatable")
    p.add_argument("--no-setup", action="store_true", help="remove the item's test setup, its bindings kept")
    p.set_defaults(func=cmd_edit)

    p = mutation("move", "add and remove an item's parent links, and place it among its siblings")
    p.add_argument("--to", required=True, help="the parent to place it under")
    p.add_argument("--before", help="sibling to land in front of (default: last)")
    p.add_argument("--from", dest="source", help="the parent link to re-point, or -- with --to another parent -- the link to drop")
    p.add_argument("--link", action="store_true", help="add --to as one more parent instead of re-pointing")
    p.set_defaults(func=cmd_move)

    p = mutation("rename", "give an item a new UID, its file and its children's parent links following it")
    p.add_argument("new_uid")
    p.set_defaults(func=cmd_rename)

    p = mutation("delete", "remove a childless item")
    p.set_defaults(func=cmd_delete)

    for name, help, func in (("query", "print an item as JSON: description, parents, sources, children and kind", cmd_query),
                             ("context", "print the seed AI-context of an item as an AI call anchored at it is formed", cmd_context)):
        p = sub.add_parser(name, help=help)
        p.add_argument("uid")
        if name == "context":
            p.add_argument("--label", help="the mark of the item's statement in the context, instead of 'active item'")
        p.set_defaults(func=func)

    p = sub.add_parser("review", help="user-only: stamp items reviewed, running and freezing the bound tests of those that carry any (stamps even on a failing test -- TDD red state)")
    p.add_argument("uid", nargs="+", help="UID(s) or glob pattern(s) like 'BUOY-00?' / 'BUOY-*' (quote patterns for the shell); patterns select leaves only")
    p.add_argument("--build-dir", default="cmake-build-debug-clang")
    p.add_argument("--coverage-out", help="coverage JSONL to fold the run's records into; a re-run binding supersedes its previous records")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("test", help="run the routines bound to leaf items, without stamping")
    p.add_argument("uid", nargs="+", help="UID(s) or glob pattern(s); patterns select leaves only")
    p.add_argument("--build-dir", default="cmake-build-debug-clang")
    p.add_argument("--coverage-out", help="coverage JSONL to fold the run's records into; a re-run binding supersedes its previous records")
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("clear", help="user-only: drop the reviewed stamp")
    p.add_argument("uid", nargs="+", help="UID(s) or glob pattern(s); patterns select reviewed items only")
    p.set_defaults(func=cmd_clear)

    p = sub.add_parser("validate", help="structural + frozen + coverage checks (CI gate)")
    p.add_argument("--coverage", action="append", default=[], help="syngate_coverage.jsonl file(s); repeatable")
    p.add_argument("--strict", action="store_true", help="require every item reviewed")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("report", help="recursive status rollup + optional HTML site")
    p.add_argument("--coverage", action="append", default=[], help="syngate_coverage.jsonl file(s); repeatable")
    p.add_argument("--out", default="syngate_status.json")
    p.add_argument("--html", help="output directory for the static site")
    p.set_defaults(func=cmd_report)

    args = parser.parse_args()
    syngatelib.set_root(args.root)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
