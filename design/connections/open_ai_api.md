# OpenAI-compatible API connections

An OpenAI-compatible API connection (`api_connection.api_connection`, module
`src/ai_scratcher/api_connection.py`) is an AI connection of AI Assassin to any server speaking the
OpenAI chat completions API: a gateway such as [MixRoute](https://mixroute.ai/docs/en/introduction),
giving one key to the models of many providers, or a self-hosted [llama.cpp](https://github.com/ggml-org/llama.cpp)
`llama-server`. The server settings configure as many connections as wanted, each by an id of its
own, and the page offers them side by side next to the Claude Code connector. Where the Claude Code
connector drives a local agent with its own file and shell tools, an API connection answers with the
model's text alone: its turn works the project only through the harness's tool calls — the tree
calls, queries, test runs, delegations, git, patch, WebSurf and the shell — and never edits a file or
runs a command itself. Its one call mode is the advanced Raw command, off by default, which lets the
shell calls of its answers run; besides it the page shows the harness's Tree edit, Edit files and
Interactive WebSurf switches.

The module depends on `synthetic` for the connection error, the prompt library and the answer
schema; `synthetic` does not import it, and the AI Assassin server builds the connections from the
settings next to the connectors `synthetic.CONNECTORS` names.
