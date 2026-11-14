# Status rollup

Two independent axes per item (`compute_axes`; what the UI shows):

- **Test**: `unknown` | `test_passed` | `test_failed`. Leaf: any failed record → failed; any binding
  without a record → unknown; else passed. Branch: the worst of its children and its own bindings,
  if it carries any — a failed item fails every ancestor, else one unknown item leaves them
  unknown (the page shows `unknown` as `not run`). The axis reflects the run records alone — a violated review never reddens it. A run that cannot execute a binding (no or several tagged
  routines, test binary not built) records it as failed — a test that cannot be found is red.
- **Review**: `not_reviewed` | `reviewed` | `review_violated`. The worst of an item's own stamp and
  its children's axes: a branch is reviewed when it and everything below it is. An item's own
  validation problem (stale stamp, drifted frozen routine, malformed item) is a violated review;
  violated outranks not reviewed, which outranks reviewed. A branch's stamp covers its statement,
  parents and the list of its children, so editing a branch or adding a child under it clears it.
  A problem is attributed to the item it names and reaches only that item's ancestors — never the
  item whose tooling detected it, and never the whole tree: a coverage gap is not an item problem,
  since one missing coverage file would otherwise redden every reviewed leaf at once.

The single-status rollup below (`compute_status`) is what `syngate report`, the CI summary and the
check run still publish; SYNGATE-LEAF-STATUS and SYNGATE-BRANCH-STATUS define it, so retiring it in favour of the axes is a
user decision.

Leaf: no executed records → `not_implemented`; any failed record → `test_failed`; all bindings
covered and passing → `test_passed`; some covered → `partially_implemented`. A childless item
without a `tests` key has no bindings to cover, so it rolls up as `not_implemented` the same way.
Branch: aggregate of children (any failed → failed; all not_implemented → not_implemented; all
passed → passed; else partial).

**Validation problems redden the item they name, never the item that found them.** A stale review
stamp, a drifted frozen routine or a malformed item is a defect of *that* item: `item_problems`
attributes it by UID, `compute_status` marks the item `test_failed`, and it rolls up through that
item's own parents only. An item whose bound test detects such a violation is working, so it
stays green — the tooling's own tests assert tooling behaviour against fixtures, and where they read
the live tree they assert its *layout* (`validate_layout`), not its review state.
Coverage gaps are deliberately not item problems: an unrun binding already rolls up as
`not_implemented`, and one missing coverage file would otherwise redden every reviewed leaf at once.
