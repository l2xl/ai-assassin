# Process rules (TDD gate)

- **Test-first, then freeze.** The covering routine is tagged with the leaf's UID before
  implementation; the user approves via `syngate review`, which freezes the routine by hash while it is
  still red — approval fixes *which* routine and *what it says*, not whether it already passes.
- **Frozen routines are immutable.** Editing a reviewed leaf's bound routine reddens the gate until
  a user-approved `syngate clear` + re-review.
- **Two-commit re-approval** (`check_self_approval.py`, Open Trader CI `approval` job): a commit that
  changes an item's approval may neither change the item's substance nor touch any file under the
  test trees. In a git work tree the review keeps it by construction: the footprint is committed
  before `review` stamps, and the page commits the stamps alone right after (the review commit).
- **CI flow** (Open Trader `.github/workflows/validate.yml`): build → ctest (emits
  `build-ci/syngate_coverage.jsonl`, uploaded as `syngate-coverage-cpp`) → syngate job: `gate.sh`,
  pytest (emits `pytest-coverage.jsonl`), coverage join via `gate.sh --coverage …`, `syngate report`,
  job summary + `Syngate Status` check run.
- **A red gate never costs the report.** The gate's verdict decides the job's colour, not whether
  the run is reported: every report step runs on `!cancelled()`, and `gate.sh`'s output (`gate: OK`
  / `gate: FAILED`) is captured into `syngate_validate.log` and folded into the top of both the job
  summary and the check run, so the reason for the red is read off the report itself.
