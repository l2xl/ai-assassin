# Synergy Context Gate (Syngate)

The subsystem managing a project's DAG of statements, their test coverage and review status as a
gate: open while every status passes, closed by anything failed. It holds the project model — the
DAG and the design documents its items link — the test binding, the review freeze and the status
rollup, as the `syngatelib` library, the `syngate` CLI, `check_self_approval` and
`render_syngate_report`.
