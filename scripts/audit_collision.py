import numpy as np
from ptcg_ai.features import DecisionFeatures, EntityFeatures, OptionFeatures, TokenZone
from ptcg_ai.direct import NumpyDirectPolicyModel

def run_audit():
    model = NumpyDirectPolicyModel("artifacts/dragapult_emergency/bc_combined_8ep.npz")
    
    # Base global features
    global_feats_A = [0.0] * 124
    global_feats_B = [0.0] * 124
    
    # Let's say Slot 1 has 50 damage, Slot 2 has 0 damage
    # In global_features, pokemon slots are encoded. 
    # For opponent (player 1), the bench slots start somewhere around index 32 + 42 = 74.
    # We don't need exact indices, we just make them different.
    global_feats_A[80] = 50.0 / 400.0  # Slot 1 damage
    global_feats_A[87] = 0.0           # Slot 2 damage
    
    global_feats_B[80] = 0.0           # Slot 1 damage
    global_feats_B[87] = 50.0 / 400.0  # Slot 2 damage
    
    # We are considering an option to target our active pokemon.
    # In both Cases, the option is identical, targeting our active (Entity 0).
    option_A = OptionFeatures(
        option_type=1, context=1, source_card=10, target_card=10, attack_id=0,
        area=0, in_play_area=0, numeric=[0.0]*19, source_serial=1, target_serial=1,
        source_entity=0, target_entity=0
    )
    option_B = OptionFeatures(
        option_type=1, context=1, source_card=10, target_card=10, attack_id=0,
        area=0, in_play_area=0, numeric=[0.0]*19, source_serial=1, target_serial=1,
        source_entity=0, target_entity=0
    )
    
    # Entities:
    # Slot 1 is Dreepy (card_id 100, serial 2)
    # Slot 2 is Drakloak (card_id 200, serial 3)
    # In Case A, Dreepy has 50 damage, Drakloak has 0.
    numeric_A_slot1 = [1.0, 10/400.0, 60/400.0, 50/400.0] + [0.0]*12
    numeric_A_slot2 = [1.0, 90/400.0, 90/400.0, 0.0] + [0.0]*12
    
    entities_A = [
        EntityFeatures(card_id=10, serial=1, owner=0, zone=TokenZone.OWN_ACTIVE, slot=0, entity_type=1, numeric=[0.0]*16),
        EntityFeatures(card_id=100, serial=2, owner=1, zone=TokenZone.OPP_BENCH, slot=1, entity_type=1, numeric=numeric_A_slot1),
        EntityFeatures(card_id=200, serial=3, owner=1, zone=TokenZone.OPP_BENCH, slot=2, entity_type=1, numeric=numeric_A_slot2),
    ]
    
    # In Case B, Dreepy has 0 damage, Drakloak has 50 damage.
    numeric_B_slot1 = [1.0, 60/400.0, 60/400.0, 0.0] + [0.0]*12
    numeric_B_slot2 = [1.0, 40/400.0, 90/400.0, 50/400.0] + [0.0]*12
    
    entities_B = [
        EntityFeatures(card_id=10, serial=1, owner=0, zone=TokenZone.OWN_ACTIVE, slot=0, entity_type=1, numeric=[0.0]*16),
        EntityFeatures(card_id=100, serial=2, owner=1, zone=TokenZone.OPP_BENCH, slot=1, entity_type=1, numeric=numeric_B_slot1),
        EntityFeatures(card_id=200, serial=3, owner=1, zone=TokenZone.OPP_BENCH, slot=2, entity_type=1, numeric=numeric_B_slot2),
    ]
    
    feat_A = DecisionFeatures(
        global_features=global_feats_A, state_tokens=[], options=[option_A], feature_version=5,
        entities=entities_A, events=[]
    )
    feat_B = DecisionFeatures(
        global_features=global_feats_B, state_tokens=[], options=[option_B], feature_version=5,
        entities=entities_B, events=[]
    )
    
    logits_A, _ = model.predict(feat_A)
    logits_B, _ = model.predict(feat_B)
    
    print("Logits A:", logits_A)
    print("Logits B:", logits_B)
    diff = np.abs(logits_A - logits_B).sum()
    print("Difference:", diff)
    if diff == 0.0:
        print("COLLISION DETECTED: The model produces identical logits for different game states!")
    else:
        print("NO COLLISION: The model differentiates the states.")

if __name__ == "__main__":
    run_audit()
