# Local models

The models AI Assassin is served by its user's own machines, and the command that sets them up,
`assassin-models` (`local_models.py`). It is a convenience beside the AI connections, not a part
of them: what it starts are ordinary OpenAI-compatible servers, reached through connections like
any other server, and nothing in AI Assassin requires that a model be local.

## The docker it needs

- An NVIDIA card with its driver and the NVIDIA Container Toolkit, for the CUDA presets.
- **Start at boot.** The containers restart with the daemon (`restart: unless-stopped`). A
  rootless daemon is a service of the user and starts with the user's first login unless lingering
  is on: `sudo loginctl enable-linger <user>` makes the models available from boot.
