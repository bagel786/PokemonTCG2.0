# Clean-checkout reproduction report

- Tested package commit: `f41cc33a7ff2675a0ad01f737682e7565585ef2f`
- Mode: clean detached Git worktree
- Environment: Python 3.13.2; Apple Git 2.39.5
- Command: `python independent_confirmation/verify_stop_record.py`
- Verifier result: `PASS: fail-closed stop record verified; no new confirmatory campaign exists`
- Wall time: 1.21 seconds
- User CPU time: 1.08 seconds
- System CPU time: 0.06 seconds
- Base-to-package diff for `prospective_repair/` and `redesign/`: empty
- Detached-worktree status after verification: clean
- Temporary worktree: removed after verification

Key hashes observed in the clean worktree:

| Artifact | SHA-256 |
| --- | --- |
| `FINAL_STATUS.json` | `7692e7fd0f5f5a6756709104a39cdc9eab35d4761d5ee45f170eb4d9122a0737` |
| `DEFECT_LEDGER.csv` | `3d2e2321d2cb856ff0e000c0208fcc8052f68ac9e9080c6597c9f2f1432d6040` |
| `literature/FULL_TEXT_VERIFICATION.csv` | `890969e5bc9eb24b8571dd8ffccf2aadc144f30409d66142e989c048630299b9` |
| `claim_ledger.csv` | `94035801d92eb0b0a9f505b6b2ffc1747d8f92c8a687119eadef1d50a7164430` |

This is reproduction of the stop record only. It does not reproduce a new experiment, analysis, table, figure, or manuscript because none was authorized or created.
