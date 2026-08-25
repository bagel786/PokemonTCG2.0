# Stage 6 stochastic-source audit decision rules

Generated from `protocol/stage6_source_audit_rules.json`; do not edit this table independently.

> A static hit does not prove execution dependence; a clean scan does not > prove determinism.

## Outcomes

| Outcome | Meaning | Claim effect |
|---|---|---|
| `CONTROLLED` | A stochastic mechanism was found and its influence on the compared executions was bounded or disabled with recorded evidence. | Supports treating the audited mechanism as controlled for the exercised schedule; does not by itself prove determinism. |
| `RESIDUAL` | A mechanism remains possible and was not shown estimand-changing, so claims are downgraded rather than suppressed. | Paired wording may not assert mechanistic equivalence; repeatability claims rest only on Stages 4-5 evidence. |
| `ESTIMAND_CHANGING` | A mechanism directly changes the execution relation needed by the comparison. | Paired mechanistic claims are suppressed for the affected comparison. |
| `UNAVAILABLE` | Source was unavailable or the boundary is black-box, blocking any source-level claim. | Stronger source-level claims are blocked; lower-stage evidence stands unchanged. |
| `UNRESOLVED` | A hit exists but the recorded evidence is insufficient to classify it; no automatic pass exists. | Claims are downgraded until remediation produces a classification. |

## Ordered decision rules

| Priority | Rule | Condition summary | Outcome | Required remediation |
|---:|---|---|---|---|
| 1 | `black_box_boundary` | source_access=unavailable_black_box | `UNAVAILABLE` | None available at this boundary; record the uninspected boundary explicitly and rely on Stages 4-5 behavioral evidence. |
| 2 | `undeclared_inventory` | source_access=available; inventory_declared=False | `UNRESOLVED` | Rerun the audit with a declared scanner version, category list, and scope; an undeclared inventory invalidates the stage. |
| 3 | `estimand_changing_hit` | source_access=available; inventory_declared=True; a hit with executes_dynamically=True, changes_execution_relation=True | `ESTIMAND_CHANGING` | Disable or bound the mechanism, re-verify Stages 4-5 on the modified configuration, and re-acquire before any paired claim. |
| 4 | `controlled_hit` | source_access=available; inventory_declared=True; a hit with executes_dynamically=True, changes_execution_relation=False, bounded_or_disabled=True, evidence_recorded=True | `CONTROLLED` | Record the bounding intervention and its evidence in the audit log; monitor for scope drift on future artifacts. |
| 5 | `unbounded_executing_hit` | source_access=available; inventory_declared=True; a hit with executes_dynamically=True, changes_execution_relation=False, bounded_or_disabled=False | `RESIDUAL` | Bound or disable the executing mechanism with recorded dynamic evidence, then reclassify under rule controlled_hit. |
| 6 | `dormant_or_unproven_hit` | source_access=available; inventory_declared=True; any hit present | `UNRESOLVED` | Collect dynamic evidence showing whether the branch executes and whether its effect is bounded; no automatic pass exists for any hit. |
| 7 | `clean_scan_no_proof` | source_access=available; inventory_declared=True; no hits | `RESIDUAL` | No remediation can convert a clean static scan into a determinism proof; rely on Stage 4-5 repeatability evidence for the exercised contexts and state the residual risk. |

Fail-closed default: `UNRESOLVED` — Unrecognized inputs, missing fields, and out-of-order evaluation default to UNRESOLVED.

