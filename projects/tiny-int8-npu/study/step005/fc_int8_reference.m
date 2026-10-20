function result = fc_int8_reference(x, weights, bias, relu_enable)
% Exact mathematical FC oracle. No cycle, handshake or RAM behavior.
    assert(isa(x,'int8') && isvector(x));
    assert(isa(weights,'int8') && ismatrix(weights));
    assert(isa(bias,'int32') && isvector(bias));
    K=numel(x); M=size(weights,1);
    assert(K>=1 && K<=256 && M>=1 && M<=8);
    assert(size(weights,2)==K && numel(bias)==M);
    assert(isscalar(relu_enable) && islogical(relu_enable));
    dots=zeros(M,1,'int64');
    for row=1:M
        products=int64(weights(row,:)).*reshape(int64(x),1,[]);
        dots(row)=sum(products,'native');
    end
    pre=dots+int64(bias(:));
    assert(all(pre>=-2^32 & pre<=2^32-1));
    values=pre;
    if relu_enable, values=max(values,int64(0)); end
    result=struct('dot',dots,'pre',pre,'output',values);
end
