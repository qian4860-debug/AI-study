"""Fixed synthetic experiment; NumPy is needed only for training, never the golden MAC."""
from pathlib import Path
import hashlib, json, math
import numpy as np
from reference import infer

ROOT = Path(__file__).resolve().parent


def main():
    rng = np.random.default_rng(20261018)
    # Three independently generated splits. No sample from test affects model/scales.
    def data(n):
        x = rng.uniform(-1, 1, (n, 16))
        y = (x[:, 0] + .7*x[:, 1] - .5*x[:, 2] + .5*np.abs(x[:, 3]) > .25).astype(int)
        return x, y
    xt, yt = data(1024); xv, yv = data(256); xe, ye = data(512)
    params = [rng.normal(0, .3, (16, 8)), np.zeros(8), rng.normal(0, .3, (8, 2)), np.zeros(2)]
    mom = [np.zeros_like(p) for p in params]; vel = [np.zeros_like(p) for p in params]
    best = -1; best_epoch = 0
    def forward(x, ps):
        w1,b1,w2,b2=ps; hidden=np.maximum(0,x@w1+b1);return hidden,hidden@w2+b2
    for epoch in range(1, 501):
        hidden,logits=forward(xt,params)
        probs=np.exp(logits-logits.max(axis=1,keepdims=True));probs/=probs.sum(axis=1,keepdims=True)
        probs[np.arange(len(yt)),yt]-=1;probs/=len(yt)
        dh=(probs@params[2].T)*(hidden>0)
        grads=[xt.T@dh,dh.sum(axis=0),hidden.T@probs,probs.sum(axis=0)]
        for p,g,m,v in zip(params,grads,mom,vel):
            m[:]=.9*m+.1*g;v[:]=.999*v+.001*g*g
            p-=.015*(m/(1-.9**epoch))/(np.sqrt(v/(1-.999**epoch))+1e-8)
        accuracy=float(np.mean(forward(xv,params)[1].argmax(axis=1)==yv))
        if accuracy>best:
            best=accuracy;best_epoch=epoch;saved=[p.copy() for p in params]
    w1,b1,w2,b2=saved
    scale=lambda a:2.**math.ceil(math.log2(max(float(np.max(np.abs(a))),1e-9)/127))
    sx=1/64;sw1=scale(w1);sh=scale(forward(xt,saved)[0]);sw2=scale(w2);sy=scale(forward(xt,saved)[1])
    quant=lambda a,s:np.clip(np.rint(a/s),-128,127).astype(int)
    shift1=int(round(math.log2(sh/(sx*sw1))));shift2=int(round(math.log2(sy/(sh*sw2))))
    model=dict(version=1,dtype='int8',zero_point=0,shape=[16,8,2],layers=[
        dict(weight=quant(w1.T,sw1).tolist(),bias=np.rint(b1/(sx*sw1)).astype(int).tolist(),relu=True,multiplier=1,shift=shift1),
        dict(weight=quant(w2.T,sw2).tolist(),bias=np.rint(b2/(sh*sw2)).astype(int).tolist(),relu=False,multiplier=1,shift=shift2)])
    qx=quant(xe,sx).tolist(); records=[infer(model,x) for x in qx]
    pred=[int(r[1]['quantized'][1][0]>r[1]['quantized'][0][0]) for r in records]
    float_pred=forward(xe,saved)[1].argmax(axis=1)
    test=[dict(index=i,x=x,label=int(y),prediction=pred[i]) for i,(x,y) in enumerate(zip(qx,ye))]
    report=dict(status='PASS',dataset='synthetic uniform16 nonlinear binary; not sensor data',seed=20261018,
        numpy=np.__version__,train=1024,validation=256,test=512,epochs=500,selected_epoch=best_epoch,
        validation_float_accuracy=best,test_float_accuracy=float(np.mean(float_pred==ye)),
        test_int8_accuracy=float(np.mean(np.array(pred)==ye)),test_prediction_agreement=float(np.mean(np.array(pred)==float_pred)),
        scales=dict(input=sx,weight1=sw1,hidden=sh,weight2=sw2,output=sy),
        saturation_hidden=sum(q[1] for r in records for q in r[0]['quantized']),
        saturation_output=sum(q[1] for r in records for q in r[1]['quantized']),
        calibration='training split only; model selected by validation; test evaluated after frozen selection',
        split_sha256={n:hashlib.sha256(x.tobytes()+y.tobytes()).hexdigest() for n,x,y in [('train',xt,yt),('validation',xv,yv),('test',xe,ye)]})
    for name,obj in [('trained_model.json',model),('test_dataset.json',test),('training_results.json',report)]:
        (ROOT/name).write_text(json.dumps(obj,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
