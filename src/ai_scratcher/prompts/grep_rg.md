---
kind: tool
default: true
description: Search the project's files with ripgrep, changing nothing
feature: grep
rank: 1
requires:
  - command: [rg, --version]
calls:
  grep:
    required: [command]
---
# Grep
`{"tool": "grep", "command": "-i -g '*.py' 'def main' src"}` searches the project's files with ripgrep (`rg`): the command line after the program's name, split into words as a shell splits them but never run by one, in the project root; its exit status and every match under its path and line number come back as your next prompt, exit 1 telling no match.
- It reads only and is always allowed. Up to `--` the words are options; the first other word is the pattern, unless `-e` or `-f` gives it, and every further word a path to search — the project root without any. Ripgrep leaves out what the ignore files hold, hidden files and binary files unless `--hidden`, `--no-ignore` or `-u` widens it.
- Its options: `-i` `--ignore-case`, `-S` `--smart-case`, `-s` `--case-sensitive`, `-w` `--word-regexp`, `-x` `--line-regexp`, `-F` `--fixed-strings`, `-v` `--invert-match`, `-n` `--line-number`, `-N` `--no-line-number`, `-l` `--files-with-matches`, `--files-without-match`, `-c` `--count`, `--count-matches`, `-o` `--only-matching`, `-U` `--multiline`, `--multiline-dotall`, `-P` `--pcre2`, `--hidden`, `--no-ignore`, `-u` `--unrestricted`, `-H` `--with-filename`, `-I` `--no-filename`, `--column`, `--vimgrep`; with a value, glued (`-A3`, `--max-count=5`) or as the next word: `-e` `--regexp`, `-f` `--file`, `-g` `--glob`, `--iglob`, `-t` `--type`, `-T` `--type-not`, `-A` `--after-context`, `-B` `--before-context`, `-C` `--context`, `-m` `--max-count`, `-d` `--max-depth`, `-M` `--max-columns`, `-r` `--replace`, `--sort`. Any other option is refused, a long one named in full.
- A path and the `-f` file stay in the project: one outside it, in `.git`, under `syngate/`, through a symbolic link or naming the server's own settings and chat files is refused, and a search never enters them whatever its globs — the items are read through the tree calls.
- The history is searched with the git tool's `grep`; the files tool reads the lines around a match.
