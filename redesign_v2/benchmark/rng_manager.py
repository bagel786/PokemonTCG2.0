"""Counter-based semantic-event RNG using NumPy Philox."""
from __future__ import annotations
import hashlib, json
import numpy as np

def canonical_bytes(value)->bytes:
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()

def sha256_id(value)->str: return hashlib.sha256(canonical_bytes(value)).hexdigest()

class PhiloxEventRNG:
    """Each event owns a Philox stream; SHA-256 maps identity to key/counter."""
    def __init__(self, root_seed:int, stream_id:str, ledger:list|None=None):
        self.root_seed=int(root_seed); self.stream_id=str(stream_id); self.ledger=ledger if ledger is not None else []
        self.counts={}
    def _generator(self,event_id:str,draw_number:int):
        material=canonical_bytes({"root_seed":self.root_seed,"stream_id":self.stream_id,"semantic_event_id":str(event_id)})
        # Philox accepts a two-word key and four-word counter. Domain-separated
        # SHA-256 digests provide all six uint64 words without Python hashing.
        kd=hashlib.sha256(b"philox-key\0"+material).digest()
        cd=hashlib.sha256(b"philox-counter\0"+material).digest()
        key=np.frombuffer(kd[:16],dtype="<u8").copy()
        counter=np.frombuffer(cd,dtype="<u8").copy()
        bitgen=np.random.Philox(counter=counter,key=key)
        if draw_number: bitgen.advance(draw_number)
        return np.random.Generator(bitgen)
    def _next(self,event_id):
        event_id=str(event_id); n=self.counts.get(event_id,0); self.counts[event_id]=n+1
        return event_id,n,self._generator(event_id,n)
    def random(self,event_id:str)->float:
        e,n,g=self._next(event_id); v=float(g.random())
        self.ledger.append({"root_seed":self.root_seed,"stream_key":self.stream_id,"semantic_event_id":e,"draw_number":n,"value":v,"value_type":"float64"}); return v
    def integers(self,event_id:str,low:int,high:int)->int:
        e,n,g=self._next(event_id); v=int(g.integers(low,high))
        self.ledger.append({"root_seed":self.root_seed,"stream_key":self.stream_id,"semantic_event_id":e,"draw_number":n,"value":v,"value_type":"int64","low":low,"high":high}); return v
    def normal(self,event_id:str)->float:
        e,n,g=self._next(event_id); v=float(g.normal())
        self.ledger.append({"root_seed":self.root_seed,"stream_key":self.stream_id,"semantic_event_id":e,"draw_number":n,"value":v,"value_type":"float64_normal"}); return v
