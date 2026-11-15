# Offered library

The prompt library holds every prompt the package ships; a chat is offered the part of it the
system the server runs on can serve. The selection is the one hook between what a machine has and
what a turn is told: a prompt states in its front matter what it needs, and the harness leaves out
what is not there, so no turn reads of a tool it cannot call and a tool with several possible
carriers is told by the best one present.

```yaml
---
kind: tool
feature: grep
rank: 1
requires:
  - command: [rg, --version]
---
```

- **Requirement.** `requires` lists the commands a prompt needs, each `{command: [argv…], output:
  text}`: met when the command, run in the project root without a shell, without stdin and within
  a short time limit, exits 0 and — where `output` is named — prints that text on its stdout or
  stderr. A command not found, failing or timing out is unmet, and so is an entry that is no such
  mapping. A prompt with any requirement unmet is left out of the offered library; a prompt without
  `requires` is always offered.
- **Feature.** `feature` names a facility several prompts serve as alternatives, `rank` their
  order of preference — a lower rank first, a prompt without one after every ranked one, ties by
  name. Of the prompts of one feature the offered library holds the first whose requirements are
  all met and none of the others; with none met the feature is absent. A prompt without `feature`
  is its own.
- **Probe.** Each requirement is probed once in a server's run, at its first need, and its outcome
  kept in the server's memory, keyed by its command and its output, for every later turn. The
  library stays live — a prompt file added or edited shapes the next turn — only a requirement
  already probed is not run again; installing a program while the server runs takes a restart.
- **Where it applies.** The offered library is what a chat's turns are built from: the default
  prompt heading a seed context, the skills and tools a connection of native delivery takes, the
  answer schema, and the library an off-context agent's lists draw from — so an agent listing a
  prompt left out is not covered. A prompt left out is as absent as one never written. The shipped
  library (`synthetic.LIBRARY`) stays whole for every reader that is no chat.
- **Default tool.** A tool declaring `default: true` — the read-only grep tool, each of its
  alternatives — is offered by the same rule as any other: while its requirements are met it
  enters every chat and every agent but a verdict agent, the agent listing it or not; while they are
  not, it enters none, its being default notwithstanding.
- **Git** is the first requirement: the git tool requires `git rev-parse --is-inside-work-tree` to
  print `true` in the project root, the hook carrying what used to be its special case.

What the hook does not do: it never installs or suggests a program, never changes a prompt's text
by what it found — an alternative of its own is written for each carrier — and never probes on a
turn's behalf beyond the commands the prompts name.
