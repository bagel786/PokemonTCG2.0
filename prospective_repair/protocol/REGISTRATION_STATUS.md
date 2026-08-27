# Registration / deposit status

This campaign's freeze is a **timestamped commit+annotated tag pushed to the private origin remote** (github.com/bagel786/PokemonTCG2.0 — private). It is NOT public preregistration, NOT a public protocol registry entry, and creates no DOI. No OSF/Zenodo/journal upload occurs from this workflow; any public deposit or submission requires explicit human authorization afterward.

Sanitized public-freeze package preparation (local only, no upload) is permitted and included in release tasks.

Wording rules enforced by tests on all repaired prose:
- required: "timestamped freeze pushed to a private remote prior to outcome acquisition"
- forbidden unless `PUBLIC_DEPOSIT_AUTHORIZED` marker file exists: "public git history", "preregistered", "registered", "publicly archived".
