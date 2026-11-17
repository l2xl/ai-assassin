# Open Trader
# Copyright (c) 2026 l2xl (l2xl/at/proton.me)
# Distributed under the Intellectual Property Reserve License, v2 (IPRL)

"""Run selection of a test setup: a `run` line expanded into the commands of the addressed bindings (design/syngate/test_setup.md).

A pure expansion -- nothing is run or touched. A binding is a mapping `{uid, binding, tag, name, path, line}`. The line is split into
words as a shell splits them; plural placeholders (`{ids}`, `{names}`, `{tags}`, `{uids}`, `{paths}`) join the values of all addressed
bindings into one command, singular ones (`{id}`, `{name}`, `{tag}`, `{uid}`, `{binding}`, `{path}`, `{line}`) make one command per
binding, a line with neither runs the whole suite once; `{report}` and `{root}` are plain substitutions.
"""

import re
import shlex

PLURAL = {"ids": lambda b: f"{b['path']}::{b['name']}", "names": lambda b: str(b["name"]), "tags": lambda b: str(b["tag"]),
          "uids": lambda b: str(b["uid"]), "paths": lambda b: str(b["path"])}
SINGULAR = {"id": lambda b: f"{b['path']}::{b['name']}", "name": lambda b: str(b["name"]), "tag": lambda b: str(b["tag"]),
            "uid": lambda b: str(b["uid"]), "binding": lambda b: str(b.get("binding") or ""), "path": lambda b: str(b["path"]),
            "line": lambda b: str(b["line"])}
PLAIN = ("report", "root")
PLACEHOLDER_RE = re.compile(r"\{(\w+)(?::([^{}]*))?\}")


def _plain(word, values):
    """The word with `{root}` and `{report}` replaced; a value that is None is refused."""
    def replace(match):
        name = match.group(1)
        if name not in PLAIN:
            return match.group(0)
        if values[name] is None:
            raise ValueError(f"{{{name}}} has no value here")
        return str(values[name])
    return PLACEHOLDER_RE.sub(replace, word)


def commands(run, bindings, root, report=None):
    """[(argv, [binding])] -- the argument lists `run` expands to for `bindings`, each with the bindings it runs; ValueError for an empty
    line, an unknown placeholder, a plural one inside a longer word without join text, or singular and plural ones mixed."""
    words = shlex.split(run)
    if not words:
        raise ValueError("empty run line")
    values = {"root": str(root), "report": None if report is None else str(report)}
    bindings = list(bindings)
    plural, singular = False, False
    for word in words:
        for match in PLACEHOLDER_RE.finditer(word):
            name, join = match.group(1), match.group(2)
            if name not in PLURAL and name not in SINGULAR and name not in PLAIN:
                raise ValueError(f"unknown placeholder {{{name}}} in run line")
            if name in SINGULAR:
                if join is not None:
                    raise ValueError(f"{{{name}}} is singular and takes no join text")
                singular = True
            elif name in PLURAL:
                plural = True
                if join is None and match.group(0) != word:
                    raise ValueError(f"{{{name}}} inside a longer word needs join text, as {{{name}:,}}")
    if plural and singular:
        raise ValueError("a run line cannot mix singular and plural selection placeholders")
    if not bindings:
        return []
    if singular:
        return [([_single(word, binding, values) for word in words], [binding]) for binding in bindings]
    if plural:
        argv = []
        for word in words:
            argv.extend(_joined(word, bindings, values))
        return [(argv, bindings)]
    return [([_plain(word, values) for word in words], bindings)]


def _single(word, binding, values):
    """The word of a one-binding command: its singular placeholders and the plain ones replaced."""
    word = PLACEHOLDER_RE.sub(lambda m: SINGULAR[m.group(1)](binding) if m.group(1) in SINGULAR else m.group(0), word)
    return _plain(word, values)


def _joined(word, bindings, values):
    """The words a word becomes in the one command of all bindings: a bare plural placeholder one word per value, else the joined text."""
    bare = PLACEHOLDER_RE.fullmatch(word)
    if bare and bare.group(1) in PLURAL and bare.group(2) is None:
        return _values(bare.group(1), bindings)

    def replace(match):
        name, join = match.groups()
        return join.join(_values(name, bindings)) if name in PLURAL else match.group(0)
    return [_plain(PLACEHOLDER_RE.sub(replace, word), values)]


def _values(name, bindings):
    """The value of a plural placeholder for each binding, `{paths}` each file once."""
    found = [PLURAL[name](binding) for binding in bindings]
    return list(dict.fromkeys(found)) if name == "paths" else found
