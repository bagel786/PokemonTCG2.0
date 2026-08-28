# Reproduce the stop record

This procedure verifies the audit and the reason no confirmatory experiment exists. It does not reproduce a new scientific result.

Requirements:

- Git
- Python 3.9 or later, using only the standard library
- the repository's historical annotated freeze tag

From the repository root:

```sh
python independent_confirmation/verify_stop_record.py
git diff --exit-code 91ad7fa9571ee0ca10200fd7fe7b589589e8b794 HEAD -- prospective_repair redesign
git status --short
```

Expected verifier terminus:

```text
PASS: fail-closed stop record verified; no new confirmatory campaign exists
```

The verifier checks the tracked XZ archives by decompressing them in memory, counts newline-delimited rows, and compares compressed and uncompressed SHA-256 values. It does not write historical raw data.

Remote identity checks, which require access to the private origin:

```sh
git ls-remote origin refs/heads/paper/claim-specific-independent-confirmation-20260828
git ls-remote origin refs/tags/claim-specific-prospective-repair-freeze-20260827 refs/tags/claim-specific-prospective-repair-freeze-20260827^{}
```

The clean-checkout run and exact commit tested are recorded in `CLEAN_REPRODUCTION.md` after the final package commit.
