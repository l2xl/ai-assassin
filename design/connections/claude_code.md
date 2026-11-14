# Claude Code connector

The Claude Code connector runs the local `claude` CLI with the call modes as its permission mode
and allowed tools: Internet allows `WebSearch` and `WebFetch` and is on by default, the advanced
Raw command allows `Bash` and Workflows `Workflow`, both off by default. Its models are the unversioned aliases `fable`, `opus`, `sonnet` and `haiku`, passed
unchanged as `--model` so the installed CLI resolves the current version, a model's display name
being its id without a `claude-` prefix, and the chosen effort goes as `--effort`, a turn without
one leaving the CLI's default. Its default setup is `sonnet` at `high`.

The model never opens the files under `syngate/`: the connector denies `Read`, `Edit` and `Write`
under `syngate/**` in every mode, a shell command reading there refused the same way.

Its own subagents are off: the connector denies `Agent` and `Task` in every mode, so every subagent
starts through the harness's agent call.

**Closed tool set.** The connector names the CLI its whole built-in tool set with `--tools`: `Read`,
the tools of the call modes that are on and `Skill` while a skill on request is delivered; an agent
call names none. What the CLI ships beyond these — its scheduling, worktree, messaging and task
tools, whatever a later version adds — is not in the model's context, so the deny list is the second
fence and not the only one. The CLI keeps the answer tool of the schema and its own `EndConversation`
whatever it is named.

**Configuration isolation.** Nothing of the machine's Claude Code configuration enters a call:
`--setting-sources ""` leaves out the user, project and local settings with their `CLAUDE.md` files,
rules, skills, commands, subagents, hooks and permission rules, `--strict-mcp-config` every MCP
server, and the environment turns off the auto memory (`CLAUDE_CODE_DISABLE_AUTO_MEMORY`) and the
bundled skills (`CLAUDE_CODE_DISABLE_BUNDLED_SKILLS`). What a turn is told about the project is its
seed context: a project's `CLAUDE.md` reaches it only as a design file an item links. The managed
policy of the host and the login are read by the CLI regardless, and its own plugins still list
their skills (`design`, `doctor`, `plugin-authoring`) while `Skill` is in the tool set.

For this connector every model offers the effort levels, Haiku included, yet whether the model
exposes its reasoning still depends on the model and the effort — so `reasoning` steps are
optional in every transcript, never promised. It closes the turn with a `usage` step — `seconds`,
`cost_usd`, `input_tokens`, `output_tokens` as the CLI's `result` event reports them.

## Subagents of its own

**Own subagents off.** The connector denies `Agent` and `Task` in every mode, so no subagent starts inside the model's own
session; should the CLI report one anyway, it is observed, not steered. The Claude Code connector runs `claude` with
`--output-format stream-json --verbose`, so every message, tool call and result arrives as an
event, a subagent's launch with its prompt and its final report among them; after the turn the
connector reads the session's transcript files for the subagents' own turns and attaches them to
the `agent` steps. The delegation skill asks the model to open every subagent prompt with its
target item (`@UID` on the first line), and the harness mirrors such a subagent's report and
transcript into that item's chat as an agent message once the turn ends — every `agent`
step naming a known item other than the turn's anchor and its explicitly delegated children. Disk changes are the connector's
own record: snapshots of the project files before and after the turn yield the `diff` step, the
`Edit` / `Write` events its order.

## Workflows

**Workflows are monolithic.** A `Workflow` tool call is one `workflow` step holding its input and
result; the disk diff covers what it wrote; nothing is mirrored to children.

## Interruption

Interrupting is cooperative first, so that the model's engine stops spending tokens on an answer
nobody will read and the session stays resumable: the connector runs `claude` with
`--input-format stream-json`, the prompt going in as a user message, and sends the
`{"type": "control_request", "request": {"subtype": "interrupt"}}` message on its stdin — the CLI
aborts the API stream at once, records `[Request interrupted by user]` in the session and answers
with an error `result`. A process that has not ended within a grace period
(`claude_code_connector.grace` seconds) is killed with its whole process group, so the shell
commands and subagents it started die with it.
