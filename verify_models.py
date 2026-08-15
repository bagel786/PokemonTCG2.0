import numpy as np
from pathlib import Path
import hashlib
import sys
import torch

ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from training.schema5 import DirectPolicyNet, load_direct
from ptcg_ai.direct import NumpyDirectPolicyModel

paths = [
    "artifacts/dragapult_emergency/bc_combined_sem.npz",
    "artifacts/dragapult_emergency/bc_combined_grim3.npz",
    "artifacts/dragapult_emergency/bc_combined_8ep.npz",
    "artifacts/dragapult_emergency/bc_flg_full.npz"
]

for p in paths:
    path = Path(p)
    if not path.exists():
        continue
    size = path.stat().st_size
    with open(path, "rb") as f:
        sha256 = hashlib.sha256(f.read()).hexdigest()
    try:
        data = np.load(path, allow_pickle=True)
        has_nans = False
        for k in data.keys():
            if k == "metadata": continue
            if np.isnan(data[k]).any() or not np.isfinite(data[k]).all():
                has_nans = True
                
        print(f"Path: {p}")
        print(f"Size: {size}")
        print(f"SHA256: {sha256}")
        print(f"model_schema_version: {data.get('model_schema_version', None)}")
        print(f"direct_model_version: {data.get('direct_model_version', None)}")
        print(f"NaNs: {has_nans}")
        
        try:
            model = NumpyDirectPolicyModel(p)
            print("NumpyDirectPolicyModel: Loaded")
        except Exception as e:
            print(f"NumpyDirectPolicyModel: Failed ({e})")
            
        try:
            net = DirectPolicyNet()
            load_direct(net, p)
            print("DirectPolicyNet+load_direct: Loaded")
        except Exception as e:
            print(f"DirectPolicyNet+load_direct: Failed ({e})")
            
    except Exception as e:
        print(f"Error {p}: {e}")
    print("---")
