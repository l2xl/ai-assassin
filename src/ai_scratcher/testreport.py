# AI Assassin
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Report discovery of the test setup (design/syngate/test_setup.md): the results of a JUnit, TAP or CTRF report, and their join
to the addressed routines by name.

`parse(text, format=None)` -> [{name, classname, file, passed, log}], the format told by the content unless named. A skipped
test is a failed one, since it did not run. `join(results, bindings)` -> {(uid, binding): [result]} over the addressed bindings,
each {uid, binding, tag, name, path, line}; a binding no result belongs to maps to []. `verdict` folds one binding's results
into its outcome, a binding without any failing with `no result`."""

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

FORMATS = ("junit", "ctrf", "tap")
NO_RESULT = "no result"
TAP_POINT_RE = re.compile(r"^\s*(not ok|ok)(?=\s|$)[ \t]*(?:\d+)?[ \t]*(?:-[ \t]*)?(.*)$")
TAIL = 4000  # characters of the output kept as the log of a binding without a result


def _result(name, classname="", file="", passed=True, log=""):
    return {"name": str(name or ""), "classname": str(classname or ""), "file": str(file or ""), "passed": bool(passed), "log": log}


def _junit_xml(text):
    """The XML document inside a text that may carry a runner's noise around it, '' where there is none."""
    start = min((i for i in (text.find("<?xml"), text.find("<testsuite")) if i >= 0), default=-1)
    ends = [text.rfind(tag) + len(tag) for tag in ("</testsuites>", "</testsuite>") if tag in text]
    return text[start:max(ends)] if start >= 0 and ends else ""


def parse_junit(text):
    """Results of the `testcase` elements of a JUnit XML; one holding a failure, an error or a skipped element is failed."""
    xml = _junit_xml(text)
    if not xml or "<!ENTITY" in xml:  # a report declares no entities; refusing them keeps a hostile one from expanding
        return []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    results = []

    def visit(node, suite_file):
        suite_file = node.get("file") or suite_file
        for child in node:
            if child.tag == "testcase":
                problems = [c for c in child if c.tag in ("failure", "error", "skipped")]
                log = "\n".join(f"{c.tag}: " + "\n".join(part for part in (c.get("message"), (c.text or "").strip()) if part)
                                for c in problems).strip()
                results.append(_result(child.get("name"), child.get("classname"), child.get("file") or suite_file, not problems, log))
            else:
                visit(child, suite_file)

    visit(root, "")
    return results


def parse_tap(text):
    """Results of the `ok` / `not ok` lines of a TAP stream; a SKIP directive fails the test, the diagnostics after a failed point are its log."""
    results = []
    for line in text.splitlines():
        point = TAP_POINT_RE.match(line)
        if point:
            description, _, directive = re.sub(r"\\#", "\0", point.group(2)).partition("#")
            skip = directive.strip().lower().startswith("skip")
            ok = point.group(1) == "ok" and not skip
            results.append(_result(description.replace("\0", "#").strip(), passed=ok, log=f"skipped {directive.strip()[4:].strip()}".strip() if skip else ""))
        elif results and not results[-1]["passed"] and line.strip() and (line.startswith("#") or line[:1] in " \t"):
            results[-1]["log"] = (results[-1]["log"] + "\n" + line.strip().lstrip("#").strip()).strip()
    return results


def _json_object(text):
    """The first JSON object of a text, or None."""
    start = text.find("{")
    while start >= 0:
        try:
            value, _ = json.JSONDecoder().raw_decode(text[start:])
        except ValueError:
            start = text.find("{", start + 1)
            continue
        if isinstance(value, dict):
            return value
        start = text.find("{", start + 1)
    return None


def parse_ctrf(text):
    """Results of the `results.tests` of a CTRF JSON; any status but `passed` is failed."""
    data = _json_object(text)
    tests = data.get("results", {}).get("tests") if isinstance(data, dict) and isinstance(data.get("results"), dict) else None
    if not isinstance(tests, list):
        return []
    results = []
    for test in tests:
        if not isinstance(test, dict):
            continue
        suite = test.get("suite")
        passed = test.get("status") == "passed"
        log = "" if passed else "\n".join(str(test[key]) for key in ("message", "trace") if test.get(key)) or f"status: {test.get('status')}"
        results.append(_result(test.get("name"), ".".join(suite) if isinstance(suite, list) else suite, test.get("filePath"), passed, log))
    return results


def detect(text):
    """The format a text is a report of -- 'junit', 'ctrf' or 'tap' -- or None."""
    if _junit_xml(text):
        return "junit"
    data = _json_object(text)
    if isinstance(data, dict) and isinstance(data.get("results"), dict) and isinstance(data["results"].get("tests"), list):
        return "ctrf"
    if any(TAP_POINT_RE.match(line) for line in text.splitlines()):
        return "tap"
    return None


def parse(text, format=None):
    """[{name, classname, file, passed, log}] -- the results of a report, in its format told by its content or named by `format`."""
    kind = format if format in FORMATS else detect(text or "")
    return {"junit": parse_junit, "ctrf": parse_ctrf, "tap": parse_tap}[kind](text) if kind else []


def _belongs(result_name, routine):
    """Whether a test name is a routine's name, or that name followed by a `(…)` signature or a `[…]` parameter."""
    return bool(routine) and (result_name == routine or result_name.startswith((routine + "(", routine + "[")))


def _names_file(result, path):
    """Whether the class or file of a result names the stem of a routine's file."""
    stem = Path(path).stem
    return stem in re.split(r"[./\\:]+", result["classname"]) or (bool(result["file"]) and Path(result["file"]).stem == stem)


def join(results, bindings):
    """{(uid, binding): [result]} -- the results belonging to each addressed binding's routine, [] where none does. A result belongs
    to a routine named as its test is; where addressed routines of different files share the name, its class or file must name the
    routine's file stem. Results of no addressed routine are dropped; several routines bound under one head share its results."""
    joined = {(b["uid"], b.get("binding") or None): [] for b in bindings}
    routines = {(b["path"], b["name"]) for b in bindings}
    for result in results:
        matching = sorted(r for r in routines if _belongs(result["name"], r[1]))
        if len(matching) > 1:
            matching = [r for r in matching if _names_file(result, r[0])]
        for b in bindings:
            if (b["path"], b["name"]) in matching:
                joined[(b["uid"], b.get("binding") or None)].append(result)
    return joined


def verdict(results, output=""):
    """(passed, log) of one binding's joined results: every one must have passed; none at all is `no result` over the tail of the output."""
    if not results:
        return False, f"{NO_RESULT}\n{(output or '')[-TAIL:]}".rstrip()
    return all(r["passed"] for r in results), "\n".join(r["log"] for r in results if not r["passed"] and r["log"])
