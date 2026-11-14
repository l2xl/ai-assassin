# Coverage JSONL

Test executions self-report which bindings ran: one JSON line
`{"tags": ["INFRA-066", "binding_name"], "passed": true, "name": …, "log": …}` appended to the
file named by `SYNGATE_COVERAGE_FILE` (no emission when unset).

- Emitters live in the managed project: a pytest `conftest.py` hook (see `tests/conftest.py` here)
  and, for Catch2, a listener linked into every test executable (Open Trader's
  `test/syngate_coverage_listener.cpp`).
- The gate joins records against `test:` in both directions: every reviewed leaf binding needs ≥1
  executed record, and every record's UID must match a known item.
