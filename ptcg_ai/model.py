"""Small NumPy policy/value network used in Kaggle submissions."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from .features import MAX_SELECT_COUNT, encode_observation
from .safety import sanitize_selection


class NumpyPolicyModel:
    """Inference-only mirror of the PyTorch behavior-cloning model."""

    def __init__(self, path: str | Path):
        arrays = np.load(path, allow_pickle=False)
        self.weights = {name: arrays[name].astype(np.float32, copy=False) for name in arrays.files}
        self.feature_version = int(np.asarray(arrays["model_schema_version"]).item()) if "model_schema_version" in arrays else 1

    @staticmethod
    def _embedding(table, indices):
        return table[np.asarray(indices, dtype=np.int64)]

    def predict(self, features):
        w = self.weights
        state_rows = self._embedding(w["state_embedding"], features.state_tokens)
        if self.feature_version >= 2:
            state = state_rows.sum(axis=0) / np.sqrt(max(1, len(state_rows)))
        else:
            state = state_rows.mean(axis=0)
        global_vector = np.tanh(np.asarray(features.global_features, dtype=np.float32) @ w["global_w"] + w["global_b"])
        shared = np.concatenate([state, global_vector])
        option_rows = []
        for option in features.options:
            numeric = np.tanh(np.asarray(option.numeric, dtype=np.float32) @ w["numeric_w"] + w["numeric_b"])
            option_rows.append(np.concatenate([
                shared,
                w["card_embedding"][option.source_card],
                w["card_embedding"][option.target_card],
                w["attack_embedding"][option.attack_id],
                w["type_embedding"][option.option_type],
                w["context_embedding"][min(option.context, len(w["context_embedding"]) - 1)],
                w["area_embedding"][min(option.area, len(w["area_embedding"]) - 1)],
                w["area_embedding"][min(option.in_play_area, len(w["area_embedding"]) - 1)],
                numeric,
            ]))
        if option_rows:
            option_matrix = np.stack(option_rows)
            hidden = np.tanh(option_matrix @ w["option_w"] + w["option_b"])
            logits = hidden @ w["score_w"] + w["score_b"]
            context = features.options[0].context
        else:
            logits = np.empty(0, dtype=np.float32)
            context = 0
        count_input = np.concatenate([shared, w["context_embedding"][min(context, len(w["context_embedding"]) - 1)]])
        count_logits = count_input @ w["count_w"] + w["count_b"]
        value_logit = shared @ w["value_w"] + w["value_b"]
        return logits.reshape(-1), count_logits.reshape(-1), float(value_logit.reshape(-1)[0])


class NeuralPolicy:
    def __init__(self, path: str | Path, fallback, search_policy=None):
        self.model = NumpyPolicyModel(path)
        self.fallback = fallback
        self.search_policy = search_policy
        # ponytail: PTCG_TEMP unset/<=0 keeps exact greedy (slot A). >0 = Gumbel-top-k
        # sample for a decorrelated, higher-variance twin (slot B) under best-of-2.
        self.temp = float(os.environ.get("PTCG_TEMP", "0") or 0)
        self._rng = np.random.default_rng()

    def choose(self, obs) -> list[int]:
        features = encode_observation(obs, self.model.feature_version)
        logits, count_logits, _ = self.model.predict(features)
        if len(logits) == 0:
            return []
        if self.temp > 0.0:
            noisy = logits / self.temp + self._rng.gumbel(size=logits.shape)
            ranked = np.argsort(-noisy).astype(int).tolist()
        else:
            ranked = np.argsort(-logits).astype(int).tolist()
        if obs.select.minCount == obs.select.maxCount:
            desired = obs.select.maxCount
        else:
            minimum = int(obs.select.minCount)
            maximum = min(int(obs.select.maxCount), len(count_logits) - 1)
            desired = minimum + int(np.argmax(count_logits[minimum : maximum + 1]))
        # Invariant 1: Never skip benching during setup if basic Pokémon are available in hand
        context_val = getattr(obs.select, "context", None)
        if (context_val == 2 or str(context_val).endswith("SETUP_BENCH_POKEMON")) and obs.select.maxCount > 0:
            desired = max(1, min(int(obs.select.maxCount), desired or 1))

        # Invariant 2: Always promote 320 HP Grimmsnarl ex to Active (Context 4: TO_ACTIVE) when available
        if context_val == 4 or str(context_val).endswith("TO_ACTIVE"):
            from .view import option_source_card
            for opt_idx, opt in enumerate(obs.select.option):
                c = option_source_card(obs, opt)
                if c is not None and getattr(c, "id", None) == 648:
                    if opt_idx in ranked:
                        ranked.remove(opt_idx)
                        ranked.insert(0, opt_idx)
                    break
        
        greedy_action = sanitize_selection(obs.select, ranked, desired)

        # Selective 1-ply lookahead when search policy is configured
        if self.search_policy is not None and self.search_policy.should_search(logits, count_logits, obs.select):
            try:
                from .agent import _public_card_ids
                opp_ids = _public_card_ids(obs)
                _name, opp_deck, jaccard = self.search_policy.registry.match(opp_ids)
                if opp_deck is not None and jaccard >= self.search_policy.jaccard_threshold:
                    candidates = [greedy_action]
                    # Generate alternative candidates from next-best ranked options
                    if len(ranked) >= 2 and desired >= 1:
                        alt_ranked = [ranked[1]] + [r for r in ranked if r != ranked[1]]
                        alt_act = sanitize_selection(obs.select, alt_ranked, desired)
                        if alt_act != greedy_action:
                            candidates.append(alt_act)
                    if len(ranked) >= 3 and desired >= 1:
                        alt_ranked_3 = [ranked[2]] + [r for r in ranked if r != ranked[2]]
                        alt_act_3 = sanitize_selection(obs.select, alt_ranked_3, desired)
                        if alt_act_3 != greedy_action and alt_act_3 not in candidates:
                            candidates.append(alt_act_3)
                    
                    search_act = self.search_policy.evaluate_candidates(obs, candidates, opp_deck)
                    if search_act is not None:
                        # Safety rail: never let 1-ply search convert a productive
                        # greedy move into a turn-ending pass. Passing the turn is
                        # catastrophic and the (saturated) value head cannot be
                        # trusted to justify it over an available action.
                        def _is_pass(action):
                            return (
                                len(action) == 1
                                and int(obs.select.option[action[0]].type) == 14  # OptionType.END
                            )

                        if _is_pass(search_act) and not _is_pass(greedy_action):
                            return greedy_action
                        return search_act
            except Exception:
                pass

        return greedy_action
