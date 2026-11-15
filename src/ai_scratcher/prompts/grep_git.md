---
kind: tool
default: true
description: Search the project's work tree with git grep, changing nothing
feature: grep
rank: 3
requires:
  - command: [git, rev-parse, --is-inside-work-tree]
    output: "true"
calls:
  grep:
    required: [command]
---
# Grep
`{"tool": "grep", "command": "-i 'def main' src"}` searches the project's work tree with `git grep`: the command line after `git grep`, split into words as a shell splits them but never run by one, in the project root; its exit status and every match under its path and line number come back as your next prompt, exit 1 telling no match.
- It reads only and is always allowed. Up to `--` the words are options; the first other word is the pattern, unless `-e` or `-f` gives it, and every further word a literal path to search — the whole work tree without any, no pathspec magic. It searches the files git tracks, `--untracked` adding the others it does not ignore and `--cached` searching the index instead.
- Its options: `-i` `--ignore-case`, `-w` `--word-regexp`, `-v` `--invert-match`, `-n` `--line-number`, `-l` `--files-with-matches` `--name-only`, `-L` `--files-without-match`, `-c` `--count`, `-o` `--only-matching`, `-h`, `-H`, `-F` `--fixed-strings`, `-E` `--extended-regexp`, `-G` `--basic-regexp`, `-P` `--perl-regexp`, `--untracked`, `--cached`, `--all-match`, `--column`; with a value, glued (`-A3`, `--max-count=5`) or as the next word: `-e`, `-f`, `-A` `--after-context`, `-B` `--before-context`, `-C` `--context`, `-m` `--max-count`, `--max-depth`. Any other option is refused, a long one named in full.
- A path and the `-f` file stay in the project: one outside it, in `.git`, under `syngate/`, through a symbolic link or naming the server's own settings and chat files is refused, and a search never enters them — the items are read through the tree calls.
- The history is searched with the git tool's `grep`; the files tool reads the lines around a match.
