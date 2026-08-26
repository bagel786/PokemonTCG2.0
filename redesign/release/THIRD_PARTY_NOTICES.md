# Third-Party Notices

The release redistributes study-authored adapters and metadata, not the source
trees of the underlying systems. Dependencies are installed from their
canonical packages at reproduction time.

## RLCard

- Package: `rlcard==1.2.0`
- Repository: <https://github.com/datamllab/rlcard>
- License: MIT
- Use: open game/agent environment for two-player limit hold'em
- Local license copy: `LICENSES/RLCARD_MIT.md`
- Modifications: no RLCard source is redistributed; the study wraps and replaces
  RNG objects at public Python interfaces.

## ising-monte-carlo-toolkit

- Package/revision: v0.1.0 / commit
  `93515592d4942af757808a88ce527076cd0706c4`
- Repository: <https://github.com/ddsyasas/ising-monte-carlo-toolkit>
- License: MIT
- Use: open scientific two-dimensional Ising Metropolis simulator
- Local license copy: `LICENSES/ISING_TOOLKIT_MIT.txt`
- Modifications: no upstream source is redistributed; the study wraps the model
  RNG and sampler through public Python objects.

## Analysis/runtime dependencies

NumPy, SciPy, Matplotlib, pandas, ReportLab, Pillow, PyYAML, and their transitive
dependencies are installed from the pinned environment file. Their source is
not included in this archive. Each remains governed by its upstream license.

## Restricted legacy material

The motivating Pokémon engine case is described only through already-audited
aggregate counts. Restricted engine assets, opponent packages, and legacy raw
records are excluded from this public candidate.
