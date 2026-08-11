from scripts.split_order_value_rollouts import split_name


def test_episode_hash_split_is_stable_and_bounded():
    observed = {split_name(f"episode-{index}") for index in range(100)}
    assert observed == {"train", "validation", "holdout"}
    assert split_name("episode-42") == split_name("episode-42")
