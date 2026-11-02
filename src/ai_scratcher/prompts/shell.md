---
kind: tool
description: Run a shell command in the project root through the harness, only while the chat's Raw command permission is on
calls:
  shell:
    required: [command]
---
# Shell
`{"tool": "shell", "command": "pytest -q tests/test_area.py"}` runs the command line with `sh -c` in the project root; its exit status and output, cut past a limit, come back as your next prompt. It is refused while the chat's Raw command permission is off: then answer in text and say what you would run.
- No stdin and no terminal: a command waiting for input or an editor fails, and one running past the time limit is ended.
- A command naming `syngate` is refused: the items are read and changed only through the tree calls.
- Change project files with the patch tool and read or record the history with the git tool; the shell is for what neither does — building, running tests or scripts, inspecting the environment, and the git commands the git tool does not run but which erase nothing, such as `git submodule add`.
