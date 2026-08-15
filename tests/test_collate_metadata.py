import sys
from pathlib import Path
import torch
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from training.train_bc import collate
from dragapult_emergency_train import semantic_group_loss, apply_grim_weight

def create_mock_row(action_groups=None, grim=None, action=[0], options=2):
    features = {
        "global": [0.0] * 31,
        "tokens": [],
        "entities": [],
        "events": [],
        "options": [
            {"option_type": 1, "context": 0, "source_card": 0, "target_card": 0, "attack_id": 0, "area": 0, "in_play_area": 0, "numeric": [0.0] * 12}
            for _ in range(options)
        ]
    }
    row = {
        "features": features,
        "action": action,
        "reward": 1.0,
        "sample_weight": 1.0,
    }
    if action_groups is not None:
        row["action_groups"] = action_groups
    if grim is not None:
        row["opponent_grimmsnarl"] = grim
    return row

def test_action_groups_survives():
    groups = [[0, 1]]
    row = create_mock_row(action_groups=groups)
    batch = collate([row])
    assert batch["record_action_groups"][0] == groups

def test_missing_action_groups_is_none():
    row = create_mock_row()
    batch = collate([row])
    assert batch["record_action_groups"][0] is None

def test_grimmsnarl_survives():
    row = create_mock_row(grim=True)
    batch = collate([row])
    assert batch["record_grimmsnarl"][0] is True

def test_missing_grimmsnarl_is_false():
    row = create_mock_row()
    batch = collate([row])
    assert batch["record_grimmsnarl"][0] is False

def test_semantic_group_loss_differs():
    # Construct a case where the network predicts option 1 strongly, but option 0 was the action.
    # If option 1 is in the same semantic group, semantic loss should be lower.
    groups = [[0, 1]]
    row = create_mock_row(action_groups=groups, action=[0], options=2)
    batch = collate([row])
    
    logits = torch.tensor([[0.0, 10.0]])  # option 1 is predicted
    
    # Standard cross entropy for this
    exact_loss = F.cross_entropy(logits, torch.tensor([0]))
    
    # Semantic loss
    sem_loss, exact_count, sem_total = semantic_group_loss(logits, batch)
    
    assert sem_loss < exact_loss
    assert sem_loss < 0.1  # It should be near zero because the predicted option 1 is in the group

def test_grim_weighting():
    batch = collate([
        create_mock_row(grim=True),
        create_mock_row(grim=False)
    ])
    
    apply_grim_weight(batch, 2.0)
                
    assert batch["weights"][0].item() == 2.0
    assert batch["weights"][1].item() == 1.0

def test_grim_weighting_zero_is_noop():
    batch = collate([create_mock_row(grim=True)])
    apply_grim_weight(batch, 0.0)
    assert batch["weights"][0].item() == 1.0

def test_grim_weighting_absent_is_noop():
    batch = collate([create_mock_row()])
    # Manually remove it to simulate an older collate or unexpected absence
    if "record_grimmsnarl" in batch:
        del batch["record_grimmsnarl"]
    apply_grim_weight(batch, 2.0)
    assert batch["weights"][0].item() == 1.0
