# Rights and access audit

## Located terms

The tracked competition engine includes
`freshstart/engine/ptcgProgram/LICENSES/LicenseRef-PTCG-ABC-Competition-Use-Only.txt`.
Its plain-language notice states that the engine is not open source, limits use
to competition participation while the competition is running, prohibits
redistribution and outside use, requires deletion after the competition, treats
derived work as game-owner material under the competition rules, and defers to
the binding rules accepted by the entrant. The paper package must not reproduce
that engine or purport to override those terms.

No repository-level license grants rights in the authors' agent code, processed
data, model weights, or newly authored paper/release materials. Git identity is
not evidence of sole authorship or authority to license. The release therefore
uses a no-license review notice rather than inventing a permissive license.

## Excluded from the sanitized release

- official engine source, binaries, adapters copied from it, and rule tables;
- card images, names, text, databases, and deck lists;
- private replay observations, team names, and credentials;
- opponent packages and another participant's implementation;
- deployable policy packages and retained feature rows pending ownership review;
- historical archives whose redistribution rights are not established.

## Included under a strict allow list

- processed candidate/control outcomes and aggregate statistics;
- anonymous representation frequencies and held-out counts;
- frozen protocols, hashes, claim ledger, and provenance documentation;
- generic analysis, table, plotting, and abstract adapter code newly prepared for
  the paper;
- code-generated figures containing no game art, logo, screenshot, or UI.

## Human actions required before public release

1. Identify every human author and contributor and determine ownership of each
   newly authored file.
2. Obtain legal review of whether processed outcomes, learned weights, and
   agent-derived materials may be published under the competition rules.
3. Select approved code and data licenses, or maintain a clearly stated access
   restriction if open licensing is not authorized.
4. Confirm participant privacy and remove or obtain consent for any remaining
   identifiers.
5. Deposit only the reviewed allow list, issue an archive DOI, and replace the
   placeholder citation and maintainer metadata.
6. Confirm whether continued possession and use of the local engine after the
   competition is lawful; follow organizer deletion instructions where required.

Until these steps are complete, `paper/release/` is a private review artifact and not
an open-science public deposit.
