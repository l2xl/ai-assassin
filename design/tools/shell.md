# Shell tool

**Shell commands go through the shell tool** (`prompts/shell.md`). `{"tool": "shell", "command":
"…"}` runs the command line with `sh -c` in the project root, without stdin, within a time limit;
its exit status and output, cut past a limit, go back as the next prompt and show in the reply. It
runs only while the chat's Raw command permission — the `bash` call mode every connector lists,
advanced and off by default — is on, a call refused otherwise (`raw commands are off for this chat
— switch Raw command on`); a command naming `syngate` is refused in every mode, the tree staying
the tree calls'. The same switch gives the Claude Code connector its own `Bash` tool.
