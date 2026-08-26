# Public release checklist (candidate → authorized)

Status: **CANDIDATE_NOT_AUTHORIZED.** Nothing below may reach `DONE` for the
authorization steps until the human completes `human_answers.yaml`. The
candidate at `paper/final_protocol/public_release_candidate/` (zip:
`public_release_candidate.zip`, manifest: `MANIFEST.sha256`) is built and
verified but must not be uploaded anywhere yet.

## Machine-verified already

- [x] Candidate assembled only from the allow-listed sanitized review package
      (build_final_release.py rejects extras, links, executables/archives,
      absolute paths, secret-like assignments, private identifiers).
- [x] No engine/binaries, third-party opponent packages, game assets or
      metadata, private observations, policy weights, raw restricted traces,
      credentials, Git history, `.venv-clean`, or nested archives present.
- [x] Recovered D03 aggregates carry source-digest provenance
      (`recovered_secondary_outputs_provenance`); positions never recorded;
      no position-level claims.
- [x] Release tests + manifest verification PASS in the clean environment
      (see CLEAN_ENV_REPRODUCTION.json).
- [x] Deterministic zip; SHA-256 sidecars recorded.

## Human authorization steps (blockers)

- [ ] Confirm ownership per component (`release_rights.owner_per_component`).
- [ ] Approve code redistribution + choose code license (recommendation: MIT).
- [ ] Approve processed-data/docs redistribution + license (rec.: CC BY 4.0).
- [ ] Approve redistribution of recovered actor counts + timing aggregates (D03).
- [ ] Authorize archive deposit (mints DOI); supply creators + maintainer.
- [ ] Run `apply_human_answers.py --apply` → writes real LICENSE files,
      CITATION.cff metadata, RELEASE_STATUS update, archive metadata.

## Post-authorization machine steps

- [ ] Rebuild candidate with approved licenses replacing `.proposed` files.
- [ ] Insert live DOI only after deposit exists (validator blocks otherwise).
- [ ] Re-run full reproduction; commit report envelope; verify chain.

## Upload (human-only)

- [ ] Deposit zip + metadata to Zenodo (or chosen repository).
- [ ] Record DOI back into YAML/apply; final rebuild; then cite the archived
      package from the manuscript DAS (Version A becomes selectable).

## Never upload (regardless of approvals above)

engine or binaries · third-party opponent packages · game assets/metadata ·
private observations · policy weights beyond what you own outright with clean
training provenance · raw restricted traces · credentials · internal QA
dossiers · review packages with no-license placeholders.
