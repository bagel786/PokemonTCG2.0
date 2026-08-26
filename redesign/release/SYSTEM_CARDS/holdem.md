# System Card: RLCard Limit Hold'em

- Role: open game/agent system
- Upstream: <https://github.com/datamllab/rlcard>
- Version: 1.2.0
- License: MIT
- Adapter: `code/benchmark/adapters.py` (`HoldemAdapter`)
- Arms: random versus conservative policy; ten hands; seat-0 chip total
- Random sources: dealer shuffle and independently spawned agent-action stream
- Trace projection: trajectory hash, terminal outcome, and step count
- Event ontology: keyed shuffle/action events in S3

Limitations: limit hold'em does not represent all stochastic games; betting
legality simplifies some dynamics; clock scenarios are laptop/context specific;
S3's keyed action implementation ignores the policy distinction and therefore
collapses the intended arm contrast. The card supports only the exact tested
wrapper and settings.
