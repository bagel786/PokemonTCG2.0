from ptcg_ai.features import DecisionFeatures, OptionFeatures
from training.evaluate_elite_topk import empty_bucket, finalize, update_bucket


def features(cards: list[int]) -> DecisionFeatures:
    return DecisionFeatures(
        global_features=[0.0] * 118,
        state_tokens=[0],
        options=[
            OptionFeatures(
                option_type=1,
                context=0,
                source_card=card,
                target_card=0,
                attack_id=0,
                area=0,
                in_play_area=0,
                numeric=[0.0] * 12,
            )
            for card in cards
        ],
        feature_version=2,
    )


def test_top3_gate_excludes_fewer_than_four_semantic_choices():
    bucket = empty_bucket()
    update_bucket(bucket, features([1, 2, 3]), [2], [0, 1, 2], [0])
    result = finalize(bucket)
    assert result["rates"]["single_index_top3"]["value"] == 1.0
    assert result["rates"]["single_semantic_top3_eligible"]["value"] is None


def test_semantic_metric_collapses_indistinguishable_duplicate_options():
    bucket = empty_bucket()
    update_bucket(bucket, features([1, 1, 2, 3, 4]), [1], [0, 2, 3, 4, 1], [0])
    result = finalize(bucket)
    assert result["rates"]["single_index_top1"]["value"] == 0.0
    assert result["rates"]["single_semantic_top1"]["value"] == 1.0
    assert result["rates"]["single_semantic_top3_eligible"]["value"] == 1.0
