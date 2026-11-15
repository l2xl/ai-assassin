# Grep tool

The **grep tool** searches the project's files for a pattern:
`{"tool": "grep", "command": "-n -i 'def main' src"}` carries the command line after the
program's name, split into words the way a POSIX shell splits them — quotes and backslashes, no
expansion — and never run by a shell. One call, three definitions: which program runs it, and so
the syntax its command line takes, is the one alternative of the `grep` feature the offered library
selects ([offered_library.md](../synthetic/offered_library.md)), the turn reading that one text
alone.

| prompt | rank | requires | runs |
|---|---|---|---|
| `grep_rg.md` | 1 | `rg --version` exits 0 | `rg` |
| `grep_gnu.md` | 2 | `grep --version` prints `GNU grep` | `grep -r` |
| `grep_git.md` | 3 | `git rev-parse --is-inside-work-tree` prints `true` | `git grep` |

- **Fallback.** Ripgrep is preferred, being fast and aware of the ignore files; GNU grep, present
  on nearly every Linux, follows it; git grep — the work tree's tracked files, `--untracked`
  adding the others — is the last, and needs git at hand for the project. With none of the three
  no grep tool is offered, and a `grep` call is refused naming why, as a git call is without git.
- **Run.** The program runs in the project root without stdin, within a time limit (60 s); its
  exit status and output, cut past a limit (30000 characters), come back as the next prompt the
  way a query's result does: `- grep <command line>:` over `exit <status>` and the output. Exit 1
  is no match, the model's to read, not a refusal. No permission switch gates the tool: it reads
  and changes nothing, like the files tool.
- **Fixed output.** The harness sets how the output reads, ahead of the turn's own options so they
  may override it: every match under its path and line number, no colour; ripgrep is run without
  its configuration file (`--no-config`, since one may name `--pre`), GNU grep recursively
  (`-r`, symbolic links not followed) with binary files skipped, git grep with no pager.

## Guard

The command line is the flexible part; the guard keeps it a read of the project's own files.

- **Listed options only.** Every option must be one the definition lists — long ones in full, no
  abbreviation; short ones alone or bundled (`-in`), a value glued (`-A3`, `--max-count=5`) or the
  next word. Any other option is refused, naming it, which keeps out what runs a program or reads
  past the project: ripgrep's `--pre`, `--search-zip`, `--follow`, `--ignore-file`, GNU grep's
  `-R` and `--devices`, git grep's `--no-index`, `-O` and `--recurse-submodules`.
- **Pattern and paths.** Up to `--` the words are options; the first other word is the pattern,
  unless an `-e` or `-f` gives it; every further word is a path — for git grep too, history being
  searched with the git tool's `grep`. A path, and the file `-f` reads, is guarded as the files tool
  guards a read: absolute, climbing or linking out of the project, in `.git`, under `syngate/` or
  naming the server settings or the stored chats, it is refused.
- **Excluded always.** A recursive search never enters `.git`, `syngate/` or those files: their
  excludes are appended last, so they win over the turn's own filters — ripgrep's `--glob '!…'`,
  GNU grep's `--exclude-dir` and `--exclude`, git grep's `:(exclude)` pathspecs after `--`.

## Options

| program | flags | taking a value |
|---|---|---|
| ripgrep | `-i` `--ignore-case`, `-S` `--smart-case`, `-s` `--case-sensitive`, `-w` `--word-regexp`, `-x` `--line-regexp`, `-F` `--fixed-strings`, `-v` `--invert-match`, `-n` `--line-number`, `-N` `--no-line-number`, `-l` `--files-with-matches`, `--files-without-match`, `-c` `--count`, `--count-matches`, `-o` `--only-matching`, `-U` `--multiline`, `--multiline-dotall`, `-P` `--pcre2`, `--hidden`, `--no-ignore`, `-u` `--unrestricted`, `-H` `--with-filename`, `-I` `--no-filename`, `--column`, `--vimgrep` | `-e` `--regexp`, `-f` `--file`, `-g` `--glob`, `--iglob`, `-t` `--type`, `-T` `--type-not`, `-A` `--after-context`, `-B` `--before-context`, `-C` `--context`, `-m` `--max-count`, `-d` `--max-depth`, `-M` `--max-columns`, `-r` `--replace`, `--sort` |
| GNU grep | `-i` `--ignore-case`, `--no-ignore-case`, `-w` `--word-regexp`, `-x` `--line-regexp`, `-F` `--fixed-strings`, `-E` `--extended-regexp`, `-G` `--basic-regexp`, `-P` `--perl-regexp`, `-v` `--invert-match`, `-n` `--line-number`, `-l` `--files-with-matches`, `-L` `--files-without-match`, `-c` `--count`, `-o` `--only-matching`, `-h` `--no-filename`, `-H` `--with-filename`, `-s` `--no-messages`, `-a` `--text`, `-I` | `-e` `--regexp`, `-f` `--file`, `-A` `--after-context`, `-B` `--before-context`, `-C` `--context`, `-m` `--max-count`, `--include`, `--exclude`, `--exclude-dir` |
| git grep | `-i` `--ignore-case`, `-w` `--word-regexp`, `-v` `--invert-match`, `-n` `--line-number`, `-l` `--files-with-matches` `--name-only`, `-L` `--files-without-match`, `-c` `--count`, `-o` `--only-matching`, `-h`, `-H`, `-F` `--fixed-strings`, `-E` `--extended-regexp`, `-G` `--basic-regexp`, `-P` `--perl-regexp`, `--untracked`, `--cached`, `--all-match`, `--column` | `-e`, `-f`, `-A` `--after-context`, `-B` `--before-context`, `-C` `--context`, `-m` `--max-count`, `--max-depth` |
