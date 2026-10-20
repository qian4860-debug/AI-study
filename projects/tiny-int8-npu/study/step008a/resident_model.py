"""Transactional host-side model residency, independent of the arithmetic RTL."""
from pathlib import Path
import copy,hashlib,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'step006'))
from reference import infer,lower_loads,validate

def model_id(model,layout):
    validate(model)
    return hashlib.sha256(json.dumps(dict(model=model,layout=layout),sort_keys=True,separators=(',',':')).encode()).hexdigest()

class ResidentModel:
    def __init__(self,layout='k4o1'):
        self.layout=layout;self.resident=None;self.pending=None;self.acknowledged=0

    def invalidate(self):
        # Conservative host policy on reset/power loss or an interrupted upload.
        self.resident=None;self.pending=None;self.acknowledged=0

    def begin_model(self,model):
        if self.pending is not None:raise RuntimeError('upload already pending')
        key=model_id(model,self.layout)
        if key==self.resident:return []
        frozen=copy.deepcopy(model)
        commands=[tuple(c) for c in lower_loads(frozen,[0]*model['shape'][0]) if c[1]!=0]
        # Partial writes may overwrite the previous model: invalidate immediately.
        self.resident=None;self.pending=(key,tuple(commands));self.acknowledged=0
        return list(commands)

    def acknowledge_write(self,command,accepted):
        if not accepted:return False
        if self.pending is None or self.acknowledged>=len(self.pending[1]):raise RuntimeError('no pending write')
        if tuple(command)!=self.pending[1][self.acknowledged]:raise RuntimeError('out-of-order write')
        self.acknowledged+=1;return True

    def finish_model(self):
        if self.pending is None or self.acknowledged!=len(self.pending[1]):raise RuntimeError('upload incomplete')
        self.resident=self.pending[0];self.pending=None

    def input_writes(self,model,x):
        if self.pending is not None or self.resident!=model_id(model,self.layout):raise RuntimeError('model not resident')
        infer(model,x)  # Exact shape/type and numerical contract validation.
        return [(0,0,j,v) for j,v in enumerate(x)]
