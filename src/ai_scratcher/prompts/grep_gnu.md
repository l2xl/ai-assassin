---
kind: tool
default: true
description: Search the project's files with GNU grep, changing nothing
feature: grep
rank: 2
requires:
  - command: [grep, --version]
    output: GNU grep
calls:
  grep:
    required: [command]
---
# Grep
`{"tool": "grep", "command": "-i --include=*.py 'def main' src"}` searches the project's files with GNU grep, recursively: the command line after the program's name, split into words as a shell splits them but never run by one, in the project root; its exit status and every match under its path and line number come back as your next prompt, exit 1 telling no match.
- It reads only and is always allowed. Up to `--` the words are options; the first other word is the pattern, unless `-e` or `-f` gives it, and every further word a path to search — the project root without any. The search is recursive (`-r`, symbolic links not followed) and skips binary files unless `-a` is given.
- Its options: `-i` `--ignore-case`, `--no-ignore-case`, `-w` `--word-regexp`, `-x` `--line-regexp`, `-F` `--fixed-strings`, `-E` `--extended-regexp`, `-G` `--basic-regexp`, `-P` `--perl-regexp`, `-v` `--invert-match`, `-n` `--line-number`, `-l` `--files-with-matches`, `-L` `--files-without-match`, `-c` `--count`, `-o` `--only-matching`, `-h` `--no-filename`, `-H` `--with-filename`, `-s` `--no-messages`, `-a` `--text`, `-I`; with a value, glued (`-A3`, `--max-count=5`) or as the next word: `-e` `--regexp`, `-f` `--file`, `-A` `--after-context`, `-B` `--before-context`, `-C` `--context`, `-m` `--max-count`, `--include`, `--exclude`, `--exclude-dir`. Any other option is refused, a long one named in full.
- A path and the `-f` file stay in the project: one outside it, in `.git`, under `syngate/`, through a symbolic link or naming the server's own settings and chat files is refused, and a search never enters them whatever its includes — the items are read through the tree calls.
- The history is searched with the git tool's `grep`; the files tool reads the lines around a match.
