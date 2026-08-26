"""V2 system probes. Hold'em uses RLCard; Ising uses the licensed toolkit."""
from __future__ import annotations
import hashlib,json,time
import numpy as np
from .rng_manager import PhiloxEventRNG,sha256_id

def digest(x): return sha256_id(x)

def _choose(state, policy):
    ids=[int(x) for x in state["legal_actions"].keys()]
    names=dict(zip(ids,list(state["raw_legal_actions"])))
    order={"target_a":["check","call","fold","raise"],"target_b":["raise","call","check","fold"],"opponent_o":["call","check","fold","raise"]}[policy]
    for wanted in order:
        for i in ids:
            if names[i]==wanted:return i
    return ids[0]

class _ChanceAdapter:
    """RLCard-compatible adapter: only exogenous deck/dealer randomness is keyed."""
    def __init__(self,rng,namespace=""):
        self.rng=rng; self.namespace=namespace; self.hand=0; self.misc=0
    def shuffle(self,deck):
        h=self.hand; self.hand+=1
        for i in range(len(deck)-1,0,-1):
            j=self.rng.integers(f"{self.namespace}deal|hand={h}|fisher={i}",0,i+1)
            deck[i],deck[j]=deck[j],deck[i]
    def randint(self,low,high=None,size=None):
        if high is None: low,high=0,low
        if size is not None:
            return np.array([self.randint(low,high) for _ in range(int(np.prod(size)))],dtype=int).reshape(size)
        e=f"{self.namespace}dealer_misc|{self.misc}"; self.misc+=1
        return self.rng.integers(e,low,high)

def holdem_arm(root_seed:int,arm:str,repeat:int,scenario:str,context:str,hands:int=4):
    import rlcard
    t0=time.perf_counter(); ledger=[]
    effective=root_seed & 0xFFFF if scenario=="S1" else root_seed
    ns=""
    if scenario=="S2": ns="shifted|"
    if scenario=="S5" and context=="reused": ns="worker_state=1|"
    if scenario=="S6" and context=="reverse": ns="queue=reverse|"
    if scenario=="S8": ns=f"residual_repeat={repeat}|"
    run_hands=hands-1 if scenario=="S4" and context=="tight_budget" else hands
    chance=PhiloxEventRNG(effective,"holdem_exogenous",ledger)
    env=rlcard.make("limit-holdem",config={"seed":0})
    ca=_ChanceAdapter(chance,ns); env.game.np_random=ca; env.np_random=ca
    actions=[]; payoff=0.0; seat_records=[]
    target_policy="target_a" if arm=="A" else "target_b"
    for h in range(run_hands):
        target_seat=h%2
        env.reset(); step=0
        while not env.is_over():
            pid=int(env.get_player_id()); st=env.get_state(pid)
            pol=target_policy if pid==target_seat else "opponent_o"
            act=_choose(st,pol); env.step(act)
            actions.append({"hand":h,"step":step,"seat":pid,"acting_player":"target" if pid==target_seat else "opponent","policy_identity":pol,"action":act}); step+=1
        payoff += float(env.get_payoffs()[target_seat])
        seat_records.append(target_seat)
    projection={"actions_sha256":digest(actions),"payoff":payoff,"hands_completed":run_hands}
    artifact={"system":"holdem","arm":arm,"artifact_identity":f"rlcard-1.2.0:{target_policy}","opponent_identity":"opponent_o:v1","declared_seed":root_seed,"effective_seed":effective,"context":context,"repeat":repeat,"seat_schedule":seat_records,"actions":actions,"chance_events":ledger,"projection":projection,"trace_sha256":digest(projection),"runtime_s":time.perf_counter()-t0}
    artifact["bytes"]=len(json.dumps(artifact,separators=(",",":")))
    return artifact

class _IsingRNG:
    def __init__(self,rng,namespace): self.rng=rng; self.namespace=namespace; self.k=0
    def integers(self,low,high=None,size=None):
        if high is None: low,high=0,low
        if size is not None:
            vals=[self.integers(low,high) for _ in range(int(np.prod(size)))]
            return np.asarray(vals).reshape(size)
        k=self.k;self.k+=1;return self.rng.integers(f"{self.namespace}site|{k}",low,high)
    def random(self,size=None):
        if size is not None:return np.asarray([self.random() for _ in range(int(np.prod(size)))]).reshape(size)
        k=self.k;self.k+=1;return self.rng.random(f"{self.namespace}accept|{k}")
    def choice(self,a,size=None,replace=True,p=None):
        if size is None:return a[self.integers(0,len(a))]
        return np.asarray([self.choice(a,p=p) for _ in range(int(np.prod(size)))]).reshape(size)

def ising_arm(root_seed:int,arm:str,repeat:int,scenario:str,context:str,size:int=6,sweeps:int=8):
    from ising_toolkit.models import Ising2D
    from ising_toolkit.samplers import MetropolisSampler
    t0=time.perf_counter(); ledger=[]
    effective=root_seed & 0xFFFF if scenario=="S1" else root_seed
    ns=""
    if scenario=="S2":ns="shifted|"
    if scenario=="S5" and context=="reused":ns="worker_state=1|"
    if scenario=="S6" and context=="reverse":ns="queue=reverse|"
    if scenario=="S8":ns=f"residual_repeat={repeat}|"
    run_sweeps=sweeps-2 if scenario=="S4" and context=="tight_budget" else sweeps
    temperature=2.269 if arm=="A" else 2.9
    model=Ising2D(size=size,temperature=temperature,use_numba=False)
    rng=PhiloxEventRNG(effective,"ising_exogenous",ledger); model._rng=_IsingRNG(rng,ns)
    sampler=MetropolisSampler(model,seed=None,use_fast_sweep=False); sampler.rng=model._rng
    mags=[]
    for _ in range(run_sweeps):
        sampler.step(); mags.append(abs(float(model.get_magnetization()))/(size*size))
    projection={"magnetization_path_sha256":digest(mags),"mean_absolute_magnetization":float(np.mean(mags)),"sweeps_completed":run_sweeps}
    artifact={"system":"ising","arm":arm,"artifact_identity":f"ising-toolkit:temperature={temperature}","declared_seed":root_seed,"effective_seed":effective,"context":context,"repeat":repeat,"temperature":temperature,"trajectory":mags,"event_log":ledger,"projection":projection,"trace_sha256":digest(projection),"runtime_s":time.perf_counter()-t0}
    artifact["bytes"]=len(json.dumps(artifact,separators=(",",":")))
    return artifact

RUNNERS={"holdem":holdem_arm,"ising":ising_arm}
